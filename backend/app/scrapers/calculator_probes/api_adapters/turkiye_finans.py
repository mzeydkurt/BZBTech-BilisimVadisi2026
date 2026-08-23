"""Türkiye Finans — GetFinanceCalculatorCreditTypeItems (GET JSON).

Ödeme planı sayfası ürün listesi; her vade bandında `Value` = aylık kâr oranı (%).
Ayrı hesaplama POST'u yok — oran client-side band tablosundan gelir.
Discovery 2026-08-23 / JS: turkiyefinans.modules.min.js
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx

from app.config import get_settings
from app.logging_config import get_logger
from app.scrapers.calculator_probes.api_adapters import (
    FinancingCalculation,
    parse_tr_rate,
)
from app.scrapers.calculator_probes.common import bddk_ornek_vade, urun_tipi_ipucu

logger = get_logger(__name__)

PAGE_URL = (
    "https://www.turkiyefinans.com.tr/tr-tr/hesaplama-araclari/"
    "Sayfalar/finansman-odeme-plani.aspx"
)
API_URL = (
    "https://www.turkiyefinans.com.tr/_vti_bin/TurkiyeFinansServices/"
    "FrontEndService.svc/GetFinanceCalculatorCreditTypeItems"
)


def _client() -> httpx.Client:
    settings = get_settings()
    return httpx.Client(
        timeout=30.0,
        headers={
            "User-Agent": settings.scraper_user_agent,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": PAGE_URL,
            "Accept-Language": "tr-TR,tr;q=0.9",
            "X-Requested-With": "XMLHttpRequest",
        },
        follow_redirects=True,
    )


def _band_sec(bands: list[dict[str, Any]]) -> dict[str, Any] | None:
    """En uzun vade bandını tercih et (Max ay)."""
    gecerli = [b for b in bands if isinstance(b, dict) and b.get("Value") is not None]
    if not gecerli:
        return None
    return max(gecerli, key=lambda b: int(b.get("Max") or 0))


def _ornek_tutar(ipucu: str | None) -> Decimal:
    if ipucu == "konut_finansmani":
        return Decimal("1000000")
    if ipucu == "tasit_finansmani":
        return Decimal("400000")
    return Decimal("100000")


def list_credit_types(client: httpx.Client | None = None) -> list[dict[str, Any]]:
    kendi = client is None
    client = client or _client()
    try:
        yanit = client.get(API_URL)
        yanit.raise_for_status()
        veri = yanit.json()
        blok = (veri or {}).get("GetFinanceCalculatorCreditTypeItemsResult") or {}
        data = blok.get("Data") or []
        if not isinstance(data, list):
            return []
        logger.info("tf_urun_listesi", adet=len(data))
        return [x for x in data if isinstance(x, dict)]
    finally:
        if kendi:
            client.close()


def probe_all(*, client: httpx.Client | None = None) -> list[FinancingCalculation]:
    """Her finansman türü için band tablosundaki aylık oranı al."""
    kendi = client is None
    client = client or _client()
    try:
        sonuclar: list[FinancingCalculation] = []
        for urun in list_credit_types(client):
            etiket = str(urun.get("Title") or urun.get("Code") or "finansman")
            ipucu = urun_tipi_ipucu(etiket)
            band = _band_sec(list(urun.get("FinanceCalculatorCreditList") or []))
            if band is None:
                continue
            oran = parse_tr_rate(band.get("Value"))
            if oran is None or oran <= 0:
                continue
            tutar = _ornek_tutar(ipucu)
            vade_max = int(band.get("Max") or 0)
            # Band Max küçük ay aralığı olabilir (1–3); BDDK örneği ile birleştir.
            vade = bddk_ornek_vade(ipucu, tutar)
            if vade_max > 0:
                # listedeki en uzun bandın Max'ı; gerçek üst sınır sayfada daha geniş
                # olabilir — Playwright probe tamamlar. Burada oranı kaydet.
                pass
            sonuclar.append(
                FinancingCalculation(
                    bank_code="turkiye_finans",
                    product_label=etiket,
                    product_type_hint=ipucu,
                    amount=tutar,
                    term_months=vade,
                    profit_rate_pct=oran,
                    annual_cost_pct=parse_tr_rate(band.get("Cost")),
                    allocation_fee=None,
                    source_url=PAGE_URL,
                    source_endpoint=API_URL,
                    raw_response={
                        "credit": {
                            "CreditID": urun.get("CreditID"),
                            "Code": urun.get("Code"),
                            "AllocationFee": urun.get("AllocationFee"),
                        },
                        "band": band,
                    },
                )
            )
        return sonuclar
    finally:
        if kendi:
            client.close()
