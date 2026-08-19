"""Ürün, oran ve limit API şemaları (Sprint 2.5 KAPI F5).

⚠️ Oran ve tutar alanları `Decimal`; `float` kullanılmaz. Kâr payı oranı
dört ondalık basamağa kadar anlamlıdır (%4,1500 ile %4,15 aynı satırdan
gelmez) ve ikili gösterim bu ayrımı bozar.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ProductRateOut(BaseModel):
    """Tek bir oran satırı.

    ⚠️ `rate_type` olmadan bu satır yorumlanamaz: aynı `profit_rate_pct`
    sütunu finansman maliyetini de (`financing_rate`) katılma hesabı
    getirisini de (`participation_yield`) taşır. Biri gider, diğeri gelir.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    rate_type: str = Field(
        description="financing_rate | participation_yield | profit_sharing_ratio"
    )
    profit_rate_pct: Decimal | None = Field(default=None, description="Kâr payı oranı (%)")
    investor_share_pct: Decimal | None = Field(default=None, description="Katılımcı payı (%)")
    bank_share_pct: Decimal | None = Field(default=None, description="Banka payı (%)")
    allocation_fee_pct: Decimal | None = None
    monthly_cost_pct: Decimal | None = None
    annual_cost_pct: Decimal | None = None
    term_months: int | None = None
    term_days_min: int | None = None
    term_days_max: int | None = None
    term_label: str | None = None
    amount_min: Decimal | None = None
    amount_max: Decimal | None = None
    currency: str
    account_tier: str | None = None
    customer_type: str | None = None
    is_gross: bool | None = Field(default=None, description="Oran stopaj öncesi mi?")
    variant: str | None = None
    effective_date: date | None = None
    rate_source: str
    confidence: Decimal
    evidence_text: str | None = None


class ProductLimitOut(BaseModel):
    """Tutar bandı × oran × azami vade matrisinin tek hücresi.

    ⚠️ Matris tek bir orana indirgenmez: %90 yalnızca en alt değer bandının
    A-B enerji sınıfında geçerlidir.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    asset_value_min: Decimal | None = None
    asset_value_max: Decimal | None = None
    financing_ratio_pct: Decimal | None = None
    term_months_min: int | None = None
    term_months_max: int | None = None
    amount_max: Decimal | None = None
    energy_class: str | None = None
    vehicle_age_min: int | None = None
    vehicle_age_max: int | None = None
    currency: str
    extraction_method: str
    source_url: str
    evidence_text: str | None = None


class ProductOut(BaseModel):
    """Ürün listesi satırı."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    bank_code: str | None = None
    bank_name: str | None = None
    external_key: str
    name: str
    product_type: str | None = None
    segment: str | None = None
    currency: str
    variant_key: str | None = None
    variant_label: str | None = None
    parent_product_id: int | None = None
    is_active: bool
    rates: list[ProductRateOut] = Field(default_factory=list)
    limits: list[ProductLimitOut] = Field(default_factory=list)


class ProductDetailOut(ProductOut):
    """Ürün detayı: varyantlar ve kaynak URL dahil (KAPI F5 §8.2).

    Kaynak URL zorunludur; arayüzde "bu oran nereden geldi" sorusu ancak
    bununla yanıtlanabilir.
    """

    description: str | None = None
    amount_min: Decimal | None = None
    amount_max: Decimal | None = None
    term_months_min: int | None = None
    term_months_max: int | None = None
    allowed_terms: list[int] | None = None
    collateral_type: str | None = None
    has_calculator: bool = False
    calculator_url: str | None = None
    limits_source: str | None = None
    limits_evidence: str | None = None
    is_binding: bool = True
    non_binding_notice: str | None = None
    source_url: str | None = Field(default=None, description="Oranın okunduğu banka sayfası")
    source_fetched_at: str | None = None
    variants: list[ProductOut] = Field(default_factory=list)
