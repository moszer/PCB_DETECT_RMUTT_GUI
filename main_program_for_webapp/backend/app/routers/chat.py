"""AI chat about the inspected board (OpenRouter)."""
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..services import chat_service
from .inspection import _storage_image

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., max_length=8000)


class ChatRequest(BaseModel):
    messages: List[ChatMessage] = Field(..., min_length=1, max_length=40)
    context: Dict[str, Any] = Field(default_factory=dict)
    image_url: Optional[str] = None


@router.get("/status")
def chat_status():
    return {"configured": chat_service.configured(), "model": chat_service.model_name()}


@router.post("")
async def chat(req: ChatRequest):
    """Streams the reply as plain text chunks."""
    if not chat_service.configured():
        raise HTTPException(503, "ยังไม่ได้ตั้งค่า OPENROUTER_API_KEY ใน backend/.env")
    image = chat_service.image_data_url(_storage_image(req.image_url)) if req.image_url else None
    messages = chat_service.build_messages([m.model_dump() for m in req.messages], req.context, image)
    return StreamingResponse(chat_service.stream_reply(messages), media_type="text/plain; charset=utf-8",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
