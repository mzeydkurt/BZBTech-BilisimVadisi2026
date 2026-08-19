"""Gold set üzerinde çıkarım kalitesinin ölçülmesi.

⚠️ DÖRT DURUM AYRI SAYILIR — üçü değil, dördü:

    TP  gold'da değer var, sistem aynısını buldu
    FP  gold'da NULL, sistem değer üretti          ← HALÜSİNASYON
    FN  gold'da değer var, sistem null döndürdü    ← KAÇIRMA
    TN  gold'da NULL, sistem de null               ← DOĞRU SUSMA

⚠️ TN RAPORLANIR. "Bilgi yokken bilgi üretmeme" şartname 7'de açıkça
puanlanan bir yetenektir; ölçülmeden iddia edilemez. Klasik F1 hesabı TN'i
yok sayar — bu yüzden halüsinasyon ve doğru susma oranları AYRICA verilir.

⚠️ YALNIZCA GOLD SET'TE BULUNAN (kampanya, alan) ÇİFTLERİ ÖLÇÜLÜR.
Etiketlenmemiş bir alan ne doğru ne yanlıştır; ölçüme sokulursa sistem
etiketleyicinin bitirmediği işten sorumlu tutulmuş olur.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Final

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.validation.merger import METHOD_PRIORITY
from app.core.normalization.date_tr import parse_date_tr
from app.db.models import Bank, Campaign, CampaignExtraction, GoldAnnotation

# Oran karşılaştırmasında kabul edilen sapma. Tutar, vade ve taksitte
# tolerans YOKTUR: "36 ay" ile "35 ay" farklı ürünlerdir.
RATE_TOLERANCE: Final[Decimal] = Decimal("0.01")

# ⚠️ KİP → ÖLÇÜME GİREN ÇIKARIM KATMANLARI. Ablasyon tablosunun temeli.
# `llm_only` tablo katmanını da DIŞARIDA bırakır: "kural ve yapısal veri
# olmasaydı ne olurdu?" sorusunun yanıtı ancak böyle alınır.
MODE_METHODS: Final[dict[str, tuple[str, ...]]] = {
    "rule_only": ("table", "rule"),
    "hybrid": ("table", "rule", "llm"),
    "llm_only": ("llm",),
}

# Bu sayının altında örneği olan alan için F1 raporlanmaz.
# ⚠️ Üç örnekle hesaplanan bir F1 gürültüdür; yazmak yanıltıcı olur.
MIN_SUPPORT: Final[int] = 5


@dataclass
class Counts:
    """Bir alan (ya da alt küme) için dört durum sayacı."""

    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    @property
    def support(self) -> int:
        """Gold'da DEĞER BULUNAN örnek sayısı (F1'in dayanağı)."""
        return self.tp + self.fn

    @property
    def precision(self) -> float:
        """Üretilen değerlerin ne kadarı doğru?"""
        payda = self.tp + self.fp
        return self.tp / payda if payda else 0.0

    @property
    def recall(self) -> float:
        """Var olan değerlerin ne kadarı bulundu?"""
        payda = self.tp + self.fn
        return self.tp / payda if payda else 0.0

    @property
    def f1(self) -> float:
        """Precision ve recall'un harmonik ortalaması."""
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def hallucination_rate(self) -> float:
        """Üretilen değerlerin ne kadarı kaynakta YOKTU? FP / (TP + FP)."""
        payda = self.tp + self.fp
        return self.fp / payda if payda else 0.0

    @property
    def correct_silence_rate(self) -> float:
        """Boş olması gereken alanların ne kadarında SUSULDU? TN / (TN + FP)."""
        payda = self.tn + self.fp
        return self.tn / payda if payda else 0.0


@dataclass
class EvaluationResult:
    """Tüm değerlendirme çıktısı."""

    mode: str
    overall: Counts = field(default_factory=Counts)
    by_field: dict[str, Counts] = field(default_factory=dict)
    by_bank: dict[str, Counts] = field(default_factory=dict)
    by_method: dict[str, Counts] = field(default_factory=dict)
    difficult: Counts = field(default_factory=Counts)
    easy: Counts = field(default_factory=Counts)
    gold_campaigns: int = 0
    gold_annotations: int = 0

    @property
    def macro_f1(self) -> float:
        """Yeterli desteğe sahip alanların F1 ortalaması.

        ⚠️ Desteksiz alanlar DIŞARIDA bırakılır; iki örnekli bir alanın 0.0
        ya da 1.0 F1'i ortalamayı olduğundan aşağı ya da yukarı çeker.
        """
        gecerli = [s.f1 for s in self.by_field.values() if s.support >= MIN_SUPPORT]
        return sum(gecerli) / len(gecerli) if gecerli else 0.0

    @property
    def bias_gap(self) -> float | None:
        """Kör ve ön-doldurmalı alt kümeler arasındaki F1 farkı.

        0,05'i aşarsa ana metrik olarak KÖR alt küme raporlanmalıdır.
        """
        kor = self.by_method.get("blind")
        yardimli = self.by_method.get("assisted")
        if not kor or not yardimli or not yardimli.support:
            return None
        return abs(kor.f1 - yardimli.f1)


