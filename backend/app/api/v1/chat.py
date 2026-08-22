"""Kanıtlı arama uç noktası — doğal dil sorusu, kanıt listesi ve denetim."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import DbSession
from app.schemas.chat import ChatRequest, ChatResponse
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
