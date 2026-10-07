"""Discover YOLO weights on disk, including Ultralytics training runs (runs/<name>/weights/*.pt)."""
from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

SKIP_DIRS = {"node_modules", "venv", ".venv", ".git", "__pycache__", ".next", "site-packages", "datasets", "dataset"}
MAX_DEPTH = 6
MAX_FILES = 600


def _walk_pt(root: Path, max_depth: int = MAX_DEPTH) -> Iterable[Path]:
    """Yield *.pt files under root without descending into heavy/irrelevant folders."""
    root_depth = len(root.parts)
    for dirpath, dirnames, filenames in os.walk(root):
        depth = len(Path(dirpath).parts) - root_depth
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".") and depth < max_depth]
        for name in filenames:
            if name.endswith(".pt"):
                yield Path(dirpath) / name


def placeholder_reason(path: Path, size: int) -> Optional[str]:
    """Why a .pt file is not real weights (a Git LFS pointer, an empty file), else None."""
    if size == 0:
        return "ไฟล์ว่าง"
    if size < 1024:
        try:
            head = path.read_bytes()[:64]
        except OSError:
            return None
        if head.startswith(b"version https://git-lfs"):
            return "ไฟล์ Git LFS ที่ยังไม่ได้ดึงจริง (รัน git lfs pull)"
        return "ไฟล์เล็กเกินกว่าจะเป็นโมเดล"
    return None


def _run_info(weights_file: Path) -> Optional[Dict[str, Any]]:
    """Training metadata when the file lives in <run>/weights/: best mAP from results.csv and args.yaml basics."""
    if weights_file.parent.name != "weights":
        return None
    run_dir = weights_file.parent.parent
    info: Dict[str, Any] = {"run": run_dir.name}
    results = run_dir / "results.csv"
    if results.is_file():
        try:
            with results.open(newline="", encoding="utf-8") as f:
                rows = [{k.strip(): v for k, v in r.items() if k} for r in csv.DictReader(f)]
            key95, key50 = "metrics/mAP50-95(B)", "metrics/mAP50(B)"
            scored = [r for r in rows if r.get(key95)]
            if scored:
                best = max(scored, key=lambda r: float(r[key95]))
                info.update(
                    epochs_done=len(rows),
                    best_epoch=int(float(best.get("epoch", 0))),
                    map50=round(float(best.get(key50) or 0), 4),
                    map50_95=round(float(best[key95]), 4),
                )
        except (OSError, ValueError, KeyError):
            pass
    args = run_dir / "args.yaml"
    if args.is_file():
        try:
            for line in args.read_text(encoding="utf-8").splitlines():
                key, _, value = line.partition(":")
                if key in ("imgsz", "epochs", "model"):
                    info[f"train_{key}"] = value.strip()
        except OSError:
            pass
    return info


def discover_models(roots: Iterable[Path], extra_dirs: Iterable[str] = ()) -> List[Dict[str, Any]]:
    seen: set[Path] = set()
    models: List[Dict[str, Any]] = []
    dirs = [(Path(r), "project") for r in roots] + [(Path(d).expanduser(), "custom") for d in extra_dirs]
    for root, source in dirs:
        if not root.is_dir():
            continue
        for path in _walk_pt(root):
            resolved = path.resolve()
            if resolved in seen or len(models) >= MAX_FILES:
                continue
            seen.add(resolved)
            try:
                stat = path.stat()
            except OSError:
                continue
            run = _run_info(path)
            try:
                label = str(path.relative_to(root))
            except ValueError:
                label = path.name
            models.append({
                "filename": f"{run['run']}/{path.name}" if run else label,
                "path": str(path),
                "size_mb": round(stat.st_size / (1024 * 1024), 2),
                "modified_at": stat.st_mtime,
                "source": "run" if run else source,
                "kind": path.stem if path.stem in ("best", "last") else None,
                "folder": str(root),
                "run": run,
                # Not loadable: listed (so it is clear why it is not usable) but not selectable.
                "unusable": placeholder_reason(path, stat.st_size),
            })
    # Training runs first (most recently updated run first, best.pt before last.pt), then the rest by name.
    run_updated: Dict[str, float] = {}
    for m in models:
        if m["run"]:
            key = str(Path(m["path"]).parent)
            run_updated[key] = max(run_updated.get(key, 0.0), m["modified_at"])
    models.sort(
        key=lambda m: (
            bool(m["unusable"]),
            m["source"] != "run",
            -run_updated.get(str(Path(m["path"]).parent), 0.0),
            m["kind"] != "best",
            m["filename"],
        )
    )
    return models
