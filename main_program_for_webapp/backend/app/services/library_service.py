"""Every library the station runs on, and whether newer releases exist.

* Python: every installed distribution of the backend's environment (the ones requirements.txt
  asks for are marked "direct"), with what it is, its licence and who needs it.
* JavaScript: the frontend's package.json dependencies, plus every installed package from
  node_modules/.package-lock.json.
* System: Python, Node, the OS / JetPack, CUDA, cuDNN, OpenCV, Tesseract, avrdude, the stage
  firmware and the project's own git commit.

Checking for updates is a background job (it asks PyPI and npm over the network): PyPI's
per-project release feed (small, unlike the JSON API that lists every file of every release)
and npm's "latest" document. Results are cached so the page opens instantly. Nothing is ever
upgraded from here — `./run_web.sh --update` does that, deliberately and visibly.
"""
from __future__ import annotations

import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
from importlib import metadata
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import BACKEND_ROOT

logger = logging.getLogger(__name__)

ROOT = BACKEND_ROOT.parent
FRONTEND = ROOT / "frontend"
CACHE = ROOT / ".cache" / "library-catalog.json"
CACHE_TTL = 24 * 3600
TIMEOUT = 8.0
WORKERS = 8
USER_AGENT = "rmutt-aoi-station (library check)"
# Chosen per machine (MPS / CUDA / Jetson wheels): never upgraded by --update.
PINNED_PY = {"torch": "เลือกรุ่นตามเครื่อง (MPS / CUDA / Jetson) — ไม่อัปเดตอัตโนมัติ",
             "torchvision": "ต้องคู่กับ torch — ไม่อัปเดตอัตโนมัติ"}


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


# ── version comparison ───────────────────────────────────────────────────────

def update_kind(current: Optional[str], latest: Optional[str]) -> Optional[str]:
    """'major' / 'minor' / 'patch' when `latest` is newer, None when not (or unknown)."""
    if not current or not latest:
        return None
    try:
        from packaging.version import InvalidVersion, Version

        try:
            a, b = Version(current), Version(latest)
        except InvalidVersion:
            return None
        if b <= a:
            return None
        ra, rb = (list(a.release) + [0, 0, 0])[:3], (list(b.release) + [0, 0, 0])[:3]
        if rb[0] != ra[0]:
            return "major"
        if rb[1] != ra[1]:
            # 0.x: a new minor is the breaking step (semver convention).
            return "major" if ra[0] == 0 else "minor"
        return "patch"
    except ImportError:
        return None if current == latest else "patch"


def _satisfies(spec: Optional[str], version: Optional[str]) -> Optional[bool]:
    if not spec or not version:
        return None
    try:
        from packaging.specifiers import SpecifierSet

        return SpecifierSet(spec).contains(version, prereleases=True)
    except Exception:
        return None


# ── what is installed ────────────────────────────────────────────────────────

def requirements() -> Dict[str, Dict[str, Any]]:
    """Packages requirements.txt asks for on this machine: norm name -> {spec, note}."""
    out: Dict[str, Dict[str, Any]] = {}
    try:
        from packaging.requirements import Requirement
    except ImportError:
        return out
    path = BACKEND_ROOT / "requirements.txt"
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return out
    for raw in lines:
        line, _, note = raw.partition("#")
        line = line.strip()
        if not line or line.startswith("-"):
            continue
        try:
            req = Requirement(line)
        except Exception:
            continue
        if req.marker is not None and not req.marker.evaluate():
            continue
        out[norm(req.name)] = {"spec": str(req.specifier) or None, "note": note.strip() or None}
    return out


def _home(meta) -> Optional[str]:
    for value in meta.get_all("Project-URL") or []:
        label, _, url = value.partition(",")
        if label.strip().lower() in ("homepage", "home", "source", "repository", "documentation") and url.strip():
            return url.strip()
    url = meta.get("Home-page")
    return url if url and url.upper() != "UNKNOWN" else None


def _licence(meta) -> Optional[str]:
    expr = meta.get("License-Expression")
    if expr:
        return expr
    text = (meta.get("License") or "").strip()
    if text and len(text) <= 40 and text.upper() != "UNKNOWN":
        return text
    for c in meta.get_all("Classifier") or []:
        if c.startswith("License :: OSI Approved :: "):
            return c.rsplit(" :: ", 1)[-1].replace(" License", "")
    return None


