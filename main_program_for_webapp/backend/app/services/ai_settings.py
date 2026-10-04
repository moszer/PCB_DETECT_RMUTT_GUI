"""AI assistant settings edited from the web UI, persisted in backend/.env.

Keys are written to the git-ignored backend/.env (mode 600) and applied to the running
process at once. They are never returned to the browser: the UI only sees whether a key
is set and a masked hint such as "AIza…x9Qk".
"""
from __future__ import annotations

import os
import re
import threading
from pathlib import Path
from typing import Dict, Optional

import httpx

from ..config import BACKEND_ROOT

ENV_PATH = BACKEND_ROOT / ".env"
KEY_VARS = {"gemini": "GEMINI_API_KEY", "openrouter": "OPENROUTER_API_KEY"}
MODEL_VARS = {"gemini": "GEMINI_MODELS", "openrouter": "OPENROUTER_MODEL"}
# Printable, no spaces/quotes/newlines: nothing that could break or inject into .env.
_KEY_RE = re.compile(r"^[A-Za-z0-9_\-.:]{8,300}$")
_MODEL_RE = re.compile(r"^[A-Za-z0-9_\-.:/@,]{1,500}$")
_lock = threading.Lock()


class SettingsError(ValueError):
    """Invalid value (shown to the user as-is)."""


def mask(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    if len(value) < 12:
        return "••••"
    return f"{value[:4]}…{value[-4:]}"


def check_key(value: str) -> str:
    value = value.strip()
    if not _KEY_RE.match(value):
        raise SettingsError("รูปแบบ API key ไม่ถูกต้อง (8–300 ตัวอักษร ไม่มีช่องว่างหรือเครื่องหมายคำพูด)")
    return value


def check_models(value: str) -> str:
    value = ",".join(m.strip() for m in value.split(",") if m.strip())
    if value and not _MODEL_RE.match(value):
        raise SettingsError("ชื่อโมเดลไม่ถูกต้อง")
    return value


def current() -> Dict[str, object]:
    from . import chat_service  # late import: chat_service reads os.environ at call time

    return {
        "provider": chat_service.provider(),
        "configured": chat_service.configured(),
        "model": chat_service.model_name(),
        "providers": {
            name: {
                "key_set": bool(os.environ.get(var)),
                "key_hint": mask(os.environ.get(var)),
                "models": os.environ.get(MODEL_VARS[name], ""),
            }
            for name, var in KEY_VARS.items()
        },
    }


def _write_env(changes: Dict[str, Optional[str]], path: Path) -> None:
    """Set (or remove, when None) KEY=VALUE lines, keeping comments and other settings."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    remaining = dict(changes)
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if key in remaining:
            value = remaining.pop(key)
            if value is not None:
                out.append(f"{key}={value}")
            continue
        out.append(line)
    out += [f"{k}={v}" for k, v in remaining.items() if v is not None]
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def update(
    provider: Optional[str] = None,
    keys: Optional[Dict[str, Optional[str]]] = None,
    models: Optional[Dict[str, Optional[str]]] = None,
    path: Optional[Path] = None,
) -> Dict[str, object]:
    """Apply and persist. A key of "" removes it; None leaves it unchanged."""
    changes: Dict[str, Optional[str]] = {}
    if provider is not None:
        if provider not in KEY_VARS:
            raise SettingsError("ผู้ให้บริการต้องเป็น gemini หรือ openrouter")
        changes["AI_PROVIDER"] = provider
    for name, value in (keys or {}).items():
        if name not in KEY_VARS or value is None:
            continue
        changes[KEY_VARS[name]] = check_key(value) if value.strip() else None
    for name, value in (models or {}).items():
        if name not in MODEL_VARS or value is None:
            continue
        changes[MODEL_VARS[name]] = check_models(value) or None
    if not changes:
        return current()
    with _lock:
        _write_env(changes, path or ENV_PATH)
        for var, value in changes.items():
            if value is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = value
    return current()


async def test_key(provider: str, key: Optional[str] = None) -> Dict[str, object]:
    """Ask the provider whether the key works (a free metadata call, no generation)."""
    if provider not in KEY_VARS:
        raise SettingsError("ผู้ให้บริการต้องเป็น gemini หรือ openrouter")
    key = check_key(key) if key else os.environ.get(KEY_VARS[provider], "")
    if not key:
        return {"ok": False, "message": "ยังไม่ได้ใส่ API key"}
    if provider == "gemini":
        url, headers = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1", {"x-goog-api-key": key}
    else:
        url, headers = "https://openrouter.ai/api/v1/key", {"Authorization": f"Bearer {key}"}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=8)) as client:
            res = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        return {"ok": False, "message": f"ติดต่อผู้ให้บริการไม่ได้ ({type(exc).__name__}) — ตรวจอินเทอร์เน็ตของสถานี"}
    if res.status_code == 200:
        return {"ok": True, "message": "ใช้งานได้"}
    if res.status_code in (400, 401, 403):
        return {"ok": False, "message": "key ไม่ถูกต้องหรือถูกยกเลิกแล้ว"}
    if res.status_code == 429:
        return {"ok": True, "message": "key ใช้ได้ แต่ตอนนี้โควตาเต็ม (429) — ลองใหม่ภายหลัง"}
    return {"ok": False, "message": f"ผู้ให้บริการตอบ HTTP {res.status_code}"}
