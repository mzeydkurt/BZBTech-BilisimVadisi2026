"""Hayat Finans — calculateloansproduct (POST JSON).

Ana sayfa 'Kredi Hesapla' widget'ı (finansman; katılma getirisi değil).
Discovery 2026-08-23: `/api/integration/calculateloansproduct` · skor 125.
"""

from __future__ import annotations

from decimal import Decimal

import httpx

from app.config import get_settings
from app.logging_config import get_logger
from app.scrapers.calculator_probes.api_adapters import (
    FinancingCalculation,
    parse_tr_money,
    parse_tr_rate,
)
from app.scrapers.calculator_probes.common import bddk_ornek_vade

logger = get_logger(__name__)

HOME_URL = "https://hayatfinans.com.tr/"
API_URL = "https://hayatfinans.com.tr/api/integration/calculateloansproduct"

# Ana sayfa widget ürün kodu (NEXT_DATA / network).
PRODUCTS: tuple[tuple[str, str, str, Decimal, int], ...] = (
    ("BBACALCULATOR", "Bana Bunu Al (ihtiyaç)", "ihtiyac_finansmani", Decimal("500000"), 18),
)


def _client() -> httpx.Client:
    settings = get_settings()
    return httpx.Client(
        timeout=30.0,
        headers={
            "User-Agent": settings.scraper_user_agent,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": "https://hayatfinans.com.tr",
            "Referer": HOME_URL,
            "Accept-Language": "tr-TR,tr;q=0.9",
        },
        follow_redirects=True,
    )


def calculate(
    *,
    product_type_id: str,
    product_label: str,
    product_type_hint: str | None,
    amount: Decimal,
    term_months: int,
    client: httpx.Client | None = None,
) -> FinancingCalculation | None:
    kendi = client is None
    client = client or _client()
    try:
        vade = min(term_months, bddk_ornek_vade(product_type_hint, amount))
        body = {
            "productTypeId": product_type_id,
            "loanMaturity": str(int(vade)),
            "calculationTypeId": "1",
            "loanAmount": int(amount),
            "customRate": 0,
        }
        yanit = client.post(API_URL, json=body)
        yanit.raise_for_status()
        veri = yanit.json()
        if not isinstance(veri, dict) or not veri.get("isSuccessful"):
            return None
        data = veri.get("data") or {}
        if not isinstance(data, dict):
            return None
        taksitler = data.get("installmentList") or []
        aylik = None
        if isinstance(taksitler, list) and taksitler:
            aylik = parse_tr_money(taksitler[0].get("amount"))
        return FinancingCalculation(
            bank_code="hayat_finans",
            product_label=product_label,
            product_type_hint=product_type_hint,
            amount=amount,
            term_months=vade,
            profit_rate_pct=parse_tr_rate(data.get("monthlyProfitRate")),
            annual_cost_pct=parse_tr_rate(data.get("annualSimpleProfitRate")),
            monthly_installment=aylik,
            total_payment=parse_tr_money(data.get("totalInstallmentAmount")),
            source_url=HOME_URL,
            source_endpoint=API_URL,
            raw_response=veri if isinstance(veri, dict) else {},
        )
    except Exception as exc:
        logger.warning("hayat_api_hata", product=product_type_id, hata=str(exc))
        return None
    finally:
        if kendi:
            client.close()


def probe_all(*, client: httpx.Client | None = None) -> list[FinancingCalculation]:
    kendi = client is None
    client = client or _client()
    try:
        sonuclar: list[FinancingCalculation] = []
        for kod, etiket, ipucu, tutar, vade in PRODUCTS:
            calc = calculate(
                product_type_id=kod,
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