def python_packages() -> List[Dict[str, Any]]:
    reqs = requirements()
    dists: Dict[str, Any] = {}
    for d in metadata.distributions():
        name = d.metadata.get("Name")
        if name and norm(name) not in dists:
            dists[norm(name)] = d
    needed_by: Dict[str, List[str]] = {}
    for key, d in dists.items():
        for r in d.requires or []:
            if "extra ==" in r:
                continue
            m = re.match(r"\s*([A-Za-z0-9_.\-]+)", r)
            if m:
                needed_by.setdefault(norm(m.group(1)), []).append(d.metadata["Name"])
    out = []
    for key, d in sorted(dists.items()):
        meta = d.metadata
        req = reqs.get(key)
        out.append({
            "name": meta["Name"],
            "version": d.version,
            "summary": (meta.get("Summary") or "").strip() or None,
            "license": _licence(meta),
            "homepage": _home(meta),
            "direct": req is not None,
            "spec": req["spec"] if req else None,
            "note": (req or {}).get("note"),
            "satisfies": _satisfies(req["spec"], d.version) if req else None,
            "needed_by": sorted(set(needed_by.get(key, [])))[:12],
            "pinned": PINNED_PY.get(key),
        })
    for key, req in reqs.items():
        if key not in dists:
            out.append({"name": key, "version": None, "summary": None, "license": None, "homepage": None, "direct": True,
                        "spec": req["spec"], "note": req.get("note"), "satisfies": False, "needed_by": [], "missing": True,
                        "pinned": PINNED_PY.get(key)})
    return out


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def node_packages() -> List[Dict[str, Any]]:
    pkg = _read_json(FRONTEND / "package.json") or {}
    direct = {**{n: (s, False) for n, s in (pkg.get("dependencies") or {}).items()},
              **{n: (s, True) for n, s in (pkg.get("devDependencies") or {}).items()}}
    lock = (_read_json(FRONTEND / "node_modules" / ".package-lock.json") or {}).get("packages") or {}
    out: Dict[str, Dict[str, Any]] = {}
    for path, info in lock.items():
        if not path.startswith("node_modules/") or "/node_modules/" in path[len("node_modules/"):]:
            continue  # nested copies: one row per top-level package
        name = path[len("node_modules/"):]
        out[name] = {"name": name, "version": info.get("version"), "dev": bool(info.get("dev")), "direct": name in direct,
                     "spec": direct.get(name, (None,))[0], "license": info.get("license")}
    for name, (spec, dev) in direct.items():
        row = out.setdefault(name, {"name": name, "version": None, "dev": dev, "direct": True, "spec": spec, "license": None, "missing": True})
        row["dev"] = dev
        info = _read_json(FRONTEND / "node_modules" / name / "package.json") or {}
        row.update({"summary": info.get("description"), "homepage": info.get("homepage"),
                    "license": row.get("license") or (info.get("license") if isinstance(info.get("license"), str) else None)})
        if not row.get("version") and info.get("version"):
            row.update(version=info["version"], missing=False)
    return sorted(out.values(), key=lambda r: (not r["direct"], r["name"]))


def _run(cmd: List[str], timeout: float = 5.0) -> Optional[str]:
    exe = shutil.which(cmd[0]) or (cmd[0] if os.path.isfile(cmd[0]) else None)
    if not exe:
        return None
    try:
        p = subprocess.run([exe, *cmd[1:]], capture_output=True, text=True, timeout=timeout)
        return (p.stdout or p.stderr).strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _avrdude() -> Optional[str]:
    found = shutil.which("avrdude")
    if not found:
        base = Path.home() / ".arduino15" / "packages" / "arduino" / "tools" / "avrdude"
        cands = sorted(base.glob("*/bin/avrdude")) if base.is_dir() else []
        found = str(cands[-1]) if cands else None
    if not found:
        return None
    text = _run([found, "-?"]) or ""
    m = re.search(r"version\s+([\w.\-]+)", text)
    return m.group(1) if m else "ติดตั้งแล้ว"


