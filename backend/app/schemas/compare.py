"""Karşılaştırma ve sıralama motoru Pydantic şemaları.

⚠️ `rate_type` ZORUNLUDUR ve varsayılanı YOKTUR. Finansman maliyeti
(`financing_rate`), katılma getirisi (`participation_yield`) ve kâr bölüşüm
oranı (`profit_sharing_ratio`) aynı `profit_rate_pct` sütununu paylaşır ama
biri gider, biri gelir, biri bölüşümdür. Aynı sıralamaya girerlerse çıkan
liste anlamsızdır.

⚠️ Değeri olmayan ürün sıralamaya KARIŞMAZ; `without_data` grubunda döner.
NULL'u sıfır sayıp "en düşük" ilan etmek yanlıştır ve jüri karşısında
savunulamaz.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

from pydantic import BaseModel, Field, model_validator

# Ölçüt → (sıralanacak alan, azalan mı, hangi oran türünde geçerli).
# `None` oran türü "her türde geçerli" demektir.
CRITERIA: Final[dict[str, tuple[str, bool, str | None]]] = {
    "en_dusuk_kar_payi": ("profit_rate_pct", False, "financing_rate"),
    "en_dusuk_masraf": ("allocation_fee_pct", False, "financing_rate"),
    "en_dusuk_toplam_maliyet": ("annual_cost_pct", False, "financing_rate"),
    "en_yuksek_getiri": ("profit_rate_pct", True, "participation_yield"),
    "en_yuksek_paylasim_orani": ("investor_share_pct", True, "profit_sharing_ratio"),
    "en_uzun_vade": ("term_months", True, None),
    "en_avantajli": ("__agirlikli__", True, None),
}


class RankingWeights(BaseModel):
    """`en_avantajli` ölçütünün ağırlıkları.

    ⚠️ Bu ağırlıklar GERÇEKTEN kullanılır. Şemada durup hesaba girmeyen bir
    ağırlık, kullanıcıya var olmayan bir denetim vaat eder.
    """

    rate_weight: Decimal = Field(default=Decimal("50"), ge=0, le=100, description="Oran ağırlığı")
    fee_weight: Decimal = Field(default=Decimal("25"), ge=0, le=100, description="Masraf ağırlığı")
    term_weight: Decimal = Field(default=Decimal("25"), ge=0, le=100, description="Vade ağırlığı")

    @model_validator(mode="after")
    def _toplam_pozitif(self) -> RankingWeights:
        """Tüm ağırlıklar sıfırsa sıralama yapılamaz."""
        if self.rate_weight + self.fee_weight + self.term_weight <= 0:
            raise ValueError("En az bir ağırlık sıfırdan büyük olmalı")
        return self


class ProductRankingRequest(BaseModel):
    """Ürün sıralama isteği."""

    rate_type: str = Field(
        description="ZORUNLU: financing_rate | participation_yield | profit_sharing_ratio"
    )
    criterion: str = Field(description=f"Ölçüt: {', '.join(CRITERIA)}")
    product_type: str | None = Field(default=None, description="Ürün türü süzgeci")
    bank_codes: list[str] | None = Field(default=None, description="Yalnızca bu bankalar")
    term_months: int | None = Field(default=None, gt=0, description="Vade süzgeci (ay)")
    term_days: int | None = Field(default=None, gt=0, description="Vade süzgeci (gün)")
    currency: str = Field(default="TRY")
    amount_try: Decimal | None = Field(default=None, gt=0, description="Tutar bandı süzgeci")
    weights: RankingWeights = Field(default_factory=RankingWeights)
    limit: int = Field(default=20, ge=1, le=100)


class RankedProduct(BaseModel):
    """Sıralanmış tek ürün satırı."""

    rank: int | None = Field(default=None, description="Sıra; veri yoksa None")
    product_id: int
    product_name: str
    bank_code: str
    bank_name: str
    product_type: str | None = None
    rate_type: str
    profit_rate_pct: Decimal | None = None
    allocation_fee_pct: Decimal | None = None
    annual_cost_pct: Decimal | None = None
    investor_share_pct: Decimal | None = None
    bank_share_pct: Decimal | None = None
    term_months: int | None = None
    term_label: str | None = None
    currency: str
    score: Decimal | None = Field(default=None, description="Yalnızca en_avantajli ölçütünde dolu")
    evidence_text: str | None = None
    source_url: str | None = None
    missing_reason: str | None = Field(default=None, description="Veri yok grubundaysa nedeni")


class ProductRankingResponse(BaseModel):
    """Ürün sıralama yanıtı."""

    rate_type: str
    criterion: str
    sort_field: str
    descending: bool
    winner: RankedProduct | None = None
    winner_reason: str | None = Field(
        default=None, description="Hangi ölçütte ne değerle kazandığı"
    )
    ranked: list[RankedProduct]
    without_data: list[RankedProduct] = Field(
        default_factory=list, description="Ölçütün alanı boş olduğu için sıralanamayanlar"
    )
    note: str
