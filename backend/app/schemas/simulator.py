"""Finansman simülatörü ve BDDK denetçisi Pydantic şemaları.

⚠️ Tüm para ve oran alanları `Decimal`. `float` kullanılmaz (CLAUDE.md).

⚠️ Verisi olmayan banka teklif listesine GİRMEZ. `banks_without_data`
alanı hangi bankanın neden dışarıda kaldığını taşır. "Veri olmayan yerde
veri uydurmak yerine mevcut olanı karşılaştırırız" (SPRINT2.5).
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


class MissingDataBank(BaseModel):
    """Teklif üretilemeyen banka ve nedeni.

    Boş bırakmak yerine açıkça bildirilir: kullanıcı 10 bankadan 4'ünün
    listede olmadığını görmeli, eksikliği başarı sanmamalıdır.
    """

    bank_code: str
    bank_name: str
    reason: str = Field(description="Neden teklif üretilemediği")


# ── Finansman simülasyonu ─────────────────────────────────


class FinancingSimulationRequest(BaseModel):
    """Finansman taksit simülasyonu isteği."""

    amount_try: Decimal = Field(gt=0, description="Finansman tutarı (TL)")
    term_months: int = Field(gt=0, le=120, description="Vade (Ay)")
    product_type: str = Field(
        default="tasit_finansmani",
        description="Ürün türü: tasit_finansmani, konut_finansmani, ihtiyac_finansmani",
    )
    bank_codes: list[str] | None = Field(
        default=None, description="Yalnızca bu bankalar; boşsa tüm bankalar"
    )


class InstallmentRow(BaseModel):
    """Eşit taksitli ödeme planının tek ay satırı."""

    month: int = Field(ge=1, description="Taksit sırası (1…n)")
    installment: Decimal = Field(description="Aylık taksit tutarı (TL)")
    profit_share: Decimal = Field(description="Bu aydaki kâr payı (TL)")
    principal: Decimal = Field(description="Bu aydaki anapara payı (TL)")
    remaining_balance: Decimal = Field(description="Ödeme sonrası kalan bakiye (TL)")


class BankFinancingOffer(BaseModel):
    """Tek bir bankanın finansman teklifi.

    ⚠️ `rate_term_months` oranın hangi vade için yayımlandığını söyler.
    İstenen vadeyle aynı değilse `is_exact_term_match` False olur ve teklif
    yaklaşıktır — arayüz bunu işaretlemelidir.
    """

    bank_code: str
    bank_name: str
    product_id: int
    product_name: str
    profit_rate_pct: Decimal = Field(description="Aylık kâr payı oranı (%)")
    rate_term_months: int | None = Field(default=None, description="Oranın yayımlandığı vade")
    is_exact_term_match: bool = Field(description="Oran tam istenen vadeye mi ait?")
    monthly_payment_try: Decimal
    total_profit_try: Decimal
    total_payment_try: Decimal
    allocation_fee_try: Decimal | None = Field(
        default=None, description="Tahsis ücreti (TL); oran yoksa None"
    )
    total_cost_try: Decimal = Field(
        description="Toplam ödeme + tahsis ücreti (sigorta hariç)"
    )
    annual_cost_pct: Decimal | None = Field(
        default=None, description="Bankanın yayımladığı yıllık toplam maliyet (%)"
    )
    installments: list[InstallmentRow] = Field(
        default_factory=list, description="Eşit taksitli amortisman tablosu"
    )
    is_best_offer: bool = False
    source_url: str | None = None
    evidence_text: str | None = Field(default=None, description="Oranın okunduğu tablo satırı")


class FinancingSimulationResponse(BaseModel):
    """Finansman simülasyon yanıtı."""

    amount_try: Decimal
    term_months: int
    product_type: str
    best_bank_code: str | None = None
    offers: list[BankFinancingOffer]
    banks_without_data: list[MissingDataBank] = Field(default_factory=list)
    method_note: str = Field(description="Hesabın nasıl yapıldığı")


# ── Katılma hesabı getirisi ───────────────────────────────


class ParticipationYieldRequest(BaseModel):
    """Katılma hesabı getiri simülasyon isteği."""

    deposit_try: Decimal = Field(gt=0, description="Yatırım tutarı")
    term_days: int = Field(gt=0, le=3650, description="Vade gün sayısı")
    currency: str = Field(default="TRY", description="Para birimi: TRY, USD, EUR, XAU, XAG")
    bank_codes: list[str] | None = Field(
        default=None, description="Yalnızca bu bankalar; boşsa tüm bankalar"
    )


class BankYieldOffer(BaseModel):
    """Tek bir bankanın katılma hesabı getiri teklifi.

    ⚠️ `annual_yield_gross_pct` bankanın KENDİ yayımladığı gerçekleşmiş
    getiridir; katılımcı payı bu orana ZATEN dahildir. Ayrıca
    `investor_share_pct` ile çarpılmaz — çarpılırsa payı iki kez düşülür.
    `investor_share_pct` yalnızca bilgi amaçlı gösterilir.
    """

    bank_code: str
    bank_name: str
    product_id: int
    product_name: str
    annual_yield_gross_pct: Decimal = Field(
        description="Bankanın yayımladığı yıllık brüt getiri (%)"
    )
    rate_term_label: str | None = None
    is_exact_term_match: bool
    investor_share_pct: Decimal | None = Field(
        default=None, description="Bilgi amaçlı: katılımcı payı"
    )
    bank_share_pct: Decimal | None = None
    gross_profit_try: Decimal
    withholding_pct: Decimal = Field(description="Uygulanan stopaj oranı (%)")
    withholding_try: Decimal
    net_profit_try: Decimal
    is_best_yield: bool = False
    source_url: str | None = None
    evidence_text: str | None = None


class ParticipationYieldResponse(BaseModel):
    """Katılma hesabı simülasyon yanıtı."""

    deposit_try: Decimal
    term_days: int
    currency: str
    best_yield_bank_code: str | None = None
    offers: list[BankYieldOffer]
    banks_without_data: list[MissingDataBank] = Field(default_factory=list)
    withholding_note: str = Field(description="Uygulanan stopaj oranı ve mevzuat dayanağı")
    method_note: str


# ── BDDK limit denetimi ───────────────────────────────────


class BDDKLimitCheckRequest(BaseModel):
    """BDDK taşıt/konut/ihtiyaç azami finansman denetim isteği."""

    asset_type: str = Field(description="Varlık türü: tasit, konut veya ihtiyac")
    asset_value_try: Decimal = Field(
        gt=0,
        description=(
            "Kasko/fatura değeri, konut ekspertiz değeri veya ihtiyaç finansman tutarı"
        ),
    )
    energy_class: str | None = Field(
        default=None,
        description="Konut enerji sınıfı (A, B, C veya diğer). Konut için önerilir.",
    )
    first_home: bool | None = Field(
        default=None,
        description=(
            "Konut için: True = ilk konut (tam LTV), False = ikinci/sonraki konut "
            "(oranlar %75 azaltılır). None = ilk konut varsayılır."
        ),
    )


class BDDKLimitCheckResponse(BaseModel):
    """BDDK mevzuat üst sınır denetim yanıtı."""

    asset_type: str
    asset_value_try: Decimal
    energy_class: str | None = None
    value_band_label: str = Field(description="Uygulanan değer bandı")
    max_financing_ratio_pct: Decimal
    max_financing_amount_try: Decimal
    max_allowed_term_months: int | None = Field(
        default=None, description="Azami vade (ay); sınır yoksa None"
    )
    is_financing_allowed: bool = Field(description="Bu değerde finansman kullandırılabilir mi?")
    legal_reference: str
    first_home: bool | None = Field(
        default=None,
        description="Konut denetiminde uygulanan ilk-ev / ikinci-ev varsayımı",
    )
