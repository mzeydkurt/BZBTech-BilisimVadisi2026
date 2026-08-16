"""Gold set örneklemi seçer.

AĞA ÇIKMAZ. Kayıtlı kampanyalardan dengeli ve zor vaka ağırlıklı bir örneklem
seçip `data/gold/gold_sample.jsonl` dosyasına yazar.

⚠️ TEKRAR ÇALIŞTIRILABİLİR ama ÖRNEKLEM DEĞİŞİR: yeni kampanya eklendiyse
seçim farklılaşır. Etiketlemeye başladıktan sonra yeniden çalıştırma —
etiketlediğin kayıtlar örneklemden düşebilir.

Çalıştırma:
    python dev.py gold-ornek
    python dev.py gold-ornek --adet 50
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.db.session import SessionLocal
from app.logging_config import configure_logging
from app.services.gold_service import (
    BLIND_COUNT,
    MIN_DIFFICULT,
    TARGET_SIZE,
    annotation_method,
    sample_gold_set,
)

# backend/scripts/ -> backend/ -> depo kökü
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CIKTI_YOLU = REPO_ROOT / "data" / "gold" / "gold_sample.jsonl"


def main(argv: list[str] | None = None) -> int:
    """Betiğin giriş noktası."""
    ayristirici = argparse.ArgumentParser(description="Gold set örneklemi")
    ayristirici.add_argument("--adet", type=int, default=TARGET_SIZE, help="Hedef kayıt sayısı")
    argumanlar = ayristirici.parse_args(argv)

    configure_logging()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if CIKTI_YOLU.exists():
        print(f"⚠️  {CIKTI_YOLU.name} zaten var. Üzerine yazılacak.")
        print("   Etiketlemeye başladıysan bu örneklemi DEĞİŞTİRME.\n")

    with SessionLocal() as session:
        sonuc = sample_gold_set(session, size=argumanlar.adet)

    if not sonuc.candidates:
        print("Etiketlenebilir kampanya bulunamadı. Önce 'python dev.py scrape' çalıştırın.")
        return 1

    CIKTI_YOLU.parent.mkdir(parents=True, exist_ok=True)
    with CIKTI_YOLU.open("w", encoding="utf-8") as dosya:
        for sira, aday in enumerate(sonuc.candidates):
            dosya.write(
                json.dumps(
                    {
                        "order": sira,
                        "campaign_id": aday.campaign_id,
                        "bank_code": aday.bank_code,
                        "title": aday.title,
                        "source_url": aday.source_url,
                        "method": annotation_method(sira),
                        "is_difficult": aday.is_difficult,
                        "difficulty_reasons": list(aday.difficulty_reasons),
                        "product_types": list(aday.product_types),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    zor = sonuc.difficult_count
    print(f"Seçilen kampanya  : {len(sonuc.candidates)} / {sonuc.total_available} uygun aday")
    print(f"Zor vaka          : {zor} (hedef ≥{MIN_DIFFICULT})")
    print(f"Kör / ön-doldurma : {min(BLIND_COUNT, len(sonuc.candidates))} / "
          f"{max(0, len(sonuc.candidates) - BLIND_COUNT)}")
    print(f"Few-shot elenen   : {sonuc.excluded_few_shot}  ·  metni boş: {sonuc.excluded_empty_text}")

    print("\nBanka dağılımı:")
    for kod, sayi in sorted(sonuc.by_bank.items(), key=lambda p: -p[1]):
        print(f"  {kod:18} {sayi}")

    print("\nÜrün türü dağılımı:")
    for tur, sayi in sorted(sonuc.by_product_type.items(), key=lambda p: -p[1]):
        print(f"  {tur:22} {sayi}")

    print(f"\nÖrneklem: {CIKTI_YOLU}")
    print("Etiketlemeye başlamak için: python dev.py etiketle")

    if zor < MIN_DIFFICULT:
        print(f"\n⚠️  Zor vaka sayısı {MIN_DIFFICULT} hedefinin altında ({zor}).")
        print("   Veri setinde yeterli zor vaka yoksa bu normaldir; raporda belirtilmeli.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
