"""Download YOLO weights from a Hugging Face model repo (standard library only).

Used three ways:
  - `install.sh` fetches best.pt when the checkout has none:
        python -m app.core.hub --file best.pt --out ../best.pt
  - the Settings page lists the repo's weights and downloads one into data/models/hub/
  - by hand:  python -m app.core.hub --list

Public repos need no account. For a private repo set HF_TOKEN (read access); the token stays
on the server and is never sent to the browser.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Dict, List, Optional

HUB = os.environ.get("HF_ENDPOINT", "https://huggingface.co").rstrip("/")
DEFAULT_REPO = os.environ.get("PCB_MODEL_REPO", "Moszer777/pcb-aoi-yolo-rmutt")
DEFAULT_FILE = os.environ.get("PCB_MODEL_FILE", "best.pt")
MAX_BYTES = 1024 ** 3  # same cap as the upload endpoint
TIMEOUT = 30
_REPO_RE = re.compile(r"^[A-Za-z0-9][\w.-]*/[A-Za-z0-9][\w.-]*$")


class HubError(RuntimeError):
    """Readable failure (no network, repo/file not found, bad checksum...)."""


def _request(url: str, headers: Optional[Dict[str, str]] = None, data: Optional[bytes] = None):
    h = {"User-Agent": "rmutt-pcb-aoi"}
    token = os.environ.get("HF_TOKEN")
    if token:
        h["Authorization"] = f"Bearer {token}"
    h.update(headers or {})
    return urllib.request.urlopen(urllib.request.Request(url, headers=h, data=data), timeout=TIMEOUT)


def _explain(exc: Exception, what: str) -> HubError:
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 404:
            return HubError(f"{what}: not found on Hugging Face (check PCB_MODEL_REPO / file name; private repos need HF_TOKEN)")
        if exc.code in (401, 403):
            return HubError(f"{what}: access denied (private repo? set HF_TOKEN in backend/.env)")
        return HubError(f"{what}: Hugging Face answered HTTP {exc.code}")
    return HubError(f"{what}: cannot reach Hugging Face ({getattr(exc, 'reason', exc)})")


def check_repo(repo: str) -> str:
    if not _REPO_RE.match(repo or ""):
        raise HubError(f"Invalid repo id '{repo}' (expected owner/name)")
    return repo


def check_file(file: str) -> str:
    parts = file.split("/")
    if not file.endswith(".pt") or file.startswith("/") or ".." in parts or "" in parts:
        raise HubError(f"Invalid weights path '{file}' (must be a relative .pt path)")
    return file


def _tree(repo: str, revision: str) -> List[dict]:
    """All file entries of the repo (follows pagination links)."""
    url: Optional[str] = f"{HUB}/api/models/{repo}/tree/{revision}?recursive=true"
    entries: List[dict] = []
    while url:
        try:
            with _request(url) as res:
                entries += json.load(res)
                link = res.headers.get("Link", "")
        except Exception as exc:  # noqa: BLE001 - mapped to a readable error
            raise _explain(exc, f"Listing {repo}") from exc
        match = re.search(r'<([^>]+)>;\s*rel="next"', link)
        url = match.group(1) if match else None
    return entries


def _paths_info(repo: str, revision: str, path: str) -> List[dict]:
    """Size and LFS checksum of one file."""
    body = json.dumps({"paths": [path], "expand": False}).encode()
    try:
        with _request(f"{HUB}/api/models/{repo}/paths-info/{revision}", {"Content-Type": "application/json"}, body) as res:
            return json.load(res)
    except Exception as exc:  # noqa: BLE001
        raise _explain(exc, f"Looking up {path}") from exc


def _describe(path: str, size: int) -> dict:
    parts = path.split("/")
    kind = "best" if path.endswith("best.pt") else "last" if path.endswith("last.pt") else "other"
    return {"path": path, "size": size, "run": parts[0] if len(parts) > 1 else None, "kind": kind}


def list_models(repo: str = DEFAULT_REPO, revision: str = "main") -> List[dict]:
    """Weights (*.pt) in the repo, training runs first, best.pt before last.pt."""
    repo = check_repo(repo)
    files = [_describe(e["path"], int(e.get("size") or 0)) for e in _tree(repo, revision) if e.get("type") == "file" and e["path"].endswith(".pt")]
    order = {"best": 0, "other": 1, "last": 2}
    return sorted(files, key=lambda f: (f["run"] is None, f["run"] or "", order[f["kind"]], f["path"]))


def local_name(file: str) -> str:
    """Flat file name for a repo path: m_new_final_l/weights/best.pt -> m_new_final_l__best.pt."""
    return "__".join(p for p in file.split("/") if p != "weights")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def download(
    file: str = DEFAULT_FILE,
    out: Path | str = "",
    repo: str = DEFAULT_REPO,
    revision: str = "main",
    progress: Optional[Callable[[int, int], None]] = None,
) -> Path:
    """Fetch one weights file to `out`, resuming a partial download and verifying its SHA-256.

    An existing, intact file is kept (re-running is cheap). The file only appears at `out`
    once it is complete and verified.
    """
    repo, file = check_repo(repo), check_file(file)
    out = Path(out)
    entries = [e for e in _paths_info(repo, revision, file) if e.get("path") == file and e.get("type") == "file"]
    if not entries:
        raise HubError(f"{file} not found in {repo}")
    size = int(entries[0].get("size") or 0)
    expected = (entries[0].get("lfs") or {}).get("oid")
    if size > MAX_BYTES:
        raise HubError(f"{file} is {size // 1024 ** 2} MB, over the {MAX_BYTES // 1024 ** 2} MB limit")

    if out.is_file() and out.stat().st_size == size and (not expected or _sha256(out) == expected):
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_name(out.name + ".part")
    have = part.stat().st_size if part.is_file() else 0
    if have > size:
        part.unlink()
        have = 0

    url = f"{HUB}/{repo}/resolve/{revision}/{urllib.parse.quote(file, safe='/')}"
    try:
        if have < size:
            try:
                res = _request(url, {"Range": f"bytes={have}-"} if have else None)
            except urllib.error.HTTPError as exc:
                if exc.code != 416:
                    raise
                part.unlink(missing_ok=True)  # the partial file is unusable; start over
                have, res = 0, _request(url)
            with res:
                if have and res.status != 206:  # server ignored Range
                    have = 0
                with part.open("ab" if have else "wb") as fh:
                    done = have
                    while chunk := res.read(1024 * 1024):
                        fh.write(chunk)
                        done += len(chunk)
                        if progress:
                            progress(done, size)
    except HubError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _explain(exc, f"Downloading {file}") from exc

    if part.stat().st_size != size or (expected and _sha256(part) != expected):
        part.unlink(missing_ok=True)
        raise HubError(f"{file}: download is corrupt (size/checksum mismatch); try again")
    part.replace(out)
    return out


def _cli(argv: List[str]) -> int:
    from .. import config  # noqa: F401  (side effect: loads backend/.env, so PCB_MODEL_REPO / HF_TOKEN apply)

    repo_default = os.environ.get("PCB_MODEL_REPO", DEFAULT_REPO)
    ap = argparse.ArgumentParser(description="Download YOLO weights from Hugging Face")
    ap.add_argument("--repo", default=repo_default, help=f"owner/name (default {repo_default})")
    ap.add_argument("--file", default=os.environ.get("PCB_MODEL_FILE", DEFAULT_FILE), help="path of the .pt file in the repo")
    ap.add_argument("--out", help="where to save it (default: ./<file name>)")
    ap.add_argument("--list", action="store_true", help="list the repo's weights and exit")
    args = ap.parse_args(argv)
    try:
        if args.list:
            for m in list_models(args.repo):
                print(f"{m['size'] / 1024 ** 2:7.1f} MB  {m['path']}")
            return 0
        shown = {"pct": -1}

        def progress(done: int, total: int) -> None:
            pct = int(done * 100 / total) if total else 100
            if pct != shown["pct"] and (pct % 5 == 0 or pct == 100):
                shown["pct"] = pct
                print(f"\r  downloading {args.file}: {pct}% ({done // 1024 ** 2}/{total // 1024 ** 2} MB)", end="", flush=True)

        path = download(args.file, args.out or Path(args.file).name, args.repo, progress=progress)
        print(f"\n  saved {path} ({path.stat().st_size // 1024 ** 2} MB)")
        return 0
    except HubError as exc:
        print(f"\n  {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
