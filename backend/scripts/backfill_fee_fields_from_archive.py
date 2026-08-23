"""Arşivlenmiş ücret sayfalarından tahsis / YMO alanlarını mevcut oranlara doldurur.

Ağa çıkmaz. `ProductRate` satırları zaten varsa yalnızca boş ücret alanlarını
günceller (oran satırı çoğaltılmaz).

Çalıştırma:
    python -m scripts.backfill_fee_fields_from_archive
    python -m scripts.backfill_fee_fields_from_archive --banka ziraat_katilim
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models.bank import Bank
from app.db.models.product import Product, ProductRate
from app.db.models.source_document import SourceDocument
from app.db.session import SessionLocal
from app.logging_config import configure_logging
from app.processing.fee_page_parsers import (
    parse_albaraka_ucret_page,
    parse_hayat_ucret_page,
    parse_turkiye_finans_ucret_page,
)
from app.scrapers.banks.ziraat_katilim import FEE_RATE_URL, _parse_fee_rate_page


def _html_yolu(doc: SourceDocument) -> Path | None:
    if not doc.raw_html_path:
        return None
    adaylar = [
        Path(doc.raw_html_path),
        Path("data/raw_html") / doc.raw_html_path,
    ]
    for yol in adaylar:
        if yol.exists():
            return yol
    return None


def _son_belge(session, *, bank_id: int, url_parca: str) -> SourceDocument | None:
    return session.scalar(
        select(SourceDocument)
        .where(
            SourceDocument.bank_id == bank_id,
            SourceDocument.url.like(f"%{url_parca}%"),
        )
        .order_by(SourceDocument.id.desc())
        .limit(1)
    )


def _tip_bazli_tahsis_yay(session, *, bank_id: int, product_type: str, tahsis) -> int:
    """Aynı banka + ürün türündeki finansman oranlarına boş tahsis yaz."""
    n = 0
    stmt = (
        select(ProductRate)
        .join(Product)
        .where(
            Product.bank_id == bank_id,
            Product.product_type == product_type,
            ProductRate.rate_type == "financing_rate",
            ProductRate.allocation_fee_pct.is_(None),
        )
    )
    for oran in session.scalars(stmt):
        oran.allocation_fee_pct = tahsis
        n += 1
    return n


def _ziraat_doldur(session, bank: Bank) -> dict:
    doc = _son_belge(session, bank_id=bank.id, url_parca="bireysel-krediler")
    if doc is None:
        return {"hata": "ücret sayfası arşivi yok"}
    yol = _html_yolu(doc)
    if yol is None:
        return {"hata": f"html yok: {doc.raw_html_path}"}
    html = yol.read_text(encoding="utf-8", errors="replace")
    ham_urunler = _parse_fee_rate_page(html, FEE_RATE_URL)
    guncellenen = 0
    for ham in ham_urunler:
        urunler = list(
            session.scalars(
                select(Product)
                .options(selectinload(Product.rates))
                .where(Product.bank_id == bank.id, Product.name == ham.name)
            )
        )
        if not urunler:
            # İsim birebir değilse ürün türü + tutar bandıyla dene
            urunler = list(
                session.scalars(
                    select(Product)
                    .options(selectinload(Product.rates))
                    .where(
                        Product.bank_id == bank.id,
                        Product.product_type == ham.product_type,
                        Product.source_url.like("%bireysel-krediler%"),
                    )
                )
            )
        for ham_oran in ham.rates:
            for urun in urunler:
                for oran in urun.rates:
                    if oran.rate_type != "financing_rate":
                        continue
                    if ham_oran.term_months is not None and oran.term_months != ham_oran.term_months:
                        continue
                    if (
                        ham_oran.profit_rate_pct is not None
                        and oran.profit_rate_pct is not None
                        and oran.profit_rate_pct != ham_oran.profit_rate_pct
                    ):
                        continue
                    degisti = False
                    if ham_oran.allocation_fee_pct is not None and oran.allocation_fee_pct is None:
                        oran.allocation_fee_pct = ham_oran.allocation_fee_pct
                        degisti = True
                    if ham_oran.annual_cost_pct is not None and oran.annual_cost_pct is None:
                        oran.annual_cost_pct = ham_oran.annual_cost_pct
                        degisti = True
                    if degisti:
                        guncellenen += 1
    return {"urun": len(ham_urunler), "guncellenen": guncellenen}


def _albaraka_doldur(session, bank: Bank) -> dict:
    doc = _son_belge(session, bank_id=bank.id, url_parca="/tr/urun-ve-hizmet-ucretleri")
    if doc is None:
        return {"hata": "ücret sayfası arşivi yok"}
    yol = _html_yolu(doc)
    if yol is None:
        return {"hata": f"html yok: {doc.raw_html_path}"}
    html = yol.read_text(encoding="utf-8", errors="replace")
    ham_urunler = parse_albaraka_ucret_page(html, doc.url)
    guncellenen = 0
    for ham in ham_urunler:
        tahsis = ham.rates[0].allocation_fee_pct if ham.rates else None
        if tahsis is None or not ham.product_type:
            continue
        guncellenen += _tip_bazli_tahsis_yay(
            session, bank_id=bank.id, product_type=ham.product_type, tahsis=tahsis
        )
    return {"urun": len(ham_urunler), "guncellenen": guncellenen}


def _hayat_doldur(session, bank: Bank) -> dict:
    doc = _son_belge(session, bank_id=bank.id, url_parca="/urun-ve-hizmet-ucretleri")
    if doc is None:
        # Hayat kazıması yeni URL'yi henüz arşivlememiş olabilir
        return {"hata": "ücret sayfası arşivi yok — urun-kazi çalıştırın"}
    yol = _html_yolu(doc)
    if yol is None:
        return {"hata": f"html yok: {doc.raw_html_path}"}
    html = yol.read_text(encoding="utf-8", errors="replace")
    ham_urunler = parse_hayat_ucret_page(html, doc.url)
    guncellenen = 0
    for ham in ham_urunler:
        tahsis = ham.rates[0].allocation_fee_pct if ham.rates else None
        if tahsis is None:
            continue
        for tip in ("ihtiyac_finansmani", "egitim_finansmani", "alisveris_finansmani"):
            guncellenen += _tip_bazli_tahsis_yay(
                session, bank_id=bank.id, product_type=tip, tahsis=tahsis
            )
    return {"urun": len(ham_urunler), "guncellenen": guncellenen}


def _tf_doldur(session, bank: Bank) -> dict:
    doc = _son_belge(session, bank_id=bank.id, url_parca="urun-hizmet-ucretleri.aspx")
    if doc is None:
        return {"hata": "ücret sayfası arşivi yok"}
    yol = _html_yolu(doc)
    if yol is None:
        return {"hata": f"html yok: {doc.raw_html_path}"}
    html = yol.read_text(encoding="utf-8", errors="replace")
    ham_urunler = parse_turkiye_finans_ucret_page(html, doc.url)
    guncellenen = 0
    for ham in ham_urunler:
        tahsis = ham.rates[0].allocation_fee_pct if ham.rates else None
        if tahsis is None or not ham.product_type:
            continue
        guncellenen += _tip_bazli_tahsis_yay(
            session, bank_id=bank.id, product_type=ham.product_type, tahsis=tahsis
        )
    return {"urun": len(ham_urunler), "guncellenen": guncellenen}


_HANDLERS = {
    "ziraat_katilim": _ziraat_doldur,
    "albaraka": _albaraka_doldur,
    "hayat_finans": _hayat_doldur,
    "turkiye_finans": _tf_doldur,
}


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--banka", default=None)
    parser.add_argument("--kuru", action="store_true")
    args = parser.parse_args(argv)

    session = SessionLocal()
    ozet: dict = {}
    try:
        kodlar = [args.banka] if args.banka else list(_HANDLERS)
        for kod in kodlar:
            fn = _HANDLERS.get(kod)
            if fn is None:
                ozet[kod] = {"hata": "desteklenmiyor"}
                continue
            bank = session.scalar(select(Bank).where(Bank.code == kod))
            if bank is None:
                ozet[kod] = {"hata": "banka yok"}
                continue
            ozet[kod] = fn(session, bank)
        if not args.kuru:
            session.commit()
        else:
            session.rollback()
            ozet["kuru"] = True
    finally:
        session.close()

    print(json.dumps(ozet, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