def system_info() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    def add(name: str, version: Optional[str], detail: Optional[str] = None, kind: str = "runtime"):
        rows.append({"name": name, "version": version, "detail": detail, "kind": kind})

    add("Python", platform.python_version(), sys.executable, "runtime")
    node = _run(["node", "--version"])
    add("Node.js", node.lstrip("v") if node else None, None, "runtime")
    npm = _run(["npm", "--version"])
    add("npm", npm, None, "runtime")
    os_name = platform.platform()
    try:
        import distro  # type: ignore

        os_name = f"{distro.name(pretty=True)} · {platform.machine()}"
    except ImportError:
        try:
            for line in Path("/etc/os-release").read_text().splitlines():
                if line.startswith("PRETTY_NAME="):
                    os_name = f"{line.split('=', 1)[1].strip(chr(34))} · {platform.machine()}"
        except OSError:
            pass
    add("ระบบปฏิบัติการ", os_name, platform.release(), "os")
    try:
        l4t = Path("/etc/nv_tegra_release").read_text().split(",")
        add("NVIDIA L4T (JetPack)", " ".join(x.strip() for x in l4t[:2]), None, "os")
    except OSError:
        pass

    torch = sys.modules.get("torch")
    if torch is None:
        try:
            import torch  # noqa: F401
        except Exception:
            torch = None
    if torch is not None:
        cuda = getattr(torch.version, "cuda", None)
        gpu = None
        try:
            if torch.cuda.is_available():
                gpu = torch.cuda.get_device_name(0)
            elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
                gpu = "Apple MPS"
        except Exception:
            pass
        add("CUDA (ของ PyTorch)", cuda, gpu, "gpu")
        try:
            cudnn = torch.backends.cudnn.version()
            if cudnn:
                add("cuDNN", f"{cudnn // 10000}.{cudnn // 100 % 100}.{cudnn % 100}" if cudnn > 9000 else str(cudnn), None, "gpu")
        except Exception:
            pass
    try:
        import cv2

        cv_cuda = 0
        try:
            cv_cuda = cv2.cuda.getCudaEnabledDeviceCount()
        except Exception:
            pass
        add("OpenCV", cv2.__version__, "มี CUDA" if cv_cuda else "CPU", "vision")
    except Exception:
        pass
    tess = _run(["tesseract", "--version"])
    add("Tesseract OCR", tess.splitlines()[0].replace("tesseract ", "") if tess else None,
        None if tess else "ไม่ได้ติดตั้ง (macOS ใช้ Apple Vision แทน)" if sys.platform == "darwin" else "ไม่ได้ติดตั้ง", "vision")
    add("avrdude (แฟลชเฟิร์มแวร์)", _avrdude(), None, "tools")
    try:
        from .machine_service import machine_service

        client = getattr(machine_service, "_client", None)
        caps = getattr(client, "capabilities", None) if client and not client.closed else None
        add("เฟิร์มแวร์สเตจ", "CNC v2" if caps else None,
            f"คำสั่ง: {' '.join(sorted(caps))}" if caps else "อ่านได้หลังเชื่อมต่อสเตจ", "tools")
    except Exception:
        pass
    commit = _run(["git", "-C", str(ROOT), "log", "-1", "--format=%h · %cs · %s"])
    add("โค้ดโปรเจกต์ (git)", commit.split(" · ")[0] if commit else None, commit, "project")
    return rows


# ── newer releases ───────────────────────────────────────────────────────────

def _get(url: str, accept: str = "*/*") -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310 (fixed hosts)
        return r.read()


def latest_pypi(name: str) -> Dict[str, Any]:
    """Newest stable release on PyPI and when it came out (from the project's release feed)."""
    from packaging.version import InvalidVersion, Version

    root = ET.fromstring(_get(f"https://pypi.org/rss/project/{norm(name)}/releases.xml", "application/rss+xml"))
    best: Optional[tuple] = None
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        try:
            v = Version(title)
        except InvalidVersion:
            continue
        if v.is_prerelease or v.is_devrelease:
            continue
        if best is None or v > best[0]:
            when = item.findtext("pubDate")
            try:
                ts = parsedate_to_datetime(when).timestamp() if when else None
            except (TypeError, ValueError):
                ts = None
            best = (v, title, ts)
    if not best:
        raise ValueError("no stable release")
    return {"latest": best[1], "released": best[2]}


