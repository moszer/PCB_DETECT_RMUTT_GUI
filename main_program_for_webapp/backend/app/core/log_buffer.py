"""The station's recent log lines in memory, so the AI agent can say what happened lately."""
from __future__ import annotations

import logging
import time
from collections import deque
from typing import Any, Deque, Dict, List

# Our own loggers (third-party chatter such as httpx or uvicorn access lines is left out).
_OURS = ("app", "pcb_backend", "machine_service", "inference_service", "aoi_scan_service", "ws_router", "camera_service")


class RingHandler(logging.Handler):
    def __init__(self, capacity: int = 400):
        super().__init__(level=logging.INFO)
        self.records: Deque[Dict[str, Any]] = deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.WARNING and not record.name.startswith(_OURS):
            return
        try:
            msg = record.getMessage()
        except Exception:
            msg = str(record.msg)
        self.records.append({
            "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.created)),
            "level": record.levelname,
            "source": record.name.rsplit(".", 1)[-1],
            "message": msg[:300] + (" …" if len(msg) > 300 else ""),
            "error": record.exc_info[0].__name__ if record.exc_info and record.exc_info[0] else None,
        })


handler = RingHandler()


def install() -> None:
    root = logging.getLogger()
    if handler not in root.handlers:
        root.addHandler(handler)


def recent(min_level: str = "INFO", limit: int = 40) -> List[Dict[str, Any]]:
    floor = logging.getLevelName(min_level.upper())
    floor = floor if isinstance(floor, int) else logging.INFO
    rows = [r for r in handler.records if logging.getLevelName(r["level"]) >= floor]
    return [{k: v for k, v in r.items() if v is not None} for r in rows[-max(1, min(limit, 200)):]]
