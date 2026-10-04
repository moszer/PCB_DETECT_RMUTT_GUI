#!/usr/bin/env python3
"""Console helpers for run_web.sh: RMUTT logo banner, library check and a "what is running" summary.

    console.py banner  < lines      logo (drawn from frontend/public/rmutt-logo.png) beside the text lines
    console.py deps    [--updates]  are the installed libraries what requirements.txt asks for?
                                    --updates also looks for newer releases (cached for a day)
    console.py status  --backend-port N --frontend-port N --mode dev|prod [--backend-pid N --frontend-pid N]

Colours are used only on a terminal (NO_COLOR disables; PCB_FORCE_COLOR=1 forces them).
Standard library plus Pillow (already a backend dependency); Pillow is optional.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
LOGO = FRONTEND / "public" / "rmutt-logo.png"
CACHE = ROOT / ".cache" / "library-updates.json"
CACHE_TTL = 24 * 3600

COLOR = (sys.stdout.isatty() and "NO_COLOR" not in os.environ) or os.environ.get("PCB_FORCE_COLOR") == "1"
TRUECOLOR = os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit")


def c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if COLOR else text


bold = lambda t: c("1", t)  # noqa: E731
dim = lambda t: c("2", t)  # noqa: E731
green = lambda t: c("32", t)  # noqa: E731
yellow = lambda t: c("33", t)  # noqa: E731
red = lambda t: c("31", t)  # noqa: E731
cyan = lambda t: c("36", t)  # noqa: E731
OK, WARN, BAD = green("✓"), yellow("!"), red("✗")


# ── logo ──────────────────────────────────────────────────────────────────────

def _ansi256(r: int, g: int, b: int) -> int:
    if abs(r - g) < 10 and abs(g - b) < 10:  # grays
        gray = round((r + g + b) / 3)
        return 16 if gray < 8 else 231 if gray > 248 else 232 + round((gray - 8) / 247 * 23)
    return 16 + 36 * round(r / 255 * 5) + 6 * round(g / 255 * 5) + round(b / 255 * 5)


def _fg(rgb) -> str:
    return f"\033[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m" if TRUECOLOR else f"\033[38;5;{_ansi256(*rgb)}m"


def _bg(rgb) -> str:
    return f"\033[48;2;{rgb[0]};{rgb[1]};{rgb[2]}m" if TRUECOLOR else f"\033[48;5;{_ansi256(*rgb)}m"


def logo_rows(text_rows: int = 18) -> list[str]:
    """The university seal as text rows (two pixels per character using half blocks)."""
    if not COLOR or not LOGO.is_file():
        return []
    try:
        from PIL import Image
    except ImportError:
        return []
    img = Image.open(LOGO).convert("RGBA")
    img = img.crop(img.getbbox())
    height = text_rows * 2
    width = max(1, round(height * img.width / img.height))
    img = img.resize((width, height), Image.LANCZOS)
    px = img.load()
    rows = []
    for y in range(0, height, 2):
        line = []
        for x in range(width):
            top, bottom = px[x, y], px[x, y + 1]
            t, b = top[3] >= 110, bottom[3] >= 110
            if t and b:
                line.append(f"{_fg(top[:3])}{_bg(bottom[:3])}▀\033[0m")
            elif t:
                line.append(f"{_fg(top[:3])}▀\033[0m")
            elif b:
                line.append(f"{_fg(bottom[:3])}▄\033[0m")
            else:
                line.append(" ")
        rows.append("".join(line))
    return rows


def cmd_banner(_args) -> int:
    lines = [ln.rstrip("\n") for ln in sys.stdin]
    logo = logo_rows()
    if not logo:
        print("\n".join(lines))
        return 0
    width = len(re.sub(r"\033\[[0-9;]*m", "", logo[0]))
    top = max(0, (len(logo) - len(lines)) // 2)
    for i in range(max(len(logo), top + len(lines))):
        left = logo[i] if i < len(logo) else " " * width
        right = lines[i - top] if 0 <= i - top < len(lines) else ""
        print(f"  {left}   {right}")
    return 0


# ── libraries ─────────────────────────────────────────────────────────────────

def _requirements() -> list:
    from packaging.requirements import Requirement

    reqs = []
    for raw in (BACKEND / "requirements.txt").read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        try:
            req = Requirement(line)
        except Exception:
            continue
        if req.marker is None or req.marker.evaluate():
            reqs.append(req)
    return reqs


def _pip(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "pip", *args], capture_output=True, text=True, timeout=timeout)


def _npm_installed_dirty() -> str:
    lock, installed = FRONTEND / "package-lock.json", FRONTEND / "node_modules" / ".package-lock.json"
    if lock.is_file() and installed.is_file() and lock.stat().st_mtime > installed.stat().st_mtime + 1:
        return "package-lock.json is newer than node_modules (run ./install.sh)"
    return ""


def _outdated() -> dict:
    """Newer releases of the libraries we depend on (cached; network failures are silent)."""
    if CACHE.is_file():
        try:
            data = json.loads(CACHE.read_text())
            if time.time() - data["time"] < CACHE_TTL:
                return {**data, "cached": True}
        except (ValueError, KeyError):
            pass
    # PyTorch is chosen per machine (MPS / CUDA / Jetson wheels) and is never upgraded automatically.
    names = {r.name.lower().replace("_", "-") for r in _requirements()} - {"torch", "torchvision"}
    py, js = [], []
    try:
        out = _pip("list", "--outdated", "--format=json", timeout=40).stdout
        py = [{"name": p["name"], "current": p["version"], "latest": p["latest_version"]}
              for p in json.loads(out or "[]") if p["name"].lower().replace("_", "-") in names]
    except Exception:
        pass
    npm = shutil.which("npm")
    if npm:
        try:
            out = subprocess.run([npm, "outdated", "--json", "--prefix", str(FRONTEND)], capture_output=True, text=True, timeout=40).stdout
            js = [{"name": n, "current": v.get("current"), "latest": v.get("latest")} for n, v in json.loads(out or "{}").items()
                  if v.get("current") and v.get("latest") and v["current"].split(".")[0] == v["latest"].split(".")[0]]
        except Exception:
            pass
    data = {"time": time.time(), "python": py, "node": js}
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(data))
    except OSError:
        pass
    return {**data, "cached": False}


def cmd_deps(args) -> int:
    from importlib import metadata

    problems = []
    missing, wrong = [], []
    try:
        for req in _requirements():
            try:
                version = metadata.version(req.name)
            except metadata.PackageNotFoundError:
                missing.append(req.name)
                continue
            if req.specifier and not req.specifier.contains(version, prereleases=True):
                wrong.append(f"{req.name} {version} (needs {req.specifier})")
    except ImportError:
        print(f"  {WARN} cannot read requirements.txt (packaging missing)")
        return 0
    if missing or wrong:
        problems.append("Python: " + ", ".join(missing + wrong))
    check = _pip("check")
    if check.returncode != 0:
        problems.append("pip check: " + (check.stdout.strip().splitlines() or ["conflicting packages"])[0])
    dirty = _npm_installed_dirty()
    if dirty:
        problems.append("Frontend: " + dirty)

    n = len(_requirements())
    if problems:
        for p in problems:
            print(f"  {WARN} {p}")
        print(f"      {dim('→ run  ./install.sh --no-system --yes  (or ./run_web.sh --update)')}")
    else:
        print(f"  {OK} libraries match requirements ({n} Python packages · frontend lockfile in sync)")

    if args.updates:
        info = _outdated()
        found = info["python"] + info["node"]
        age = f" (checked {round((time.time() - info['time']) / 3600)} h ago)" if info["cached"] else ""
        if found:
            print(f"  {WARN} newer library versions available{age}:")
            for item in found[:8]:
                print(f"      {item['name']:<22} {item['current']} → {item['latest']}")
            if len(found) > 8:
                print(f"      … and {len(found) - 8} more")
            print(f"      {dim('→ ./run_web.sh --update to upgrade (not automatic: new releases can change behaviour)')}")
        else:
            print(f"  {OK} libraries are up to date{age}")
    return 0


# ── status ────────────────────────────────────────────────────────────────────

def _get(url: str, timeout: float = 4.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as res:
            return json.loads(res.read().decode())
    except Exception:
        return None


def _lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def _version(cmd: list) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout.strip().lstrip("v")
    except Exception:
        return "?"


def cmd_status(args) -> int:
    base = f"http://127.0.0.1:{args.backend_port}"
    health = _get(f"{base}/api/health") or {}
    system = _get(f"{base}/api/system/status") or {}
    cam = _get(f"{base}/api/camera/status") or {}
    chat = _get(f"{base}/api/chat/status") or {}
    stats = _get(f"{base}/api/history/statistics") or {}
    boards = (_get(f"{base}/api/aoi/point-sets") or {}).get("sets", [])
    machine = system.get("machine") or {}

    sys.path.insert(0, str(BACKEND))
    try:
        from app.core.ocr import engine_name  # type: ignore

        ocr = {"apple-vision": "Apple Vision", "tesseract": "tesseract"}.get(engine_name() or "", "none (install tesseract-ocr)")
    except Exception:
        ocr = "unknown"

    def row(label: str, text: str, state: str = "ok") -> None:
        mark = {"ok": green("●"), "warn": yellow("●"), "off": dim("○"), "bad": red("●")}[state]
        print(f"  {mark} {bold(label):<{14 + (len(bold(label)) - len(label))}} {text}")

    model_file = Path(system.get("model_path") or "").name
    model_run = Path(system.get("model_path") or "").parent.parent.name if "weights" in (system.get("model_path") or "") else ""
    pid = lambda p: f"pid {p}  " if p else ""  # noqa: E731
    print()
    print(f"  {bold(green('กำลังทำงาน · RUNNING'))}   {dim(time.strftime('%Y-%m-%d %H:%M:%S'))}")
    row("Backend", f"FastAPI/uvicorn · {pid(args.backend_pid)}Python {platform.python_version()} · http://127.0.0.1:{args.backend_port}",
        "ok" if health else "bad")
    row("Frontend", f"Next.js ({'production' if args.mode == 'prod' else 'development, hot reload'}) · {pid(args.frontend_pid)}Node {_version(['node', '--version'])} · port {args.frontend_port}")
    row("AI model", (f"{model_run + ' · ' if model_run else ''}{model_file or 'best.pt'} · {health.get('device', system.get('active_device', '?'))}")
        if health.get("model_loaded") else "not loaded — choose one in Settings", "ok" if health.get("model_loaded") else "warn")
    if cam.get("active"):
        r = cam.get("resolution") or [0, 0]
        row("Camera", f"{'test camera' if cam.get('is_mock') else 'live'} · {r[0]}×{r[1]} @ {cam.get('fps', 0):.0f} fps · {cam.get('output_mode')}", "warn" if cam.get("is_mock") else "ok")
    else:
        row("Camera", "idle — opens when the live view is used", "off")
    if machine.get("connected"):
        row("XY stage", f"{machine.get('mode')} · {'homed' if machine.get('homed') else 'not homed'}", "ok" if machine.get("homed") else "warn")
    else:
        row("XY stage", "not connected — connect in the AOI page", "off")
    if chat.get("configured"):
        row("AI assistant", f"{chat.get('provider')} · {chat.get('model')} (API key set)")
    else:
        row("AI assistant", "no API key — add GEMINI_API_KEY to backend/.env", "warn")
    row("OCR", ocr, "ok" if "none" not in ocr else "warn")
    row("Data", f"{stats.get('total_runs', 0)} scan runs · {stats.get('single_inspections_count', 0)} single inspections · {len(boards)} saved boards")
    print()
    print(f"  {bold('Open')}   http://localhost:{args.frontend_port}    {dim('LAN')} http://{_lan_ip()}:{args.frontend_port}")
    print(f"  {dim('Operator passcode: PCB_OPERATOR_PASSCODE in backend/.env (default rmutt-aoi).  Ctrl+C stops everything.')}")
    print()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("banner").set_defaults(fn=cmd_banner)
    d = sub.add_parser("deps")
    d.add_argument("--updates", action="store_true")
    d.set_defaults(fn=cmd_deps)
    s = sub.add_parser("status")
    s.add_argument("--backend-port", type=int, default=8000)
    s.add_argument("--frontend-port", type=int, default=3001)
    s.add_argument("--mode", default="dev")
    s.add_argument("--backend-pid", default="")
    s.add_argument("--frontend-pid", default="")
    s.set_defaults(fn=cmd_status)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
