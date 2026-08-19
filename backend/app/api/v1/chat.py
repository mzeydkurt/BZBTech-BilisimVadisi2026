"""Sohbet, arama ve katılım terminolojisi denetim uç noktası."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import DbSession
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat_service import process_chat_query

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
def chat_query(
    req: ChatRequest,
    db: DbSession,
) -> ChatResponse:
    """Doğal dil sorusunu işler, katılım terminolojisini denetler ve sonuçları döndürür."""
    return process_chat_query(db, req)
