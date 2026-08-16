"""Ablasyon tablosu — üç konfigürasyonun karşılaştırması (KAPI A9).

AĞA ÇIKMAZ.

    rule_only  tablo + kural        LLM'e hiç çağrı yok
    llm_only   yalnızca LLM         kural ve yapısal veri devre dışı
    hybrid     üçü birlikte         üretim kipi

⚠️ BU SPRINT'TE YALNIZCA `rule_only` GERÇEK SAYI ÜRETİR. `llm_only` ve
`hybrid` MockProvider ile çalışır; mock her alanı `null` döndürdüğü için
LLM katmanının katkısı SIFIRDIR ve `hybrid` = `rule_only` çıkar. Tablo
iskeleti burada kurulur, gerçek sayılar SPRINT 3B'de doldurulur.

⚠️ ÖLÇÜM TEK ÇALIŞTIRMADAN ÇIKAR. `hybrid` çıkarımı tablo, kural ve LLM
kayıtlarının hepsini yazar; `evaluate()` her kipte yalnızca ilgili
katmanları okur (`MODE_METHODS`). Bu yüzden ablasyon üç kez çıkarım
yapmaz — üç kez ÖLÇER. Aksi hâlde yerel modelle üç tam tur saatler sürerdi.

Çalıştırma:
    python dev.py ablation
    python dev.py ablation --cikarim    # önce hybrid çıkarımı da çalıştır
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

from app.ai.evaluation import MIN_SUPPORT, MODE_METHODS, EvaluationResult, evaluate
from app.ai.pipeline import run_extraction
from app.ai.providers import get_provider
from app.config import get_settings
from app.db.session import SessionLocal
from app.logging_config import configure_logging

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RAPOR_YOLU = REPO_ROOT / "docs" / "ablation.md"
JSON_DIZINI = REPO_ROOT / "data" / "eval"

# Tabloda görünecek kip sırası.
MODES: tuple[str, ...] = ("rule_only", "llm_only", "hybrid")

# MockProvider ile üretilmiş, yani anlamsız sayı taşıyan kipler.
MOCK_MODES: frozenset[str] = frozenset({"llm_only", "hybrid"})


def _tablo(sonuclar: dict[str, EvaluationResult], *, mock: bool) -> list[str]:
    """Alan bazında karşılaştırma tablosunu üretir."""
    # Alanlar `rule_only`in desteğine göre sıralanır: en çok etiketlenen üstte.
    referans = sonuclar["rule_only"]
    alanlar = [
        ad
        for ad, sayac in sorted(referans.by_field.items(), key=lambda p: -p[1].support)
        if sayac.support >= MIN_SUPPORT
    ]

    satirlar = [
        "| Alan | destek | " + " | ".join(MODES) + " |",
        "|---|---|" + "---|" * len(MODES),
    ]
    for ad in alanlar:
        hucreler = []
        for kip in MODES:
            sayac = sonuclar[kip].by_field.get(ad)
            if sayac is None or sayac.support == 0:
                hucreler.append("—")
            elif kip in MOCK_MODES and mock:
                hucreler.append(f"{sayac.f1:.2f} (mock)")
            else:
                hucreler.append(f"{sayac.f1:.2f}")
        destek = referans.by_field[ad].support
        satirlar.append(f"| `{ad}` | {destek} | " + " | ".join(hucreler) + " |")

    return satirlar


def _ozet_tablosu(sonuclar: dict[str, EvaluationResult]) -> list[str]:
    """Genel metrikleri karşılaştırır."""
    olcumler = (
        ("Mikro F1", lambda s: f"{s.overall.f1:.3f}"),
        ("Makro F1", lambda s: f"{s.macro_f1:.3f}"),
        ("Precision", lambda s: f"{s.overall.precision:.3f}"),
        ("Recall", lambda s: f"{s.overall.recall:.3f}"),
        ("Halüsinasyon", lambda s: f"{s.overall.hallucination_rate:.3f}"),
        ("Doğru susma", lambda s: f"{s.overall.correct_silence_rate:.3f}"),
        (
            "TP / FP / FN / TN",
            lambda s: f"{s.overall.tp}/{s.overall.fp}/{s.overall.fn}/{s.overall.tn}",
        ),
    )
    satirlar = [
        "| Ölçüm | " + " | ".join(MODES) + " |",
        "|---|" + "---|" * len(MODES),
    ]
    for ad, cikar in olcumler:
        satirlar.append(f"| {ad} | " + " | ".join(cikar(sonuclar[kip]) for kip in MODES) + " |")
    return satirlar


def _rapor(sonuclar: dict[str, EvaluationResult], *, mock: bool, model_adi: str) -> str:
    """`docs/ablation.md` içeriğini üretir."""
    referans = sonuclar["rule_only"]
    kor = referans.by_method.get("blind")

    satirlar = [
        "# Ablasyon — konfigürasyon karşılaştırması",
        "",
        "> `python dev.py ablation` çıktısı. Otomatik üretilir.",
        "",
        f"Gold set: **{referans.gold_campaigns}** kampanya · "
        f"**{referans.gold_annotations}** etiket",
        f"Model: `{model_adi}`",
        "",
    ]

    if mock:
        satirlar += [
            "> ⚠️ **`llm_only` ve `hybrid` sayıları ANLAMLI DEĞİLDİR.**",
            "> Bu sprint MockProvider ile çalışır; sahte sağlayıcı her alanı",
            "> `null` döndürür, dolayısıyla LLM katmanının katkısı sıfırdır ve",
            "> `hybrid` = `rule_only` çıkar. Tablo iskeleti kurulmuştur;",
            "> gerçek sayılar SPRINT 3B'de gerçek model takılınca dolacaktır.",
            "",
        ]

    if kor is not None and referans.bias_gap is not None and referans.bias_gap > 0.05:
        satirlar += [
            f"> ⚠️ **Ana metrik kör alt kümedir: F1 = {kor.f1:.3f}**",
            f"> Kör ile ön-doldurmalı arasındaki fark {referans.bias_gap:.3f}",
            "> (eşik 0,05). Ön-doldurma yanlılık taşıdığı için mikro F1",
            "> ikincil bilgidir.",
            "",
        ]

    satirlar += ["## Genel", "", *_ozet_tablosu(sonuclar), ""]
    satirlar += [
        "## Alan bazında F1",
        "",
        f"Yalnızca desteği ≥{MIN_SUPPORT} olan alanlar listelenir.",
        "",
        *_tablo(sonuclar, mock=mock),
        "",
    ]
    satirlar += [
        "## Kip tanımları",
        "",
        "| Kip | Okunan çıkarım katmanları |",
        "|---|---|",
        *[f"| `{kip}` | {', '.join(MODE_METHODS[kip])} |" for kip in MODES],
        "",
        "⚠️ Ablasyon üç kez ÇIKARIM yapmaz, üç kez ÖLÇER: `hybrid` çalıştırması",
        "her katmanın kaydını yazar, ölçüm her kipte yalnızca ilgili alt kümeyi",
        "okur. Yerel modelle üç tam tur saatler sürerdi.",
        "",
    ]
    return "\n".join(satirlar) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Betiğin giriş noktası."""
    ayristirici = argparse.ArgumentParser(description="Ablasyon karşılaştırması")
    ayristirici.add_argument(
        "--cikarim",
        action="store_true",
        help="Ölçümden önce hybrid çıkarımı da çalıştır (tüm katmanları tazeler)",
    )
    argumanlar = ayristirici.parse_args(argv)

    configure_logging()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    ayarlar = get_settings()
    saglayici = get_provider(ayarlar)
    mock = not saglayici.model_info.name.startswith("local")

    with SessionLocal() as session:
        if argumanlar.cikarim:
            print("Hybrid çıkarımı çalıştırılıyor (tüm katmanlar)...")
            asyncio.run(run_extraction(session, saglayici, mode="hybrid"))

        sonuclar = {kip: evaluate(session, mode=kip) for kip in MODES}

    if sonuclar["rule_only"].gold_annotations == 0:
        print("Gold set boş. Önce: python dev.py etiketle")
        return 1

    RAPOR_YOLU.parent.mkdir(parents=True, exist_ok=True)
    RAPOR_YOLU.write_text(
        _rapor(sonuclar, mock=mock, model_adi=saglayici.model_info.name), encoding="utf-8"
    )

    JSON_DIZINI.mkdir(parents=True, exist_ok=True)
    for kip, sonuc in sonuclar.items():
        (JSON_DIZINI / f"results_{kip}.json").write_text(
            json.dumps(
                {
                    "mode": kip,
                    "gold_campaigns": sonuc.gold_campaigns,
                    "gold_annotations": sonuc.gold_annotations,
                    "micro_f1": round(sonuc.overall.f1, 4),
                    "macro_f1": round(sonuc.macro_f1, 4),
                    "hallucination_rate": round(sonuc.overall.hallucination_rate, 4),
                    "correct_silence_rate": round(sonuc.overall.correct_silence_rate, 4),
                    "overall": asdict(sonuc.overall),
                    "by_field": {ad: asdict(s) for ad, s in sonuc.by_field.items()},
                    "by_method": {ad: asdict(s) for ad, s in sonuc.by_method.items()},
                    "by_bank": {ad: asdict(s) for ad, s in sonuc.by_bank.items()},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    print("\nAblasyon — mikro F1")
    for kip in MODES:
        isaret = "  (mock, anlamsız)" if kip in MOCK_MODES and mock else ""
        print(f"  {kip:12} {sonuclar[kip].overall.f1:.3f}{isaret}")

    print(f"\nRapor: {RAPOR_YOLU}")
    print(f"JSON : {JSON_DIZINI}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