def latest_npm(name: str) -> Dict[str, Any]:
    doc = json.loads(_get(f"https://registry.npmjs.org/{name.replace('/', '%2F')}/latest", "application/json"))
    return {"latest": doc.get("version")}


class LibraryService:
    def __init__(self):
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._job: Dict[str, Any] = {"state": "idle"}

    def cache(self) -> Dict[str, Any]:
        return _read_json(CACHE) or {}

    def job(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._job)

    def check(self, include_all_python: bool = True) -> Dict[str, Any]:
        """Start asking PyPI/npm for newer releases (in the background)."""
        with self._lock:
            if self._thread and self._thread.is_alive():
                return dict(self._job)
            py = [p["name"] for p in python_packages() if not p.get("missing") and (include_all_python or p["direct"])]
            js = [p["name"] for p in node_packages() if p["direct"]]
            self._job = {"state": "running", "done": 0, "total": len(py) + len(js), "started": time.time()}
            self._thread = threading.Thread(target=self._run, args=(py, js), name="library-check", daemon=True)
            self._thread.start()
            return dict(self._job)

    def _run(self, py: List[str], js: List[str]) -> None:
        results: Dict[str, Dict[str, Any]] = {"python": {}, "node": {}}
        failed: List[str] = []

        def one(kind: str, name: str):
            try:
                results[kind][norm(name) if kind == "python" else name] = (latest_pypi if kind == "python" else latest_npm)(name)
            except Exception as exc:  # offline, not on PyPI (local builds), rate limited…
                failed.append(name)
                logger.debug("library check %s: %s", name, exc)
            with self._lock:
                self._job["done"] = self._job.get("done", 0) + 1

        try:
            with ThreadPoolExecutor(WORKERS) as pool:
                for name in py:
                    pool.submit(one, "python", name)
                for name in js:
                    pool.submit(one, "node", name)
            if not results["python"] and not results["node"]:
                raise RuntimeError("ติดต่อ PyPI/npm ไม่ได้ — ตรวจการเชื่อมต่ออินเทอร์เน็ตของเครื่อง")
            data = {"time": time.time(), **results, "failed": sorted(failed)}
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            CACHE.write_text(json.dumps(data))
            with self._lock:
                self._job.update(state="done", finished=time.time(), failed=len(failed))
        except Exception as exc:
            logger.warning("Library update check failed: %s", exc)
            with self._lock:
                self._job.update(state="error", message=str(exc), finished=time.time())

    def catalog(self) -> Dict[str, Any]:
        """Everything for the libraries page, with the last check's newer versions merged in."""
        cache = self.cache()
        latest_py, latest_js = cache.get("python") or {}, cache.get("node") or {}
        py = python_packages()
        for p in py:
            info = latest_py.get(norm(p["name"]))
            if info:
                p["latest"], p["released"] = info.get("latest"), info.get("released")
                p["update"] = update_kind(p["version"], p["latest"])
                p["latest_in_spec"] = _satisfies(p["spec"], p["latest"]) if p["spec"] else True
        js = node_packages()
        for p in js:
            info = latest_js.get(p["name"])
            if info:
                p["latest"] = info.get("latest")
                p["update"] = update_kind(p["version"], p["latest"])
        def count(rows):
            return {k: sum(1 for r in rows if r.get("update") == k) for k in ("major", "minor", "patch")}

        return {
            "python": py,
            "node": js,
            "system": system_info(),
            "checked_at": cache.get("time"),
            "stale": not cache.get("time") or time.time() - cache["time"] > CACHE_TTL,
            "failed": cache.get("failed") or [],
            "job": self.job(),
            "summary": {
                "python": {"installed": len(py), "direct": sum(1 for p in py if p["direct"]), "updates": count(py),
                           "mismatched": [p["name"] for p in py if p["direct"] and p.get("satisfies") is False]},
                "node": {"installed": len(js), "direct": sum(1 for p in js if p["direct"]), "updates": count(js)},
            },
        }


library_service = LibraryService()
