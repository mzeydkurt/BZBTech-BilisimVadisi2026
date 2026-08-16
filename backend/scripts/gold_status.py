"""Gold set etiketleme ilerlemesini raporlar.

AĞA ÇIKMAZ.

Çalıştırma:
    python dev.py gold-durum
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Campaign, GoldAnnotation, SourceDocument
from app.db.session import SessionLocal
from app.logging_config import configure_logging
from app.services.gold_service import (
    BLIND_COUNT,
    MIN_DIFFICULT,
    TARGET_SIZE,
    gold_progress,
    load_sample,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ORNEK_YOLU = REPO_ROOT / "data" / "gold" / "gold_sample.jsonl"

# Kanıt olarak kabul edilen en uzun metin. Arayüzdeki sınırla aynı tutulur
# (`app/static/annotate.html::KANIT_MAX`).
KANIT_MAX = 220


def _kanit_denetimi(session: Session) -> None:
    """Kanıt (evidence) kalitesini denetler ve sorunlu kampanyaları listeler.

    ⚠️ Kılavuz (§4.5 kural 2) her etiket için kaynaktan BİREBİR kopyalanmış
    bir kanıt ister. Arayüzdeki iki hata bunu bozuyordu:

      1. Metinden yapılan seçim tüketilmiyordu; aynı seçim sonradan
         tıklanan HER alana kopyalanıyordu. Bir kampanyanın bütün
         alanlarının kanıtı birebir aynı metin oluyordu.
      2. Seçim uzunluğuna sınır yoktu; tüm sayfayı seçmek mümkündü.

    İkisi de düzeltildi ama ÖNCEDEN kaydedilmiş etiketler düzelmez —
    kanıt insan girdisidir, otomatik yeniden üretilmesi onu kanıt
    olmaktan çıkarır. Bu denetim, elden geçirilmesi gereken kampanyaları
    görünür kılar.

    Args:
        session: Veritabanı oturumu.
    """
    kayitlar = list(
        session.execute(
            select(GoldAnnotation, SourceDocument.clean_text)
            .join(Campaign, Campaign.id == GoldAnnotation.campaign_id)
            .join(SourceDocument, Campaign.source_document_id == SourceDocument.id)
            .where(GoldAnnotation.gold_value.isnot(None))
        )
    )
    if not kayitlar:
        return

    uzun: set[int] = set()
    tekrarlayan: set[int] = set()
    bulunamayan: set[int] = set()
    kanitsiz = 0
    kampanya_kanitlari: dict[int, list[str]] = defaultdict(list)

    for etiket, clean_text in kayitlar:
        kanit = " ".join((etiket.evidence_text or "").split())
        if not kanit:
            kanitsiz += 1
            continue
        kampanya_kanitlari[etiket.campaign_id].append(kanit)
        if len(kanit) > KANIT_MAX:
            uzun.add(etiket.campaign_id)
        if kanit not in " ".join((clean_text or "").split()):
            bulunamayan.add(etiket.campaign_id)

    for kampanya_id, kanitlar in kampanya_kanitlari.items():
        if len(kanitlar) >= 3 and len(set(kanitlar)) == 1:
            tekrarlayan.add(kampanya_id)

    sorunlu = uzun | tekrarlayan | bulunamayan
    print("\nKanıt denetimi (§4.5 kural 2)")
    print(f"  kanıtı boş etiket        : {kanitsiz}")
    print(f"  kanıt > {KANIT_MAX} karakter    : {len(uzun)} kampanya")
    print(f"  tüm alanlarda aynı kanıt : {len(tekrarlayan)} kampanya")
    print(f"  kanıt metinde bulunamadı : {len(bulunamayan)} kampanya")

    if sorunlu:
        print(f"\n  ⚠️  {len(sorunlu)} kampanyanın kanıtı elden geçirilmeli:")
        print(f"      {sorted(sorunlu)}")
        print("      Arayüzdeki hata düzeltildi; bu kayıtlar önceki sürümden kalma.")


def main(argv: list[str] | None = None) -> int:
    """Betiğin giriş noktası."""
    del argv

    configure_logging()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    ornek = load_sample(ORNEK_YOLU)
    if not ornek:
        print("Örneklem bulunamadı. Önce: python dev.py gold-ornek")
        return 1

    with SessionLocal() as session:
        ilerleme = gold_progress(session)

    print(f"Örneklem            : {len(ornek)} kampanya (hedef {TARGET_SIZE})")
    print(f"Etiketlenen         : {ilerleme.annotated_campaigns} kampanya")
    print(f"Toplam alan etiketi : {ilerleme.total_annotations}")
    print(f"Kör (blind)         : {ilerleme.blind_campaigns} / {BLIND_COUNT}")
    print(f"Ön-doldurmalı       : {ilerleme.assisted_campaigns}")
    print(f"Zor vaka            : {ilerleme.difficult_campaigns} (hedef ≥{MIN_DIFFICULT})")
    print(f"'Metinde yok' (∅)   : {ilerleme.explicit_null_fields} alan")

    if ilerleme.annotated_campaigns and not ilerleme.explicit_null_fields:
        # ⚠️ Hiç ∅ işaretlenmemişse etiketleme eksik yapılmış demektir:
        # halüsinasyon ölçümünün paydası boş kalır.
        print(
            "\n⚠️  Hiçbir alan ∅ ('metinde yok') işaretlenmemiş.\n"
            "   Bu, sistemin uydurup uydurmadığının ölçülemeyeceği anlamına gelir.\n"
            "   Kaynakta bulunmayan alanlar ∅ ile işaretlenmeli."
        )
        return 1

    with SessionLocal() as session:
        _kanit_denetimi(session)

    if ilerleme.blind_campaigns < BLIND_COUNT:
        kalan = BLIND_COUNT - ilerleme.blind_campaigns
        print(f"\n→ KAPI A5'ten önce {kalan} kör kayıt daha etiketlenmeli.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
