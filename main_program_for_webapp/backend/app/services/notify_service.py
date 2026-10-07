"""Alerts after a scan: Telegram (bot) and/or a webhook (Discord, Slack, a LINE bot relay…).

Rules (all optional): a board FAILs, a scan stops with an error, N boards in a row FAIL, and
the yield of the last N boards drops below a threshold (sent once when it crosses, again only
after it has recovered). Simulated scans are left out unless asked for.

The bot token and the webhook URL are secrets: kept in backend/.env (mode 600, like the AI
keys) and only shown masked. The rules and the Telegram chat id live in notify.json. Sending
runs in a background thread, so a slow or unreachable service never holds up a scan.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from ..config import STORAGE_DIR, settings

logger = logging.getLogger(__name__)

CONFIG_FILE = STORAGE_DIR / "notify.json"
TOKEN_VAR = "TELEGRAM_BOT_TOKEN"
WEBHOOK_VAR = "NOTIFY_WEBHOOK_URL"
TIMEOUT = 10.0

DEFAULTS: Dict[str, Any] = {
    "enabled": False,
    "telegram_chat_id": "",
    "on_fail": True,
    "on_error": True,
    "fail_streak": 3,          # 0 = off
    "yield_below_pct": 0.0,    # 0 = off
    "yield_window": 20,
    "send_photo": True,
    "include_simulation": False,
}
_TOKEN_RE = re.compile(r"^\d{5,15}:[A-Za-z0-9_-]{20,80}$")
_CHAT_RE = re.compile(r"^(-?\d{1,20}|@[A-Za-z0-9_]{4,64})$")
_lock = threading.Lock()


class NotifyError(ValueError):
    """Invalid setting (shown as is)."""


def _mask(v: Optional[str]) -> Optional[str]:
    if not v:
        return None
    return "••••" if len(v) < 12 else f"{v[:6]}…{v[-4:]}"


def _load() -> Dict[str, Any]:
    try:
        data = json.loads(CONFIG_FILE.read_text())
    except (OSError, ValueError):
        data = {}
    return {**DEFAULTS, **{k: v for k, v in data.items() if k in DEFAULTS or k == "yield_alerted"}}


def _save(data: Dict[str, Any]) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    tmp.replace(CONFIG_FILE)


def config() -> Dict[str, Any]:
    """What the settings page shows (secrets masked)."""
    data = _load()
    data.pop("yield_alerted", None)
    token, hook = os.environ.get(TOKEN_VAR), os.environ.get(WEBHOOK_VAR)
    return {**data, "telegram_token_set": bool(token), "telegram_token_hint": _mask(token),
            "webhook_set": bool(hook), "webhook_hint": _mask(hook)}


def update(changes: Dict[str, Any], env_path: Optional[Path] = None) -> Dict[str, Any]:
    """Apply settings. telegram_token / webhook_url: "" removes, None leaves as is."""
    from .ai_settings import ENV_PATH, _write_env

    data = _load()
    for key in ("enabled", "on_fail", "on_error", "send_photo", "include_simulation"):
        if changes.get(key) is not None:
            data[key] = bool(changes[key])
    if changes.get("telegram_chat_id") is not None:
        chat = str(changes["telegram_chat_id"]).strip()
        if chat and not _CHAT_RE.match(chat):
            raise NotifyError("Chat ID ต้องเป็นตัวเลข (เช่น 123456789 หรือ -100… ของกลุ่ม) หรือ @ชื่อช่อง")
        data["telegram_chat_id"] = chat
    if changes.get("fail_streak") is not None:
        data["fail_streak"] = max(0, min(50, int(changes["fail_streak"])))
    if changes.get("yield_below_pct") is not None:
        data["yield_below_pct"] = max(0.0, min(100.0, float(changes["yield_below_pct"])))
    if changes.get("yield_window") is not None:
        data["yield_window"] = max(3, min(500, int(changes["yield_window"])))
    secrets: Dict[str, Optional[str]] = {}
    token = changes.get("telegram_token")
    if token is not None:
        token = token.strip()
        if token and not _TOKEN_RE.match(token):
            raise NotifyError("รูปแบบ Bot token ไม่ถูกต้อง (ได้จาก @BotFather เช่น 123456:ABC-…)")
        secrets[TOKEN_VAR] = token or None
    hook = changes.get("webhook_url")
    if hook is not None:
        hook = hook.strip()
        if hook and (not re.match(r"^https://[^\s\"']{8,500}$", hook)):
            raise NotifyError("Webhook ต้องเป็นลิงก์ https://…")
        secrets[WEBHOOK_VAR] = hook or None
    with _lock:
        _save(data)
        if secrets:
            _write_env(secrets, env_path or ENV_PATH)
            for var, value in secrets.items():
                if value is None:
                    os.environ.pop(var, None)
                else:
                    os.environ[var] = value
    return config()


# ── sending ──────────────────────────────────────────────────────────────────

def _send(text: str, photo: Optional[str] = None, details: Optional[Dict[str, Any]] = None) -> List[str]:
    """Send to every configured channel; returns the problems (empty when all went out)."""
    data = _load()
    problems: List[str] = []
    token, chat = os.environ.get(TOKEN_VAR), data.get("telegram_chat_id")
    if token and chat:
        try:
            base = f"https://api.telegram.org/bot{token}"
            if photo and Path(photo).is_file() and data.get("send_photo"):
                with open(photo, "rb") as f:
                    r = httpx.post(f"{base}/sendPhoto", data={"chat_id": chat, "caption": text[:1000]},
                                   files={"photo": ("point.jpg", f, "image/jpeg")}, timeout=TIMEOUT)
            else:
                r = httpx.post(f"{base}/sendMessage", json={"chat_id": chat, "text": text, "disable_web_page_preview": True}, timeout=TIMEOUT)
            if r.status_code != 200:
                problems.append(f"Telegram: {r.json().get('description', r.status_code) if r.headers.get('content-type', '').startswith('application/json') else r.status_code}")
        except Exception as exc:  # network down, bad token…
            problems.append(f"Telegram: {exc}")
    hook = os.environ.get(WEBHOOK_VAR)
    if hook:
        try:
            # "text" for Slack-style hooks, "content" for Discord; the rest for custom receivers.
            r = httpx.post(hook, json={"text": text, "content": text[:1900], **(details or {})}, timeout=TIMEOUT)
            if r.status_code >= 300:
                problems.append(f"Webhook: HTTP {r.status_code}")
        except Exception as exc:
            problems.append(f"Webhook: {exc}")
    if not (token and chat) and not hook:
        problems.append("ยังไม่ได้ตั้งค่าช่องทาง (Telegram bot + chat ID หรือ webhook)")
    for p in problems:
        logger.warning("Notification not sent: %s", p)
    return problems


def send_test() -> List[str]:
    return _send(f"🔔 ทดสอบการแจ้งเตือนจากสถานี {settings.station_name} — ถ้าเห็นข้อความนี้ การแจ้งเตือนใช้ได้แล้ว",
                 details={"event": "test", "station": settings.station_name})


def _recent_boards(n: int, include_sim: bool) -> List[str]:
    """Verdicts of the last n finished production scans (newest first)."""
    from .storage_service import storage_service

    sim = "" if include_sim else " AND is_simulation = 0"
    with storage_service._get_connection() as conn:
        rows = conn.execute(
            "SELECT overall_verdict FROM runs WHERE status = 'complete' AND is_golden_scan = 0" + sim +
            " ORDER BY created_at DESC LIMIT ?", (n,)).fetchall()
    return [r[0] for r in rows]


def messages_for(report: Any, data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The alerts a finished scan triggers under these rules (pure; for tests too)."""
    out: List[Dict[str, Any]] = []
    plan = report.plan
    who = " · ".join(x for x in (plan.board_name, f"เลข {plan.serial}" if plan.serial else None) if x) or report.id
    details = {"station": settings.station_name, "run_id": report.id, "board": plan.board_name, "serial": plan.serial,
               "verdict": report.overall_verdict, "status": report.status, "pass": report.pass_count,
               "fail": report.fail_count, "review": report.review_count, "points": len(report.points)}
    if report.status == "error" and data["on_error"]:
        out.append({"text": f"⚠️ สแกนผิดพลาด · {who}\n{report.error_message or ''}".strip(), "details": {**details, "event": "error"}})
    if report.status != "complete":
        return out
    if report.overall_verdict == "FAIL" and data["on_fail"]:
        bad = [r for r in report.results if r.verdict == "FAIL"]
        lines = []
        for r in bad[:6]:
            parts = [f"{(c.get('expected') or {}).get('name', '?')} {'ขาด' if c.get('status') == 'missing' else 'ผิดชนิด'}"
                     for c in (r.component_eval or []) if c.get("status") in ("missing", "wrong")]
            lines.append(f"• {r.name or f'จุด {r.point_index + 1}'}: {', '.join(parts[:4]) or r.reason or 'ไม่ผ่าน'}")
        photo = bad[0].annotated_path if bad else None
        out.append({"text": f"❌ FAIL · {who}\nไม่ผ่าน {report.fail_count}/{len(report.points)} จุด\n" + "\n".join(lines),
                    "photo": photo, "details": {**details, "event": "fail"}})
    return out


