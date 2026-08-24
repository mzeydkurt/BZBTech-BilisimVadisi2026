"""Kanıtlı arama uç noktası — doğal dil sorusu, kanıt listesi ve denetim."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status

from app.api.deps import DbSession
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ChatSessionCreateResponse,
    ChatSessionDetail,
)
from app.services import chat_session_service as sessions
from app.services.chat_service import process_chat_query

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat_query(
    req: ChatRequest,
    db: DbSession,
) -> ChatResponse:
    """Doğal dil sorusunu işler ve kanıtlı yanıt döndürür.

    ⚠️ `async` ZORUNLU. Yanıt üretimi yerel modele `await` ile gidiyor;
    senkron bir uç, tek bir yavaş model çağrısında (bu donanımda ~70 sn)
    FastAPI'nin iş parçacığı havuzunu tutar ve diğer istekleri bekletirdi.

    ⚠️ BOŞ SONUÇ HATA DEĞİLDİR. Kanıt bulunamadığında yanıt yine HTTP 200
    döner; `results` boş, `relaxation_hints` doludur. 4xx döndürmek arayüzde
    `ErrorState` tetikler ve "veri yok" ile "istek başarısız" karışır.
    """
    return await process_chat_query(db, req)


@router.post("/sessions", response_model=ChatSessionCreateResponse)
def create_chat_session(db: DbSession) -> ChatSessionCreateResponse:
    """Yeni sohbet oturumu açar."""
    oturum = sessions.create_session(db)
    db.commit()
    return sessions.create_response(oturum)


@router.get("/sessions/{session_key}", response_model=ChatSessionDetail)
def get_chat_session(session_key: str, db: DbSession) -> ChatSessionDetail:
    """Oturum geçmişini döner (kartlar response_json içinde)."""
    oturum = sessions.get_session_by_key(db, session_key)
    if oturum is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Oturum bulunamadı")
    return sessions.session_detail(oturum)


@router.delete(
    "/sessions/{session_key}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def end_chat_session(session_key: str, db: DbSession) -> Response:
    """Sohbeti sonlandırır — `ended_at` yazar, satır silmez."""
    oturum = sessions.end_session(db, session_key)
    if oturum is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Oturum bulunamadı")
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
