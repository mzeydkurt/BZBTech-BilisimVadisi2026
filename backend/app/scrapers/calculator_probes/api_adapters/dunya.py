"""Dünya Katılım — LoanInstallmentValues + LoanCheckRate (POST + CSRF).

Discovery: `/LoanInstallmentValues` ve `/LoanCheckRate` (JSON).
Tutar/vade limitleri `/LoanInstallmentValues` üzerinden dinamik olarak çekilir;
Sorgu tutarı hiçbir zaman azami limiti (maxAmount) aşamaz.
Sıfır kâr payı veya RATEERROR dönen sorgular kabul edilmez.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any
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
from app.scrapers.calculator_probes.common import urun_tipi_ipucu

import time

logger = get_logger(__name__)

CALCULATOR_URL = (
    "https://dunyakatilim.com.tr/kendim-icin/finansmanlar/konut-finansmanlari/konut-finansmani"
)
VALUES_URL = "https://dunyakatilim.com.tr/LoanInstallmentValues?lang=tr"
RATE_URL = "https://dunyakatilim.com.tr/LoanCheckRate?lang=tr"


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
            "Origin": "https://dunyakatilim.com.tr",
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


def list_finance_options(
    client: httpx.Client | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Hesaplayıcı sayfasındaki seçenekleri ve token'ı döndürür."""
    kendi = client is None
    client = client or _client()
    try:
        sayfa = client.get(CALCULATOR_URL)
        sayfa.raise_for_status()
        token = _csrf_token(sayfa.text)
        if not token:
            logger.warning("dunya_csrf_yok")
            return "", []

        soup = BeautifulSoup(sayfa.text, "lxml")
        sel = soup.select_one("#loanSelect")
        if sel is None:
            logger.warning("dunya_select_yok")
            return token, []

        options: list[dict[str, Any]] = []
        for opt in sel.find_all("option"):
            kod = (opt.get("value") or "").strip()
            etiket = opt.get_text(strip=True)
            if not kod or not etiket:
                continue

            time.sleep(0.4)
            # Limitleri LoanInstallmentValues'tan çek
            val_res = client.post(
                VALUES_URL,
                data={"productCode": kod, "__RequestVerificationToken": token},
            )
            if val_res.status_code != 200:
                continue
            try:
                values_data = val_res.json()
            except Exception:
                continue

            if not isinstance(values_data, dict) or values_data.get("result") != "SUCCESS":
                continue

            options.append(
                {
                    "code": kod,
                    "label": etiket,
                    "values": values_data,
                }
            )

        logger.info("dunya_urun_secenekleri", adet=len(options))
        return token, options
    except Exception as exc:
        logger.warning("dunya_secenek_hata", hata=str(exc))
        return "", []
    finally:
        if kendi:
            client.close()


def calculate(
    option: dict[str, Any],
    token: str,
    *,
    amount: Decimal | None = None,
    term_months: int | None = None,
    client: httpx.Client | None = None,
) -> FinancingCalculation | None:
    """Tek ürün için azami limit tavanına uygun LoanCheckRate çağırır."""
    kod = option.get("code") or ""
    etiket = option.get("label") or ""
    values = option.get("values") or {}

    max_amount_num = float(values.get("maxAmount") or 0)
    min_amount_num = float(values.get("minAmount") or 0)
    default_amount_num = float(values.get("defaultAmount") or 0)

    # Sorgu tutarını belirle ve azami limit tavanı ile sınırla
    tutar_sayi = float(amount) if amount is not None else (default_amount_num or max_amount_num)
    if max_amount_num > 0 and tutar_sayi > max_amount_num:
        tutar_sayi = max_amount_num
    if min_amount_num > 0 and tutar_sayi < min_amount_num:
        tutar_sayi = min_amount_num

    tutar = Decimal(str(int(tutar_sayi)))

    max_inst = int(values.get("maxInstallment") or 12)
    min_inst = int(values.get("minInstallment") or 1)
    def_inst = int(values.get("defaultInstallment") or 12)

    vade = term_months if term_months is not None else def_inst
    if max_inst > 0 and vade > max_inst:
        vade = max_inst
    if min_inst > 0 and vade < min_inst:
        vade = min_inst

    cat = values.get("category") or ""
    amount_str = f"{int(tutar_sayi):,.0f}".replace(",", ".")

    ipucu = urun_tipi_ipucu(etiket)

    payload = {
        "productName": etiket,
        "productCode": kod,
        "productCategory": cat,
        "amount": amount_str,
        "installmentCount": vade,
        "userRate": "0,00",
        "userSelected": "false",
        "__RequestVerificationToken": token,
    }

    kendi = client is None
    client = client or _client()
    try:
        time.sleep(0.4)
        resp = client.post(RATE_URL, data=payload)
        resp.raise_for_status()
        res_data = resp.json()
        if not isinstance(res_data, dict):
            logger.warning("dunya_api_bos_yanit", kod=kod)
            return None

        if res_data.get("result") != "SUCCESS":
            logger.info("dunya_api_basarisiz", kod=kod, result=res_data.get("result"))
            return None

        oran = parse_tr_rate(res_data.get("rate"))
        # Sıfır veya negatif oran hatalı limit/API sonucudur; kabul edilmez
        if oran is None or oran <= Decimal("0.05"):
            logger.info("dunya_api_gecersiz_oran", kod=kod, oran=str(oran))
            return None

        taksit = parse_tr_money(res_data.get("monthlyInterest"))
        toplam = parse_tr_money(res_data.get("totalPayment"))

        return FinancingCalculation(
            bank_code="dunya_katilim",
            product_label=etiket,
            product_type_hint=ipucu,
            amount=tutar,
            term_months=vade,
            profit_rate_pct=oran,
            monthly_installment=taksit,
            total_payment=toplam,
            source_url=CALCULATOR_URL,
            source_endpoint=(f"{RATE_URL} (code={kod}, amount={amount_str}, term={vade})"),
            raw_response={"values": values, "rate": res_data},
        )
    except Exception as exc:
        logger.warning("dunya_api_hata", kod=kod, hata=str(exc))
        return None
    finally:
        if kendi:
            client.close()


def probe_all(
    *,
    client: httpx.Client | None = None,
) -> list[FinancingCalculation]:
    """Tüm Dünya Katılım finansman seçeneklerini API üzerinden sorgular."""
    kendi = client is None
    client = client or _client()
    try:
        token, options = list_finance_options(client=client)
        if not token or not options:
            return []

        sonuclar: list[FinancingCalculation] = []
        for opt in options:
            calc = calculate(opt, token, client=client)
            if calc and calc.profit_rate_pct is not None and calc.profit_rate_pct > Decimal("0.05"):
                sonuclar.append(calc)
        return sonuclar
    finally:
        if kendi:
            client.close()
