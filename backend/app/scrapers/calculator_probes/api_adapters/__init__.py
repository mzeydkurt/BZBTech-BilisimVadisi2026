"""Doğrudan httpx ile finansman hesaplama API adapter'ları.

Öncelik: XHR/fetch endpoint (network discovery ile doğrulanmış).
CAPTCHA / auth bypass yok. Sonuçlar bağlayıcı değildir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.core.normalization.money import parse_decimal_tr
from app.core.normalization.rate import parse_rate
from app.scrapers.calculator_probes.common import ProbeReading, oran_gecerli, urun_tipi_ipucu


@dataclass
class FinancingCalculation:
    """Normalize edilmiş hesaplama sonucu (banka yanıtının özeti)."""

    bank_code: str
    product_label: str
    product_type_hint: str | None
    amount: Decimal
    term_months: int
    profit_rate_pct: Decimal | None = None
    annual_cost_pct: Decimal | None = None
    monthly_installment: Decimal | None = None
    total_payment: Decimal | None = None
    allocation_fee: Decimal | None = None
    source_url: str = ""
    source_endpoint: str = ""
    raw_response: dict[str, Any] = field(default_factory=dict)

    def to_probe_reading(self) -> ProbeReading:
        return ProbeReading(
            bank_code=self.bank_code,
            source_url=self.source_url or self.source_endpoint,
            variant_label=self.product_label,
            amount=self.amount,
            term_months=self.term_months,
            profit_rate_pct=self.profit_rate_pct,
            monthly_installment=self.monthly_installment,
            total_repayment=self.total_payment,
            allocation_fee=self.allocation_fee,
            annual_cost_pct=self.annual_cost_pct,
            product_type_hint=self.product_type_hint or urun_tipi_ipucu(self.product_label),
            raw_meta=self.raw_response,
        )


def parse_tr_money(value: Any) -> Decimal | None:
    """'11.349,76 TL' / 11349.76 / '862,50' → Decimal."""
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))
    metin = str(value).strip()
    if not metin or metin.lower() in ("null", "-", "none"):
        return None
    return parse_decimal_tr(metin.replace("TL", "").replace("₺", "").strip())


def parse_tr_rate(value: Any) -> Decimal | None:
    """'%3,75' / '4,0' / 4.01 → Decimal aylık oran."""
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        oran = Decimal(str(value))
        return oran if oran_gecerli(oran) else oran
    metin = str(value).strip()
    if not metin or metin.lower() == "null":
        return None
    oran = parse_rate(metin) or parse_decimal_tr(metin.lstrip("%").strip())
    return oran
