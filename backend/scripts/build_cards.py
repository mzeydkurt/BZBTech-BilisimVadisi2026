"""Varlık kartlarını üretir ve `entity_cards` tablosuna yazar (KAPI A9).

AĞA ÇIKMAZ.

⚠️ DEĞİŞMEYEN KART YENİDEN ÜRETİLMEZ. `card_hash` aynıysa satır olduğu gibi
bırakılır; SPRINT 5'te gömme (embedding) bu tablodan beslenecek ve
değişmeyen metni yeniden gömmek boşa maliyettir.

Çalıştırma:
    python dev.py kart-uret
    python dev.py kart-uret --kuru          # yazmaz, örnek basar
    python dev.py kart-uret --ornek 5       # üretilen karttan örnek göster
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.cards import (
    build_bank_card,
    build_campaign_card,
    build_glossary_card,
    build_product_card,
    build_product_rate_card,
    card_hash,
)
from app.db.base import utc_now
from app.db.models import (
    Bank,
    Campaign,
    EntityCard,
    GlossaryTerm,
    Product,
    ProductRate,
)
from app.db.session import SessionLocal
from app.logging_config import configure_logging

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _upsert(session: Session, entity_type: str, entity_id: int, metin: str) -> str:
    """Kartı yazar; değişmemişse dokunmaz.

    Returns:
        `yeni` | `guncellendi` | `degismedi`
    """
    ozet = card_hash(metin)
    kayit = session.scalar(
        select(EntityCard).where(
            EntityCard.entity_type == entity_type, EntityCard.entity_id == entity_id
        )
    )

    if kayit is None:
        session.add(
            EntityCard(
                entity_type=entity_type,
                entity_id=entity_id,
                card_text=metin,
                card_hash=ozet,
                generated_at=utc_now(),
            )
        )
        return "yeni"

    if kayit.card_hash == ozet:
        return "degismedi"

    kayit.card_text = metin
    kayit.card_hash = ozet
    kayit.generated_at = utc_now()
    return "guncellendi"


def main(argv: list[str] | None = None) -> int:
    """Betiğin giriş noktası."""
    ayristirici = argparse.ArgumentParser(description="Varlık kartlarını üretir")
    ayristirici.add_argument("--kuru", action="store_true", help="Veritabanına yazmaz")
    ayristirici.add_argument("--ornek", type=int, default=3, help="Gösterilecek örnek kart sayısı")
    argumanlar = ayristirici.parse_args(argv)

    configure_logging()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    sayac: Counter[str] = Counter()
    ornekler: list[tuple[str, str]] = []

    with SessionLocal() as session:
        for kampanya in session.scalars(select(Campaign).order_by(Campaign.id)):
            metin = build_campaign_card(session, kampanya)
            sayac[f"campaign:{_upsert(session, 'campaign', kampanya.id, metin)}"] += 1
            sayac["campaign"] += 1
            if len(ornekler) < argumanlar.ornek:
                ornekler.append(("campaign", metin))

        for banka in session.scalars(select(Bank).order_by(Bank.id)):
            metin = build_bank_card(session, banka)
            sayac[f"bank:{_upsert(session, 'bank', banka.id, metin)}"] += 1
            sayac["bank"] += 1

        for terim in session.scalars(select(GlossaryTerm).order_by(GlossaryTerm.id)):
            metin = build_glossary_card(terim)
            sayac[f"glossary:{_upsert(session, 'glossary', terim.id, metin)}"] += 1
            sayac["glossary"] += 1

        for urun in session.scalars(select(Product).order_by(Product.id)):
            metin = build_product_card(session, urun)
            sayac[f"product:{_upsert(session, 'product', urun.id, metin)}"] += 1
            sayac["product"] += 1

        for oran in session.scalars(select(ProductRate).order_by(ProductRate.id)):
            metin = build_product_rate_card(session, oran)
            sayac[f"product_rate:{_upsert(session, 'product_rate', oran.id, metin)}"] += 1
            sayac["product_rate"] += 1

        if argumanlar.kuru:
            session.rollback()
        else:
            session.commit()

    print("\nKART ÜRETİMİ")
    print("=" * 60)
    for tur in ("campaign", "bank", "glossary", "product", "product_rate"):
        toplam = sayac.get(tur, 0)
        detay = " · ".join(
            f"{durum}={sayac.get(f'{tur}:{durum}', 0)}"
            for durum in ("yeni", "guncellendi", "degismedi")
        )
        # ⚠️ Sıfır kayıt GİZLENMEZ: hangi varlık türünde veri olmadığı
        # bilgisi de bir bulgudur.
        print(f"  {tur:14} {toplam:5}  ({detay})")

    for tur, metin in ornekler:
        print(f"\n── örnek {tur} kartı " + "─" * 40)
        for satir in metin.split("\n"):
            print(f"   {satir}")

    if argumanlar.kuru:
        print("\n--kuru: veritabanına YAZILMADI.")
    else:
        print("\nYazıldı. SPRINT 5'te bu kartlar gömülecek (embeddings).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
