"""Gold set'e karşı çıkarım kalitesini ölçer.

AĞA ÇIKMAZ.

Çalıştırma:
    python dev.py degerlendir --mod rule_only
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from app.ai.evaluation import MIN_SUPPORT, build_report, evaluate
from app.db.session import SessionLocal
from app.logging_config import configure_logging

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RAPOR_YOLU = REPO_ROOT / "docs" / "evaluation.md"
JSON_DIZINI = REPO_ROOT / "data" / "eval"


def main(argv: list[str] | None = None) -> int:
    """Betiğin giriş noktası."""
    ayristirici = argparse.ArgumentParser(description="Çıkarım değerlendirmesi")
    ayristirici.add_argument("--mod", default="rule_only", help="Rapora yazılacak kip etiketi")
    argumanlar = ayristirici.parse_args(argv)

    configure_logging()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    with SessionLocal() as session:
        sonuc = evaluate(session, mode=argumanlar.mod)

    if sonuc.gold_annotations == 0:
        print("Gold set boş. Önce: python dev.py etiketle")
        return 1

    o = sonuc.overall
    print(f"\nKip                : {sonuc.mod if hasattr(sonuc, 'mod') else sonuc.mode}")
    print(f"Gold set           : {sonuc.gold_campaigns} kampanya · {sonuc.gold_annotations} etiket")
    print(f"Mikro F1           : {o.f1:.3f}")
    print(f"Makro F1 (≥{MIN_SUPPORT})      : {sonuc.macro_f1:.3f}")
    print(f"Precision / Recall : {o.precision:.3f} / {o.recall:.3f}")
    print(f"Halüsinasyon oranı : {o.hallucination_rate:.3f}")
    print(f"Doğru susma oranı  : {o.correct_silence_rate:.3f}")
    print(f"TP/FP/FN/TN        : {o.tp}/{o.fp}/{o.fn}/{o.tn}")

    print("\nAlan bazında (destek ≥%d):" % MIN_SUPPORT)
    for alan, s in sorted(sonuc.by_field.items(), key=lambda p: -p[1].support):
        if s.support >= MIN_SUPPORT:
            print(f"  {alan:24} F1={s.f1:.2f}  destek={s.support}")

    fark = sonuc.bias_gap
    if fark is not None:
        isaret = "ihmal edilebilir" if fark <= 0.05 else "⚠️ ANA METRİK KÖR ALT KÜME OLMALI"
        print(f"\nYanlılık farkı     : {fark:.3f}  ({isaret})")

    RAPOR_YOLU.parent.mkdir(parents=True, exist_ok=True)
    RAPOR_YOLU.write_text(build_report(sonuc), encoding="utf-8")

    JSON_DIZINI.mkdir(parents=True, exist_ok=True)
    json_yolu = JSON_DIZINI / f"results_{sonuc.mode}.json"
    json_yolu.write_text(
        json.dumps(
            {
                "mode": sonuc.mode,
                "gold_campaigns": sonuc.gold_campaigns,
                "gold_annotations": sonuc.gold_annotations,
                "micro_f1": round(o.f1, 4),
                "macro_f1": round(sonuc.macro_f1, 4),
                "hallucination_rate": round(o.hallucination_rate, 4),
                "correct_silence_rate": round(o.correct_silence_rate, 4),
                "overall": asdict(o),
                "by_field": {ad: asdict(s) for ad, s in sonuc.by_field.items()},
                "by_method": {ad: asdict(s) for ad, s in sonuc.by_method.items()},
                "by_bank": {ad: asdict(s) for ad, s in sonuc.by_bank.items()},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"\nRapor: {RAPOR_YOLU}")
    print(f"JSON : {json_yolu}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
