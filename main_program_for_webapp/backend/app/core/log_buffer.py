"""The station's recent log lines in memory, so the AI agent can say what happened lately."""
from __future__ import annotations

import logging
import os
import re
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

# Secrets must never reach a log line: a Telegram bot token sits in the request URL, which
# httpx logged in full at INFO (run_web.log had it in plain text).
_SECRET_VARS = ("TELEGRAM_BOT_TOKEN", "NOTIFY_WEBHOOK_URL", "GEMINI_API_KEY", "OPENROUTER_API_KEY", "PCB_OPERATOR_PASSCODE")
_BOT_TOKEN = re.compile(r"bot\d{5,15}:[A-Za-z0-9_-]{20,}")


def redact(text: str) -> str:
    text = _BOT_TOKEN.sub("bot***", text)
    for var in _SECRET_VARS:
        value = os.environ.get(var)
        if value and len(value) >= 8 and value in text:
            text = text.replace(value, "***")
    return text


class SecretFilter(logging.Filter):
    """Rewrites the record's message with secrets masked (attached to every root handler)."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        clean = redact(msg)
        if clean != msg:
            record.msg, record.args = clean, None
        return True


_filter = SecretFilter()


def install() -> None:
    root = logging.getLogger()
    if handler not in root.handlers:
        root.addHandler(handler)
    for h in root.handlers:
        if _filter not in h.filters:
            h.addFilter(_filter)
    # Request lines (with URLs) from the HTTP client are noise at INFO, and carry tokens.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


def recent(min_level: str = "INFO", limit: int = 40) -> List[Dict[str, Any]]:
    floor = logging.getLevelName(min_level.upper())
    floor = floor if isinstance(floor, int) else logging.INFO
    rows = [r for r in handler.records if logging.getLevelName(r["level"]) >= floor]
    return [{k: v for k, v in r.items() if v is not None} for r in rows[-max(1, min(limit, 200)):]]
