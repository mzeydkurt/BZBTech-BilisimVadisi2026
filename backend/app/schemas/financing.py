"""Finansmanlar sekmesi API şeması (KATİP KAPI 6).

⚠️ `/api/v1/products/compare` sözleşmesine DOKUNMAZ — bu, o ucun yanına
eklenen AYRI bir uç. `ProductOut`'u yeniden kullanır, kod tekrarı yok.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.bddk import BddkCanonicalLimitsOut
from app.schemas.product import ProductOut


class FinancingResponse(BaseModel):
    """Finansmanlar sekmesinin listeleme yanıtı."""

    financing: list[ProductOut] = Field(default_factory=list)
    no_data_products: list[str] = Field(
        default_factory=list,
        description="Ne oran ne limit bilgisi yayımlanmış ürünler ({banka} — {ürün adı})",
    )
    coverage_note: str
    bddk_limits: BddkCanonicalLimitsOut | None = Field(
        default=None,
        description="Filtrelenen finansman türüne ait BDDK yasal tavanları; tür yoksa None",
    )
    bddk_limits_by_family: dict[str, BddkCanonicalLimitsOut] = Field(
        default_factory=dict,
        description="ihtiyac / konut / tasit ailelerinin BDDK tavanları (liste banner'ı)",
    )
