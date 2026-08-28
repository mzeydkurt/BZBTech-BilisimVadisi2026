"""Albaraka — getFinanceCalculate (GET, JSON).

Discovery 2026-08-23: `/plugins/getFinanceCalculate` · skor 105.
FinanceType dropdown option JSON'undan gelir; tutar/vade query parametresi.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup

from app.config import get_settings
from app.logging_config import get_logger
from app.scrapers.banks.albaraka_jet import (
    JetCatalog,
    cap_amount_term,
    family_code_for_hint,
    parse_setting_params,
)
from app.scrapers.calculator_probes.api_adapters import (
    FinancingCalculation,
    parse_tr_money,
    parse_tr_rate,
)
from app.scrapers.calculator_probes.common import bddk_ornek_vade, urun_tipi_ipucu

logger = get_logger(__name__)

LANG_ID = "bf2689d9-071e-4a20-9450-b1dbdd39778f"
CALCULATOR_URL = (
    "https://www.albaraka.com.tr/tr/hesaplama-araclari/"
    "finansman-hesaplama/ihtiyac-finansmani-hesaplama"
)
API_URL = "https://www.albaraka.com.tr/plugins/getFinanceCalculate"
SETTINGS_URL = "https://basvur.albaraka.com.tr/ws/wsGetSettingParams"
JET_REFERER = "https://basvur.albaraka.com.tr/jet-finansman"


def _client(
    *,
    accept: str = "application/json, text/javascript, */*; q=0.01",
    ajax: bool = True,
) -> httpx.Client:
    settings = get_settings()
    headers = {
        "User-Agent": settings.scraper_user_agent,
        "Accept": accept,
        "Referer": CALCULATOR_URL,
        "Accept-Language": "tr-TR,tr;q=0.9",
    }
    if ajax:
        headers["X-Requested-With"] = "XMLHttpRequest"
    return httpx.Client(
        timeout=30.0,
        headers=headers,
        follow_redirects=True,
    )


def list_finance_types(client: httpx.Client | None = None) -> list[dict[str, Any]]:
    """Hesaplayıcı sayfasındaki ürün seçeneklerini (option value JSON) döndürür."""
    kendi = client is None
    # X-Requested-With ile istek JSON kabuğu döndürüyor; HTML için ajax=False.
    client = client or _client(accept="text/html,application/xhtml+xml;q=0.9,*/*;q=0.8", ajax=False)
    try:
        yanit = client.get(CALCULATOR_URL)
        yanit.raise_for_status()
        soup = BeautifulSoup(yanit.text, "lxml")
        sel = soup.select_one("#slcfinansmanTuru")
        if sel is None:
            logger.warning("albaraka_select_yok", content_type=yanit.headers.get("content-type"))
            return []
        urunler: list[dict[str, Any]] = []
        for opt in sel.find_all("option"):
            ham = (opt.get("value") or "").strip()
            etiket = opt.get_text(strip=True)
            if not ham or not etiket:
                continue
            try:
                meta = json.loads(ham)
            except json.JSONDecodeError:
                continue
            if not isinstance(meta, dict):
                continue
            meta["_label"] = etiket
            urunler.append(meta)
        logger.info("albaraka_urun_listesi", adet=len(urunler))
        return urunler
    finally:
        if kendi:
            client.close()


def load_setting_params(client: httpx.Client | None = None) -> JetCatalog:
    """Jet başvuru limitlerini çeker; hata olursa boş katalog."""
    kendi = client is None
    client = client or _client(accept="application/json, */*;q=0.8", ajax=False)
    try:
        # Referer başvuru formu; settings başka host'ta.
        yanit = client.get(SETTINGS_URL, headers={"Referer": JET_REFERER})
        yanit.raise_for_status()
        return parse_setting_params(yanit.json() if yanit.content else yanit.text)
    except Exception as exc:
        logger.warning("albaraka_jet_settings_hata", hata=str(exc))
        return JetCatalog()
    finally:
        if kendi:
            client.close()


def calculate(
    finance_type: dict[str, Any],
    *,
    amount: Decimal | None = None,
    term_months: int | None = None,
    client: httpx.Client | None = None,
    catalog: JetCatalog | None = None,
) -> FinancingCalculation | None:
    """Tek ürün için getFinanceCalculate çağırır."""
    etiket = str(finance_type.get("_label") or finance_type.get("CampaignName") or "finansman")
    ipucu = urun_tipi_ipucu(etiket)
    tutar = amount
    if tutar is None:
        tutar = Decimal(str(int(float(finance_type.get("AmountDefaultValue") or 150000))))
    if tutar > Decimal("2000000"):
        tutar = Decimal("1000000")

    vade = term_months
    if vade is None:
        vade = int(
            finance_type.get("MaturityDefaultValue") or finance_type.get("MaturityMaxValue") or 36
        )
    vade = min(
        vade, int(finance_type.get("MaturityMaxValue") or vade), bddk_ornek_vade(ipucu, tutar)
    )
    if catalog is not None and not catalog.is_empty:
        tutar, vade = cap_amount_term(
            catalog,
            family_code=family_code_for_hint(ipucu),
            amount=tutar,
            term_months=vade,
        )

    # API'ye gönderilecek FinanceType — iç etiket alanını çıkar
    tip = {k: v for k, v in finance_type.items() if not k.startswith("_")}

    params = {
        "langId": LANG_ID,
        "language": "tr",
        "Slug": "ihtiyac-finansmani-hesaplama",
        "searchUrl": "/tr/arama",
        "customFinancingName": "",
        "ProfitRateByMe": "false",
        "FinanceType": json.dumps(tip, ensure_ascii=False, separators=(",", ":")),
        "FinanceAmount": str(int(tutar)),
        "Maturity": str(int(vade)),
        "ProfitRate": "0",
        "Type": "B",
        "CreditType": "B",
    }

    kendi = client is None
    client = client or _client()
    try:
        yanit = client.get(API_URL, params=params)
        yanit.raise_for_status()
        veri = yanit.json()
        data = veri.get("Data") if isinstance(veri, dict) else None
        if not isinstance(data, dict):
            logger.warning("albaraka_api_bos", etiket=etiket, status=yanit.status_code)
            return None

        oran = parse_tr_rate(data.get("ProfitRate"))
        ymo_ham = data.get("AnnualCostRate")
        ymo = None
        if ymo_ham:
            # "% 85,1" yıllık maliyet — yüzde puanı
            m = re.search(r"([\d.,]+)", str(ymo_ham))
            if m:
                ymo = parse_tr_rate(m.group(1))

        tahsis = None
        for masraf in data.get("AmortizationScheduleExpenses") or []:
            if (
                isinstance(masraf, dict)
                and "tahsis" in str(masraf.get("FeeExplanation", "")).lower()
            ):
                tahsis = parse_tr_money(masraf.get("AmountWithTax"))
                break
        if tahsis is None:
            tahsis = parse_tr_money(data.get("TotalFees"))

        return FinancingCalculation(
            bank_code="albaraka",
            product_label=etiket,
            product_type_hint=ipucu,
            amount=tutar,
            term_months=vade,
            profit_rate_pct=oran,
            annual_cost_pct=ymo,
            monthly_installment=parse_tr_money(data.get("MonthlyInstallmentAmount")),
            total_payment=parse_tr_money(data.get("TotalAmountTobeRefunded")),
            allocation_fee=tahsis,
            source_url=CALCULATOR_URL,
            source_endpoint=(
                f"{API_URL}?{urlencode({'FinanceAmount': int(tutar), 'Maturity': vade})}"
            ),
            raw_response=veri if isinstance(veri, dict) else {"raw": veri},
        )
    except Exception as exc:
        logger.warning("albaraka_api_hata", etiket=etiket, hata=str(exc))
        return None
    finally:
        if kendi:
            client.close()


def probe_all(
    *,
    max_products: int = 24,
    client: httpx.Client | None = None,
) -> list[FinancingCalculation]:
    """Dropdown'daki ürünlerin bir kısmını API ile hesaplar.

    ⚠️ ÜST SINIR LİSTEYİ AŞMALI. Ölçüldü (2026-08-28): sayfada 16 tür var,
    sınır 12'ydi ve liste sonundaki `KONTKRD` (konut) hiç sorgulanmıyordu.
    Kesilen tür hata üretmez — yalnızca eksik veri üretir, ki fark edilmesi
    çok daha zordur.
    """
    # Liste HTML, hesaplama JSON — ayrı client'lar
    tipler = list_finance_types()
    katalog = load_setting_params()
    kendi = client is None
    client = client or _client()
    try:
        sonuclar: list[FinancingCalculation] = []
        if len(tipler) > max_products:
            # Kesme SESSİZ OLMAZ: kaç türün dışarıda kaldığı yazılır.
            logger.warning(
                "albaraka_tur_listesi_kesildi",
                toplam=len(tipler),
                sinir=max_products,
            )
        for tip in tipler[:max_products]:
            calc = calculate(tip, client=client, catalog=katalog)
            if calc and calc.profit_rate_pct is not None:
                sonuclar.append(calc)
        return sonuclar
    finally:
        if kendi:
            client.close()
