"""Aynı banka + normalize ad + product_type için ürünleri tekilleştirir.

    python -m scripts.dedupe_products
    python -m scripts.dedupe_products --kuru
    python -m scripts.dedupe_products --banka albaraka

Kanonik ürüne oran/limit taşınır; kopya `is_active=False` yapılır (silinmez).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.normalization.text import ascii_fold_tr, lower_tr, normalize_text
from app.db.models.bank import Bank
from app.db.models.product import Product
from app.db.session import SessionLocal
from app.logging_config import configure_logging, get_logger

logger = get_logger(__name__)


def _norm_ad(ad: str) -> str:
    return ascii_fold_tr(lower_tr(normalize_text(ad or "")))


def _kanonik_sec(grup: list[Product]) -> Product:
    """En çok oran/limit taşıyan, yoksa en düşük id."""
    return sorted(
        grup,
        key=lambda p: (
            -(len(p.rates) + len(p.limits)),
            0 if p.description else 1,
            p.id,
        ),
    )[0]


def _oran_tasi(session: Session, kaynak: Product, hedef: Product) -> int:
    tasinan = 0
    mevcut = {
        (o.rate_type, o.term_months, o.currency, o.customer_type, o.account_tier)
        for o in hedef.rates
    }
    for oran in list(kaynak.rates):
        anahtar = (
            oran.rate_type,
            oran.term_months,
            oran.currency,
            oran.customer_type,
            oran.account_tier,
        )
        if anahtar in mevcut:
            continue
        oran.product_id = hedef.id
        mevcut.add(anahtar)
        tasinan += 1
    session.flush()
    return tasinan


def _limit_tasi(session: Session, kaynak: Product, hedef: Product) -> int:
    if hedef.limits:
        return 0
    say = 0
    for limit in list(kaynak.limits):
        limit.product_id = hedef.id
        say += 1
    session.flush()
    return say


def dedupe(session: Session, *, bank_code: str | None, dry_run: bool) -> dict[str, int]:
    stmt = (
        select(Product)
        .options(
            selectinload(Product.rates),
            selectinload(Product.limits),
            selectinload(Product.bank),
        )
        .where(Product.is_active.is_(True), Product.parent_product_id.is_(None))
        .order_by(Product.id)
    )
    if bank_code:
        bank = session.scalar(select(Bank).where(Bank.code == bank_code))
        if bank is None:
            raise ValueError(f"banka yok: {bank_code}")
        stmt = stmt.where(Product.bank_id == bank.id)

    urunler = list(session.scalars(stmt))
    gruplar: dict[tuple[int, str, str], list[Product]] = defaultdict(list)
    for u in urunler:
        tip = u.product_type or ""
        gruplar[(u.bank_id, _norm_ad(u.name), tip)].append(u)

    birlesen = pasif = oran_t = limit_t = 0
    for anahtar, grup in gruplar.items():
        if len(grup) < 2:
            continue
        kanonik = _kanonik_sec(grup)
        for kopya in grup:
            if kopya.id == kanonik.id:
                continue
            oran_t += _oran_tasi(session, kopya, kanonik)
            limit_t += _limit_tasi(session, kopya, kanonik)
            if not kanonik.description and kopya.description:
                kanonik.description = kopya.description
            kopya.is_active = False
            pasif += 1
            logger.info(
                "urun_tekillestirildi",
                bank_id=anahtar[0],
                kanonik=kanonik.id,
                kopya=kopya.id,
                ad=kanonik.name,
            )
        birlesen += 1

    if not dry_run:
        session.commit()
    else:
        session.rollback()

    return {
        "grup": birlesen,
        "pasif": pasif,
        "oran_tasinan": oran_t,
        "limit_tasinan": limit_t,
        "kuru": int(dry_run),
    }


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--banka", default=None)
    parser.add_argument("--kuru", action="store_true")
    args = parser.parse_args(argv)
    with SessionLocal() as session:
        try:
            ozet = dedupe(session, bank_code=args.banka, dry_run=args.kuru)
        except ValueError as exc:
            print(json.dumps({"hata": str(exc)}, ensure_ascii=False))
            return 2
    print(json.dumps(ozet, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
