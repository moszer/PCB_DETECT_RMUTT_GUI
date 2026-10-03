"""AI chat about an inspected board via Google Gemini (default) or OpenRouter.

The board context (photo, detected parts, OCR'd markings, verdict) goes in with every
request so the model can explain what the board is and what it is for. The API key is
read from the environment (backend/.env) and never sent to the browser. AI_PROVIDER picks
"gemini" or "openrouter" (default: gemini when GEMINI_API_KEY is set).
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from contextlib import aclosing
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

import cv2
import httpx

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "qwen/qwen3.8-27b:free"
# Free models are often overloaded upstream (HTTP 429 "Provider returned error"); OpenRouter
# moves on to these (also free, with image input) when the main one is busy.
DEFAULT_FALLBACKS = "google/gemma-4-31b-it:free,google/gemma-4-26b-a4b-it:free"
RETRY_DELAYS_SEC = (3, 6)

SYSTEM_PROMPT = """คุณคือผู้ช่วยวิศวกรอิเล็กทรอนิกส์ประจำสถานีตรวจ PCB (AOI) ของ RMUTT
ตอบเป็นภาษาไทย กระชับ เข้าใจง่าย ใช้ศัพท์เทคนิคภาษาอังกฤษได้ตามปกติ

คุณได้รับภาพบอร์ดหนึ่งจุดตรวจ พร้อมข้อมูลจากระบบ: ชิ้นส่วนที่ YOLO ตรวจพบ ตัวอักษรบนชิ้นที่อ่านด้วย OCR และผลตรวจ
- ใช้เบอร์ชิปจาก OCR ระบุว่าชิปคืออะไร ทำหน้าที่อะไร (เช่น MAX232 = แปลงระดับสัญญาณ RS-232)
- อนุมานว่าบอร์ดนี้ใช้ทำอะไรจากชิ้นส่วนทั้งหมดรวมกัน และบอกว่าเห็นอะไรในภาพประกอบ
- ภาพเป็นแค่บางส่วนของบอร์ด และ OCR อาจอ่านผิดบางตัว ถ้าไม่แน่ใจให้บอกตรงๆ ว่าเป็นการคาดการณ์
- อย่าแต่งสเปกหรือตัวเลขที่ไม่รู้จริง"""


GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse"
# Tried in order: the next one is used when a model is overloaded (503) or rate-limited (429).
DEFAULT_GEMINI_MODELS = "gemini-flash-latest,gemini-3.5-flash,gemini-2.5-flash,gemini-flash-lite-latest"
RETRYABLE = (429, 500, 502, 503, 504)


def provider() -> str:
    chosen = (os.environ.get("AI_PROVIDER") or "").strip().lower()
    if chosen in ("gemini", "openrouter"):
        return chosen
    return "gemini" if os.environ.get("GEMINI_API_KEY") else "openrouter"


def configured() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY" if provider() == "gemini" else "OPENROUTER_API_KEY"))


def gemini_models() -> List[str]:
    raw = os.environ.get("GEMINI_MODELS") or os.environ.get("GEMINI_MODEL") or DEFAULT_GEMINI_MODELS
    return [m.strip() for m in raw.split(",") if m.strip()]


def model_name() -> str:
    if provider() == "gemini":
        return gemini_models()[0]
    return os.environ.get("OPENROUTER_MODEL") or DEFAULT_MODEL


def fallback_models() -> List[str]:
    raw = os.environ.get("OPENROUTER_FALLBACK_MODELS", DEFAULT_FALLBACKS)
    return [m.strip() for m in raw.split(",") if m.strip() and m.strip() != model_name()]


def image_data_url(path: Path, max_side: int = 1280) -> Optional[str]:
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        return None
    h, w = img.shape[:2]
    scale = min(1.0, max_side / max(h, w))
    if scale < 1:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    ok, jpeg = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    return "data:image/jpeg;base64," + base64.b64encode(jpeg.tobytes()).decode() if ok else None


def context_text(ctx: Dict[str, Any]) -> str:
    """Board facts from the inspection, as plain text for the model."""
    lines = ["ข้อมูลจากระบบตรวจ:"]
    if ctx.get("point_name"):
        lines.append(f"- จุดตรวจ: {ctx['point_name']}")
    if ctx.get("verdict"):
        lines.append(f"- ผลตรวจ: {ctx['verdict']}" + (f" ({ctx['reason']})" if ctx.get("reason") else ""))
    counts = ctx.get("counts") or {}
    if counts:
        lines.append("- ชิ้นส่วนที่ตรวจพบ: " + ", ".join(f"{k} ×{v}" for k, v in counts.items()))
    parts = [p for p in ctx.get("parts") or [] if p.get("text") or p.get("status")]
    if parts:
        lines.append("- รายละเอียดชิ้น (ชื่อ / สถานะ / ตัวอักษรที่อ่านได้):")
        for p in parts[:80]:
            text = " ".join(str(p.get("text") or "").split())
            status = f" [{p['status']}]" if p.get("status") else ""
            lines.append(f"  • {p.get('name', '?')}{status}" + (f": \"{text}\"" if text else ""))
    if not any(p.get("text") for p in ctx.get("parts") or []):
        lines.append("- (ยังไม่ได้อ่านตัวอักษรบนชิ้น — ถ้าต้องการให้ระบุชิปแม่นขึ้น กด \"อ่านตัวอักษรทุกชิ้น\" ก่อน)")
    return "\n".join(lines)


def build_messages(history: List[Dict[str, str]], ctx: Dict[str, Any], image: Optional[str]) -> List[Dict[str, Any]]:
    intro: List[Dict[str, Any]] = [{"type": "text", "text": context_text(ctx)}]
    if image:
        intro.append({"type": "image_url", "image_url": {"url": image}})
    messages: List[Dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": intro},
                                      {"role": "assistant", "content": "รับทราบข้อมูลบอร์ดแล้ว ถามได้เลยครับ"}]
    for m in history[-20:]:
        if m.get("role") in ("user", "assistant") and m.get("content"):
            messages.append({"role": m["role"], "content": str(m["content"])[:4000]})
    return messages


def to_gemini(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """OpenAI-style messages -> Gemini generateContent body (system instruction, user/model turns, inline images)."""
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system" and isinstance(m["content"], str))
    contents = []
    for m in messages:
        if m["role"] == "system":
            continue
        parts: List[Dict[str, Any]] = []
        items = m["content"] if isinstance(m["content"], list) else [{"type": "text", "text": m["content"]}]
        for item in items:
            if item.get("type") == "text":
                parts.append({"text": item["text"]})
            elif item.get("type") == "image_url":
                url = item["image_url"]["url"]
                header, _, data = url.partition(",")
                mime = header.split(":", 1)[-1].split(";", 1)[0] or "image/jpeg"
                parts.append({"inlineData": {"mimeType": mime, "data": data}})
        contents.append({"role": "model" if m["role"] == "assistant" else "user", "parts": parts})
    body: Dict[str, Any] = {"contents": contents, "generationConfig": {"maxOutputTokens": 8192}}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    return body


async def stream_reply(messages: List[Dict[str, Any]]) -> AsyncIterator[str]:
    """Yield text deltas from the configured provider; errors come back as a readable message."""
    if provider() == "gemini":
        async for piece in _stream_gemini(messages):
            yield piece
        return
    async for piece in _stream_openrouter(messages):
        yield piece


async def _stream_gemini(messages: List[Dict[str, Any]]) -> AsyncIterator[str]:
    headers = {"x-goog-api-key": os.environ.get("GEMINI_API_KEY", ""), "Content-Type": "application/json"}
    body = to_gemini(messages)
    models = gemini_models()
    # Each model once, then the first model again after a pause (busy spikes are short).
    plan = [(m, 0.0) for m in models] + [(models[0], 4.0)]
    last_error = ""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=15)) as client:
            for model, pause in plan:
                if pause:
                    await asyncio.sleep(pause)
                async with client.stream("POST", GEMINI_URL.format(model=model), headers=headers, json=body) as res:
                    if res.status_code != 200:
                        detail = (await res.aread()).decode("utf-8", "replace")
                        try:
                            detail = json.loads(detail).get("error", {}).get("message", detail)
                        except ValueError:
                            pass
                        last_error = f"HTTP {res.status_code} ({model}): {detail[:200]}"
                        if res.status_code in RETRYABLE:
                            logger.info("Gemini %s busy (%s), trying next", model, res.status_code)
                            continue
                        yield f"\n⚠️ AI ตอบไม่ได้ — {last_error}"
                        return
                    async for line in res.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        try:
                            chunk = json.loads(line[5:])
                        except ValueError:
                            continue
                        for cand in chunk.get("candidates") or []:
                            for part in (cand.get("content") or {}).get("parts") or []:
                                if part.get("text") and not part.get("thought"):
                                    yield part["text"]
                    return
        yield f"\n⚠️ Gemini ทุกรุ่นไม่ว่างตอนนี้ (ไม่ใช่โควตาหมดเสมอไป) ลองใหม่ในอีกสักครู่ — {last_error}"
    except httpx.HTTPError as exc:
        logger.warning("Gemini request failed: %s", exc)
        yield f"\n⚠️ เชื่อมต่อ AI ไม่ได้: {exc.__class__.__name__}"


async def _stream_openrouter(messages: List[Dict[str, Any]]) -> AsyncIterator[str]:
    """Yield text deltas from OpenRouter (SSE)."""
    headers = {
        "Authorization": f"Bearer {os.environ.get('OPENROUTER_API_KEY', '')}",
        "Content-Type": "application/json",
        "X-Title": "RMUTT PCB AOI Station",
    }
    body: Dict[str, Any] = {"model": model_name(), "messages": messages, "stream": True, "max_tokens": 4000}
    fallbacks = fallback_models()
    if fallbacks:
        body["models"] = [model_name(), *fallbacks]
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=15)) as client:
            for attempt in range(len(RETRY_DELAYS_SEC) + 1):
                retry = False
                async with aclosing(_one_attempt(client, headers, body, last=attempt == len(RETRY_DELAYS_SEC))) as pieces:
                    async for piece in pieces:
                        if piece is None:  # busy upstream: wait and try again
                            retry = True
                            break
                        yield piece
                if not retry:
                    return
                await asyncio.sleep(RETRY_DELAYS_SEC[attempt])
    except httpx.HTTPError as exc:
        logger.warning("OpenRouter request failed: %s", exc)
        yield f"\n⚠️ เชื่อมต่อ AI ไม่ได้: {exc.__class__.__name__}"


async def _one_attempt(client: httpx.AsyncClient, headers: Dict[str, str], body: Dict[str, Any], last: bool) -> AsyncIterator[Optional[str]]:
    """Text deltas of one request; yields None (once, before any text) when it should be retried."""
    async with client.stream("POST", OPENROUTER_URL, headers=headers, json=body) as res:
        if res.status_code != 200:
            detail = (await res.aread()).decode("utf-8", "replace")
            try:
                detail = json.loads(detail).get("error", {}).get("message", detail)
            except ValueError:
                pass
            if res.status_code in (429, 502, 503) and not last:
                logger.info("OpenRouter busy (HTTP %s), retrying", res.status_code)
                yield None
                return
            hint = (" — เซิร์ฟเวอร์โมเดลฟรีทุกตัวคิวเต็มตอนนี้ (ไม่ใช่โควตาหมด) ลองใหม่ในอีกสักครู่"
                    if res.status_code == 429 else "")
            yield f"\n⚠️ AI ตอบไม่ได้ (HTTP {res.status_code}): {detail[:300]}{hint}"
            return
        async for line in res.aiter_lines():
            if not line.startswith("data:"):
                continue  # keep-alive comments
            data = line[5:].strip()
            if data == "[DONE]":
                return
            try:
                chunk = json.loads(data)
            except ValueError:
                continue
            if chunk.get("error"):
                yield f"\n⚠️ {chunk['error'].get('message', 'error')}"
                return
            delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
            if delta.get("content"):
                yield delta["content"]
