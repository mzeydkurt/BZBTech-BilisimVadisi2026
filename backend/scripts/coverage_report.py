"""Kapsama ve geri çağırma — hangi sayının paydası ne (E1).

AĞA ÇIKMAZ.

⚠️ BU BETİK BİR SORUYU KAPATMAK İÇİN VAR: *"kâr payı oranı kampanyaların
%36'sında dolu"* cümlesi sistemi olduğundan kötü gösteriyor, çünkü PAYDA
YANLIŞ. Kart kampanyalarının çoğunda banka zaten oran yayımlamıyor; o
kampanyaları paydaya koymak, sistemi bulunmayan bir bilgiyi bulamadığı için
cezalandırmak olur.

Üç ölçüt üç FARKLI paydadan çıkar ve rapor bunu satır satır yazar:

    doldurma oranı   payda = kampanyaların TAMAMI
    geri çağırma     payda = gold'da DEĞERİ BULUNAN alan etiketleri
    kesinlik         payda = sistemin ÜRETTİĞİ değerler

Ek olarak gold set'in kendi tanıklığı raporlanır: etiketleyici alanların
kaçında *"bu alan kaynakta yok"* demiş? O sayı, düşük doldurma oranının
sistemden değil kaynaktan geldiğinin doğrudan kanıtıdır.

Çalıştırma:
    python dev.py kapsama
    python -m scripts.coverage_report --mod hybrid
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.evaluation import MIN_SUPPORT, MODE_METHODS, Counts, EvaluationResult, evaluate
from app.ai.fields import EXTRACTABLE_FIELDS
from app.db.models import Campaign, CampaignExtraction, GoldAnnotation
from app.db.session import SessionLocal
from app.logging_config import configure_logging

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RAPOR_YOLU = REPO_ROOT / "docs" / "kapsama_ve_geri_cagirma.md"
JSON_YOLU = REPO_ROOT / "data" / "eval" / "coverage.json"


def _doldurma(session: Session, *, methods: tuple[str, ...]) -> tuple[int, dict[str, int]]:
    """Alan bazında kaç kampanyada değer üretilmiş?

    ⚠️ REDDEDİLEN KAYITLAR SAYILMAZ: guard'ın elediği bir değer kullanıcıya
    sunulmuyor, doldurma oranına girmesi rakamı şişirirdi.

    Args:
        session: Veritabanı oturumu.
        methods: Sayıma girecek çıkarım katmanları (`MODE_METHODS`).

    Returns:
        (kampanya sayısı, alan → dolu kampanya sayısı).
    """
    kampanya_sayisi = session.scalar(select(func.count()).select_from(Campaign)) or 0

    satirlar = session.execute(
        select(
            CampaignExtraction.field_name,
            func.count(func.distinct(CampaignExtraction.campaign_id)),
        )
        .where(
            CampaignExtraction.rejected_reason.is_(None),
            CampaignExtraction.extraction_method.in_(methods),
        )
        .group_by(CampaignExtraction.field_name)
    ).all()

    return kampanya_sayisi, {ad: int(sayi) for ad, sayi in satirlar}


def _gold_tanikligi(session: Session) -> tuple[int, int, dict[str, tuple[int, int]]]:
    """Gold set'in kendi tanıklığı: kaç etiket "kaynakta yok" diyor?

    ⚠️ REFERANS TUR SEÇİMİ `evaluate()` İLE AYNI OLMAK ZORUNDA. Farklı
    etiketleyici turu seçilirse rapordaki payda ile F1'in paydası ayrışır ve
    iki sayı yan yana konulamaz.

    Args:
        session: Veritabanı oturumu.

    Returns:
        (toplam etiket, boş etiket, alan → (toplam, boş)).
    """
    referans = session.scalar(
        select(GoldAnnotation.annotator)
        .group_by(GoldAnnotation.annotator)
        .order_by(func.count().desc())
        .limit(1)
    )
    # ⚠️ `Campaign` İLE JOIN ZORUNLU. `evaluate()` de bu joini yapıyor;
    # yapılmazsa kampanyası silinmiş (yeniden kazımada düşmüş) etiketler
    # sayıma girer ve payda F1'in paydasından büyük çıkar — ölçüldü: 2.272
    # etiketin 820'sinin kampanyası artık veritabanında yok.
    sorgu = (
        select(
            GoldAnnotation.field_name,
            func.count(),
            func.sum(func.iif(GoldAnnotation.gold_value.is_(None), 1, 0)),
        )
        .join(Campaign, Campaign.id == GoldAnnotation.campaign_id)
        .group_by(GoldAnnotation.field_name)
    )
    if referans is not None:
        sorgu = sorgu.where(GoldAnnotation.annotator == referans)

    alanlar: dict[str, tuple[int, int]] = {}
    toplam = bos = 0
    for ad, sayi, bos_sayi in session.execute(sorgu):
        alanlar[ad] = (int(sayi), int(bos_sayi or 0))
        toplam += int(sayi)
        bos += int(bos_sayi or 0)
    return toplam, bos, alanlar


def _yuzde(pay: int, payda: int) -> str:
    """Yüzdeyi Türkçe ondalıkla biçimler; payda sıfırsa tire.

    Args:
        pay: Bölünen.
        payda: Bölen.

    Returns:
        `%83,3` biçiminde dize ya da `—`.
    """
    if not payda:
        return "—"
    return f"%{100 * pay / payda:.1f}".replace(".", ",")


def _ozet_tablosu(
    *, sonuc: EvaluationResult, kampanya_sayisi: int, doldurma: dict[str, int]
) -> list[str]:
    """Üç paydayı yan yana koyan özet tablosunu üretir."""
    o: Counts = sonuc.overall
    alan_sayisi = len(EXTRACTABLE_FIELDS)
    return [
        "| Ölçüt | Değer | Payda | Payda ne demek |",
        "|---|---|---|---|",
        f"| Alan doldurma oranı | {_yuzde(sum(doldurma.values()), kampanya_sayisi * alan_sayisi)} "
        f"| {kampanya_sayisi} × {alan_sayisi} | "
        "kampanyaların tamamı × çıkarılabilir alanların tamamı |",
        f"| **Geri çağırma** | **{_yuzde(o.tp, o.support)}** | {o.support} | "
        "gold'da **değeri bulunan** alan etiketi |",
        f"| Kesinlik | {_yuzde(o.tp, o.tp + o.fp)} | {o.tp + o.fp} | "
        "sistemin **ürettiği** değer |",
        f"| Doğru susma | {_yuzde(o.tn, o.silence_opportunities)} | {o.silence_opportunities} | "
        "gold'da **boş** olan, susulması gereken alan |",
        f"| Uydurma oranı | {_yuzde(o.fp_invented, o.tp + o.fp)} | {o.tp + o.fp} | "
        "üretilen değer (kaçı kaynakta hiç yoktu) |",
    ]


def _alan_tablosu(
    *,
    sonuc: EvaluationResult,
    kampanya_sayisi: int,
    doldurma: dict[str, int],
    gold_alanlar: dict[str, tuple[int, int]],
) -> list[str]:
    """Alan bazında üç paydayı yan yana koyan tabloyu üretir."""
    satirlar = [
        f"| Alan | dolu / {kampanya_sayisi} | doldurma | gold var | gold boş | R | uydurma |",
        "|---|---|---|---|---|---|---|",
    ]
    for alan in sorted(
        EXTRACTABLE_FIELDS,
        key=lambda ad: (-(gold_alanlar.get(ad, (0, 0))[0] - gold_alanlar.get(ad, (0, 0))[1]), ad),
    ):
        dolu = doldurma.get(alan, 0)
        gold_tum, gold_alan_bos = gold_alanlar.get(alan, (0, 0))
        sayac = sonuc.by_field.get(alan)
        if sayac is not None and sayac.support >= MIN_SUPPORT:
            geri = _yuzde(sayac.tp, sayac.support)
            uydurma = f"{sayac.invention_rate:.2f}"
        else:
            geri = uydurma = "—"
        satirlar.append(
            f"| `{alan}` | {dolu} | {_yuzde(dolu, kampanya_sayisi)} "
            f"| {gold_tum - gold_alan_bos} | {gold_alan_bos} | {geri} | {uydurma} |"
        )
    return satirlar


def _rapor(
    *,
    mode: str,
    sonuc: EvaluationResult,
    kampanya_sayisi: int,
    doldurma: dict[str, int],
    gold_toplam: int,
    gold_bos: int,
    gold_alanlar: dict[str, tuple[int, int]],
) -> str:
    """Markdown raporunu üretir."""
    o: Counts = sonuc.overall
    satirlar: list[str] = [
        "# Kapsama ve geri çağırma — hangi sayının paydası ne",
        "",
        f"> `python dev.py kapsama --mod {mode}` çıktısı. Otomatik üretilir.",
        "",
        "⚠️ **ÜÇ ÖLÇÜT, ÜÇ FARKLI PAYDA.** Aynı tabloda paydası yazılmadan durursa",
        "okuyan kişi bunları birbiriyle karşılaştırır — ve karşılaştırılamazlar.",
        "",
        "## Özet",
        "",
        *_ozet_tablosu(sonuc=sonuc, kampanya_sayisi=kampanya_sayisi, doldurma=doldurma),
        "",
        f"Kip: `{mode}` · gold set {sonuc.gold_campaigns} kampanya · "
        f"{sonuc.gold_annotations} alan etiketi · "
        f"TP {o.tp} · FP {o.fp} ({o.fp_invented} uydurma + {o.fp_wrong} yanlış okuma) · "
        f"FN {o.fn} · TN {o.tn}",
        "",
        "## Düşük doldurma oranı nereden geliyor?",
        "",
        "Gold set'i etiketleyen kişi her alan için **kaynakta değer var mı**",
        "sorusuna da yanıt verdi. Bu sayı, doldurma oranının neden düşük",
        "göründüğünün doğrudan kanıtıdır:",
        "",
        "| | sayı | oran |",
        "|---|---|---|",
        f"| Etiketlenen (kampanya, alan) çifti | {gold_toplam} | |",
        f'| Etiketleyicinin **"kaynakta yok"** dediği | **{gold_bos}** '
        f"| {_yuzde(gold_bos, gold_toplam)} |",
        f"| Kaynakta gerçekten değer bulunan | {gold_toplam - gold_bos} "
        f"| {_yuzde(gold_toplam - gold_bos, gold_toplam)} |",
        "",
        f"> Etiketlenen alanların **{_yuzde(gold_bos, gold_toplam)}'ünde kaynağın",
        "> kendisi boş.** Alan boş değil — kaynak boş. Doldurma oranı bu boşluğu",
        "> sisteme yazıyor, geri çağırma yazmıyor. Doğru ölçüt geri çağırmadır.",
        "",
        "## Alan bazında — üç payda yan yana",
        "",
        "`dolu` sistemin değer ürettiği kampanya sayısı (payda: tüm kampanyalar).",
        "`gold var` etiketleyicinin kaynakta değer gördüğü etiket sayısı.",
        "`R` geri çağırma — payda `gold var`.",
        "",
        *_alan_tablosu(
            sonuc=sonuc,
            kampanya_sayisi=kampanya_sayisi,
            doldurma=doldurma,
            gold_alanlar=gold_alanlar,
        ),
        "",
        f"> `R` yalnızca desteği ≥{MIN_SUPPORT} olan alanlarda yazılır; üç örnekle",
        "> hesaplanan bir oran gürültüdür.",
        "",
        "## Sunumda söylenecek cümle",
        "",
        f"> Kaynakta değeri bulunan alanların **{_yuzde(o.tp, o.support)}'ünü** doğru",
        "> çıkarıyoruz. Doldurma oranının düşük görünmesi, kart kampanyalarının",
        "> çoğunda bankanın oran yayımlamamasından kaynaklanıyor — gold set'i",
        f"> etiketleyen kişi de {gold_toplam} alanın **{gold_bos}'sinde** *\"kaynakta",
        '> yok"* demiş. Alan boş değil, kaynak boş.',
        "",
        "## İlgili raporlar",
        "",
        "| Dosya | Ne ölçer |",
        "|---|---|",
        "| `docs/evaluation.md` | tek kipte alan çıkarımı F1, alan/banka kırılımı |",
        "| `docs/ablation.md` | üç kipin (rule_only / llm_only / hybrid) karşılaştırması |",
        "| `docs/paraf_degismezlik.md` | aynı olgunun N yazımında aynı değeri üretme |",
        "| `docs/sprint5_evaluation.md` | sohbet uçtan uca (niyet, susma, gecikme) |",
        "| `docs/erisim_recall.md` | erişim isabeti (recall@k) ve kanal ablasyonu |",
    ]
    return "\n".join(satirlar) + "\n"


def main() -> int:
    """Kapsama ve geri çağırma raporunu üretir.

    Returns:
        Çıkış kodu; gold set boşsa 1.
    """
    ayristirici = argparse.ArgumentParser(description="Kapsama ve geri çağırma raporu")
    ayristirici.add_argument(
        "--mod",
        default="rule_only",
        choices=tuple(MODE_METHODS),
        help="Ölçülecek çıkarım kipi (varsayılan: rule_only)",
    )
    argumanlar = ayristirici.parse_args()

    configure_logging()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    with SessionLocal() as session:
        sonuc = evaluate(session, mode=argumanlar.mod)
        if sonuc.gold_annotations == 0:
            print("Gold set boş. Önce: python dev.py etiketle")
            return 1
        kampanya_sayisi, doldurma = _doldurma(session, methods=MODE_METHODS[argumanlar.mod])
        gold_toplam, gold_bos, gold_alanlar = _gold_tanikligi(session)

    RAPOR_YOLU.parent.mkdir(parents=True, exist_ok=True)
    RAPOR_YOLU.write_text(
        _rapor(
            mode=argumanlar.mod,
            sonuc=sonuc,
            kampanya_sayisi=kampanya_sayisi,
            doldurma=doldurma,
            gold_toplam=gold_toplam,
            gold_bos=gold_bos,
            gold_alanlar=gold_alanlar,
        ),
        encoding="utf-8",
    )

    o = sonuc.overall
    JSON_YOLU.parent.mkdir(parents=True, exist_ok=True)
    JSON_YOLU.write_text(
        json.dumps(
            {
                "mode": argumanlar.mod,
                "campaigns": kampanya_sayisi,
                "extractable_fields": len(EXTRACTABLE_FIELDS),
                "recall": round(o.recall, 4),
                "recall_denominator": o.support,
                "precision": round(o.precision, 4),
                "precision_denominator": o.tp + o.fp,
                "correct_silence_rate": round(o.correct_silence_rate, 4),
                "silence_opportunities": o.silence_opportunities,
                "invention_rate": round(o.invention_rate, 4),
                "value_error_rate": round(o.value_error_rate, 4),
                "gold_annotations": gold_toplam,
                "gold_null_annotations": gold_bos,
                "fill_by_field": doldurma,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Kip                : {argumanlar.mod}")
    print(f"Geri çağırma       : {o.recall:.3f}  (payda {o.support} — kaynakta değeri olan alan)")
    print(f"Kesinlik           : {o.precision:.3f}  (payda {o.tp + o.fp} — üretilen değer)")
    print(
        f"Doğru susma        : {o.correct_silence_rate:.3f}  "
        f"(payda {o.silence_opportunities} — susulması gereken alan)"
    )
    print(f"Uydurma oranı      : {o.invention_rate:.3f}  ({o.fp_invented} kayıt)")
    print(f"Yanlış okuma       : {o.value_error_rate:.3f}  ({o.fp_wrong} kayıt)")
    print(f'Gold "kaynakta yok": {gold_bos}/{gold_toplam}')
    print(f"\nRapor: {RAPOR_YOLU}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
