"""AI chat about the inspected board (Gemini or OpenRouter)."""
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
