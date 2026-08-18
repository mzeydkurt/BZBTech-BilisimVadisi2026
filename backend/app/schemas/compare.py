"""Karşılaştırma motoru Pydantic şemaları."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class ComparisonWeights(BaseModel):
    """Kullanıcı özelleştirilebilir puanlama ağırlıkları (Toplam = 100)."""

    rate_weight: float = Field(default=40.0, ge=0, le=100, description="Kâr Payı Oranı Ağırlığı (%)")
    term_weight: float = Field(default=20.0, ge=0, le=100, description="Vade Esnekliği Ağırlığı (%)")
    fee_weight: float = Field(default=20.0, ge=0, le=100, description="Masraf/Tahsis Ağırlığı (%)")
    reward_weight: float = Field(default=20.0, ge=0, le=100, description="Ödül/İade Ağırlığı (%)")


class ComparisonRequest(BaseModel):
    """Karşılaştırma isteği şeması."""

    campaign_ids: list[int] = Field(default_factory=list, description="Karşılaştırılacak kampanya kimlikleri")
    weights: ComparisonWeights = Field(default_factory=ComparisonWeights)


class ComparisonItem(BaseModel):
    """Karşılaştırılan tek bir kampanya veya ürün."""

    id: int
    bank_code: str
    bank_name: str
    title: str
    category: str | None = None
    product_type: str | None = None
    profit_rate_pct: float | None = None
    term_months_max: int | None = None
    financing_amount_max: float | None = None
    reward_amount_try: float | None = None
    min_spend_try: float | None = None
    has_no_fee: bool = False
    evidence_map: dict[str, str] = Field(default_factory=dict, description="Her alanın kanıt cümlesi")
    custom_score: float = Field(default=0.0, description="Hesaplanan toplam avantaj skoru (0-100)")


class ComparisonResponse(BaseModel):
    """Karşılaştırma motoru yanıtı."""

    winner_id: int | None = None
    winner_bank_code: str | None = None
    winner_reason: str | None = None
    items: list[ComparisonItem]
    weights: ComparisonWeights
