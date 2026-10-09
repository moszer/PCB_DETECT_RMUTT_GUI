"""AI chat about the inspected board (Gemini or OpenRouter) and the station-wide agent."""
import asyncio
import json
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from ..core.security import lease_manager
from ..services import ai_settings, chat_service, chat_store, tts_service
from .inspection import _storage_image

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., max_length=8000)


class ChatRequest(BaseModel):
    messages: List[ChatMessage] = Field(..., min_length=1, max_length=40)
    context: Dict[str, Any] = Field(default_factory=dict)
    image_url: Optional[str] = None
    # Conversation to save the exchange under (the inspected image URL); omit to not save.
    conversation_key: Optional[str] = Field(None, max_length=512)


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


@router.get("/tts/status")
def tts_status():
    """Whether answers can be read with Gemini TTS (otherwise the browser uses its own voice)."""
    return {"available": tts_service.available(), "voice": tts_service.voice(), "model": tts_service.model_name()}


@router.post("/tts")
def tts(req: TTSRequest):
    """One piece of an AI answer as WAV (Gemini TTS, cached). 503 = use the browser voice."""
    try:
        audio, model = tts_service.synthesize(req.text)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except tts_service.TTSUnavailable as exc:
        raise HTTPException(503, str(exc))
    return Response(content=audio, media_type="audio/wav", headers={"X-TTS-Model": model, "Cache-Control": "private, max-age=86400"})


@router.get("/status")
def chat_status():
    return {"configured": chat_service.configured(), "provider": chat_service.provider(), "model": chat_service.model_name()}


class AIConfigUpdate(BaseModel):
    provider: Optional[Literal["gemini", "openrouter"]] = None
    # "" removes a key; omitted/None keeps the saved one.
    gemini_api_key: Optional[str] = Field(None, max_length=300)
    openrouter_api_key: Optional[str] = Field(None, max_length=300)
    gemini_models: Optional[str] = Field(None, max_length=500)
    openrouter_model: Optional[str] = Field(None, max_length=500)


class AIKeyTest(BaseModel):
    provider: Literal["gemini", "openrouter"]
    api_key: Optional[str] = Field(None, max_length=300)  # omit to test the saved key


def _require_control(token: Optional[str]) -> None:
    """Secrets need the operator lease (passcode), even when nobody else holds the station."""
    if not lease_manager.is_operator(token):
        raise HTTPException(403, "ต้องขอสิทธิ์ควบคุมสถานี (รหัสผ่าน) ก่อนแก้ไข AI key")


@router.get("/config")
def ai_config():
    """Provider, models and whether each key is set (masked; the key itself is never sent)."""
    return ai_settings.current()


@router.put("/config")
def update_ai_config(req: AIConfigUpdate, x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token")):
    _require_control(x_operator_token)
    try:
        return ai_settings.update(
            provider=req.provider,
            keys={"gemini": req.gemini_api_key, "openrouter": req.openrouter_api_key},
            models={"gemini": req.gemini_models, "openrouter": req.openrouter_model},
        )
    except ai_settings.SettingsError as exc:
        raise HTTPException(400, str(exc))


@router.post("/config/test")
async def test_ai_key(req: AIKeyTest, x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token")):
    _require_control(x_operator_token)
    try:
        return await ai_settings.test_key(req.provider, req.api_key)
    except ai_settings.SettingsError as exc:
        raise HTTPException(400, str(exc))


@router.post("")
async def chat(req: ChatRequest):
    """Streams the reply as plain text chunks."""
    if not chat_service.configured():
        key = "GEMINI_API_KEY" if chat_service.provider() == "gemini" else "OPENROUTER_API_KEY"
        raise HTTPException(503, f"ยังไม่ได้ตั้งค่า {key} — ใส่ได้ที่ ตั้งค่าสถานี → ผู้ช่วย AI")
    image = chat_service.image_data_url(_storage_image(req.image_url)) if req.image_url else None
    messages = chat_service.build_messages([m.model_dump() for m in req.messages], req.context, image)
    stream = chat_service.stream_reply(messages)
    if req.conversation_key:
        stream = _saving(stream, req.conversation_key, req.messages[-1].content)
    return StreamingResponse(stream, media_type="text/plain; charset=utf-8",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def _saving(stream, key: str, question: str):
    """Pass the reply through and store the exchange when it ends (also if the user stops it)."""
    parts: List[str] = []
    stopped = False
    try:
        async for piece in stream:
            parts.append(piece)
            yield piece
    except BaseException:
        stopped = True  # client went away / pressed stop
        raise
    finally:
        answer = "".join(parts).strip()
        failed = not answer or (answer.startswith("⚠️") and len(parts) <= 2)
        if not failed:
            chat_store.append_exchange(key, question, answer + ("\n\n_(หยุดกลางคัน)_" if stopped else ""))


@router.get("/history")
def chat_history(key: str):
    return {"messages": chat_store.history(key)}


@router.delete("/history")
def clear_chat_history(key: str):
    return {"deleted": chat_store.clear(key)}


# ── Station-wide agent (every page) ──

AGENT_CONVERSATION = "agent:station"


class AgentRequest(BaseModel):
    messages: List[ChatMessage] = Field(..., min_length=1, max_length=40)
    page: Optional[str] = Field(None, max_length=32)


@router.post("/agent")
async def agent(req: AgentRequest):
    """NDJSON stream of agent events (tool steps, navigate, final text); the exchange is saved."""
    from ..services import agent_service

    question = req.messages[-1].content

    async def events():
        answer = ""
        async for line in with_heartbeat(agent_service.run_agent([m.model_dump() for m in req.messages], req.page)):
            event = json.loads(line)
            if event.get("type") == "text":
                answer = event.get("text", "")
            yield line
        if answer:
            chat_store.append_exchange(AGENT_CONVERSATION, question, answer)

    return StreamingResponse(events(), media_type="application/x-ndjson", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


HEARTBEAT_SEC = 5.0


async def with_heartbeat(stream, interval: float = HEARTBEAT_SEC):
    """Pass NDJSON lines through, adding a ping while the agent waits (keeps proxies from timing out)."""
    it = stream.__aiter__()
    pending = asyncio.ensure_future(it.__anext__())
    from ..core.shutdown import shutting_down

    try:
        while not shutting_down.is_set():
            done, _ = await asyncio.wait({pending}, timeout=interval)
            if not done:
                yield json.dumps({"type": "ping"}) + "\n"
                continue
            try:
                line = pending.result()
            except StopAsyncIteration:
                return
            yield line
            pending = asyncio.ensure_future(it.__anext__())
    finally:
        if not pending.done():
            pending.cancel()
        aclose = getattr(stream, "aclose", None)
        if aclose:
            await aclose()


@router.get("/agent/history")
def agent_history():
    return {"messages": chat_store.history(AGENT_CONVERSATION)}


@router.delete("/agent/history")
def clear_agent_history():
    return {"deleted": chat_store.clear(AGENT_CONVERSATION)}
