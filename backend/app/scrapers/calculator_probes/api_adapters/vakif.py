"""Vakıf Katılım — InstallmentPayBack (POST + CSRF).

Discovery 2026-08-23: `/plugins/InstallmentPayBack` · skor 115.
Önce hesaplama sayfasından `__RequestVerificationToken` alınır.
"""

from __future__ import annotations

import re
from decimal import Decimal
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup

from app.config import get_settings
from app.logging_config import get_logger
from app.scrapers.calculator_probes.api_adapters import (
    FinancingCalculation,
    parse_tr_money,
    parse_tr_rate,
)
from app.scrapers.calculator_probes.common import bddk_ornek_vade, urun_tipi_ipucu

logger = get_logger(__name__)

LANG_ID = "bf2689d9-071e-4a20-9450-b1dbdd39778f"
CALCULATOR_URL = (
    "https://www.vakifkatilim.com.tr/tr/yardimci-sayfalar/hesaplama-araclari/finansman-hesaplama"
)
API_PATH = "https://www.vakifkatilim.com.tr/plugins/InstallmentPayBack"

# financingType kodları + örnek tutar/vade (ürün ailesine uygun)
FINANCING_TYPES: tuple[tuple[str, str, str, Decimal, int], ...] = (
    ("IF", "İhtiyaç Finansmanı", "ihtiyac_finansmani", Decimal("100000"), 18),
    ("KF", "Konut Finansmanı", "konut_finansmani", Decimal("1000000"), 120),
    ("TF", "Taşıt Finansmanı", "tasit_finansmani", Decimal("400000"), 48),
)


def _client() -> httpx.Client:
    settings = get_settings()
    return httpx.Client(
        timeout=30.0,
        headers={
            "User-Agent": settings.scraper_user_agent,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": CALCULATOR_URL,
            "Accept-Language": "tr-TR,tr;q=0.9",
            "Origin": "https://www.vakifkatilim.com.tr",
        },
        follow_redirects=True,
    )


def _csrf_token(html: str) -> str | None:
    soup = BeautifulSoup(html, "lxml")
    inp = soup.select_one('input[name="__RequestVerificationToken"]')
    if inp and inp.get("value"):
        return str(inp["value"])
    m = re.search(r'name="__RequestVerificationToken"\s+type="hidden"\s+value="([^"]+)"', html)
    if m:
        return m.group(1)
    m = re.search(r'__RequestVerificationToken"\s+value="([^"]+)"', html)
    return m.group(1) if m else None


def calculate(
    *,
    financing_type: str,
    product_label: str,
    product_type_hint: str | None,
    amount: Decimal,
    term_months: int,
    client: httpx.Client | None = None,
) -> FinancingCalculation | None:
    """InstallmentPayBack ile tek hesaplama."""
    kendi = client is None
    client = client or _client()
    try:
        sayfa = client.get(CALCULATOR_URL)
        sayfa.raise_for_status()
        token = _csrf_token(sayfa.text)
        if not token:
            logger.warning("vakif_csrf_yok")
            return None

        vade = min(term_months, bddk_ornek_vade(product_type_hint, amount))
        params = {
            "langId": LANG_ID,
            "language": "tr",
            "financingType": financing_type,
            "amount": str(int(amount)),
            "numberOfInstallments": str(int(vade)),
            "profitRate": "null",
            "calculateType": "1",
        }
        yanit = client.post(
            API_PATH,
            params=params,
            data={"__RequestVerificationToken": token},
            headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
        )
        yanit.raise_for_status()
        veri = yanit.json()
        if not isinstance(veri, dict):
            return None

        bilgi = veri.get("ornekOdemeBilgisi") or {}
        if not isinstance(bilgi, dict):
            bilgi = {}

        return FinancingCalculation(
            bank_code="vakif_katilim",
            product_label=product_label,
            product_type_hint=product_type_hint or urun_tipi_ipucu(product_label),
            amount=amount,
            term_months=vade,
            profit_rate_pct=parse_tr_rate(bilgi.get("karOrani")),
            monthly_installment=parse_tr_money(bilgi.get("taksitTutari")),
            total_payment=parse_tr_money(bilgi.get("odenecekToplamTutar")),
            source_url=CALCULATOR_URL,
            source_endpoint=f"{API_PATH}?{urlencode(params)}",
            raw_response=veri,
        )
    except Exception as exc:
        logger.warning("vakif_api_hata", tip=financing_type, hata=str(exc))
        return None
    finally:
        if kendi:
            client.close()


def probe_all(
    *,
    client: httpx.Client | None = None,
) -> list[FinancingCalculation]:
    """Üç ana finansman türü için örnek hesaplama (aileye uygun tutar/vade)."""
    kendi = client is None
    client = client or _client()
    try:
        sonuclar: list[FinancingCalculation] = []
        for kod, etiket, ipucu, tutar, vade in FINANCING_TYPES:
            calc = calculate(
                financing_type=kod,
                product_label=etiket,
                product_type_hint=ipucu,
                amount=tutar,
                term_months=vade,
                client=client,
            )
            if calc and calc.profit_rate_pct is not None:
                sonuclar.append(calc)
        return sonuclar
    finally:
        if kendi:
            client.close()