def _sayi(deger: str | None) -> Decimal | None:
    """Metni sayıya çevirir; sayı değilse None."""
    if deger is None:
        return None
    try:
        return Decimal(deger.strip())
    except (InvalidOperation, AttributeError):
        return None


def _tarih(deger: str) -> date | None:
    """Tarih dizesini `date` nesnesine çevirir; çeviremezse None.

    Hem ISO (`2026-08-31`) hem Türkçe yazım (`31.08.2026`, `31 Ağustos 2026`)
    desteklenir: gold etiketleri elle yazıldığı için ikisi de görülüyor.

    Args:
        deger: Ayrıştırılacak dize.

    Returns:
        Tarih veya None.
    """
    try:
        return date.fromisoformat(deger.strip())
    except ValueError:
        return parse_date_tr(deger)


def values_match(gold: str, sistem: str, unit: str) -> bool:
    """İki değerin eşleşip eşleşmediğine birime göre karar verir.

    Args:
        gold: İnsanın yazdığı değer.
        sistem: Sistemin ürettiği değer.
        unit: Alanın birimi.

    Returns:
        Eşleşiyorsa True.
    """
    g, s = gold.strip(), sistem.strip()

    if unit == "bool":
        # "true"/"True"/"1" aynı şeydir; biçim farkı hata sayılmaz.
        return (
            g.casefold() in {"true", "1"}
            if s.casefold() in {"true", "1"}
            else g.casefold() == s.casefold()
        )

    if unit in {"pct", "TRY", "month", "count"}:
        gs, ss = _sayi(g), _sayi(s)
        if gs is None or ss is None:
            return g.casefold() == s.casefold()
        # ⚠️ Tolerans YALNIZCA oranda. Tutar ve vadede "36" ile "35" farklıdır.
        return abs(gs - ss) <= RATE_TOLERANCE if unit == "pct" else gs == ss

    if unit == "date":
        # ⚠️ Tarihler DEĞER olarak karşılaştırılır, dize olarak değil.
        #
        # Kılavuz (§4.5) gold biçimi olarak `2026-08-31` diyor ama 67 tarih
        # etiketinin 14'ü `31.08.2026` / `08-06-2026` yazılmış. Dize
        # karşılaştırması bunları sistemin `isoformat()` çıktısıyla asla
        # eşleştiremiyor: aynı gün, farklı yazım, hem FN hem FP sayılıyordu.
        # Tarih alanlarının F1'i bu yüzden yapay bir tavana çarpıyordu.
        #
        # Ayrıştırılamayan değerde dize karşılaştırmasına düşülür.
        gt, st = _tarih(g), _tarih(s)
        if gt is not None and st is not None:
            return gt == st

    # enum ve ayrıştırılamayan tarih: tam eşleşme (küçük/büyük harf duyarsız).
    return g.casefold() == s.casefold()


def _tally(hedefler: list[Counts], durum: str) -> None:
    """Aynı gözlemi birden çok alt küme sayacına işler."""
    for sayac in hedefler:
        setattr(sayac, durum, getattr(sayac, durum) + 1)


def _referans_annotator(session: Session) -> str | None:
    """Puanlamaya girecek etiketleme turunu seçer.

    En çok etikete sahip etiketleyici referanstır. Öz-tutarlılık turları
    kılavuz §4 gereği yalnızca ilk 15 kaydı kapsar; bu yüzden daima daha
    küçüktür ve seçim kararlıdır.

    Returns:
        Referans etiketleyici adı; hiç etiket yoksa None.

    """
    return session.scalar(
        select(GoldAnnotation.annotator)
        .group_by(GoldAnnotation.annotator)
        .order_by(func.count().desc())
        .limit(1)
    )


