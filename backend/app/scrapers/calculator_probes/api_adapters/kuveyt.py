"""Kuveyt Türk — ck0d84 LoanCalculator (oturumlu httpx).

1) Hesaplama sayfasını aç (çerez)
2) GET `ck0d84?{CFG}&p1=LoanCalculator` → ürün listesi
3) POST `ck0d84?{CALC}` JSON gövde → Meta.ProfitRate

CAPTCHA bypass yok; bu uç HTTP ile yanıt veriyor (Playwright şart değil).
Route hash'leri sayfa HTML'inde sabit; discovery 2026-08-23 ile doğrulandı.
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any

import httpx

from app.config import get_settings
from app.logging_config import get_logger
from app.scrapers.calculator_probes.api_adapters import (
    FinancingCalculation,
    parse_tr_money,
    parse_tr_rate,
)
from app.scrapers.calculator_probes.common import bddk_ornek_vade, urun_tipi_ipucu

logger = get_logger(__name__)

CALC_URL = "https://www.kuveytturk.com.tr/hesaplama-araclari/finansman-hesaplama"
# Sayfa route tablosundaki sabit uçlar (oturum çerezi gerekir, hash değişmez).
CFG_HASH = "9592031673D7885E535AEF67BC5D9213"
CALC_HASH = "30134915811C6D92B8F34A01FCF910EE"


def _client() -> httpx.Client:
    settings = get_settings()
    return httpx.Client(
        timeout=40.0,
        headers={
            "User-Agent": settings.scraper_user_agent,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "tr-TR,tr;q=0.9",
            "X-Bone-Language": "TR",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": CALC_URL,
            "Origin": "https://www.kuveytturk.com.tr",
        },
        follow_redirects=True,
    )


def _param(product: dict[str, Any], key: str) -> str | None:
    for p in product.get("Parameters") or []:
        if isinstance(p, dict) and p.get("Key") == key:
            val = p.get("Value")
            return str(val) if val is not None else None
    return None


def _ornek_tutar_vade(title: str, product: dict[str, Any]) -> tuple[Decimal, int]:
    ipucu = urun_tipi_ipucu(title)
    max_amt = _param(product, "DefaultAmountMax")
    max_term = _param(product, "MaturityTermMax")
    try:
        ust_tutar = Decimal(max_amt) if max_amt else Decimal("500000")
    except Exception:
        ust_tutar = Decimal("500000")
    try:
        ust_vade = int(float(max_term)) if max_term else 36
    except Exception:
        ust_vade = 36
    if ust_vade < 1:
        ust_vade = 1

    if ipucu == "konut_finansmani":
        tutar = min(ust_tutar, Decimal("1000000"))
    elif ipucu == "tasit_finansmani":
        tutar = min(ust_tutar, Decimal("500000"))
    else:
        tutar = min(ust_tutar, Decimal("100000"))
    if tutar < 1000:
        tutar = min(ust_tutar, Decimal("1000"))

    vade = min(ust_vade, bddk_ornek_vade(ipucu, tutar))
    vade = max(1, min(vade, ust_vade))
    return tutar, vade


def bootstrap(client: httpx.Client) -> None:
    """Çerez için hesaplama sayfasını aç."""
    client.get(CALC_URL, headers={"Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"})


def list_products(client: httpx.Client | None = None) -> list[dict[str, Any]]:
    kendi = client is None
    client = client or _client()
    try:
        bootstrap(client)
        yanit = client.get(
            f"https://www.kuveytturk.com.tr/ck0d84?{CFG_HASH}&p1=LoanCalculator",
        )
        yanit.raise_for_status()
        veri = yanit.json()
        if not isinstance(veri, list):
            return []
        logger.info("kuveyt_urun_listesi", adet=len(veri))
        return [p for p in veri if isinstance(p, dict) and p.get("Title")]
    finally:
        if kendi:
            client.close()


def calculate(
    product: dict[str, Any],
    *,
    amount: Decimal | None = None,
    term_months: int | None = None,
    client: httpx.Client | None = None,
) -> FinancingCalculation | None:
    kendi = client is None
    client = client or _client()
    try:
        if kendi:
            bootstrap(client)
        title = str(product.get("Title") or "finansman")
        code = _param(product, "ProductCode") or "ECOMMERCE"
        ornek_tutar, ornek_vade = _ornek_tutar_vade(title, product)
        tutar = amount if amount is not None else ornek_tutar
        vade = term_months if term_months is not None else ornek_vade
        body = {
            "i": True,
            "p1": "1",
            "p2": str(int(tutar)),
            "p3": str(int(vade)),
            "p4": code,
            "p5": code,
            "p6": "0.00",
            "p7": "",
            "p8": title,
        }
        yanit = client.post(
            f"https://www.kuveytturk.com.tr/ck0d84?{CALC_HASH}",
            json=body,
            headers={"Content-Type": "application/json; charset=UTF-8"},
        )
        yanit.raise_for_status()
        veri = yanit.json()
        if not isinstance(veri, dict):
            return None
        meta = veri.get("Meta") or {}
        if not isinstance(meta, dict):
            return None
        oran = parse_tr_rate(meta.get("ProfitRate"))
        if oran is None:
            return None
        return FinancingCalculation(
            bank_code="kuveyt_turk",
            product_label=title,
            product_type_hint=urun_tipi_ipucu(title),
            amount=tutar,
            term_months=vade,
            profit_rate_pct=oran,
            annual_cost_pct=parse_tr_rate(meta.get("YearlyCost")),
            monthly_installment=parse_tr_money(meta.get("InstallmentPayment")),
            total_payment=parse_tr_money(meta.get("TotalAmount")),
            allocation_fee=parse_tr_money(meta.get("AllocationAmount")),
            source_url=CALC_URL,
            source_endpoint=f"https://www.kuveytturk.com.tr/ck0d84?{CALC_HASH}",
            raw_response=veri,
        )
    except Exception as exc:
        logger.warning("kuveyt_api_hata", urun=product.get("Title"), hata=str(exc))
        return None
    finally:
        if kendi:
            client.close()


def probe_all(*, client: httpx.Client | None = None) -> list[FinancingCalculation]:
    kendi = client is None
    client = client or _client()
    try:
        urunler = list_products(client)
        sonuclar: list[FinancingCalculation] = []
        for i, urun in enumerate(urunler):
            if i:
                time.sleep(0.6)
            calc = calculate(urun, client=client)
            if calc and calc.profit_rate_pct is not None:
                sonuclar.append(calc)
        return sonuclar
    finally:
        if kendi:
            client.close()
