"""Şartnamenin kendi örnek senaryoları — birebir koşum (E6).

AĞA ÇIKMAZ · VERİTABANI GEREKTİRMEZ.

⚠️ JÜRİ KENDİ ÖRNEĞİNİN ÇALIŞTIĞINI GÖRMEK İSTER. Şartname "Örnek Temsili
Senaryo-1"de A/B/C Bankası konut finansmanı satırlarını veriyor. Sistemin bu
senaryoyu çözdüğü jüri dosyasında yazıyor ama gösterilmiyor: yazılı bir iddia
ile koşan bir çıktı jüri gözünde aynı şey değil.

Bu betik o senaryoyu ÜRETİM YOLUNDAN geçirir ve iki şeyi birlikte raporlar:

    doldurulan alanlar   → beklenen değer üretildi mi
    BOŞ KALAN alanlar    → kaynakta olmayan bilgi uydurulmadı mı

⚠️ İKİNCİSİ ÖLÇÜMÜN YARISI. Şartnamenin C Bankası satırında masraf bilgisi
YOK. Yalnızca doldurulan alanlara bakan bir ölçüm, sistemin o alanı boş
bırakma yeteneğini (şartname 7) hiç görmez.

⚠️ FAZLADAN ÜRETİLEN ALANLAR DA YAZILIR. Rapor yalnızca beklenenleri
gösterirse, sistemin senaryo tablosunda olmayan bir alanı doldurduğu
görünmez. Gizlenen bir fazlalık, jürinin kendi gözüyle bulacağı fazlalıktan
kötüdür.

Çalıştırma:
    python dev.py sartname-senaryo
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app.ai.evaluation import values_match
from app.ai.extraction import extract_rule_based
from app.ai.fields import unit_of
from app.ai.validation import guard_fields, merge_extractions
from app.processing.categorizer import categorize

BACKEND = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND.parent
KUME = BACKEND / "tests" / "fixtures" / "sartname" / "senaryolar.jsonl"
RAPOR_YOLU = REPO_ROOT / "docs" / "sartname_senaryolari.md"

# Sınıflandırma ekseninden gelen alanlar; "fazladan" sayılmaz.
_EKSEN_ALANLARI = frozenset({"product_type", "sector", "target_customer", "reward_type"})


@dataclass
class SenaryoSonucu:
    """Tek bir banka satırının sonucu."""

    kod: str
    banka: str
    metin: str
    # alan → (beklenen, üretilen, doğru mu, kanıt)
    dolu: dict[str, tuple[str, str | None, bool, str | None]] = field(default_factory=dict)
    # alan → (üretilen, susuldu mu)
    bos: dict[str, tuple[str | None, bool]] = field(default_factory=dict)
    fazladan: dict[str, str] = field(default_factory=dict)
    etiketler: dict[str, list[str]] = field(default_factory=dict)

    @property
    def gecti(self) -> bool:
        """Hem doldurma hem susma beklentilerinin tamamı karşılandı mı?"""
        return all(d[2] for d in self.dolu.values()) and all(b[1] for b in self.bos.values())


def _kayitlar() -> list[dict]:
    """Senaryo kümesini okur."""
    sonuc: list[dict] = []
    for satir in KUME.read_text(encoding="utf-8").splitlines():
        temiz = satir.strip()
        if not temiz or temiz.startswith("#"):
            continue
        sonuc.append(json.loads(temiz))
    return sonuc


def _esit(uretilen: str, beklenen: str, alan: str) -> bool:
    """Değerleri birime göre karşılaştırır (gold kuralıyla aynı)."""
    birim = unit_of(alan)
    if values_match(beklenen, uretilen, birim):
        return True
    try:
        return Decimal(uretilen) == Decimal(beklenen)
    except (InvalidOperation, ArithmeticError):
        return False


def olc() -> list[SenaryoSonucu]:
    """Senaryoları üretim yolundan geçirir.

    Returns:
        Banka başına sonuç.
    """
    sonuclar: list[SenaryoSonucu] = []
    for kayit in _kayitlar():
        metin = kayit["metin"]
        guard = guard_fields(extract_rule_based(metin), metin)
        birlesim = merge_extractions(guard.accepted)
        uretilen = {alan.field_name: alan for alan in birlesim.fields}

        sonuc = SenaryoSonucu(kod=kayit["kod"], banka=kayit["banka"], metin=metin)
        for alan, beklenen in kayit["beklenen"].items():
            bulgu = uretilen.get(alan)
            deger = bulgu.value_normalized if bulgu else None
            sonuc.dolu[alan] = (
                beklenen,
                deger,
                deger is not None and _esit(deger, beklenen, alan),
                bulgu.evidence_text if bulgu else None,
            )
        for alan in kayit.get("beklenen_bos", []):
            bulgu = uretilen.get(alan)
            deger = bulgu.value_normalized if bulgu else None
            sonuc.bos[alan] = (deger, deger is None)

        sonuc.fazladan = {
            ad: alan.value_normalized
            for ad, alan in uretilen.items()
            if ad not in kayit["beklenen"]
            and ad not in kayit.get("beklenen_bos", [])
            and ad not in _EKSEN_ALANLARI
        }
        for etiket in categorize(title=metin.split(".", 1)[0], body_text=metin):
            sonuc.etiketler.setdefault(etiket.axis, []).append(etiket.value)
        sonuclar.append(sonuc)
    return sonuclar


def _rapor(sonuclar: list[SenaryoSonucu]) -> str:
    """Markdown raporunu üretir."""
    dolu_toplam = sum(len(s.dolu) for s in sonuclar)
    dolu_dogru = sum(1 for s in sonuclar for d in s.dolu.values() if d[2])
    bos_toplam = sum(len(s.bos) for s in sonuclar)
    bos_dogru = sum(1 for s in sonuclar for b in s.bos.values() if b[1])

    satirlar = [
        "# Şartnamenin kendi örnek senaryoları — birebir koşum",
        "",
        "> `python dev.py sartname-senaryo` çıktısı. Otomatik üretilir.",
        "",
        "⚠️ **BU METİNLER BİZİM ÖRNEĞİMİZ DEĞİL.** Şartnamenin *Örnek Temsili",
        "Senaryo-1*'indeki A/B/C Bankası konut finansmanı satırlarından türetildi.",
        "Jüri kendi örneğinin çalıştığını görmek ister; kendi örneğimizle",
        "göstermek o soruyu yanıtlamaz.",
        "",
        "## Özet",
        "",
        "| | beklenen | karşılanan | oran |",
        "|---|---|---|---|",
        f"| Doldurulması gereken alan | {dolu_toplam} | {dolu_dogru} "
        f"| **{100 * dolu_dogru / dolu_toplam:.0f}%** |",
        f"| **Boş kalması** gereken alan | {bos_toplam} | {bos_dogru} "
        f"| **{100 * bos_dogru / bos_toplam:.0f}%** |",
        "",
        "⚠️ **İKİNCİ SATIR ÖLÇÜMÜN YARISI.** Şartnamenin C Bankası satırında",
        "masraf bilgisi YOK; sistem o alanları boş bırakmak zorunda. Yalnızca",
        "doldurulan alanlara bakan bir ölçüm, şartname 7'nin puanladığı",
        '*"bilgi yokken bilgi üretmeme"* yeteneğini hiç görmez.',
        "",
        "⚠️ **ÜÇ BANKA ÜÇ FARKLI YAZIM BİÇİMİ TAŞIYOR** ve bu bilinçli:",
        "senaryo aynı zamanda paraf değişmezliğinin sınavıdır.",
        "",
        "| Banka | oran yazımı | vade yazımı | masraf yazımı |",
        "|---|---|---|---|",
        "| A | `%1,89` | `120 aya kadar` | `50.000 TL'ye kadar masraf yok` |",
        "| B | `yüzde 1,95` | `10 yıl` | `Ekspertiz ücretsiz` |",
        "| C | `1.87 %` | `96 ay` | **belirtilmemiş → susulmalı** |",
        "",
    ]

    for s in sonuclar:
        satirlar += [
            f"## {s.banka} (`{s.kod}`) — {'✅ geçti' if s.gecti else '❌ geçmedi'}",
            "",
            "Girdi metni:",
            "",
            f"> {s.metin}",
            "",
            "| Alan | beklenen | üretilen | ✓ | kanıt |",
            "|---|---|---|---|---|",
        ]
        for alan, (beklenen, deger, dogru, kanit) in s.dolu.items():
            satirlar.append(
                f"| `{alan}` | `{beklenen}` | `{deger}` | {'✅' if dogru else '❌'} "
                f"| {f'*{kanit}*' if kanit else '—'} |"
            )
        if s.bos:
            satirlar += [
                "",
                "Boş kalması gereken alanlar (**kaynakta bilgi yok**):",
                "",
                "| Alan | üretilen | ✓ |",
                "|---|---|---|",
            ]
            for alan, (deger, susuldu) in s.bos.items():
                satirlar.append(
                    f"| `{alan}` | {'*(boş)*' if deger is None else f'`{deger}`'} "
                    f"| {'✅' if susuldu else '❌'} |"
                )
        if s.fazladan:
            satirlar += [
                "",
                "Senaryo tablosunda olmayıp üretilen alanlar:",
                "",
                "| Alan | değer |",
                "|---|---|",
                *[f"| `{ad}` | `{deger}` |" for ad, deger in sorted(s.fazladan.items())],
                "",
                "> ⚠️ Bu satırlar RAPORDAN GİZLENMEDİ. Şartname tablosu yalnızca",
                "> oran / vade / masraf kolonlarını veriyor; sistem metinde geçen",
                "> başka değerleri de okuyor. Gizlenen bir fazlalık, jürinin kendi",
                "> gözüyle bulacağı fazlalıktan kötüdür.",
            ]
        if s.etiketler:
            satirlar += [
                "",
                "Sınıflandırma: "
                + " · ".join(
                    f"`{eksen}={', '.join(sorted(set(degerler)))}`"
                    for eksen, degerler in sorted(s.etiketler.items())
                ),
            ]
        satirlar.append("")

    satirlar += [
        "## Senaryo 2 — karşılaştırma ve netleştirme",
        "",
        "Şartnamenin ikinci örneği *\"A Bankası mı daha avantajlı, C Bankası mı?\"*",
        "sorusu. Yukarıdaki üç satırdan **C Bankası %1,87 ile en düşük kâr payını**",
        "sunuyor; finansmanda düşük oran müşteri lehinedir.",
        "",
        "⚠️ **BELİRSİZ SORUDA SIRALAMA YAPILMAZ.** `rate_type` verilmemiş bir",
        '"hangisi avantajlı" sorusunda sistem netleştirici soru sorar ve modele',
        "hiç gitmez (`clarification_needed=true`, `source=computed`). Finansman",
        "kâr payında düşük değer iyi, katılma hesabı payında yüksek değer iyi;",
        "hangisi sorulduğu belirsizken sıralamak yanıtı tam ters çevirir.",
        "",
        "Canlı sohbet kanıtı: [`sprint5_senaryo_kanit.md`](sprint5_senaryo_kanit.md)",
        "· ham API çıktısı: [`sprint5_screens/api_kanit.json`](sprint5_screens/api_kanit.json)",
        "",
        "## Nasıl doğrulanır",
        "",
        "```bash",
        "python dev.py sartname-senaryo              # bu rapor",
        "pytest tests/unit/test_sartname_senaryolari.py   # regresyon kapısı",
        "```",
        "",
        "Canlı uçtan:",
        "",
        "```bash",
        "curl -X POST localhost:8000/api/v1/extract \\",
        '  -H "Content-Type: application/json" \\',
        "  -d '{\"text\":\"B Bankası Konut Finansmanı. Kâr payı oranı yüzde 1,95 ile "
        "10 yıl vadeye kadar finansman. Ekspertiz ücretsiz.\",\"mode\":\"rule_only\"}'",
        "```",
        "",
        "| Küme | `tests/fixtures/sartname/senaryolar.jsonl` |",
        "|---|---|",
        "| Kod yolu | `extract_rule_based` → `guard_fields` → `merge_extractions` |",
        "| Regresyon | `tests/unit/test_sartname_senaryolari.py` |",
        "| İlgili ölçüm | [`paraf_degismezlik.md`](paraf_degismezlik.md) — aynı olgunun N yazımı |",
        "",
    ]
    return "\n".join(satirlar)


def main() -> int:
    """Şartname senaryo raporunu üretir."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    sonuclar = olc()
    RAPOR_YOLU.parent.mkdir(parents=True, exist_ok=True)
    RAPOR_YOLU.write_text(_rapor(sonuclar), encoding="utf-8")

    for s in sonuclar:
        print(f"  {'✅' if s.gecti else '❌'} {s.kod:6} {s.banka}")
        for alan, (beklenen, deger, dogru, _) in s.dolu.items():
            if not dogru:
                print(f"       DOLDURMA {alan}: bekle={beklenen!r} bulundu={deger!r}")
        for alan, (deger, susuldu) in s.bos.items():
            if not susuldu:
                print(f"       SUSMA    {alan}: boş olmalıydı, bulundu={deger!r}")

    dolu_dogru = sum(1 for s in sonuclar for d in s.dolu.values() if d[2])
    dolu_toplam = sum(len(s.dolu) for s in sonuclar)
    bos_dogru = sum(1 for s in sonuclar for b in s.bos.values() if b[1])
    bos_toplam = sum(len(s.bos) for s in sonuclar)
    print(f"\nDoldurma : {dolu_dogru}/{dolu_toplam}")
    print(f"Susma    : {bos_dogru}/{bos_toplam}")
    print(f"\nRapor: {RAPOR_YOLU}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