def evaluate(session: Session, *, mode: str = "rule_only") -> EvaluationResult:
    """Gold set'e karşı çıkarım kalitesini ölçer.

    ⚠️ `mode` YALNIZCA BİR ETİKET DEĞİLDİR; hangi çıkarım katmanlarının
    ölçüme gireceğini de belirler (`MODE_METHODS`). Önceki sürümde etiket
    olarak kalıyordu: `hybrid` çalıştırmasından sonra `--mod llm_only`
    denince dosya yanlış adla yazılıyor ve ablasyon tablosu aynı sayıyı üç
    kolona kopyalıyordu.

    Bu sayede TEK çalıştırmadan üç kipin ölçümü çıkarılabilir: `hybrid`
    koşusu tablo, kural ve LLM kayıtlarının hepsini yazar; ablasyon her
    kipte yalnızca ilgili alt kümeyi okur.

    Args:
        session: Veritabanı oturumu.
        mode: `rule_only` | `hybrid` | `llm_only`.

    Returns:
        Alan, banka, yöntem ve zorluk kırılımlarıyla ölçüm sonucu.

    Raises:
        ValueError: Tanımsız kip verildiyse.
    """
    if mode not in MODE_METHODS:
        raise ValueError(f"Tanımsız kip: {mode!r}. Geçerli: {tuple(MODE_METHODS)}")

    sonuc = EvaluationResult(mode=mode)

    referans_tur = _referans_annotator(session)

    sorgu = (
        select(GoldAnnotation, Bank.code)
        .join(Campaign, Campaign.id == GoldAnnotation.campaign_id)
        .join(Bank, Bank.id == Campaign.bank_id)
    )
    if referans_tur is not None:
        sorgu = sorgu.where(GoldAnnotation.annotator == referans_tur)

    etiketler = list(session.execute(sorgu))
    if not etiketler:
        return sonuc

    # Sistemin ürettikleri: (kampanya, alan) → değer.
    #
    # ⚠️ REDDEDİLEN KAYITLAR ÖLÇÜME GİRMEZ. Guard'ın (KAPI A7) elediği bir
    # çıkarım sisteme sunulmaz; onu "sistem bunu üretti" saymak, guard'ın
    # işini görmezden gelmek olurdu.
    #
    # ⚠️ ÇAKIŞMADA MERGER ÖNCELİĞİ UYGULANIR (tablo > kural > LLM), "ilk
    # gelen" değil. Aksi hâlde ölçüm satır sırasına bağlı olur ve aynı
    # veritabanı farklı sonuç verebilir.
    yontemler = MODE_METHODS[mode]
    uretilen: dict[tuple[int, str], tuple[int, str]] = {}
    for kayit in session.scalars(
        select(CampaignExtraction).where(
            CampaignExtraction.rejected_reason.is_(None),
            CampaignExtraction.extraction_method.in_(yontemler),
        )
    ):
        anahtar = (kayit.campaign_id, kayit.field_name)
        oncelik = METHOD_PRIORITY.get(kayit.extraction_method, 0)
        mevcut = uretilen.get(anahtar)
        if mevcut is None or oncelik > mevcut[0]:
            uretilen[anahtar] = (oncelik, kayit.value_normalized or "")

    kampanyalar: set[int] = set()

    for etiket, banka_kodu in etiketler:
        kampanyalar.add(etiket.campaign_id)
        sonuc.gold_annotations += 1

        alan_sayaci = sonuc.by_field.setdefault(etiket.field_name, Counts())
        banka_sayaci = sonuc.by_bank.setdefault(banka_kodu, Counts())
        yontem_sayaci = sonuc.by_method.setdefault(etiket.method, Counts())
        zorluk_sayaci = sonuc.difficult if etiket.is_difficult else sonuc.easy
        hedefler = [sonuc.overall, alan_sayaci, banka_sayaci, yontem_sayaci, zorluk_sayaci]

        bulgu = uretilen.get((etiket.campaign_id, etiket.field_name))
        sistem = bulgu[1] if bulgu is not None else None

        if etiket.gold_value is None:
            # Gold: "metinde yok".
            _tally(hedefler, "fp" if sistem else "tn")
            continue

        if sistem is None:
            _tally(hedefler, "fn")  # Kaçırma.
        elif values_match(etiket.gold_value, sistem, etiket.unit or "enum"):
            _tally(hedefler, "tp")
        else:
            # ⚠️ Yanlış değer HEM yanlış pozitif HEM kaçırmadır: doğru değer
            # bulunamadı (FN) ve olmayan bir değer üretildi (FP).
            _tally(hedefler, "fp")
            _tally(hedefler, "fn")

    sonuc.gold_campaigns = len(kampanyalar)
    return sonuc


