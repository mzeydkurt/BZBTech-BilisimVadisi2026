"""Ürün açıklamalarını arşivlenmiş clean_text'ten geri doldurur (ağa çıkmaz).

Kazıma sırasında description boş kalan finansman ürünleri için
`source_documents.clean_text` üzerinden `extract_product_description` çalışır.

Çalıştırma:
    python dev.py urun-aciklama-doldur
    python dev.py urun-aciklama-doldur --kuru
    python dev.py urun-aciklama-doldur --banka turkiye_finans
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

logger = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--banka", default=None, help="Yalnızca bu banka kodu")
    parser.add_argument("--kuru", action="store_true", help="DB'ye yazma")
    parser.add_argument(
        "--zorla",
        action="store_true",
        help="Mevcut açıklamayı da yeniden çıkar (varsayılan: yalnızca boş)",
    )
    args = parser.parse_args(argv)

    session = SessionLocal()
    try:
        stmt = (
            select(Product)
            .options(
                selectinload(Product.source_document),
                selectinload(Product.bank),
            )
            .where(
                Product.product_type.in_(FINANSMAN_TIPLERI),
                Product.parent_product_id.is_(None),
            )
            .order_by(Product.id)
        )
        if args.banka:
            banka = session.scalar(select(Bank).where(Bank.code == args.banka))
            if banka is None:
                print(json.dumps({"hata": f"banka yok: {args.banka}"}, ensure_ascii=False))
                return 2
            stmt = stmt.where(Product.bank_id == banka.id)

        urunler = list(session.scalars(stmt))
        doldurulan = 0
        atlanan = 0
        basarisiz = 0

        for urun in urunler:
            if urun.description and not args.zorla:
                atlanan += 1
                continue
            belge = urun.source_document
            if belge is None or not belge.clean_text:
                basarisiz += 1
                continue
            aciklama = extract_product_description(belge.clean_text, urun.name)
            if not aciklama:
                basarisiz += 1
                logger.info(
                    "aciklama_cikarilamadi",
                    product_id=urun.id,
                    name=urun.name,
                    bank=urun.bank.code if urun.bank else None,
                )
                continue
            logger.info(
                "aciklama_dolduruldu",
                product_id=urun.id,
                name=urun.name,
                uzunluk=len(aciklama),
            )
            if not args.kuru:
                urun.description = aciklama
            doldurulan += 1

        if not args.kuru:
            session.commit()

        ozet = {
            "toplam": len(urunler),
            "doldurulan": doldurulan,
            "atlanan_dolu": atlanan,
            "basarisiz": basarisiz,
            "kuru": args.kuru,
        }
        print(json.dumps(ozet, ensure_ascii=False))
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
