"""Kampanya dönemini SERBEST METİNDEN çıkarır (yapısal tarih alanı yoksa).

## Neden bu dosya var

Bankaların bir kısmı kampanya tarihini ayrı bir HTML alanında vermiyor;
tarih yalnızca koşul cümlesinin içinde, düz metin olarak geçiyor. Scraper
yapısal alanı bulamayınca `date_precision="unknown"` yazıyordu.

Ölçüldü — Türkiye Finans'ın 22 kampanyasının TAMAMI `unknown` kayıtlıydı,
ama 18'inin metninde tarih AÇIKÇA yazıyor:

    "Kampanya 25 Mayıs - 31 Aralık 2026 tarihleri arasında geçerlidir."
    "Kampanya 31.12.2026 tarihine kadar geçerlidir."

Bu, "veri yok" değil "veri okunmadı" durumudur; ikisi ayrı şeydir ve
karıştırılması veri setini olduğundan fakir gösterir.

## Neden gövdedeki İLK tarih alınmaz

Metindeki her tarih kampanya dönemi değildir. Canlı veride ölçülen tuzaklar:

    "5 Ağustos 2023 tarihi itibarıyla ... müşterisi olan"   → uygunluk koşulu
    "Bonusların kullanım süresi 15 gündür"                   → süre, tarih değil
    "SAMSUNG boşluk TCKN boşluk Doğum Tarihi yazıp 3855'e"   → SMS örneği
    "* 15-08-2026 09:29:58 tarihli kur bilgileridir."        → kur afişi
    "1 Haziran Dünya Bankacılar Günü'ne Özel Avantajlar"     → başlıktaki gün adı

Bu yüzden YAKINLIK kuralı uygulanır (§5.2): tarih, ancak aynı satırda bir
DÖNEM İFADESİ ile birlikte geçiyorsa kampanya dönemi sayılır. `PERIOD_MARKERS`
bilinçli olarak dardır — `"tarihi itibarıyla"` ve yalın `"tarihinde"` listede
YOKTUR; ikisi de dönem değil koşul bildirir.

## Bilgi yoksa bilgi üretilmez

Geçersiz tarih (`31.04.26`), yılsız aralık (`1-30 Nisan`) veya işaretçisiz
tarih bulunduğunda `unknown` döner ve alanlar `NULL` kalır. Şartname 7'nin
"eksik bilgi karşısında doğru sonuç üretme" maddesi budur: eksik veriyi
tamamlamak değil, eksik olduğunu doğru bildirmek.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Final

from app.core.normalization.date_tr import parse_date_range_tr
from app.core.normalization.text import ascii_fold_tr, lower_tr

# Tarihi "kampanya dönemi" yapan ifadeler. ASCII'ye katlanmış biçimde tutulur.
#
# ⚠️ Bu liste DAR tutulmalıdır. Yalın "tarihinde" veya "tarihi itibarıyla"
# eklenirse uygunluk koşulundaki tarih kampanya dönemi sanılır:
# "5 Ağustos 2023 tarihi itibarıyla müşterisi olan" (Türkiye Finans #438).
PERIOD_MARKERS: Final[tuple[str, ...]] = (
    "tarihleri arasinda",
    "tarihleri arasi",
    "tarih araliginda",
    "tarihine kadar",
    "tarihinde sona er",
    "tarihine kadar gecerli",
    "kampanya donemi",
    "kampanya tarihleri",
    "kampanya baslangic",
    "baslangic ve bitis",
    "son gun",
    "sona erecektir",
    "devam edecektir",
    "gecerlilik suresi",
)

# Kesinlik sıralaması — daha kesin bulgu daha zayıfının yerine geçer.
_PRECISION_RANK: Final[dict[str, int]] = {
    "unknown": 0,
    "partial": 1,
    "inferred": 2,
    "exact": 3,
}


@dataclass(frozen=True)
class CampaignPeriod:
    """Bulunan kampanya dönemi ve onu taşıyan satırın konumu.

    Ofsetler, çıkarım kaydının `evidence_text` alanının kaynaktan BİREBİR
    dilimlenebilmesi için gereklidir (KAPI A4 ofset doğrulaması).
    """

    start: date | None
    end: date | None
    precision: str
    evidence_start: int = -1
    evidence_end: int = -1

    @property
    def bulundu(self) -> bool:
        """Güvenilir bir dönem bulundu mu?"""
        return self.precision != "unknown"


def _has_marker(line: str) -> bool:
    """Satır bir kampanya dönemi ifadesi taşıyor mu?

    Args:
        line: Sınanacak satır.

    Returns:
        Dönem ifadesi varsa True.
    """
    folded = ascii_fold_tr(lower_tr(line))
    return any(marker in folded for marker in PERIOD_MARKERS)


def find_campaign_period(text: str | None) -> tuple[date | None, date | None, str]:
    """Metindeki dönem cümlesinden kampanya tarihlerini çıkarır.

    Yalnızca dönem ifadesi taşıyan satırlar değerlendirilir; satırlar
    tek tek ayrıştırılır ve EN KESİN bulgu döndürülür. Aynı kesinlikte
    birden çok bulgu varsa ilki kazanır.

    Örnek — Türkiye Finans #448'de üç aday satır var:

        "Kampanyadan 23 Şubat - 22 Mart 2026 tarihleri arasında ..."  → exact
        "Kampanya 22 Mart 2026 tarihine kadar devam edecektir."       → partial
        "... Bonuslar 1 Nisan 2026 tarihinde yüklenecektir."          → aday değil

    Sonuç, birincisinden gelen tam aralıktır.

    Args:
        text: Kampanyanın temiz metni.

    Returns:
        (başlangıç, bitiş, kesinlik) üçlüsü. Güvenilir bulgu yoksa
        `(None, None, "unknown")` — tarih UYDURULMAZ.
    """
    donem = find_campaign_period_detailed(text)
    return donem.start, donem.end, donem.precision


def find_campaign_period_detailed(text: str | None) -> CampaignPeriod:
    """`find_campaign_period` ile aynıdır, ayrıca kanıt ofsetlerini döndürür.

    Args:
        text: Kampanyanın temiz metni.

    Returns:
        Bulunan dönem ve onu taşıyan satırın karakter aralığı.
    """
    if not text:
        return CampaignPeriod(None, None, "unknown")

    en_iyi = CampaignPeriod(None, None, "unknown")
    en_iyi_puan = 0
    imlec = 0

    for line in text.split("\n"):
        bas = imlec
        imlec += len(line) + 1

        if not _has_marker(line):
            continue

        start, end, precision = parse_date_range_tr(line)
        if start is None and end is None:
            continue

        puan = _PRECISION_RANK.get(precision, 0)
        if puan > en_iyi_puan:
            en_iyi = CampaignPeriod(start, end, precision, bas, bas + len(line))
            en_iyi_puan = puan
            if puan == _PRECISION_RANK["exact"]:
                break

    return en_iyi
