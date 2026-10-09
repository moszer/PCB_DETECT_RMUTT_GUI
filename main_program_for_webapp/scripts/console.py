#!/usr/bin/env python3
"""Console helpers for run_web.sh: RMUTT logo banner, library check and a "what is running" summary.

    console.py banner  < lines      RMUTT ASCII logo (scripts/rmutt-ascii.txt) beside the text lines
    console.py deps    [--updates]  are the installed libraries what requirements.txt asks for?
                                    --updates also looks for newer releases (cached for a day)
    console.py status  --backend-port N --frontend-port N --mode dev|prod [--backend-pid N --frontend-pid N]

Colours are used only on a terminal (NO_COLOR disables; PCB_FORCE_COLOR=1 forces them).
Standard library only.
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
CACHE = ROOT / ".cache" / "library-updates.json"
CACHE_TTL = 24 * 3600

COLOR = (sys.stdout.isatty() and "NO_COLOR" not in os.environ) or os.environ.get("PCB_FORCE_COLOR") == "1"
TRUECOLOR = os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit")
ANIMATE = sys.stdout.isatty() and "NO_COLOR" not in os.environ and not os.environ.get("PCB_NO_ANIM")


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

ASCII_LOGO = Path(__file__).with_name("rmutt-ascii.txt")


def _ansi256(r: int, g: int, b: int) -> int:
    return 16 + 36 * round(r / 255 * 5) + 6 * round(g / 255 * 5) + round(b / 255 * 5)


def _fg(rgb) -> str:
    return f"\033[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m" if TRUECOLOR else f"\033[38;5;{_ansi256(*rgb)}m"


def _logo_art() -> tuple[list[str], list[tuple[int, int, int]]]:
    """The seal's ASCII lines (trimmed, same width) and a colour per line (gold -> orange)."""
    if not ASCII_LOGO.is_file():
        return [], []
    lines = [ln.rstrip() for ln in ASCII_LOGO.read_text(encoding="utf-8").splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    indent = min((len(ln) - len(ln.lstrip()) for ln in lines if ln.strip()), default=0)
    lines = [ln[indent:] for ln in lines]
    width = max((len(ln) for ln in lines), default=0)
    lines = [ln.ljust(width) for ln in lines]
    rgbs = []
    for i in range(len(lines)):
        t = i / max(1, len(lines) - 1)
        rgbs.append((round(255 - 25 * t), round(190 - 100 * t), round(20 + 10 * t)))
    return lines, rgbs


def logo_rows() -> list[tuple[str, int]]:
    """The seal as ASCII art, trimmed, tinted gold at the spire to orange at the base."""
    lines, rgbs = _logo_art()
    width = len(lines[0]) if lines else 0
    return [((f"{_fg(rgb)}{ln}\033[0m" if COLOR else ln), width) for ln, rgb in zip(lines, rgbs)]


def _visible_len(text: str) -> int:
    return len(re.sub(r"\033\[[0-9;]*m", "", text))


def _snake_banner(lines: list[str], top: int, rows: int) -> None:
    """The seal drawn by a snake: it zig-zags down the faint art in bands, every character its
    head passes is eaten and lights up in colour, it grows as it eats, then slides off."""
    art, rgbs = _logo_art()
    h, w = len(art), len(art[0])
    band = 3
    # The head's path: left to right on band 0, right to left on band 1, … (centre row of each band).
    path: list[tuple[int, int]] = []
    for b, r0 in enumerate(range(0, h, band)):
        r = min(h - 1, r0 + band // 2)
        cols = range(w) if b % 2 == 0 else range(w - 1, -1, -1)
        path += [(r, x) for x in cols]
        if r0 + band < h:  # the turn down to the next band
            x = w - 1 if b % 2 == 0 else 0
            path += [(rr, x) for rr in range(r + 1, min(h - 1, r + band) + 1)]
    eaten = [[False] * w for _ in range(h)]
    green = [(40, 230, 110), (30, 200, 90), (25, 165, 75), (20, 130, 60)]
    duration = 2.6
    steps_per_frame = max(1, round(len(path) / (duration * 50)))
    length = 6

    def cell(r: int, x: int, snake: dict) -> str:
        ch = art[r][x]
        if (r, x) in snake:
            k = snake[(r, x)]
            if k == 0:
                return f"\033[1m{_fg(green[0])}@\033[0m"
            return f"{_fg(green[min(3, 1 + k // 6)])}{'o' if k % 3 else 'O'}\033[0m"
        if ch == " ":
            return " "
        return f"{_fg(rgbs[r])}{ch}\033[0m" if eaten[r][x] else f"\033[38;5;239m{ch}\033[0m"

    def row_text(i: int, snake: dict) -> str:
        left = "".join(cell(i, x, snake) for x in range(w)) if i < h else " " * w
        right = lines[i - top] if 0 <= i - top < len(lines) else ""
        return f"  {left}   {right}"

    out = sys.stdout
    out.write("\033[?25l")  # hide the cursor while drawing
    try:
        for i in range(rows):
            out.write(row_text(i, {}) + "\n")
        out.flush()
        prev_rows: set = set()
        head = 0
        last = len(path) + 40  # run on until the tail has left the art
        while head <= last:
            for _ in range(steps_per_frame):
                if head < len(path):
                    r, x = path[head]
                    for rr in range(max(0, r - band // 2), min(h, r + band // 2 + 1)):
                        if not eaten[rr][x] and art[rr][x] != " ":
                            eaten[rr][x] = True
                            if art[rr][x] in "*#%@&$":
                                length = min(40, length + 1)  # the rich bits make it grow
                        eaten[rr][x] = True
                head += 1
            snake = {}
            for k in range(length):
                j = head - 1 - k
                if 0 <= j < len(path):
                    snake.setdefault(path[j], k)
            now_rows = {r for r, _ in snake}
            for i in sorted(now_rows | prev_rows):
                up = rows - i
                out.write(f"\033[{up}F" + row_text(i, snake) + "\033[K" + f"\033[{up}E")
            out.flush()
            prev_rows = now_rows
            time.sleep(0.02)
        for i in range(h):  # everything in colour at the end
            eaten[i] = [True] * w
        for i in range(min(rows, h)):
            up = rows - i
            out.write(f"\033[{up}F" + row_text(i, {}) + "\033[K" + f"\033[{up}E")
        out.flush()
    finally:
        out.write("\033[?25h")
        out.flush()


# Block letters, 5 rows; each "#" becomes a full block (twice, for squarer letters).
_GLYPHS = {
    "N": ["#   #", "##  #", "# # #", "#  ##", "#   #"],
    "V": ["#   #", "#   #", "#   #", " # # ", "  #  "],
    "I": ["###", " # ", " # ", " # ", "###"],
    "D": ["#### ", "#   #", "#   #", "#   #", "#### "],
    "A": [" ### ", "#   #", "#####", "#   #", "#   #"],
}
NVIDIA_GREEN = (118, 185, 0)


def _jetson() -> str | None:
    """The board's name when running on an NVIDIA Jetson (else None)."""
    if not Path("/etc/nv_tegra_release").is_file():
        return None
    try:
        model = Path("/proc/device-tree/model").read_bytes().rstrip(b"\0").decode("utf-8", "replace").strip()
    except OSError:
        model = "NVIDIA Jetson"
    try:
        rel = Path("/etc/nv_tegra_release").read_text().split(",")
        l4t = rel[0].replace("#", "").replace("(release)", "").split()
        model += f" · L4T {l4t[0]}.{rel[1].split(':')[-1].strip()}" if l4t else ""
    except (OSError, IndexError):
        pass
    return model.replace("Engineering Reference Developer Kit", "Developer Kit")


NVIDIA_ART = Path(__file__).with_name("nvidia-ascii.txt")


def _nvidia_art() -> tuple[list[str], list[str]]:
    """The NVIDIA art file as (eye rows, wordmark rows): two blocks separated by blank lines,
    stripped of their common left margin (the file is centred in a wide canvas)."""
    if not NVIDIA_ART.is_file():
        return [], []
    blocks: list[list[str]] = [[]]
    for ln in NVIDIA_ART.read_text(encoding="utf-8").splitlines():
        if ln.strip():
            blocks[-1].append(ln.rstrip())
        elif blocks[-1]:
            blocks.append([])
    blocks = [b for b in blocks if b]
    if len(blocks) < 2:
        return [], []
    # Each block loses its own margin, then the narrower one is centred under/over the wider.
    trimmed = []
    for b in blocks[:2]:
        indent = min(len(ln) - len(ln.lstrip()) for ln in b)
        trimmed.append([ln[indent:] for ln in b])
    widths = [max(len(ln) for ln in b) for b in trimmed]
    wide = max(widths)
    return tuple([" " * ((wide - w) // 2) + ln for ln in b] for b, w in zip(trimmed, widths))  # type: ignore[return-value]


def nvidia_lines(max_width: int) -> list[str]:
    """The NVIDIA eye (green) and wordmark (white) from scripts/nvidia-ascii.txt and the
    Jetson board's name; block letters when the terminal is too narrow for the art."""
    board = _jetson()
    if not board:
        return []
    eye, word = _nvidia_art()
    width = max((len(ln) for ln in eye + word), default=0)
    if eye and word and width > max_width:
        # Two thirds as wide: every third column dropped (the strokes are 5+ characters thick).
        thin = lambda rows: ["".join(ch for i, ch in enumerate(r) if i % 3 != 2).rstrip() for r in rows]  # noqa: E731
        eye, word = thin(eye), thin(word)
        width = max((len(ln) for ln in eye + word), default=0)
    if eye and word and width <= max_width:
        green = (lambda t: f"{_fg(NVIDIA_GREEN)}{t}\033[0m") if COLOR else (lambda t: t)
        white = (lambda t: f"\033[1;97m{t}\033[0m") if COLOR else (lambda t: t)
        return ["", *[green(r) for r in eye], "", *[white(r) for r in word], "", f"{dim('powered by')} {bold(board)}"]
    return _nvidia_blocks(max_width, board)


def _nvidia_blocks(max_width: int, board: str) -> list[str]:
    """NVIDIA in green block letters and the Jetson board's name (wide or compact letters)."""
    word = "NVIDIA"
    for scale in (2, 1):
        rows = ["  ".join(_GLYPHS[ch][r].replace("#", "█" * scale).replace(" ", " " * scale) for ch in word) for r in range(5)]
        if len(rows[0]) <= max_width:
            break
    else:
        return [c("1;32", "NVIDIA"), dim(board)]
    paint = (lambda t: f"{_fg(NVIDIA_GREEN)}{t}\033[0m") if COLOR else (lambda t: t)
    return ["", *[paint(r) for r in rows], "", f"{dim('powered by')} {bold(board)}"]


def cmd_banner(_args) -> int:
    lines = [ln.rstrip("\n") for ln in sys.stdin]
    # The art is for people at a terminal; a log file only gets the text.
    logo = logo_rows() if (sys.stdout.isatty() or COLOR) else []
    if not logo:
        print("\n".join(lines))
        return 0
    width = logo[0][1]
    size = shutil.get_terminal_size((100, 24))
    # On a Jetson the NVIDIA mark goes under the station text, as wide as the terminal allows.
    lines += nvidia_lines(size.columns - (2 + width + 3) - 1)
    text_width = max((_visible_len(ln) for ln in lines), default=0)
    if size.columns < 2 + width + 3 + text_width:  # narrow terminal: the text goes below the art
        print("\n".join(f"  {ln}" for ln, _ in logo))
        print()
        print("\n".join(f"  {ln}" for ln in lines))
        return 0
    top = max(0, (len(logo) - len(lines)) // 2)
    rows = max(len(logo), top + len(lines))
    # A snake draws the seal on a terminal tall enough to hold it (redrawing in place);
    # otherwise it is drawn top to bottom, and logs get it at once.
    if ANIMATE and COLOR and size.lines >= rows + 2:
        try:
            _snake_banner(lines, top, rows)
            return 0
        except (OSError, KeyboardInterrupt):
            sys.stdout.write("\033[?25h\n")
    delay = 0.5 / rows if ANIMATE else 0.0
    for i in range(rows):
        left = logo[i][0] if i < len(logo) else ""
        pad = " " * (width - _visible_len(left))
        right = lines[i - top] if 0 <= i - top < len(lines) else ""
        print(f"  {left}{pad}   {right}", flush=True)
        if delay:
            time.sleep(delay)
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
