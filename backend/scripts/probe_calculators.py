"""Hesaplayıcı örnek tutar sorgusu (oran boş ürünler için).

Statik HTML tablosunda kâr payı oranı olmayan finansman ürünlerinde,
envanterlenmiş hesaplayıcıya BDDK bandına uygun örnek tutarlar girilir.

⚠️ Çıktılar bağlayıcı DEĞİLDİR (`is_binding=False`).
⚠️ Banka başına sınırlı sorgu; tam kombinasyon taraması YOK.
⚠️ robots / nezaket: istekler arası ≥2 sn.

Çalıştırma:
    python dev.py hesaplayici-sorgula
    python dev.py hesaplayici-sorgula --banka ziraat_katilim
    python dev.py hesaplayici-sorgula --kuru
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.normalization.money import parse_decimal_tr
from app.core.normalization.rate import parse_rate
from app.db.models import Bank, CalculatorInventory, Product
from app.db.session import SessionLocal
from app.logging_config import configure_logging, get_logger
from app.scrapers.browser import (
    NETWORK_IDLE_MS,
    browser_page,
    is_playwright_available,
    playwright_kurulum_mesaji,
)
from app.services.calculator_probe_service import (
    is_zero_rate_promotional,
    probe_samples_for_product,
    products_needing_probe,
    upsert_probe_and_rate,
)

logger = get_logger(__name__)

BEKLEME = 2.0
# Banka başına azami Playwright sayfa açılışı (nezaket).
MAX_SAYFA_BANKA = 3
# Sayfa başına azami örnek tutar sorgusu.
MAX_ORNEK_SAYFA = 3


def _metinden_oran_ve_taksit(metin: str) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    """Sayfa metninden kâr payı / taksit / toplam çıkarmaya çalışır."""
    oran: Decimal | None = None
    taksit: Decimal | None = None
    toplam: Decimal | None = None

    for kalip in (
        r"(?:ayl[ıi]k\s*)?(?:k[aâ]r\s*pay[ıi]|kar\s*oran[ıi]|finansman\s*oran[ıi])\s*[:%]?\s*%?\s*(\d+[.,]\d+)",
        r"%\s*(\d+[.,]\d+)\s*(?:ayl[ıi]k)?",
    ):
        m = re.search(kalip, metin, re.IGNORECASE)
        if m:
            oran = parse_rate(m.group(0)) or parse_decimal_tr(m.group(1))
            if oran is not None:
                break

    for kalip in (
        r"(?:ayl[ıi]k\s*)?taksit\s*(?:tutarı)?\s*[:\-]?\s*([\d.\s]+,\d{2})\s*TL",
        r"taksit\s*[:\-]?\s*([\d.\s]+,\d{2})",
    ):
        m = re.search(kalip, metin, re.IGNORECASE)
        if m:
            taksit = parse_decimal_tr(m.group(1))
            break

    for kalip in (
        r"(?:ödenecek\s*)?toplam\s*(?:tutar)?\s*[:\-]?\s*([\d.\s]+,\d{2})\s*TL",
        r"toplam\s*geri\s*ödeme\s*[:\-]?\s*([\d.\s]+,\d{2})",
    ):
        m = re.search(kalip, metin, re.IGNORECASE)
        if m:
            toplam = parse_decimal_tr(m.group(1))
            break

    return oran, taksit, toplam


def _formu_doldur(page: Any, amount: Decimal, term_months: int) -> bool:
    """Tutar ve vade alanlarını doldurup hesapla düğmesine basmayı dener."""
    dolduruldu = False
    for secici in (
        'input[name*="tutar" i]',
        'input[id*="tutar" i]',
        'input[placeholder*="Tutar" i]',
        'input[type="number"]',
        'input[type="range"]',
        'input[name*="amount" i]',
    ):
        try:
            loc = page.locator(secici).first
            if loc.count() == 0:
                continue
            loc.fill(str(int(amount)), timeout=2000)
            dolduruldu = True
            break
        except Exception:
            continue

    for secici in (
        'select[name*="vade" i]',
        'select[id*="vade" i]',
        'input[name*="vade" i]',
    ):
        try:
            loc = page.locator(secici).first
            if loc.count() == 0:
                continue
            tag = loc.evaluate("el => el.tagName").lower()
            if tag == "select":
                loc.select_option(label=re.compile(str(term_months)), timeout=2000)
            else:
                loc.fill(str(term_months), timeout=2000)
            break
        except Exception:
            continue

    for secici in (
        'button:has-text("Hesapla")',
        'button:has-text("Hesaplama")',
        'input[type="submit"]',
        'button[type="submit"]',
    ):
        try:
            loc = page.locator(secici).first
            if loc.count() == 0:
                continue
            loc.click(timeout=2000)
            page.wait_for_timeout(1500)
            break
        except Exception:
            continue

    return dolduruldu


def _urun_icin_envanter(
    session: Any, product: Product
) -> CalculatorInventory | None:
    """Ürünün calculator_url veya banka envanterinden eşleşen kaydı bulur."""
    if product.calculator_url:
        kayit = session.scalar(
            select(CalculatorInventory).where(
                CalculatorInventory.bank_id == product.bank_id,
                CalculatorInventory.page_url == product.calculator_url,
            )
        )
        if kayit:
            return kayit
    return session.scalar(
        select(CalculatorInventory)
        .where(CalculatorInventory.bank_id == product.bank_id)
        .order_by(CalculatorInventory.id)
        .limit(1)
    )


def _sayfayi_sorgula(
    session: Any,
    product: Product,
    inventory: CalculatorInventory | None,
    *,
    dry_run: bool,
) -> int:
    """Tek ürün sayfasında örnek tutarlarla Playwright sorgusu yapar."""
    url = product.calculator_url or (
        inventory.page_url if inventory else None
    )
    if not url:
        logger.info("probe_url_yok", product_id=product.id, name=product.name)
        return 0

    ornekler = probe_samples_for_product(product.product_type)[:MAX_ORNEK_SAYFA]
    yazilan = 0
    denenen_kombinasyonlar: set[tuple[Decimal, int]] = set()

    with browser_page() as page:
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(NETWORK_IDLE_MS)

        for ornek in ornekler:
            tutar = ornek.amount
            if product.amount_max is not None and product.amount_max > 0 and tutar > product.amount_max:
                tutar = product.amount_max
            vade = ornek.term_months
            if product.term_months_max is not None and product.term_months_max > 0 and vade > product.term_months_max:
                vade = product.term_months_max

            cift = (tutar, vade)
            if cift in denenen_kombinasyonlar:
                continue
            denenen_kombinasyonlar.add(cift)

            time.sleep(BEKLEME)
            doldu = _formu_doldur(page, tutar, vade)
            metin = page.inner_text("body")
            oran, taksit, toplam = _metinden_oran_ve_taksit(metin)

            # Sıfır veya negatif oran kontrolü
            if oran is not None and oran <= Decimal("0.05"):
                if not is_zero_rate_promotional(
                    product_name=product.name,
                    description=product.description,
                    product_type=product.product_type,
                ):
                    oran = None

            if oran is None and taksit is None and not doldu:
                logger.info(
                    "probe_sonuc_yok",
                    product_id=product.id,
                    amount=str(tutar),
                )
                continue

            logger.info(
                "probe_ok",
                product_id=product.id,
                amount=str(tutar),
                term=vade,
                oran=str(oran),
                taksit=str(taksit),
            )
            if dry_run:
                yazilan += 1
                continue

            upsert_probe_and_rate(
                session,
                product=product,
                inventory=inventory,
                amount=tutar,
                term_months=vade,
                method="playwright",
                profit_rate_pct=oran,
                monthly_installment=taksit,
                total_repayment=toplam,
                response_raw=metin[:8000],
                request_payload={
                    "amount": str(tutar),
                    "term_months": vade,
                    "url": url,
                },
            )
            yazilan += 1

    return yazilan


def main(argv: list[str] | None = None) -> int:
    """CLI giriş noktası."""
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--banka", default=None, help="Yalnızca bu banka kodu")
    parser.add_argument("--kuru", action="store_true", help="DB'ye yazma")
    args = parser.parse_args(argv)

    if not is_playwright_available():
        print(playwright_kurulum_mesaji())
        return 2

    session = SessionLocal()
    try:
        urunler = products_needing_probe(session, bank_code=args.banka)
        # İlişkileri yükle
        urunler = list(
            session.scalars(
                select(Product)
                .options(selectinload(Product.rates), selectinload(Product.bank))
                .where(Product.id.in_([u.id for u in urunler] or [-1]))
            )
        )
        logger.info("probe_aday", adet=len(urunler), banka=args.banka)

        banka_sayfa: dict[int, int] = {}
        toplam_yazilan = 0

        for urun in urunler:
            sayac = banka_sayfa.get(urun.bank_id, 0)
            if sayac >= MAX_SAYFA_BANKA:
                continue
            envanter = _urun_icin_envanter(session, urun)
            try:
                n = _sayfayi_sorgula(session, urun, envanter, dry_run=args.kuru)
            except Exception as exc:
                logger.warning(
                    "probe_hata",
                    product_id=urun.id,
                    hata=str(exc),
                )
                continue
            if n > 0:
                banka_sayfa[urun.bank_id] = sayac + 1
                toplam_yazilan += n
                if not args.kuru:
                    session.commit()

        ozet = {"aday": len(urunler), "yazilan_probe": toplam_yazilan, "kuru": args.kuru}
        print(json.dumps(ozet, ensure_ascii=False))
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
