"""Kanıtlı arama uç noktası — doğal dil sorusu, kanıt listesi ve denetim."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.api.deps import DbSession
from app.schemas.chat import (
    ChatModelsResponse,
    ChatRequest,
    ChatResponse,
    ChatSessionCreateResponse,
    ChatSessionDetail,
    ChatSessionList,
)
from app.services import chat_model_service as chat_models
from app.services import chat_session_service as chat_sessions
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


@router.get("/models", response_model=ChatModelsResponse)
async def list_chat_models() -> ChatModelsResponse:
    """Sohbette seçilebilecek modeller ve sağlık durumları.

    ⚠️ Erişilemeyen model listeden gizlenmez; kullanıcı neden seçemediğini
    görmeli (bkz. `chat_model_service`).
    """
    return await chat_models.list_models()


@router.get("/sessions", response_model=ChatSessionList)
def list_chat_sessions(
    db: DbSession,
    limit: int = Query(default=50, ge=1, le=200),
    include_empty: bool = Query(
        default=False,
        description="Hiç mesajı olmayan oturumlar da dönsün (varsayılan gizli)",
    ),
) -> ChatSessionList:
    """Sohbet geçmişini en son etkinliğe göre listeler.

    ⚠️ MESAJ İÇERİĞİ DÖNMEZ. Tıklanan oturum
    `GET /chat/sessions/{session_key}` ile ayrıca çekilir.
    """
    satirlar, toplam = chat_sessions.list_sessions(db, limit=limit, include_empty=include_empty)
    return ChatSessionList(items=satirlar, total=toplam)


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
