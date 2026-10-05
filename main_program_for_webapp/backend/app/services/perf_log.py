"""Performance log for comparing machines (e.g. a computer vs a Jetson, thesis table 4.13).

- system_info(): the machine, software versions, model file/precision and power settings.
- record(): one JSON line per inference in data/perf/perf-YYYY-MM-DD.jsonl (raw data).
- Benchmarks (fixed image set + mAP50) are saved in data/benchmarks/ by benchmark.py.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import re
import socket
import subprocess
import threading
import time
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

import psutil

from ..config import STORAGE_DIR

logger = logging.getLogger(__name__)

PERF_DIR = STORAGE_DIR / "perf"
BENCH_DIR = STORAGE_DIR / "benchmarks"
SESSION = uuid.uuid4().hex[:8]  # one per backend start, to tell test sessions apart
_lock = threading.Lock()


def _read(path: str) -> Optional[str]:
    try:
        return Path(path).read_text(errors="ignore").replace("\x00", "").strip()
    except OSError:
        return None


def _cmd(*args: str) -> Optional[str]:
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=5, check=False).stdout.strip()
        return out or None
    except (OSError, subprocess.SubprocessError):
        return None


@lru_cache(maxsize=1)
def _static_info() -> Dict[str, Any]:
    """Facts that don't change while the backend runs."""
    info: Dict[str, Any] = {
        "hostname": socket.gethostname(),
        "os": platform.platform(),
        "python": platform.python_version(),
        "cpu_cores": psutil.cpu_count(logical=True),
        "ram_gb": round(psutil.virtual_memory().total / 1024 ** 3, 1),
    }
    if platform.system() == "Darwin":
        info["board"] = _cmd("sysctl", "-n", "hw.model")
        info["cpu"] = _cmd("sysctl", "-n", "machdep.cpu.brand_string")
        ver = _cmd("sw_vers", "-productVersion")
        info["os"] = f"macOS {ver}" if ver else info["os"]
    else:
        info["board"] = _read("/proc/device-tree/model") or _read("/sys/devices/virtual/dmi/id/product_name")
        cpuinfo = _read("/proc/cpuinfo") or ""
        m = re.search(r"model name\s*:\s*(.+)", cpuinfo)
        info["cpu"] = m.group(1).strip() if m else platform.processor() or platform.machine()
        osr = _read("/etc/os-release") or ""
        m = re.search(r'PRETTY_NAME="([^"]+)"', osr)
        if m:
            info["os"] = m.group(1)
        l4t = _read("/etc/nv_tegra_release")
        if l4t:
            m = re.search(r"R(\d+).*REVISION:\s*([\d.]+)", l4t)
            info["l4t"] = f"R{m.group(1)}.{m.group(2)}" if m else l4t.splitlines()[0]
            jp = _cmd("dpkg-query", "-W", "-f=${Version}", "nvidia-jetpack")
            info["jetpack"] = jp.split("+")[0] if jp else None
    versions = {}
    for mod in ("torch", "torchvision", "ultralytics", "cv2", "numpy"):
        try:
            versions[mod] = __import__(mod).__version__
        except Exception:  # noqa: BLE001
            versions[mod] = None
    try:
        import torch

        versions["cuda"] = torch.version.cuda
        versions["cudnn"] = torch.backends.cudnn.version() if torch.backends.cudnn.is_available() else None
        if torch.cuda.is_available():
            info["gpu"] = torch.cuda.get_device_name(0)
        elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            info["gpu"] = "Apple GPU (MPS)"
    except Exception:  # noqa: BLE001
        pass
    info["versions"] = versions
    return info


@lru_cache(maxsize=8)
def _model_fingerprint(path: str, size: int, mtime: float) -> Dict[str, Any]:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(1024 * 1024):
            digest.update(chunk)
    return {"sha256": digest.hexdigest()[:16], "size_mb": round(size / 1024 ** 2, 1)}


def model_info(infer=None) -> Dict[str, Any]:
    """The loaded model (the station's, or the one passed in, e.g. by the standalone benchmark)."""
    from .inference_service import inference_service

    inference_service = infer or inference_service
    path = inference_service.model_path or ""
    info: Dict[str, Any] = {"file": Path(path).name if path else None, "path": path, "format": Path(path).suffix.lstrip(".") or None}
    # Weights run as loaded: FP32 (the station does not convert to FP16/INT8).
    info["precision"] = "FP32"
    if path and os.path.isfile(path):
        st = os.stat(path)
        info.update(_model_fingerprint(path, st.st_size, st.st_mtime))
    dev = inference_service.device_info
    info["device"] = dev.label if dev else None
    return info


def system_info(infer=None) -> Dict[str, Any]:
    """Machine + software + model + current power settings (for the comparison table)."""
    info = {**_static_info(), "model": model_info(infer), "session": SESSION, "time": time.time()}
    try:
        from .hardware_service import hardware_service, is_jetson

        if is_jetson():
            hw = hardware_service.snapshot()
            mode = hw.get("power_mode") or {}
            names = {m["id"]: m["name"] for m in mode.get("modes", [])}
            info["power"] = {
                "mode": names.get(mode.get("current"), mode.get("current")),
                "clocks_max": hw.get("clocks_max"),
                "fan": hw.get("fan"),
            }
    except Exception as exc:  # noqa: BLE001
        logger.debug("power info unavailable: %s", exc)
    return info


def record(tag: str, speed: Dict[str, float], image_shape: Any = None, imgsz: Optional[int] = None, detections: int = 0) -> None:
    """Append one inference to today's JSONL log (never raises)."""
    try:
        from .inference_service import inference_service

        entry = {
            "t": round(time.time(), 3),
            "session": SESSION,
            "tag": tag,
            "host": _static_info()["hostname"],
            "device": inference_service.device_info.label if inference_service.device_info else None,
            "model": Path(inference_service.model_path or "").name or None,
            "imgsz": imgsz,
            "image": list(image_shape[:2]) if image_shape is not None else None,
            "detections": detections,
            **{f"{k}_ms": round(float(v), 2) for k, v in speed.items()},
        }
        PERF_DIR.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False)
        with _lock, open(PERF_DIR / f"perf-{time.strftime('%Y-%m-%d')}.jsonl", "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception as exc:  # noqa: BLE001 - logging must never break an inspection
        logger.debug("perf log write failed: %s", exc)