def build_report(sonuc: EvaluationResult) -> str:
    """Değerlendirmeyi Markdown raporuna çevirir."""
    o = sonuc.overall
    satirlar: list[str] = [
        "# Değerlendirme Raporu",
        "",
        f"> `python dev.py degerlendir --mod {sonuc.mode}` çıktısı. Otomatik üretilir.",
        "",
        "## Özet",
        "",
        "| | |",
        "|---|---|",
        f"| Kip | `{sonuc.mode}` |",
        f"| Gold set | {sonuc.gold_campaigns} kampanya · {sonuc.gold_annotations} alan etiketi |",
        f"| Mikro F1 | **{o.f1:.3f}** |",
        f"| Makro F1 (destek ≥{MIN_SUPPORT}) | **{sonuc.macro_f1:.3f}** |",
        f"| Precision / Recall | {o.precision:.3f} / {o.recall:.3f} |",
        f"| Halüsinasyon oranı | **{o.hallucination_rate:.3f}** (FP/(TP+FP)) |",
        f"| Doğru susma oranı | **{o.correct_silence_rate:.3f}** (TN/(TN+FP)) |",
        f"| TP / FP / FN / TN | {o.tp} / {o.fp} / {o.fn} / {o.tn} |",
        "",
        "> **Doğru susma**, kaynakta bilgi olmadığında sistemin bilgi üretmemesidir",
        "> (şartname 7). Klasik F1 bu yeteneği ölçmez; ayrıca raporlanır.",
        "",
        "## Alan bazında",
        "",
        "| Alan | P | R | F1 | Destek | Halüsinasyon |",
        "|---|---|---|---|---|---|",
    ]

    for alan, s in sorted(sonuc.by_field.items(), key=lambda p: -p[1].support):
        if s.support < MIN_SUPPORT:
            satirlar.append(f"| `{alan}` | — | — | *yetersiz örnek* | {s.support} | — |")
        else:
            satirlar.append(
                f"| `{alan}` | {s.precision:.2f} | {s.recall:.2f} | **{s.f1:.2f}** "
                f"| {s.support} | {s.hallucination_rate:.2f} |"
            )

    satirlar += [
        "",
        f"> Destek < {MIN_SUPPORT} olan alanlarda F1 YAZILMAZ. Üç örnekle hesaplanan",
        "> bir değer gürültüdür; sayı üretmek yanıltıcı olurdu.",
        "",
        "## Zor vaka ayrımı",
        "",
        "| Alt küme | F1 | Destek | Halüsinasyon |",
        "|---|---|---|---|",
        f"| Zor vaka | {sonuc.difficult.f1:.3f} | {sonuc.difficult.support} "
        f"| {sonuc.difficult.hallucination_rate:.3f} |",
        f"| Kolay | {sonuc.easy.f1:.3f} | {sonuc.easy.support} "
        f"| {sonuc.easy.hallucination_rate:.3f} |",
        "",
        "## Yanlılık kontrolü (kör / ön-doldurmalı)",
        "",
        "| Yöntem | F1 | Destek |",
        "|---|---|---|",
    ]

    for yontem in ("blind", "assisted"):
        alt = sonuc.by_method.get(yontem)
        if alt:
            satirlar.append(f"| `{yontem}` | {alt.f1:.3f} | {alt.support} |")

    fark = sonuc.bias_gap
    if fark is None:
        satirlar += ["", "> Karşılaştırma için iki alt kümede de yeterli veri yok."]
    elif fark <= 0.05:
        satirlar += [
            "",
            f"> Fark **{fark:.3f}** ≤ 0,05 — yanlılık ihmal edilebilir düzeyde.",
        ]
    else:
        satirlar += [
            "",
            f"> ⚠️ Fark **{fark:.3f}** > 0,05. Ön-doldurma etiketleyiciyi etkilemiş;",
            "> ana metrik olarak **kör alt kümenin F1'i** raporlanmalıdır.",
        ]

    satirlar += ["", "## Banka bazında", "", "| Banka | F1 | Destek |", "|---|---|---|"]
    for banka, s in sorted(sonuc.by_bank.items(), key=lambda p: -p[1].support):
        satirlar.append(f"| {banka} | {s.f1:.3f} | {s.support} |")

    return "\n".join(satirlar) + "\n"
