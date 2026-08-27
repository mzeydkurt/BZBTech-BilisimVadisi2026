"""Finansman ürünleri vergi (BSMV ve KKDF) oranları ve hesaplama kuralları.

Mevzuat Dayanağı:
- 6802 sayılı Gider Vergileri Kanunu md. 28, 29/x ve 33:
  * Konut finansmanı/kredisi BSMV'den muaftır (%0).
  * Bireysel tüketici (ihtiyaç, taşıt) finansmanlarında kâr payı üzerinden %15 BSMV uygulanır.
  * Ticari/kurumsal finansmanlarda kâr payı üzerinden %5 BSMV uygulanır.
- Kaynak Kullanımını Destekleme Fonu (KKDF) Mevzuatı (88/12944 sayılı BKK ve değişiklikleri):
  * Konut finansmanı/kredisi KKDF'den muaftır (%0).
  * Bireysel tüketici (ihtiyaç, taşıt) finansmanlarında kâr payı üzerinden %15 KKDF uygulanır.
  * Ticari finansmanlar KKDF'den muaftır (%0).

⚠️ Vergiler anapara üzerinden DEĞİL, her ay tahakkuk eden kâr payı üzerinden kesilir.
Efektif aylık taksit oranı: r_efektif = r * (1 + BSMV + KKDF)
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

_SIFIR: Final[Decimal] = Decimal("0.00")
_BES: Final[Decimal] = Decimal("0.05")
_ON_BES: Final[Decimal] = Decimal("0.15")
_BIR: Final[Decimal] = Decimal("1.00")


@dataclass(frozen=True)
class FinancingTaxRates:
    """Finansman türüne ait vergi oranları ve çarpanı."""

    bsmv_rate: Decimal  # Örn: 0.15 (%15)
    kkdf_rate: Decimal  # Örn: 0.15 (%15)
    total_tax_multiplier: Decimal  # 1 + BSMV + KKDF (Örn: 1.30)
    basis_note: str

    @property
    def bsmv_pct(self) -> Decimal:
        """Yüzde olarak BSMV oranı (%15.0)."""
        return self.bsmv_rate * Decimal("100")

    @property
    def kkdf_pct(self) -> Decimal:
        """Yüzde olarak KKDF oranı (%15.0)."""
        return self.kkdf_rate * Decimal("100")

    @property
    def is_tax_exempt(self) -> bool:
        """Vergiden tamamen muaf mı?"""
        return self.bsmv_rate == _SIFIR and self.kkdf_rate == _SIFIR


def financing_tax_rates(product_type: str | None, segment: str = "bireysel") -> FinancingTaxRates:
    """Ürün türü ve müşteri segmentine göre BSMV & KKDF oranlarını döndürür."""
    seg = (segment or "bireysel").lower()

    if seg in ("ticari", "kurumsal", "kobi"):
        return FinancingTaxRates(
            bsmv_rate=_BES,
            kkdf_rate=_SIFIR,
            total_tax_multiplier=Decimal("1.05"),
            basis_note="Ticari finansman: %5 BSMV, %0 KKDF (muaf).",
        )

    ptype = (product_type or "").lower()
    if ptype in ("konut_finansmani", "konut") or "konut" in ptype:
        return FinancingTaxRates(
            bsmv_rate=_SIFIR,
            kkdf_rate=_SIFIR,
            total_tax_multiplier=_BIR,
            basis_note=(
                "Konut finansmanı: 6802 s.K. ve KKDF mevzuatı gereği vergiden "
                "muaftır (%0 BSMV, %0 KKDF)."
            ),
        )

    if ptype in ("tasit_finansmani", "tasit", "arac") or "tasit" in ptype or "arac" in ptype:
        return FinancingTaxRates(
            bsmv_rate=_ON_BES,
            kkdf_rate=_ON_BES,
            total_tax_multiplier=Decimal("1.30"),
            basis_note=(
                "Bireysel taşıt finansmanı: Kâr payı üzerinden %15 BSMV ve %15 KKDF "
                "(toplam +%30 vergi) uygulanır."
            ),
        )

    if ptype in ("ihtiyac_finansmani", "ihtiyac") or "ihtiyac" in ptype:
        return FinancingTaxRates(
            bsmv_rate=_ON_BES,
            kkdf_rate=_ON_BES,
            total_tax_multiplier=Decimal("1.30"),
            basis_note=(
                "Bireysel ihtiyaç finansmanı: Kâr payı üzerinden %15 BSMV ve %15 KKDF "
                "(toplam +%30 vergi) uygulanır."
            ),
        )

    # Varsayılan bireysel tüketici finansmanı vergisi (%15 BSMV + %15 KKDF)
    return FinancingTaxRates(
        bsmv_rate=_ON_BES,
        kkdf_rate=_ON_BES,
        total_tax_multiplier=Decimal("1.30"),
        basis_note=(
            "Bireysel finansman: Kâr payı üzerinden %15 BSMV ve %15 KKDF "
            "(toplam +%30 vergi) uygulanır."
        ),
    )
