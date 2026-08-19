"""Kampanyaları ürünlerle eşleştirir ve `campaign_products`'a yazar.

AĞA ÇIKMAZ.

Çalıştırma:
    python dev.py urun-esle
    python dev.py urun-esle --kuru      # yazmadan raporla
    python dev.py urun-esle --banka albaraka
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import Bank, Campaign, CampaignProduct, Product, SourceDocument
from app.db.session import SessionLocal
from app.logging_config import configure_logging, get_logger
from app.processing.campaign_product_matcher import UrunAdayi, esles

logger = get_logger(__name__)


def _banka_urunleri(session: Session) -> dict[int, list[UrunAdayi]]:
    """Banka kimliği → o bankanın ürün adayları."""
    havuz: dict[int, list[UrunAdayi]] = {}
    for pid, bid, ad, anahtar in session.execute(
        # ⚠️ VARYANTLAR ADAY DEĞİLDİR. Varyant adı ana ürün adını İÇERİR
        # ("Sigortalı İhtiyaç Finansmanı"), bu yüzden metinde "İhtiyaç
        # Finansmanı" geçtiğinde ana ürün ve her varyantı ayrı ayrı eşleşir;
        # tek bir anıştan üç bağ çıkar. Kampanya metni zaten sigortalı mı
        # sigortasız mı demiyor — o ayrımı iddia etmek uydurma olur.
        # Varyantlara `parent_product_id` üzerinden ulaşılır.
        select(Product.id, Product.bank_id, Product.name, Product.external_key).where(
            Product.parent_product_id.is_(None)
        )
    ).all():
        havuz.setdefault(bid, []).append(
            UrunAdayi(product_id=pid, name=ad, url_slug=str(anahtar).split("#", 1)[0])
        )
    return havuz


def calistir(session: Session, *, kuru: bool, banka: str | None) -> Counter[str]:
    """Eşleştirmeyi yürütür ve sayaçları döndürür."""
    havuz = _banka_urunleri(session)

    sorgu = (
        select(
            Campaign.id,
            Campaign.bank_id,
            Campaign.title,
            Campaign.external_slug,
            Campaign.source_url,
            SourceDocument.clean_text,
        )
        .outerjoin(SourceDocument, Campaign.source_document_id == SourceDocument.id)
        .where(Campaign.parent_campaign_id.is_(None))
    )
    if banka:
        sorgu = sorgu.join(Bank, Bank.id == Campaign.bank_id).where(Bank.code == banka)

    kampanyalar = session.execute(sorgu).all()
    sayac: Counter[str] = Counter()

    if not kuru:
        # ⚠️ Bağlar HESAPLANMIŞ veridir, elle girilmiş değil: her çalıştırmada
        # sıfırdan üretilir. Aksi hâlde ürün adı değiştiğinde eski bağ kalır
        # ve hangi kampanyanın hangi sürümle eşleştiği izlenemez olur.
        kimlikler = [k[0] for k in kampanyalar]
        if kimlikler:
            session.execute(
                delete(CampaignProduct).where(CampaignProduct.campaign_id.in_(kimlikler))
            )

    for cid, bid, baslik, slug, url, metin in kampanyalar:
        eslesmeler = esles(
            title=baslik or "",
            campaign_slug=slug or "",
            source_url=url or "",
            clean_text=metin,
            adaylar=havuz.get(bid, []),
        )
        if not eslesmeler:
            sayac["eşleşmedi"] += 1
            continue

        sayac["eşleşen kampanya"] += 1
        for e in eslesmeler:
            sayac[f"bağ: {e.match_method}"] += 1
            if not kuru:
                session.add(
                    CampaignProduct(
                        campaign_id=cid,
                        product_id=e.product_id,
                        match_method=e.match_method,
                        confidence=e.confidence,
                        evidence=e.evidence,
                    )
                )

    if not kuru:
        session.commit()
    return sayac


def main(argv: list[str] | None = None) -> int:
    """Komut satırı girişi."""
    ayristirici = argparse.ArgumentParser(
        prog="match_campaign_products",
        description="Kampanyaları ürünlerle eşleştirir (ağa çıkmaz).",
    )
    ayristirici.add_argument("--kuru", action="store_true", help="Yazma, yalnızca raporla")
    ayristirici.add_argument("--banka", help="Tek banka kodu")
    secenekler = ayristirici.parse_args(argv)

    configure_logging()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    with SessionLocal() as session:
        sayac = calistir(session, kuru=secenekler.kuru, banka=secenekler.banka)

    print("\nKampanya ↔ ürün eşleştirmesi" + (" (KURU)" if secenekler.kuru else ""))
    for ad, adet in sorted(sayac.items()):
        print(f"  {ad:24} {adet}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
