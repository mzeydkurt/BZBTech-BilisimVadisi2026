"""Hesaplayıcı probe ortak yardımcıları."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.core.normalization.money import parse_decimal_tr
from app.core.normalization.rate import parse_rate

BEKLEME_SANIYE = 2.0


@dataclass
class ProbeReading:
    """Tek bir hesaplayıcı sorgu sonucu."""

    bank_code: str
    source_url: str
    variant_label: str
    amount: Decimal
    term_months: int
    profit_rate_pct: Decimal | None = None
    monthly_installment: Decimal | None = None
    total_repayment: Decimal | None = None
    allocation_fee: Decimal | None = None
    annual_cost_pct: Decimal | None = None
    notice_text: str | None = None
    product_type_hint: str | None = None
    raw_meta: dict[str, Any] = field(default_factory=dict)


def bekle() -> None:
    time.sleep(BEKLEME_SANIYE)


def cerez_kapat(page: Any) -> None:
    for sel in (
        'button:has-text("Tüm Çerezleri Kabul")',
        'button:has-text("Tümünü Kabul")',
        'button:has-text("Kabul Et")',
        'button:has-text("Kabul")',
        'button:has-text("Tümünü Kabul Et")',
    ):
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible():
                loc.click(timeout=2000)
                page.wait_for_timeout(700)
                return
        except Exception:
            continue


def metinden_oran(metin: str) -> Decimal | None:
    for kalip in (
        r"ayl[ıi]k\s*k[aâ]r\s*oran[ıi]\s*%?\s*(\d+[.,]\d+)",
        r"%\s*(\d+[.,]\d+)\s*(?:ayl[ıi]k)?",
        r"k[aâ]r\s*oran[ıi]\s*[:%]?\s*(\d+[.,]\d+)",
    ):
        m = re.search(kalip, metin, re.IGNORECASE)
        if m:
            return parse_rate(m.group(0)) or parse_decimal_tr(m.group(1))
    return None


def metinden_taksit_toplam(metin: str) -> tuple[Decimal | None, Decimal | None]:
    taksit = toplam = None
    m = re.search(
        r"(?:ayl[ıi]k\s*)?taksit\s*(?:tutar[ıi])?\s*[:\-]?\s*([\d.\s]+,\d{2})\s*TL",
        metin,
        re.IGNORECASE,
    )
    if m:
        taksit = parse_decimal_tr(m.group(1))
    m = re.search(
        r"(?:ödenecek\s*)?toplam\s*(?:tutar)?\s*[:\-]?\s*([\d.\s]+,\d{2})\s*TL",
        metin,
        re.IGNORECASE,
    )
    if m:
        toplam = parse_decimal_tr(m.group(1))
    return taksit, toplam


def bddk_ornek_vade(product_type_hint: str | None, amount: Decimal) -> int:
    """BDDK hizalı örnek vade — mümkün olan en uzun izinli."""
    from app.services.bddk_limits_service import (
        family_for_product_type,
        max_term_for_ihtiyac_amount,
    )

    aile = family_for_product_type(product_type_hint)
    if aile == "ihtiyac":
        return max_term_for_ihtiyac_amount(amount)[0]
    if aile == "konut":
        return 120
    if aile == "tasit":
        if amount <= Decimal("400000"):
            return 48
        if amount <= Decimal("800000"):
            return 36
        if amount <= Decimal("1200000"):
            return 24
        return 12
    return 36


# Ürün ailesine göre örnek tutar × vade (BDDK bantlarıyla hizalı).
_BDDK_PROBE_NOKTALARI: dict[str, tuple[tuple[Decimal, int], ...]] = {
    "ihtiyac": (
        (Decimal("10000"), 36),
        (Decimal("200000"), 24),
        (Decimal("1000000"), 12),
    ),
    "konut": ((Decimal("1000000"), 120),),
    "tasit": (
        (Decimal("400000"), 48),
        (Decimal("800000"), 36),
        (Decimal("1200000"), 24),
    ),
}
_DEFAULT_PROBE_NOKTALARI: tuple[tuple[Decimal, int], ...] = ((Decimal("1000000"), 36),)


def bddk_ornek_noktalar(product_type_hint: str | None) -> list[tuple[Decimal, int]]:
    """Aileye göre BDDK hizalı (finansman tutarı, vade) örnekleri."""
    from app.services.bddk_limits_service import family_for_product_type

    aile = family_for_product_type(product_type_hint)
    return list(_BDDK_PROBE_NOKTALARI.get(aile or "", _DEFAULT_PROBE_NOKTALARI))


def oran_gecerli(oran: Decimal | None) -> bool:
    """Aylık kâr payı makul aralıkta mı?"""
    if oran is None:
        return False
    return Decimal("0.05") <= oran <= Decimal("15")


def urun_tipi_ipucu(etiket: str) -> str | None:
    from app.core.normalization.text import ascii_fold_tr, lower_tr

    d = ascii_fold_tr(lower_tr(etiket))
    if any(ascii_fold_tr(k) in d for k in ("konut", "toki", "gayrimenkul", "kira finans")):
        return "konut_finansmani"
    if any(
        ascii_fold_tr(k) in d
        for k in ("taşıt", "tasit", "araç", "arac", "motosiklet", "binek", "otomobil")
    ):
        return "tasit_finansmani"
    if any(
        ascii_fold_tr(k) in d
        for k in ("arsa", "işyeri", "is yeri", "iş yeri", "ticari gayrimenkul")
    ):
        return "konut_finansmani"
    if any(
        ascii_fold_tr(k) in d
        for k in (
            "ihtiyaç",
            "ihtiyac",
            "alışveriş",
            "alisveris",
            "eğitim",
            "egitim",
            "hac",
            "umre",
        )
    ):
        return "ihtiyac_finansmani"
    return None
