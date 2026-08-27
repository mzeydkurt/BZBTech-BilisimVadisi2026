"""Banka hesaplayıcı sayfalarından Playwright ile veri okuma."""

from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any

from app.core.normalization.money import parse_decimal_tr
from app.core.normalization.rate import parse_rate
from app.core.normalization.text import lower_tr
from app.scrapers.calculator_probes.common import (
    ProbeReading,
    bddk_ornek_noktalar,
    bddk_ornek_vade,
    bekle,
    cerez_kapat,
    metinden_oran,
    metinden_taksit_toplam,
    oran_gecerli,
    urun_tipi_ipucu,
)
from app.scrapers.calculator_probes.targets import ProbeTarget


def _filtre(etiket: str, filtre: tuple[str, ...] | None) -> bool:
    if not filtre:
        return True
    d = lower_tr(etiket)
    return any(f in d for f in filtre)


def probe_albaraka_json(page: Any, hedef: ProbeTarget) -> list[ProbeReading]:
    """Albaraka dropdown option value'ları JSON — profitRate doğrudan okunur."""
    page.goto(hedef.url, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(2500)
    cerez_kapat(page)
    opts_data = page.evaluate(
        """() => {
        const sel = document.querySelector('#slcfinansmanTuru');
        if (!sel) return [];
        return [...sel.options].map(o => ({ t: o.textContent.trim(), v: o.value }));
    }"""
    )
    sonuclar: list[ProbeReading] = []
    for opt in opts_data:
        etiket = (opt.get("t") or "").strip()
        if not etiket or not _filtre(etiket, hedef.product_filter):
            continue
        raw = opt.get("v") or ""
        try:
            meta = json.loads(raw)
        except json.JSONDecodeError:
            continue
        oran = Decimal(str(meta.get("profitRate"))) if meta.get("profitRate") is not None else None
        amount = Decimal(str(int(float(meta.get("AmountMaxValue", 500000)))))
        if amount > Decimal("2000000"):
            amount = Decimal("1000000")
        term = int(meta.get("MaturityMaxValue") or 36)
        if term <= 0:
            term = 36
        ipucu = urun_tipi_ipucu(etiket)
        term = min(term, bddk_ornek_vade(ipucu, amount))
        if oran is None:
            continue
        sonuclar.append(
            ProbeReading(
                bank_code=hedef.bank_code,
                source_url=hedef.url,
                variant_label=etiket,
                amount=amount,
                term_months=term,
                profit_rate_pct=oran,
                product_type_hint=ipucu,
                raw_meta=meta,
            )
        )
    return sonuclar


def _kuveyt_oran(metin: str) -> Decimal | None:
    """Kuveyt tablosunda taksit ile karışmasın diye hedefli çıkarım."""
    dusuk = metin.casefold()
    for baslik in ("aylık kâr oranı", "aylik kar orani", "aylık kar oranı"):
        idx = dusuk.find(baslik)
        if idx >= 0:
            parca = metin[idx : idx + 120]
            m = re.search(r"%\s*(\d+[.,]\d+)", parca)
            if m:
                o = parse_rate(m.group(0))
                if o is not None and o < Decimal("10"):
                    return o
    for m in re.finditer(r"%\s*(\d+[.,]\d+)", metin):
        o = parse_rate(m.group(0))
        if o is not None and Decimal("0.5") <= o <= Decimal("10"):
            return o
    return None


def probe_kuveyt_product_dropdown(page: Any, hedef: ProbeTarget) -> list[ProbeReading]:
    page.goto(hedef.url, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(2500)
    cerez_kapat(page)
    sel = page.locator("select").first
    opts = sel.evaluate(
        "el => [...el.options].map(o => ({v:o.value,t:o.textContent.trim()})).filter(o=>o.v)"
    )
    sonuclar: list[ProbeReading] = []
    for opt in opts:
        etiket = opt["t"]
        sel.select_option(value=opt["v"])
        page.wait_for_timeout(1200)
        ipucu = urun_tipi_ipucu(etiket)
        amount, _bddk_vade = bddk_ornek_noktalar(ipucu)[0]
        # tutar
        for s in ('input[type="number"]', 'input[name*="amount" i]'):
            try:
                loc = page.locator(s).first
                if loc.count():
                    loc.fill(str(int(amount)))
                    break
            except Exception:
                pass
        page.wait_for_timeout(800)
        # vade — son seçenek
        vade_sel = page.locator("select").nth(1)
        try:
            if vade_sel.count():
                vals = vade_sel.evaluate("el => [...el.options].map(o=>o.value).filter(Boolean)")
                if vals:
                    vade_sel.select_option(value=vals[-1])
                    term = int(vals[-1])
                else:
                    term = 36
            else:
                term = 36
        except Exception:
            term = 36
        page.wait_for_timeout(1500)
        metin = page.inner_text("body")
        oran = _kuveyt_oran(metin)
        taksit, toplam = metinden_taksit_toplam(metin)
        term = min(term, bddk_ornek_vade(ipucu, amount))
        notice = None
        nm = re.search(r"(125\.000 TL.+?aşamaz\.)", metin.replace("\u00a0", " "))
        if nm:
            notice = nm.group(1)
        sonuclar.append(
            ProbeReading(
                bank_code=hedef.bank_code,
                source_url=hedef.url,
                variant_label=etiket,
                amount=amount,
                term_months=term,
                profit_rate_pct=oran,
                monthly_installment=taksit,
                total_repayment=toplam,
                notice_text=notice,
                product_type_hint=ipucu,
            )
        )
        bekle()
    return sonuclar


def probe_vakif_loan_type(page: Any, hedef: ProbeTarget) -> list[ProbeReading]:
    page.goto(hedef.url, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(2500)
    cerez_kapat(page)
    tip_sel = page.locator("#financing-type-select")
    opts = tip_sel.evaluate("el => [...el.options].map(o=>({v:o.value,t:o.textContent.trim()}))")
    sonuclar: list[ProbeReading] = []
    for opt in opts:
        etiket = opt["t"]
        tip_sel.select_option(value=opt["v"])
        page.wait_for_timeout(1200)
        vade_sel = page.locator("#number-of-installments-select")
        term = 36
        try:
            vals = vade_sel.evaluate(
                "el => [...el.options].map(o=>parseInt(o.value)).filter(n=>n>0)"
            )
            if vals:
                term = max(vals)
                vade_sel.select_option(value=str(term))
        except Exception:
            pass
        amount = Decimal("500000")
        for s in ('input[id*="amount" i]', 'input[type="text"]'):
            try:
                loc = page.locator(s).first
                if loc.count() and loc.is_visible():
                    loc.fill(str(int(amount)))
                    break
            except Exception:
                pass
        page.wait_for_timeout(1500)
        metin = page.inner_text("body")
        oran = metinden_oran(metin)
        # vakıf kar oranı input
        try:
            val = page.locator('input[id*="rate" i], input[name*="rate" i]').first.input_value()
            if val:
                o2 = parse_decimal_tr(val)
                if o2 is not None:
                    oran = o2
        except Exception:
            pass
        taksit, toplam = metinden_taksit_toplam(metin)
        ipucu = urun_tipi_ipucu(etiket)
        sonuclar.append(
            ProbeReading(
                bank_code=hedef.bank_code,
                source_url=hedef.url,
                variant_label=etiket,
                amount=amount,
                term_months=term,
                profit_rate_pct=oran,
                monthly_installment=taksit,
                total_repayment=toplam,
                product_type_hint=ipucu,
            )
        )
        bekle()
    return sonuclar


def _select2_sec(page: Any, select_id: str, value: str) -> None:
    """Gizli select / select2 için JS ile değer ata."""
    page.evaluate(
        """([id, val]) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.value = val;
        el.dispatchEvent(new Event('change', { bubbles: true }));
        if (window.jQuery) window.jQuery(el).trigger('change');
    }""",
        [select_id, value],
    )


def probe_turkiye_finans_type(page: Any, hedef: ProbeTarget) -> list[ProbeReading]:
    page.goto(hedef.url, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(3000)
    cerez_kapat(page)
    opts = page.evaluate(
        """() => {
        const el = document.getElementById('financial_type');
        if (!el) return [];
        return [...el.options].map(o => ({v: o.value, t: o.textContent.trim()}));
    }"""
    )
    sonuclar: list[ProbeReading] = []
    for opt in opts:
        etiket = opt["t"]
        _select2_sec(page, "financial_type", opt["v"])
        page.wait_for_timeout(2500)
        amount = Decimal("500000")
        ipucu = urun_tipi_ipucu(etiket)
        term = bddk_ornek_vade(ipucu, amount)
        try:
            page.locator("#txtFinansman").fill(str(int(amount)))
            page.locator("#txtFinansman").dispatch_event("change")
        except Exception:
            pass
        # vade select2
        try:
            page.locator(".select2-choice, .select2-selection").first.click(timeout=2000)
            page.wait_for_timeout(400)
            page.locator(".select2-results li").last.click(timeout=2000)
        except Exception:
            pass
        page.wait_for_timeout(2000)
        oran = None
        taksit = toplam = None
        try:
            rv = page.locator("#txtRate").input_value()
            if rv:
                oran = parse_decimal_tr(rv)
        except Exception:
            pass
        try:
            tv = page.locator("#txtAylikTaksitTutari").input_value()
            if tv:
                taksit = parse_decimal_tr(tv)
        except Exception:
            pass
        metin = page.inner_text("body")
        if oran is None:
            oran = metinden_oran(metin)
        if taksit is None:
            taksit, toplam = metinden_taksit_toplam(metin)
        # tablo satırı
        try:
            hucreler = page.locator("table tr").nth(1).locator("td").all_inner_texts()
            if len(hucreler) >= 4:
                if oran is None:
                    oran = parse_rate(hucreler[3])
                if taksit is None and len(hucreler) > 1:
                    taksit = parse_decimal_tr(hucreler[1])
        except Exception:
            pass
        notice = None
        # Sayfa içi ürün açıklaması blokları
        for par in page.locator(".ms-rtestate-field, .page-content, #DeltaPlaceHolderMain").all():
            try:
                t = par.inner_text()
                if etiket.split("/")[0].strip()[:12].casefold() in t.casefold()[:200]:
                    notice = t.strip()[:1200]
                    break
            except Exception:
                continue
        sonuclar.append(
            ProbeReading(
                bank_code=hedef.bank_code,
                source_url=hedef.url,
                variant_label=etiket,
                amount=amount,
                term_months=term,
                profit_rate_pct=oran,
                monthly_installment=taksit,
                total_repayment=toplam,
                notice_text=notice,
                product_type_hint=ipucu,
            )
        )
        bekle()
    return sonuclar


def probe_ziraat_product_dropdown(page: Any, hedef: ProbeTarget) -> list[ProbeReading]:
    page.goto(hedef.url, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(3000)
    cerez_kapat(page)
    if "rejected" in page.inner_text("body").casefold():
        return []
    opts = page.evaluate(
        """() => {
        const el = document.getElementById('edit-finansman-type');
        if (!el) return [];
        return [...el.options].map(o => ({v: o.value, t: o.textContent.trim()})).filter(o => o.t);
    }"""
    )
    sonuclar: list[ProbeReading] = []
    for opt in opts:
        etiket = opt["t"]
        if not _filtre(etiket, hedef.product_filter):
            continue
        _select2_sec(page, "edit-finansman-type", opt["v"])
        page.wait_for_timeout(2000)
        amount = Decimal("1000000")
        term = 120
        try:
            vade_vals = page.evaluate(
                """() => {
                const el = document.getElementById('edit-finansman-vade');
                if (!el) return [];
                return [...el.options].map(o => parseInt(o.value)).filter(n => n > 0);
            }"""
            )
            if vade_vals:
                term = max(vade_vals)
                _select2_sec(page, "edit-finansman-vade", str(term))
        except Exception:
            pass
        page.wait_for_timeout(1500)
        oran = None
        try:
            rv = page.locator("#edit-finansman-kendi-kar-oranim").input_value()
            if rv:
                oran = parse_decimal_tr(rv)
        except Exception:
            pass
        metin = page.inner_text("body")
        if oran is None:
            oran = metinden_oran(metin)
        taksit, toplam = metinden_taksit_toplam(metin)
        ipucu = urun_tipi_ipucu(etiket)
        if not oran_gecerli(oran):
            continue
        sonuclar.append(
            ProbeReading(
                bank_code=hedef.bank_code,
                source_url=hedef.url,
                variant_label=etiket,
                amount=amount,
                term_months=min(term, bddk_ornek_vade(ipucu, amount)),
                profit_rate_pct=oran,
                monthly_installment=taksit,
                total_repayment=toplam,
                product_type_hint=ipucu,
            )
        )
        bekle()
    return sonuclar


def _dunya_oran_oku(page: Any) -> Decimal | None:
    try:
        rv = page.locator("#checkProfitRateInput").input_value()
        if rv:
            o = parse_decimal_tr(rv)
            if o is not None and o > Decimal("0.05"):
                return o
    except Exception:
        pass
    metin = page.inner_text("body")
    m = re.search(r"Aylık Kâr Oranı\s*\n\s*%\s*([\d.,]+)", metin)
    if m:
        o = parse_decimal_tr(m.group(1))
        if o is not None and o > Decimal("0.05"):
            return o
    return metinden_oran(metin)


def probe_dunya_embedded(page: Any, hedef: ProbeTarget) -> list[ProbeReading]:
    """Dünya gömülü hesaplayıcı — LoanInstallmentValues + LoanCheckRate JSON.

    Tutar/vade ürün limitlerine (maxAmount/maxInstallment) göre sınırlandırılır.
    Oran DOM yerine API `rate` alanından okunur; sıfır veya hata durumunda atlanır.
    """
    page.goto(hedef.url, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(3000)
    cerez_kapat(page)
    opts = page.evaluate(
        """() => {
        const el = document.getElementById('loanSelect');
        if (!el) return [];
        return [...el.options].map(o => ({v: o.value, t: o.textContent.trim()}));
    }"""
    )
    sonuclar: list[ProbeReading] = []
    for opt in opts:
        etiket = (opt.get("t") or "").strip()
        kod = opt.get("v") or ""
        if not etiket or not kod or not _filtre(etiket, hedef.product_filter):
            continue
        api = page.evaluate(
            """(productCode) => {
            const $ = window.jQuery;
            if (!$ || !productCode) return null;
            $('#loanSelect').val(productCode);
            const form = $('#loanForm');
            const token = $('input[name="__RequestVerificationToken"]', form).val();
            const lang = document.documentElement.lang || 'tr';
            const valuesUrl = ($('#LoanInstallmentValues').val() || '/LoanInstallmentValues')
                + '?lang=' + lang;
            const rateUrl = ($('#LoanCheckRate').val() || '/LoanCheckRate') + '?lang=' + lang;
            let values = null;
            $.ajax({
                url: valuesUrl, type: 'POST', async: false,
                data: { productCode, __RequestVerificationToken: token },
                success: (d) => { values = d; }
            });
            if (!values || values.result !== 'SUCCESS') {
                return { values, rate: null };
            }
            const maxAmount = Number(values.maxAmount) || 0;
            const minAmount = Number(values.minAmount) || 0;
            let amountNum = Number(values.defaultAmount) || 0;
            if (maxAmount > 0 && (amountNum <= 0 || amountNum > maxAmount)) {
                amountNum = maxAmount;
            }
            const maxInst = Number(values.maxInstallment) || 12;
            let installment = Number(values.defaultInstallment) || 12;
            if (maxInst > 0 && installment > maxInst) {
                installment = maxInst;
            }
            const productName =
                ($('#loanSelect option[value=\"' + productCode + '\"]').text() || '').trim();
            const category = values.category || '';
            const amountStr = Math.round(amountNum).toLocaleString('tr-TR');
            let rateBody = null;
            $.ajax({
                url: rateUrl, type: 'POST', async: false,
                data: {
                    productName,
                    productCode,
                    productCategory: category,
                    amount: amountStr,
                    installmentCount: installment,
                    userRate: '0,00',
                    userSelected: false,
                    __RequestVerificationToken: token,
                },
                success: (d) => { rateBody = d; }
            });
            return { values, rate: rateBody, amount: amountNum, installment, productName };
        }""",
            kod,
        )
        if not isinstance(api, dict):
            continue
        rate_body = api.get("rate") or {}
        if rate_body.get("result") != "SUCCESS" or rate_body.get("rate") is None:
            continue
        try:
            oran = Decimal(str(rate_body["rate"]))
        except Exception:
            continue
        if not oran_gecerli(oran) or oran <= Decimal("0.05"):
            continue
        amount_raw = api.get("amount")
        try:
            # ⚠️ `amount_raw` None olabilir; `float(None)` TypeError verir ve
            # `except Exception` onu yutup sessizce 200.000'e düşerdi.
            if amount_raw is None:
                raise ValueError("amount yok")
            amount = Decimal(str(int(float(amount_raw))))
        except Exception:
            amount = Decimal("200000")
        try:
            term = int(api.get("installment") or 12)
        except Exception:
            term = 12
        ipucu = urun_tipi_ipucu(etiket)
        taksit = None
        toplam = None
        try:
            if rate_body.get("monthlyInterest") is not None:
                taksit = Decimal(str(rate_body["monthlyInterest"]))
            if rate_body.get("totalPayment") is not None:
                toplam = Decimal(str(rate_body["totalPayment"]))
        except Exception:
            pass
        sonuclar.append(
            ProbeReading(
                bank_code=hedef.bank_code,
                source_url=hedef.url,
                variant_label=etiket,
                amount=amount,
                term_months=term,
                profit_rate_pct=oran,
                monthly_installment=taksit,
                total_repayment=toplam,
                product_type_hint=ipucu,
                raw_meta={"product_code": kod, "api": api.get("values")},
            )
        )
        bekle()
    return sonuclar


def probe_emlak_listing(page: Any, hedef: ProbeTarget) -> list[ProbeReading]:
    """Liste sayfası — oran yok; tanıtım metni ürün eşlemesi için."""
    page.goto(hedef.url, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(2500)
    cerez_kapat(page)
    kartlar = page.locator("h3, .card-title, .product-title").all()
    sonuclar: list[ProbeReading] = []
    for kart in kartlar[:20]:
        try:
            baslik = kart.inner_text().strip()
        except Exception:
            continue
        if not baslik or len(baslik) < 5:
            continue
        if "finansman" not in baslik.casefold() and "toki" not in baslik.casefold():
            continue
        ipucu = urun_tipi_ipucu(baslik)
        sonuclar.append(
            ProbeReading(
                bank_code=hedef.bank_code,
                source_url=hedef.url,
                variant_label=baslik,
                amount=Decimal("1000000"),
                term_months=bddk_ornek_vade(ipucu, Decimal("1000000")),
                product_type_hint=ipucu,
                notice_text="Liste sayfası — hesaplayıcı oranı yok, tanıtım kartı.",
            )
        )
    return sonuclar


def _hayat_oran(metin: str) -> Decimal | None:
    m = re.search(r"Kâr Oranı \(Aylık\)\s*([\d.,]+)\s*%", metin)
    if m:
        return parse_decimal_tr(m.group(1))
    return metinden_oran(metin)


def probe_hayat_home(page: Any, hedef: ProbeTarget) -> list[ProbeReading]:
    page.goto(hedef.url, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(5000)
    cerez_kapat(page)
    try:
        page.locator('button:has-text("Kredi Hesapla")').first.click(timeout=5000)
        page.wait_for_timeout(1500)
    except Exception:
        pass
    amount = Decimal("500000")
    term = 18
    try:
        etiket = page.locator(".react-select__single-value").first.inner_text().strip()
    except Exception:
        etiket = "Bana Bunu Al"
    try:
        page.locator("#requiredAmount").fill(str(int(amount)))
        page.locator("#requiredAmount").dispatch_event("input")
    except Exception:
        pass
    try:
        page.locator("#maturity-period-input").fill(str(term))
        page.locator("#maturity-period-input").dispatch_event("input")
    except Exception:
        pass
    page.wait_for_timeout(2000)
    metin = page.inner_text("body")
    oran = _hayat_oran(metin)
    taksit, toplam = metinden_taksit_toplam(metin)
    m_taksit = re.search(r"Taksit Tutarı\s*([\d.\s]+,\d{2})\s*₺", metin)
    if m_taksit:
        taksit = parse_decimal_tr(m_taksit.group(1))
    m_toplam = re.search(r"Ödenecek Toplam\s*([\d.\s]+,\d{2})\s*₺", metin)
    if m_toplam:
        toplam = parse_decimal_tr(m_toplam.group(1))
    ipucu = urun_tipi_ipucu(etiket)
    if not oran_gecerli(oran):
        return []
    return [
        ProbeReading(
            bank_code=hedef.bank_code,
            source_url=hedef.url,
            variant_label=etiket,
            amount=amount,
            term_months=min(term, bddk_ornek_vade(ipucu, amount)),
            profit_rate_pct=oran,
            monthly_installment=taksit,
            total_repayment=toplam,
            product_type_hint=ipucu or "ihtiyac_finansmani",
        )
    ]


_STRATEGIES = {
    "albaraka_json": probe_albaraka_json,
    "kuveyt_product_dropdown": probe_kuveyt_product_dropdown,
    "vakif_loan_type": probe_vakif_loan_type,
    "turkiye_finans_type": probe_turkiye_finans_type,
    "ziraat_product_dropdown": probe_ziraat_product_dropdown,
    "dunya_embedded": probe_dunya_embedded,
    "emlak_listing": probe_emlak_listing,
    "hayat_home": probe_hayat_home,
}


def probe_target(page: Any, hedef: ProbeTarget) -> list[ProbeReading]:
    fn = _STRATEGIES.get(hedef.strategy)
    if fn is None:
        raise ValueError(f"Bilinmeyen strateji: {hedef.strategy}")
    return fn(page, hedef)
