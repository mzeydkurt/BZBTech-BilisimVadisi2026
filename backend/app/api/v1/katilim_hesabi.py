"""Katılım Hesabı sekmesi API ucu (KATİP KAPI 7)."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import DbSession
from app.schemas.katilim_hesabi import KatilimHesabiResponse
from app.services.katilim_hesabi_service import build_katilim_hesabi

router = APIRouter(prefix="/katilim-hesabi", tags=["katilim-hesabi"])

_VADE_AY: dict[str, int] = {"aylik": 1, "3_aylik": 3, "6_aylik": 6, "yillik": 12}


@router.get("", response_model=KatilimHesabiResponse, summary="Katılım hesabı pivot tablosu")
def read_katilim_hesabi(
    db: DbSession,
    rate_type: Annotated[
        Literal["participation_yield", "profit_sharing_ratio"],
        Query(description="participation_yield (getiri) | profit_sharing_ratio (paylaşım)"),
    ] = "participation_yield",
    variant: Annotated[
        Literal["normal", "ara_odemeli"], Query(description="normal | ara_odemeli")
    ] = "normal",
    currency: Annotated[str | None, Query(description="TRY | USD | EUR | XAU")] = None,
    term: Annotated[
        Literal["aylik", "3_aylik", "6_aylik", "yillik"] | None,
        Query(description="Verilirse yalnızca bu vadedeki hücreler döner"),
    ] = None,
) -> KatilimHesabiResponse:
    """TKBB Veri Peteği + banka sitelerinden gelen katılma hesabı verisini bir arada gösterir.

    Response şekli TKBB'nin kendi dashboard görünümünü taklit eder: satır
    banka, sütun `{vade}|{para_birimi}`. "Ara ödemeli" ürünün yalnızca 5
    bankada olduğu `not_offered_banks` ile açıkça işaretlenir — boş hücre
    değil, "bu ürün yok" notu.
    """
    try:
        return build_katilim_hesabi(
            db,
            rate_type=rate_type,
            variant=variant,
            currency=currency,
            term_months=_VADE_AY.get(term) if term else None,
        )
    except ValueError as hata:
        raise HTTPException(status_code=422, detail=str(hata)) from hata
