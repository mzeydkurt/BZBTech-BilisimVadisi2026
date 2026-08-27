"""Paraf değişmezlik ölçümü (E2) — şartname K4'ün ilk alt maddesi.

AĞA ÇIKMAZ · VERİTABANI GEREKTİRMEZ.

⚠️ NE ÖLÇÜLDÜĞÜ DOĞRULUK DEĞİL DEĞİŞMEZLİKTİR. Şartname K4'ün ilk alt maddesi
*"farklı ifade biçimlerini doğru yorumlayabilmesi"* diyor. F1 bunu DOLAYLI
ölçer: gold set'te her olgu tek bir yazımla geçtiği için, sistem o yazımı
çözdüğünde diğer yazımları çözüp çözemediği hiç görünmez.

Bu betik aynı olguyu N biçimde yazıp çıktının **değişmediğini** ölçer.
Kümedeki her grup bir olgudur; grubun içindeki varyantlar arasında anlam
farkı YOKTUR. Bir grubun 6 varyantından 5'i aynı değeri veriyorsa sistem o
olguda %83 değişmezdir.

⚠️ ÜRETİM YOLU KULLANILIR, kopyası değil. `extract_rule_based` →
`guard_fields` → `merge_extractions` sırası `POST /api/v1/extract` ucundaki
sıranın aynısıdır. Ayrı bir kod yolu yazılırsa ölçüm gerçek davranışı değil
ölçüm kodunu ölçer.

⚠️ LLM KATMANI ÖLÇÜME GİRMEZ. Değişmezlik bir DETERMİNİZM iddiasıdır; model
çağrısı eklenince aynı girdi iki koşuda farklı çıkabilir ve "değişmez" demek
anlamsızlaşır. Kural katmanı bu iddiayı taşıyabilir, model katmanı taşıyamaz.

Çalıştırma:
    python dev.py paraf-degismezlik
    python -m scripts.paraphrase_invariance --json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app.ai.evaluation import values_match
from app.ai.extraction import extract_rule_based
from app.ai.validation import guard_fields, merge_extractions
from app.processing.categorizer import categorize

BACKEND = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND.parent
ALAN_KUMESI = BACKEND / "tests" / "fixtures" / "paraphrase" / "paraf_degismezlik.jsonl"
ETIKET_KUMESI = BACKEND / "tests" / "fixtures" / "paraphrase" / "etiket_degismezlik.jsonl"
RAPOR_YOLU = REPO_ROOT / "docs" / "paraf_degismezlik.md"
JSON_YOLU = REPO_ROOT / "data" / "eval" / "paraphrase.json"


@dataclass(frozen=True)
class VaryantSonucu:
    """Tek bir yazımın çözümlenme sonucu."""

    metin: str
    uretilen: str | None
    dogru: bool
    # Bilinen ve gerekçesi yazılmış boşluk mu?
    beklenen_basarisiz: str | None = None


@dataclass
class GrupSonucu:
    """Bir olgunun tüm yazımlarının sonucu."""

    grup: str
    hedef: str
    beklenen: str
    kaynak: str
    varyantlar: list[VaryantSonucu] = field(default_factory=list)

    @property
    def toplam(self) -> int:
        """Gruptaki varyant sayısı."""
        return len(self.varyantlar)

    @property
    def cozulen(self) -> int:
        """Beklenen değeri üreten varyant sayısı."""
        return sum(1 for v in self.varyantlar if v.dogru)

    @property
    def bilinen_bosluk(self) -> int:
        """Gerekçesi yazılmış, bilinçli kapatılmamış varyant sayısı."""
        return sum(1 for v in self.varyantlar if v.beklenen_basarisiz and not v.dogru)

    @property
    def surpriz_hata(self) -> int:
        """Gerekçesi OLMAYAN başarısızlık — gerçek boşluk budur."""
        return sum(1 for v in self.varyantlar if not v.dogru and not v.beklenen_basarisiz)

    @property
    def oran(self) -> float:
        """Grubun değişmezlik oranı."""
        return self.cozulen / self.toplam if self.toplam else 0.0


def _satirlar(yol: Path) -> list[dict]:
    """JSONL kümesini okur; `#` ile başlayan satırlar yorumdur.

    Args:
        yol: Küme dosyası.

    Returns:
        Kayıt listesi.
    """
    kayitlar: list[dict] = []
    for satir in yol.read_text(encoding="utf-8").splitlines():
        temiz = satir.strip()
        if not temiz or temiz.startswith("#"):
            continue
        kayitlar.append(json.loads(temiz))
    return kayitlar


def _alan_degeri(metin: str, alan: str) -> str | None:
    """Üretim yolunu çalıştırıp istenen alanın değerini döndürür.

    ⚠️ `guard_fields` ve `merge_extractions` ATLANMAZ. Guard'ın reddettiği ya
    da merger'ın elediği bir değer kullanıcıya sunulmuyor; ölçüme sokulursa
    sistem sunmadığı bir başarıyla kredilendirilmiş olur.

    Args:
        metin: Tek varyant metni.
        alan: Beklenen alan adı.

    Returns:
        Normalize edilmiş değer; alan üretilmediyse None.
    """
    guard = guard_fields(extract_rule_based(metin), metin)
    birlesim = merge_extractions(guard.accepted)
    for bulgu in birlesim.fields:
        if bulgu.field_name == alan:
            return bulgu.value_normalized
    return None


def _sayisal_esit(uretilen: str, beklenen: str, birim: str) -> bool:
    """Sayısal değerleri biçimden bağımsız karşılaştırır.

    `values_match` gold karşılaştırmasının kuralını taşır (oranda ±0,01
    tolerans, tutarda tam eşleşme) ama `120` ile `120.0` gibi biçim farkını
    görmez; `Decimal` üzerinden ikinci bir deneme yapılır.
    """
    if values_match(beklenen, uretilen, birim):
        return True
    try:
        return Decimal(uretilen) == Decimal(beklenen)
    except (InvalidOperation, ArithmeticError):
        return False


def _alan_gruplari() -> list[GrupSonucu]:
    """Alan çıkarımı değişmezliğini ölçer."""
    sonuclar: list[GrupSonucu] = []
    for kayit in _satirlar(ALAN_KUMESI):
        birim = kayit.get("birim", "enum")
        bilinenler: dict[str, str] = kayit.get("beklenen_basarisiz", {})
        grup = GrupSonucu(
            grup=kayit["grup"],
            hedef=kayit["alan"],
            beklenen=kayit["beklenen"],
            kaynak=kayit.get("kaynak", ""),
        )
        for metin in [*kayit["varyantlar"], *bilinenler]:
            uretilen = _alan_degeri(metin, kayit["alan"])
            dogru = uretilen is not None and _sayisal_esit(uretilen, kayit["beklenen"], birim)
            grup.varyantlar.append(
                VaryantSonucu(
                    metin=metin,
                    uretilen=uretilen,
                    dogru=dogru,
                    beklenen_basarisiz=bilinenler.get(metin),
                )
            )
        sonuclar.append(grup)
    return sonuclar


def _etiket_gruplari() -> list[GrupSonucu]:
    """Sınıflandırma değişmezliğini ölçer."""
    sonuclar: list[GrupSonucu] = []
    for kayit in _satirlar(ETIKET_KUMESI):
        bilinenler: dict[str, str] = kayit.get("beklenen_basarisiz", {})
        grup = GrupSonucu(
            grup=kayit["grup"],
            hedef=kayit["eksen"],
            beklenen=kayit["beklenen"],
            kaynak=kayit.get("kaynak", ""),
        )
        for metin in [*kayit["varyantlar"], *bilinenler]:
            uretilen = [
                etiket.value
                for etiket in categorize(title=metin, body_text=metin)
                if etiket.axis == kayit["eksen"]
            ]
            grup.varyantlar.append(
                VaryantSonucu(
                    metin=metin,
                    uretilen=", ".join(uretilen) or None,
                    dogru=kayit["beklenen"] in uretilen,
                    beklenen_basarisiz=bilinenler.get(metin),
                )
            )
        sonuclar.append(grup)
    return sonuclar


def _ozet(gruplar: list[GrupSonucu]) -> tuple[int, int, int, int]:
    """(toplam varyant, çözülen, bilinen boşluk, sürpriz hata)."""
    return (
        sum(g.toplam for g in gruplar),
        sum(g.cozulen for g in gruplar),
        sum(g.bilinen_bosluk for g in gruplar),
        sum(g.surpriz_hata for g in gruplar),
    )


def _grup_tablosu(gruplar: list[GrupSonucu], *, hedef_basligi: str) -> list[str]:
    """Grup bazında değişmezlik tablosunu üretir."""
    satirlar = [
        f"| Olgu | {hedef_basligi} | beklenen | varyant | çözülen | değişmezlik |",
        "|---|---|---|---|---|---|",
    ]
    for g in sorted(gruplar, key=lambda x: (x.oran, x.grup)):
        isaret = "" if g.cozulen == g.toplam else " ⚠️"
        satirlar.append(
            f"| `{g.grup}` | `{g.hedef}` | `{g.beklenen}` | {g.toplam} "
            f"| {g.cozulen} | **{100 * g.oran:.0f}%**{isaret} |"
        )
    return satirlar


def _basarisizlik_dokumu(gruplar: list[GrupSonucu]) -> list[str]:
    """Çözülmeyen varyantları gerekçesiyle listeler."""
    satirlar: list[str] = []
    for g in gruplar:
        for v in g.varyantlar:
            if v.dogru:
                continue
            tur = "bilinen boşluk" if v.beklenen_basarisiz else "**sürpriz**"
            satirlar.append(f"- `{g.grup}` · {tur} · yazım: *{v.metin}*")
            satirlar.append(f"  - üretilen: `{v.uretilen}` · beklenen: `{g.beklenen}`")
            if v.beklenen_basarisiz:
                satirlar.append(f"  - gerekçe: {v.beklenen_basarisiz}")
    return satirlar or ["Çözülmeyen varyant yok."]


def _rapor(alan: list[GrupSonucu], etiket: list[GrupSonucu]) -> str:
    """Markdown raporunu üretir."""
    a_top, a_coz, a_bil, a_sur = _ozet(alan)
    e_top, e_coz, e_bil, e_sur = _ozet(etiket)
    top, coz = a_top + e_top, a_coz + e_coz
    tam_grup = sum(1 for g in [*alan, *etiket] if g.cozulen == g.toplam)

    return "\n".join(
        [
            "# Paraf değişmezliği — aynı olgu, N yazım",
            "",
            "> `python dev.py paraf-degismezlik` çıktısı. Otomatik üretilir.",
            "",
            "⚠️ **BU ÖLÇÜM DOĞRULUK DEĞİL DEĞİŞMEZLİK ÖLÇER.** Şartname K4'ün ilk",
            "alt maddesi *\"farklı ifade biçimlerini doğru yorumlayabilmesi\"* diyor.",
            "F1 bunu ancak dolaylı gösterir: gold set'te her olgu TEK bir yazımla",
            "geçtiği için, sistemin o olgunun diğer yazımlarını çözüp çözemediği",
            "hiç görünmez. Burada aynı olgu N biçimde yazılıyor ve çıktının",
            "**değişmediği** ölçülüyor.",
            "",
            "## Özet",
            "",
            "| | varyant | çözülen | değişmezlik |",
            "|---|---|---|---|",
            f"| Alan çıkarımı | {a_top} | {a_coz} | **{100 * a_coz / a_top:.1f}%** |",
            f"| Sınıflandırma | {e_top} | {e_coz} | **{100 * e_coz / e_top:.1f}%** |",
            f"| **Toplam** | **{top}** | **{coz}** | **{100 * coz / top:.1f}%** |",
            "",
            f"{len(alan) + len(etiket)} olgu · **{tam_grup}** olguda tüm yazımlar aynı "
            "değeri üretti.",
            "",
            f"Çözülmeyen {top - coz} varyanttan **{a_bil + e_bil}** tanesi gerekçesi",
            f"yazılmış bilinen boşluk, **{a_sur + e_sur}** tanesi sürpriz.",
            "",
            "> ⚠️ Bilinen boşluk kümeden ÇIKARILMADI. Kapatılmamış bir varyantı",
            "> kümeden silmek oranı güzelleştirmek olurdu; kümede kalır, ayrı",
            "> sayılır ve neden kapatılmadığı yazılır.",
            "",
            "## Alan çıkarımı — olgu bazında",
            "",
            *_grup_tablosu(alan, hedef_basligi="alan"),
            "",
            "## Sınıflandırma — olgu bazında",
            "",
            *_grup_tablosu(etiket, hedef_basligi="eksen"),
            "",
            "## Çözülmeyen yazımlar",
            "",
            *_basarisizlik_dokumu([*alan, *etiket]),
            "",
            "## Ölçüm nasıl yapılıyor",
            "",
            "| | |",
            "|---|---|",
            "| Küme | `tests/fixtures/paraphrase/paraf_degismezlik.jsonl` (alan) · "
            "`etiket_degismezlik.jsonl` (etiket) |",
            "| Kod yolu | `extract_rule_based` → `guard_fields` → `merge_extractions` "
            "— `POST /api/v1/extract` ucundaki sıranın aynısı |",
            "| Sınıflandırma | `categorize()` — dört eksen, veritabanı gerektirmez |",
            "| LLM | **ölçüme girmez** (aşağıdaki gerekçe) |",
            "| Regresyon koruması | `tests/unit/test_paraf_degismezlik.py` |",
            "",
            "⚠️ **LLM KATMANI BİLEREK DIŞARIDA.** Değişmezlik bir DETERMİNİZM",
            "iddiasıdır: aynı girdi her koşuda aynı çıktıyı vermeli. Model çağrısı",
            "eklenince bu iddia taşınamaz hâle gelir — aynı metin iki koşuda farklı",
            "çözülebilir. Kural katmanı bu iddiayı taşıyabilir; ölçüm bu yüzden",
            "üretim kipiyle (`rule_only`, bkz. `docs/ablation.md`) tam örtüşür.",
            "",
            "⚠️ **VARYANTLAR GÖVDEDEN TÜRETİLDİ.** Her olgunun `kaynak` alanı",
            "ifadenin 482 kampanyalık gövdede kaç kez geçtiğini ya da hangi bankanın",
            "yazımından alındığını söyler. Uydurulmuş varyantla ölçülen değişmezlik",
            "gerçek metinlerde geçerli olmayabilir.",
            "",
            "## Bu ölçümün kapattığı boşluklar",
            "",
            "Küme ilk kez koşulduğunda **60/70** çıktı. Bulunan on boşluğun tamamı",
            "gövdede gerçekten geçen yazımlardı — yani ölçüm yapılmadan önce sistem",
            "bu metinleri sessizce kaçırıyordu:",
            "",
            "| Boşluk | Gövdedeki geçiş | Düzeltme |",
            "|---|---|---|",
            "| `yüzde 2,05` sözcük biçimi | 104 | `_YUZDE_SAYI` |",
            "| `vade farkı yok` | — | `ZERO_RATE` |",
            "| `3 milyon TL'ye kadar` çarpan sözcüğü | 262 | `_TUTAR` |",
            "| `tahsis ücreti yansıtılmayacaktır` | 85 | `_OLUMSUZ` |",
            "| `ücret veya komisyon talep edilmemektedir` | 15 | `_OLUMSUZ` |",
            "| `kart ücreti yok` | 15 | `_UCRET_ADI` |",
            "| `sıfır dosya masrafı` | sentetik | `NO_FEE` |",
            "| `%30’a varan indirim` (tipografik kesme U+2019) | 1 | `DISCOUNT_PCT` |",
            "| `%20 oranında indirim` | sentetik | `DISCOUNT_PCT` |",
            "| `5.000 TL'den başlayan` | — | `MIN_SPEND` |",
            "",
            "⚠️ Bu düzeltmeler F1'i DÜŞÜRMEDİ; gold set üzerinde ölçüldü:",
            "`rule_only` mikro F1 **0,8320 → 0,8328**, `max_spend_try` F1",
            "**0,67 → 0,71**, uydurma oranı **0,058 → 0,054**. Kalıp genişletmenin",
            "kesinliği düşürmediğinin kanıtı ölçümün kendisidir — genişletme",
            "sırasında iki yanlış pozitif kaynağı da bulunup kapatıldı",
            "(`_kademe_sinirlari` ve `_UCRET_ADI` beyaz listesi).",
            "",
        ]
    )


def main() -> int:
    """Paraf değişmezlik raporunu üretir.

    Returns:
        Çıkış kodu; sürpriz başarısızlık varsa 0 (rapor yine yazılır) — kapı
        görevini `tests/unit/test_paraf_degismezlik.py` üstlenir.
    """
    ayristirici = argparse.ArgumentParser(description="Paraf değişmezlik ölçümü")
    ayristirici.add_argument("--json", action="store_true", help="Yalnızca JSON özet yaz")
    argumanlar = ayristirici.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    alan = _alan_gruplari()
    etiket = _etiket_gruplari()
    a_top, a_coz, a_bil, a_sur = _ozet(alan)
    e_top, e_coz, e_bil, e_sur = _ozet(etiket)

    ozet = {
        "field_variants": a_top,
        "field_resolved": a_coz,
        "label_variants": e_top,
        "label_resolved": e_coz,
        "total_variants": a_top + e_top,
        "total_resolved": a_coz + e_coz,
        "invariance": round((a_coz + e_coz) / (a_top + e_top), 4),
        "known_gaps": a_bil + e_bil,
        "surprises": a_sur + e_sur,
        "groups": [
            {
                "group": g.grup,
                "target": g.hedef,
                "expected": g.beklenen,
                "variants": g.toplam,
                "resolved": g.cozulen,
            }
            for g in [*alan, *etiket]
        ],
    }

    if argumanlar.json:
        print(json.dumps(ozet, ensure_ascii=False, indent=2))
        return 0

    RAPOR_YOLU.parent.mkdir(parents=True, exist_ok=True)
    RAPOR_YOLU.write_text(_rapor(alan, etiket), encoding="utf-8")
    JSON_YOLU.parent.mkdir(parents=True, exist_ok=True)
    JSON_YOLU.write_text(json.dumps(ozet, ensure_ascii=False, indent=2), encoding="utf-8")

    for g in [*alan, *etiket]:
        if g.cozulen == g.toplam:
            continue
        print(f"  ⚠️ {g.grup:22} {g.cozulen}/{g.toplam}")
        for v in g.varyantlar:
            if not v.dogru:
                tur = "bilinen" if v.beklenen_basarisiz else "SÜRPRİZ"
                print(f"       [{tur}] {v.metin!r} -> {v.uretilen!r}")

    print(f"\nAlan   : {a_coz}/{a_top}")
    print(f"Etiket : {e_coz}/{e_top}")
    print(f"TOPLAM : {a_coz + e_coz}/{a_top + e_top}  ({100 * ozet['invariance']:.1f}%)")
    print(f"         bilinen boşluk {a_bil + e_bil} · sürpriz {a_sur + e_sur}")
    print(f"\nRapor: {RAPOR_YOLU}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
