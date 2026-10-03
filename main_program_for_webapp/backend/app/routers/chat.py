"""AI chat about the inspected board (Gemini or OpenRouter) and the station-wide agent."""
import asyncio
import json
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..services import chat_service, chat_store
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


@router.get("/status")
def chat_status():
    return {"configured": chat_service.configured(), "provider": chat_service.provider(), "model": chat_service.model_name()}


@router.post("")
async def chat(req: ChatRequest):
    """Streams the reply as plain text chunks."""
    if not chat_service.configured():
        key = "GEMINI_API_KEY" if chat_service.provider() == "gemini" else "OPENROUTER_API_KEY"
        raise HTTPException(503, f"ยังไม่ได้ตั้งค่า {key} ใน backend/.env")
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
    try:
        while True:
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
