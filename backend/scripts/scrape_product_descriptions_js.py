"""Playwright ile ürün detayında \"Nedir?\" / tanıtım bloğu çıkarımı.

Banka scraper'larına gömülmez. `product_description` süzgeçleri korunur.

    python -m scripts.scrape_product_descriptions_js
    python -m scripts.scrape_product_descriptions_js --zorla --banka kuveyt_turk
"""

from __future__ import annotations

import argparse
import json
import sys

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.vocab import FINANSMAN_TIPLERI
from app.db.models.bank import Bank
from app.db.models.product import Product
from app.db.session import SessionLocal
from app.logging_config import configure_logging, get_logger
from app.processing.product_description import extract_product_description
from app.scrapers.browser import (
    NETWORK_IDLE_MS,
    browser_page,
    is_playwright_available,
    playwright_kurulum_mesaji,
)

logger = get_logger(__name__)


def _sayfa_metni(url: str) -> str | None:
    if not is_playwright_available():
        logger.warning("playwright_yok", mesaj=playwright_kurulum_mesaji())
        return None
    try:
        with browser_page() as page:
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(NETWORK_IDLE_MS)
            # "Nedir?" sekmesi / düğmesi varsa tıkla.
            for el in page.query_selector_all("button, a, [role='tab']"):
                try:
                    metin = (el.inner_text() or "").strip().lower()
                except Exception:
                    continue
                if "nedir" in metin or "tanitim" in metin or "tanıtım" in metin:
                    try:
                        if el.is_visible():
                            el.click(timeout=3_000)
                            page.wait_for_timeout(800)
                            break
                    except Exception:
                        continue
            return page.inner_text("body") or None
    except Exception as exc:
        logger.warning("urun_js_aciklama_hata", url=url, hata=str(exc))
        return None


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--banka", default=None)
    parser.add_argument("--kuru", action="store_true")
    parser.add_argument("--zorla", action="store_true")
    parser.add_argument("--limit", type=int, default=40)
    args = parser.parse_args(argv)

    if not is_playwright_available():
        print(json.dumps({"hata": playwright_kurulum_mesaji()}, ensure_ascii=False))
        return 1

    with SessionLocal() as session:
        stmt = (
            select(Product)
            .options(selectinload(Product.bank), selectinload(Product.source_document))
            .where(
                Product.product_type.in_(FINANSMAN_TIPLERI),
                Product.parent_product_id.is_(None),
                Product.is_active.is_(True),
            )
            .order_by(Product.id)
            .limit(args.limit)
        )
        if args.banka:
            bank = session.scalar(select(Bank).where(Bank.code == args.banka))
            if bank is None:
                print(json.dumps({"hata": f"banka yok: {args.banka}"}, ensure_ascii=False))
                return 2
            stmt = stmt.where(Product.bank_id == bank.id)

        doldurulan = basarisiz = atlanan = 0
        for urun in session.scalars(stmt):
            if urun.description and not args.zorla:
                atlanan += 1
                continue
            # Kaynak URL: source_document.url veya oran evidence yoksa atla.
            url = None
            if urun.source_document is not None:
                url = urun.source_document.url
            if not url:
                basarisiz += 1
                continue
            ham = _sayfa_metni(url)
            if not ham:
                basarisiz += 1
                continue
            aciklama = extract_product_description(ham, urun.name)
            if not aciklama:
                basarisiz += 1
                continue
            if not args.kuru:
                urun.description = aciklama
            doldurulan += 1
            logger.info("js_aciklama_dolduruldu", product_id=urun.id, url=url)

        if not args.kuru:
            session.commit()
        print(
            json.dumps(
                {
                    "doldurulan": doldurulan,
                    "atlanan": atlanan,
                    "basarisiz": basarisiz,
                    "kuru": args.kuru,
                },
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
