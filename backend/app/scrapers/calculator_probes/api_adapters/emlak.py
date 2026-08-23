"""Emlak Katılım — CalculateLoansProduct (GET JSON).

Ana sayfa finansman widget'ı (`#js-productType`).
Discovery 2026-08-23: `/Plugins/CalculateLoansProduct` · skor 105.
"""

from __future__ import annotations

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

HOME_URL = "https://www.emlakkatilim.com.tr/tr"
API_URL = "https://www.emlakkatilim.com.tr/Plugins/CalculateLoansProduct"

_FALLBACK: tuple[tuple[str, str], ...] = (
    ("ARACBINEK2EL", "2. El Taşıt Finansmanı"),
    ("ARACBINEKYENI", "0 Km Taşıt Finansmanı"),
    ("EVOFISGERECLERI", "İhtiyaç Finansmanı"),
    ("GMENKULKONUTYENI", "Yeni Konut Finansmanı"),
)


def _html_client() -> httpx.Client:
    settings = get_settings()
    return httpx.Client(
        timeout=30.0,
        headers={
            "User-Agent": settings.scraper_user_agent,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "tr-TR,tr;q=0.9",
        },
        follow_redirects=True,
    )


def _api_client() -> httpx.Client:
    settings = get_settings()
    return httpx.Client(
        timeout=30.0,
        headers={
            "User-Agent": settings.scraper_user_agent,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": HOME_URL,
            "Accept-Language": "tr-TR,tr;q=0.9",
        },
        follow_redirects=True,
    )


def list_products(client: httpx.Client | None = None) -> list[tuple[str, str]]:
    """Ana sayfa `#js-productType` seçenekleri."""
    kendi = client is None
    client = client or _html_client()
    try:
        yanit = client.get(HOME_URL)
        yanit.raise_for_status()
        soup = BeautifulSoup(yanit.text, "lxml")
        sel = soup.select_one("#js-productType, select.js-productType")
        urunler: list[tuple[str, str]] = []
        if sel is not None:
            for opt in sel.find_all("option"):
                kod = (opt.get("value") or "").strip()
                etiket = opt.get_text(strip=True)
                if kod and etiket:
                    urunler.append((kod, etiket))
        if not urunler:
            logger.warning("emlak_select_yok_fallback")
            return list(_FALLBACK)
        logger.info("emlak_urun_listesi", adet=len(urunler))
        return urunler
    finally:
        if kendi:
            client.close()


def _ornek_tutar_vade(ipucu: str | None) -> tuple[Decimal, int]:
    if ipucu == "konut_finansmani":
        return Decimal("1000000"), 120
    if ipucu == "tasit_finansmani":
        return Decimal("400000"), 48
    return Decimal("100000"), 18


def calculate(
    *,
    product_type_id: str,
    product_label: str,
    amount: Decimal | None = None,
    term_months: int | None = None,
    client: httpx.Client | None = None,
) -> FinancingCalculation | None:
    kendi = client is None
    client = client or _api_client()
    try:
        ipucu = urun_tipi_ipucu(product_label)
        ornek_tutar, ornek_vade = _ornek_tutar_vade(ipucu)
        tutar = amount if amount is not None else ornek_tutar
        vade = term_months if term_months is not None else ornek_vade
        vade = min(vade, bddk_ornek_vade(ipucu, tutar))
        params = {
            "CalculationTypeId": "1",
            "ProductTypeId": product_type_id,
            "LoanAmount": str(int(tutar)),
            "LoanMaturity": str(int(vade)),
            "LoanSegmentId": "1",
        }
        yanit = client.get(API_URL, params=params)
        yanit.raise_for_status()
        veri = yanit.json()
        if not isinstance(veri, dict) or not veri.get("Success"):
            return None
        data = veri.get("Data") or {}
        if not isinstance(data, dict):
            return None
        oran = parse_tr_rate(data.get("ProfitRate"))
        if oran is None or oran <= 0:
            return None
        taksitler = data.get("InstallmentContractList") or []
        aylik = None
        if isinstance(taksitler, list) and taksitler:
            aylik = parse_tr_money(taksitler[0].get("Amount"))
        return FinancingCalculation(
            bank_code="emlak_katilim",
            product_label=product_label,
            product_type_hint=ipucu,
            amount=tutar,
            term_months=vade,
            profit_rate_pct=oran,
            monthly_installment=aylik,
            total_payment=parse_tr_money(data.get("TotalInstallmentAmount")),
            allocation_fee=parse_tr_money(data.get("CommissionAmount")),
            source_url=HOME_URL,
            source_endpoint=f"{API_URL}?{urlencode(params)}",
            raw_response=veri,
        )
    except Exception as exc:
        logger.warning("emlak_api_hata", product=product_type_id, hata=str(exc))
        return None
    finally:
        if kendi:
            client.close()


def probe_all(*, client: httpx.Client | None = None) -> list[FinancingCalculation]:
    kendi = client is None
    api = client or _api_client()
    try:
        urunler = list_products()
        sonuclar: list[FinancingCalculation] = []
        for kod, etiket in urunler:
            calc = calculate(
                product_type_id=kod,
                product_label=etiket,
                client=api,
            )
            if calc and calc.profit_rate_pct is not None:
                sonuclar.append(calc)
        return sonuclar
    finally:
        if kendi:
            api.close()
