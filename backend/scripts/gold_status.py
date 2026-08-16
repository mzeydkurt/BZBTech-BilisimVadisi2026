"""Gold set etiketleme ilerlemesini raporlar.

AĞA ÇIKMAZ.

Çalıştırma:
    python dev.py gold-durum
"""

from __future__ import annotations

import sys
from pathlib import Path

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

    if ilerleme.blind_campaigns < BLIND_COUNT:
        kalan = BLIND_COUNT - ilerleme.blind_campaigns
        print(f"\n→ KAPI A5'ten önce {kalan} kör kayıt daha etiketlenmeli.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