def trend_messages(data: Dict[str, Any], recent: List[str]) -> List[Dict[str, Any]]:
    """Streak and yield alerts from the latest production verdicts (newest first)."""
    out: List[Dict[str, Any]] = []
    n = data["fail_streak"]
    if n and recent and recent[0] == "FAIL":
        streak = next((i for i, v in enumerate(recent) if v != "FAIL"), len(recent))
        if streak and streak % n == 0:
            out.append({"text": f"🚨 FAIL ติดกัน {streak} บอร์ด — ตรวจเครื่อง/ชิ้นส่วนด้วย", "details": {"event": "fail_streak", "streak": streak}})
    limit, window = data["yield_below_pct"], data["yield_window"]
    if limit and len(recent) >= window:
        last = recent[:window]
        decided = [v for v in last if v in ("PASS", "FAIL")]
        if decided:
            y = 100.0 * sum(v == "PASS" for v in decided) / len(decided)
            if y < limit and not data.get("yield_alerted"):
                out.append({"text": f"📉 Yield {window} บอร์ดล่าสุดเหลือ {y:.0f}% (ต่ำกว่า {limit:g}%)",
                            "details": {"event": "yield_low", "yield_pct": round(y, 1)}, "set_alerted": True})
            elif y >= limit and data.get("yield_alerted"):
                out.append({"text": None, "set_alerted": False})  # recovered: arm again, say nothing
    return out


def on_run_finished(report: Any) -> None:
    """Called when a scan ends; evaluates the rules and sends in the background."""
    data = _load()
    if not data["enabled"] or report.is_golden_scan or (report.is_simulation and not data["include_simulation"]):
        return

    def work():
        try:
            msgs = messages_for(report, data)
            if report.status == "complete":
                window = max(data["yield_window"], data["fail_streak"] * 4, 1)
                msgs += trend_messages(data, _recent_boards(window, data["include_simulation"]))
            for m in msgs:
                if "set_alerted" in m:
                    with _lock:
                        cur = _load()
                        cur["yield_alerted"] = m["set_alerted"]
                        _save(cur)
                if m.get("text"):
                    _send(m["text"], m.get("photo"), m.get("details"))
        except Exception:
            logger.exception("Scan notification failed")

    threading.Thread(target=work, name="notify", daemon=True).start()
