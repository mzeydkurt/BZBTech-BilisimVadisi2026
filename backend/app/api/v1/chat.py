"""Sohbet, arama ve katılım terminolojisi denetim uç noktası."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat_service import process_chat_query

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
def chat_query(req: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    """Doğal dil sorusunu işler, katılım terminolojisini denetler ve sonuçları döndürür."""
    return process_chat_query(db, req)
