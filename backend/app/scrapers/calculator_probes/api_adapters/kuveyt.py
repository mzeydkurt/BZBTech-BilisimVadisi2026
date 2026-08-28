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
from app.scrapers.calculator_probes.common import (
    bddk_ornek_noktalar,
    bddk_ornek_vade,
    urun_tipi_ipucu,
)

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


def _param_entry(product: dict[str, Any], key: str) -> dict[str, Any] | None:
    for p in product.get("Parameters") or []:
        if isinstance(p, dict) and p.get("Key") == key:
            return p
    return None


def _as_decimal(ham: Any) -> Decimal | None:
    if ham is None or ham == "":
        return None
    try:
        return Decimal(str(ham))
    except Exception:
        return None


def _as_int(ham: Any) -> int | None:
    if ham is None or ham == "":
        return None
    try:
        return int(float(ham))
    except Exception:
        return None


def _katalog_tutar_sinirlari(product: dict[str, Any]) -> tuple[Decimal, Decimal]:
    lo = _as_decimal(_param(product, "DefaultAmountMin")) or Decimal("1000")
    hi = _as_decimal(_param(product, "DefaultAmountMax")) or Decimal("5000000")
    if hi < lo:
        hi = lo
    return lo, hi


def _katalog_vade_adimlari(product: dict[str, Any]) -> list[tuple[Decimal, int, int]]:
    """Katalogdaki tutar eşiği → (vade_min, vade_max). Description = eşik TL."""
    adimlar: list[tuple[Decimal, int, int]] = []
    for sonek in ("", "2", "3", "4"):
        emax = _param_entry(product, f"MaturityTermMax{sonek}")
        if emax is None:
            continue
        vmax = _as_int(emax.get("Value"))
        if vmax is None or vmax < 1:
            continue
        emin = _param_entry(product, f"MaturityTermMin{sonek}")
        vmin = _as_int(emin.get("Value")) if emin else None
        if vmin is None or vmin < 1:
            vmin = 1
        desc = emax.get("Description")
        if desc in (None, ""):
            desc = emin.get("Description") if emin else None
        esik = _as_decimal(desc) or Decimal("0")
        adimlar.append((esik, vmin, vmax))
    adimlar.sort(key=lambda a: a[0])
    return adimlar


def _katalog_vade_araligi(product: dict[str, Any], amount: Decimal) -> tuple[int, int]:
    adimlar = _katalog_vade_adimlari(product)
    if not adimlar:
        return 1, 120
    secilen = adimlar[0]
    for esik, vmin, vmax in adimlar:
        if amount >= esik:
            secilen = (esik, vmin, vmax)
        else:
            break
    return secilen[1], secilen[2]


def _noktayi_kirp(
    product: dict[str, Any],
    *,
    title: str,
    amount: Decimal,
    term_months: int,
) -> tuple[Decimal, int] | None:
    ipucu = urun_tipi_ipucu(title)
    lo, hi = _katalog_tutar_sinirlari(product)
    tutar = min(max(amount, lo), hi)
    kat_min, kat_max = _katalog_vade_araligi(product, tutar)
    vade = min(term_months, kat_max, bddk_ornek_vade(ipucu, tutar))
    vade = max(vade, kat_min, 1)
    if tutar < lo or tutar > hi or vade < 1:
        return None
    return tutar, vade


def probe_noktalari(title: str, product: dict[str, Any]) -> list[tuple[Decimal, int]]:
    """BDDK bantları + katalog vade basamaklarından (tutar, vade) listesi.

    Kâr payı sayfada yok; her nokta için `p2`/`p3` POST'u `Meta.ProfitRate` döner.
    Taşıtta 500.000 TL örnek BDDK 400.000/48 bandını kaçırır — o yüzden bant
    tavanlarında sorgulanır.
    """
    ipucu = urun_tipi_ipucu(title)
    adaylar: list[tuple[Decimal, int]] = list(bddk_ornek_noktalar(ipucu))
    noktalar: list[tuple[Decimal, int]] = []
    gorulen: set[tuple[int, int]] = set()
    terimler: set[int] = set()
    for tutar, vade in adaylar:
        kirpilmis = _noktayi_kirp(product, title=title, amount=tutar, term_months=vade)
        if kirpilmis is None:
            continue
        anahtar = (int(kirpilmis[0]), kirpilmis[1])
        if anahtar in gorulen:
            continue
        gorulen.add(anahtar)
        terimler.add(kirpilmis[1])
        noktalar.append(kirpilmis)

    lo, hi = _katalog_tutar_sinirlari(product)
    adimlar = _katalog_vade_adimlari(product)
    for i, (esik, _vmin, vmax) in enumerate(adimlar):
        sonraki = adimlar[i + 1][0] if i + 1 < len(adimlar) else hi + Decimal("1")
        tutar = max(esik, lo)
        if tutar < Decimal("10000") and Decimal("10000") < sonraki:
            tutar = Decimal("10000")
        if tutar >= sonraki:
            tutar = max(esik, lo)
        kirpilmis = _noktayi_kirp(product, title=title, amount=tutar, term_months=vmax)
        if kirpilmis is None:
            continue
        if kirpilmis[1] in terimler:
            continue
        anahtar = (int(kirpilmis[0]), kirpilmis[1])
        if anahtar in gorulen:
            continue
        gorulen.add(anahtar)
        terimler.add(kirpilmis[1])
        noktalar.append(kirpilmis)

    if noktalar:
        return noktalar
    yedek = _noktayi_kirp(product, title=title, amount=Decimal("100000"), term_months=36)
    return [yedek] if yedek else []


def _ornek_tutar_vade(title: str, product: dict[str, Any]) -> tuple[Decimal, int]:
    noktalar = probe_noktalari(title, product)
    if noktalar:
        return noktalar[0]
    return Decimal("100000"), 36


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
        if amount is None or term_months is None:
            ornek_tutar, ornek_vade = _ornek_tutar_vade(title, product)
            tutar = amount if amount is not None else ornek_tutar
            vade = term_months if term_months is not None else ornek_vade
        else:
            tutar, vade = amount, term_months
        kirpilmis = _noktayi_kirp(product, title=title, amount=tutar, term_months=vade)
        if kirpilmis is None:
            return None
        tutar, vade = kirpilmis
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
            # AllocationAmount hesaplayıcı tahminidir; Kuveyt tablosu
            # "bağlayıcı değildir" der ve tahsis peşin/ayrı tahsil edilir.
            # Kesin ücret tablosu yoksa simülatöre yazılmaz.
            allocation_fee=None,
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
        ilk = True
        for urun in urunler:
            title = str(urun.get("Title") or "finansman")
            for tutar, vade in probe_noktalari(title, urun):
                if not ilk:
                    time.sleep(0.6)
                ilk = False
                calc = calculate(urun, amount=tutar, term_months=vade, client=client)
                if calc and calc.profit_rate_pct is not None:
                    sonuclar.append(calc)
        return sonuclar
    finally:
        if kendi:
            client.close()
