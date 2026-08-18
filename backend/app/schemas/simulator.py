"""Finansman simülatörü ve BDDK denetçisi Pydantic şemaları."""

from __future__ import annotations

from decimal import Decimal
from pydantic import BaseModel, Field


class FinancingSimulationRequest(BaseModel):
    """Finansman taksit simülasyonu isteği."""

    amount_try: Decimal = Field(gt=0, description="Finansman tutarı (TL)")
    term_months: int = Field(gt=0, le=120, description="Vade (Ay)")
    product_type: str = Field(default="tasit_finansmani", description="Ürün türü: tasit_finansmani, konut_finansmani, ihtiyac_finansmani")


class BankFinancingOffer(BaseModel):
    """Tek bir bankanın finansman teklifi simülasyon çıktısı."""

    bank_code: str
    bank_name: str
    profit_rate_pct: float = Field(description="Aylık Kâr Payı Oranı (%)")
    monthly_payment_try: float = Field(description="Aylık Taksit Tutarı (TL)")
    total_profit_try: float = Field(description="Toplam Ödenecek Kâr Payı (TL)")
    total_payment_try: float = Field(description="Toplam Geri Ödeme Tutarı (TL)")
    is_best_offer: bool = Field(default=False, description="En avantajlı teklif mi?")


class FinancingSimulationResponse(BaseModel):
    """Finansman simülasyon yanıtı."""

    amount_try: float
    term_months: int
    product_type: str
    best_bank_code: str | None = None
    offers: list[BankFinancingOffer]


class ParticipationYieldRequest(BaseModel):
    """Katılma hesabı kâr paylaşım getiri simülasyon isteği."""

    deposit_try: Decimal = Field(gt=0, description="Yatırım Tutarı (TL)")
    term_days: int = Field(gt=0, description="Vade Gün Sayısı (31, 91, 183, 365 gün)")
    currency: str = Field(default="TRY", description="Para Birimi (TRY, USD, EUR)")


class BankYieldOffer(BaseModel):
    """Tek bir bankanın katılma hesabı getiri teklifi."""

    bank_code: str
    bank_name: str
    investor_share_pct: float = Field(description="Müşteri Kâr Paylaşım Oranı (%)")
    bank_share_pct: float = Field(description="Banka Kâr Paylaşım Oranı (%)")
    annual_yield_gross_pct: float = Field(description="Tahmini Yıllık Brüt Getiri Oranı (%)")
    estimated_gross_profit_try: float = Field(description="Tahmini Brüt Kâr (TL)")
    estimated_net_profit_try: float = Field(description="Tahmini Net Kâr (TL)")
    is_best_yield: bool = Field(default=False)


class ParticipationYieldResponse(BaseModel):
    """Katılma hesabı simülasyon yanıtı."""

    deposit_try: float
    term_days: int
    currency: str
    best_yield_bank_code: str | None = None
    offers: list[BankYieldOffer]


class BDDKLimitCheckRequest(BaseModel):
    """BDDK Taşıt/Konut LTV limit denetim isteği."""

    asset_type: str = Field(description="Varlık Türü: tasit veya konut")
    asset_value_try: Decimal = Field(gt=0, description="Araç kasko/fatura değeri veya Konut ekspertiz değeri")
    energy_class: str | None = Field(default="A", description="Konut Enerji Sınıfı (A, B, C)")


class BDDKLimitCheckResponse(BaseModel):
    """BDDK Mevzuat Üst Sınır Denetim Yanıtı."""

    asset_type: str
    asset_value_try: float
    max_financing_ratio_pct: float = Field(description="BDDK İzin Verilen Azami Finansman Oranı (%)")
    max_financing_amount_try: float = Field(description="BDDK İzin Verilen Azami Finansman Tutarı (TL)")
    max_allowed_term_months: int = Field(description="BDDK İzin Verilen Azami Vade (Ay)")
    legal_reference: str = Field(description="Mevzuat Dayanağı / BDDK Karar No")
