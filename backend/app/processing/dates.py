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

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date
from enum import StrEnum
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
    # Aşağıdakiler canlı arşivde ölçülerek eklendi; bunlar olmadan 467
    # tarihli kampanyanın 97'si okunamıyordu.
    "gecerlilik tarihi",  # Vakıf
    "bitis tarihi",  # Dünya
    "baslangic tarihi",
    "arasinda gecerli",  # Ziraat
    "kadar gecerli",  # T.O.M.
    # ⚠️ ÇOĞUL "tarihlerinde" aralık bildirir; TEKİL "tarihinde" koşul bildirir
    # ve listeye GİRMEZ.
    "tarihlerinde",
)

# ⚠️ Yayın/eklenme tarihi kampanya başlangıcı DEĞİLDİR: banka kampanyayı
# başladıktan sonra yayımlamış ya da başlamadan önce duyurmuş olabilir.
# Bu ifadeleri taşıyan satır, dönem işaretçisi de geçse aday sayılmaz.
PUBLICATION_MARKERS: Final[tuple[str, ...]] = (
    "yayin tarihi",
    "yayinlanma",
    "yayimlanma",
    "yayin baslangic",
    "guncelleme tarihi",
    "son guncelleme",
    "eklenme tarihi",
    "paylasim tarihi",
    "olusturulma",
    "duyuru tarihi",
)


def _is_publication_line(line: str) -> bool:
    """Satır bir yayın/güncelleme tarihi bildiriyor mu?

    Args:
        line: Sınanacak satır.

    Returns:
        Yayın tarihi ifadesi taşıyorsa True — bu satır dönem adayı olamaz.
    """
    folded = ascii_fold_tr(lower_tr(line))
    return any(marker in folded for marker in PUBLICATION_MARKERS)


# Satır içindeki tarih ifadesini yakalayan kalıp (sayısal ve Türkçe aylı).
_DATE_IN_LINE_RE: Final[re.Pattern[str]] = re.compile(
    r"\d{1,2}\s*[./-]\s*\d{1,2}\s*[./-]\s*\d{2,4}"
    r"|\d{1,2}\s+(?:ocak|şubat|subat|mart|nisan|mayıs|mayis|haziran|temmuz|"
    r"ağustos|agustos|eylül|eylul|ekim|kasım|kasim|aralık|aralik)"
    r"(?:\s+\d{4})?",
    re.IGNORECASE,
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


# Etiket kısadır. Bu sınır olmadan dönem ifadesi geçen uzun bir paragraf,
# kendinden sonraki her tarih satırına işaretçisini bağışlar.
LABEL_MAX_CHARS: Final[int] = 80


def _is_label(line: str) -> bool:
    """Satır, değeri bir alt satırda duran bir alan etiketi mi?

    Bankalar dönemi etiket/değer çifti olarak yayımlıyor ve HTML metne
    çevrilince ikisi ayrı satıra düşüyor ("Kampanya Dönemi" / "11-08-2026").
    İşaretçi yalnızca aynı satırda arandığında 467 tarihin 197'si kayboluyordu.

    Args:
        line: Sınanacak satır.

    Returns:
        Etiket sayılıyorsa True.
    """
    kirpik = line.strip()
    if not kirpik or len(kirpik) > LABEL_MAX_CHARS:
        return False
    if not _has_marker(kirpik) or _is_publication_line(kirpik):
        return False
    # Kendi tarihini taşıyan satır etiket değil, veridir; işaretçisini
    # devretmez (yoksa arka arkaya iki tarih satırı zincirleme kabul edilir).
    return not _DATE_IN_LINE_RE.search(kirpik)


# Etiketten sonra değer sayılacak en fazla satır. Ziraat dönemi üç satıra
# bölüyor (Kampanya Dönemi / 11-08-2026 / - / 31-08-2026) ve
# `parse_date_range_tr` tek tarihte `unknown` döndürdüğü için blok
# birleştirilmek zorunda.
VALUE_BLOCK_MAX_LINES: Final[int] = 5

# Değer bloğunda tarihler arasında durabilen ayraç satırları.
_SEPARATOR_LINE_RE: Final[re.Pattern[str]] = re.compile(
    r"^[\s\-–—/|:.]*$|^(?:ile|ve|arası|arasi|tarihleri)$",
    re.IGNORECASE,
)


def _value_block_span(
    text: str,
    lines: Sequence[tuple[str, int]],
    label_index: int,
) -> tuple[int, int] | None:
    """Etiket satırından sonraki değer bloğunun karakter aralığını verir.

    Blok yalnızca tarih taşıyan veya ayraç olan satırlardan oluşur; ilk başka
    satırda durur, böylece koşul paragrafları bloğa karışmaz.

    Args:
        text: Ofsetlerin ait olduğu metnin tamamı.
        lines: (satır, başlangıç ofseti) çiftleri.
        label_index: Etiket satırının `lines` içindeki sırası.

    Returns:
        Bloğun (başlangıç, bitiş) ofseti; blokta tarih yoksa None.
    """
    bas: int | None = None
    son: int | None = None
    alinan = 0

    for line, ofs in lines[label_index + 1 :]:
        kirpik = line.strip()
        if not kirpik:
            if bas is None:
                # Etiketle değer arasındaki boş satır bağı koparmaz.
                continue
            break
        if _is_publication_line(kirpik):
            break
        if not (_DATE_IN_LINE_RE.search(kirpik) or _SEPARATOR_LINE_RE.match(kirpik)):
            break
        if bas is None:
            bas = ofs
        son = ofs + len(line)
        alinan += 1
        if alinan >= VALUE_BLOCK_MAX_LINES:
            break

    if bas is None or son is None:
        return None
    if not _DATE_IN_LINE_RE.search(text[bas:son]):
        # Yalnızca ayraç toplandı; değer yok.
        return None
    return bas, son


def _value_block_span_before(
    text: str,
    lines: Sequence[tuple[str, int]],
    marker_index: int,
) -> tuple[int, int] | None:
    """İşaretçi satırından önceki değer bloğunun karakter aralığını verir.

    `_value_block_span`'ın aynası. Ziraat dönemi işaretçiden önce yazıyor
    ("Kampanya" / "09-02-2026" / "Tarihinde Sona Ermiştir."); 22 kampanya böyle.

    Args:
        text: Ofsetlerin ait olduğu metnin tamamı.
        lines: (satır, başlangıç ofseti) çiftleri.
        marker_index: İşaretçi satırının `lines` içindeki sırası.

    Returns:
        Bloğun (başlangıç, bitiş) ofseti; blokta tarih yoksa None.
    """
    bas: int | None = None
    son: int | None = None
    alinan = 0

    for line, ofs in reversed(lines[:marker_index]):
        kirpik = line.strip()
        if not kirpik:
            if son is None:
                continue
            break
        if _is_publication_line(kirpik):
            break
        if not (_DATE_IN_LINE_RE.search(kirpik) or _SEPARATOR_LINE_RE.match(kirpik)):
            break
        if son is None:
            son = ofs + len(line)
        bas = ofs
        alinan += 1
        if alinan >= VALUE_BLOCK_MAX_LINES:
            break

    if bas is None or son is None:
        return None
    if not _DATE_IN_LINE_RE.search(text[bas:son]):
        return None
    return bas, son


def _is_pure_date_line(line: str) -> bool:
    """Satır yalnızca bir tarih ifadesinden mi oluşuyor?

    Böyle bir satır tarih alanının değeridir; etiketi görsel rozette kalıp
    metne çevrilirken kaybolmuştur (T.O.M.: "05 Aralık - 15 Ocak 2025").
    ⚠️ Satırda tarih ve ayraç dışında hiçbir şey bulunmamalı; düz yazı içinde
    geçen tuzak tarihler böylece reddedilir.

    Args:
        line: Sınanacak satır.

    Returns:
        Satır salt tarih ifadesiyse True.
    """
    kirpik = line.strip()
    if not kirpik or not _DATE_IN_LINE_RE.search(kirpik):
        return False
    kalan = _DATE_IN_LINE_RE.sub("", kirpik)
    return bool(_SEPARATOR_LINE_RE.match(kalan.strip()))


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


def _date_span_in_line(line: str) -> tuple[int, int] | None:
    """Satır içindeki tarih ifadesinin dar aralığını döndürür.

    ⚠️ KANIT OLABİLDİĞİNCE DAR OLMALI. Kanıt satırın tamamı bırakılırsa,
    tek paragraflık bir girdide (ör. `POST /extract` ucuna yapıştırılan
    metin) "bu tarih nereden geldi?" sorusunun yanıtı 300 karakterlik bir
    paragraf olur ve açıklanabilirlik pratikte kaybolur.

    Satırda birden çok tarih varsa ilkinden sonuncuya kadarki aralık
    alınır: `1 Ağustos - 31 Ağustos 2026` tek bir ifadedir.

    Args:
        line: Dönem ifadesi taşıyan satır.

    Returns:
        Satır içindeki (başlangıç, bitiş) ya da tarih bulunamazsa None.
    """
    eslesmeler = list(_DATE_IN_LINE_RE.finditer(line))
    if not eslesmeler:
        return None
    return eslesmeler[0].start(), eslesmeler[-1].end()


def find_campaign_period_detailed(text: str | None) -> CampaignPeriod:
    """`find_campaign_period` ile aynıdır, ayrıca kanıt ofsetlerini döndürür.

    Args:
        text: Kampanyanın temiz metni.

    Returns:
        Bulunan dönem ve onu taşıyan tarih ifadesinin karakter aralığı.
    """
    if not text:
        return CampaignPeriod(None, None, "unknown")

    lines: list[tuple[str, int]] = []
    imlec = 0
    for line in text.split("\n"):
        lines.append((line, imlec))
        imlec += len(line) + 1

    en_iyi = CampaignPeriod(None, None, "unknown")
    en_iyi_puan = 0
    # Salt tarih satırları EN ZAYIF adaydır; işaretçili hiçbir bulgu yoksa
    # kullanılır. İşaretçili cümlenin yerine ASLA geçmez.
    yedek: CampaignPeriod | None = None

    for i, (line, bas) in enumerate(lines):
        if not line.strip():
            continue

        # ⚠️ Yayın/güncelleme tarihi satırı hiçbir kuralda aday olamaz.
        if _is_publication_line(line):
            continue

        # ── 1. ETİKETLİ DEĞER ALANI — bulunursa TARTIŞMASIZ kazanır ──
        #
        # ⚠️ Kesinlik sıralamasına GİRMEZ ve döngüyü hemen bitirir. Gerekçe
        # ölçülmüş bir hatadır: Ziraat sayfalarının altında komşu kampanya
        # kartları var ve onların da "Son Gün" etiketi bulunuyor. Kesinlik
        # yarışına girilirse kampanyanın kendi `partial` dönemi, komşu kartın
        # `exact` aralığına yeniliyor. #195'te sayfada 09-02-2026 yazarken
        # veritabanına 31-08-2026 yazılmasının nedeni tam olarak buydu.
        #
        # Sayfanın KENDİ alanı, ilgili-kampanyalar bölümünden ÖNCE gelir;
        # bu yüzden belge sırasındaki ilk etiketli alan doğru olandır.
        if _is_label(line):
            blok = _value_block_span(text, lines, i)
            if blok is not None:
                b_bas, b_son = blok
                start, end, precision = parse_date_range_tr(text[b_bas:b_son])
                if start is not None or end is not None:
                    aralik = _date_span_in_line(text[b_bas:b_son])
                    if aralik is None:
                        return CampaignPeriod(start, end, precision, b_bas, b_son)
                    return CampaignPeriod(
                        start,
                        end,
                        precision,
                        b_bas + aralik[0],
                        b_bas + aralik[1],
                    )

        # ── 1b. İŞARETÇİ ÖNDE DEĞİL ARKADA ──
        #
        # ⚠️ 1a'nın AKSİNE hemen dönmez, kesinlik sıralamasına girer.
        # Gerekçe ölçülmüş: Ziraat'in "… Tarihinde Sona Ermiştir." bandı
        # yalnızca BİTİŞ tarihini taşıyor (`partial`), oysa aynı sayfanın
        # koşul metninde tam aralık yazılı ("8 Haziran 2026 saat 09.00 -
        # 30 Haziran 2026 … arasında geçerlidir" → `exact`). Bant tartışmasız
        # kabul edilince 10 kampanyanın BAŞLANGIÇ tarihi düşüyordu.
        if _has_marker(line) and not _DATE_IN_LINE_RE.search(line):
            blok = _value_block_span_before(text, lines, i)
            if blok is not None:
                b_bas, b_son = blok
                # İşaretçi, ayrıştırıcıya bağlam olarak birlikte verilir:
                # "09-02-2026" tek başına `unknown` döner, işaretçiyle
                # birlikte "bitiş tarihi" olarak çözülür.
                start, end, precision = parse_date_range_tr(f"{text[b_bas:b_son]} {line.strip()}")
                puan = _PRECISION_RANK.get(precision, 0)
                if (start is not None or end is not None) and puan > en_iyi_puan:
                    aralik = _date_span_in_line(text[b_bas:b_son])
                    if aralik is None:
                        en_iyi = CampaignPeriod(start, end, precision, b_bas, b_son)
                    else:
                        en_iyi = CampaignPeriod(
                            start, end, precision, b_bas + aralik[0], b_bas + aralik[1]
                        )
                    en_iyi_puan = puan

        # ── 3. SALT TARİH SATIRI — yedek aday olarak kaydedilir ──
        if yedek is None and _is_pure_date_line(line):
            start, end, precision = parse_date_range_tr(line)
            if start is not None or end is not None:
                aralik = _date_span_in_line(line)
                b, s = (
                    (bas, bas + len(line)) if aralik is None else (bas + aralik[0], bas + aralik[1])
                )
                yedek = CampaignPeriod(start, end, precision, b, s)

        # ── 2. İŞARETÇİLİ CÜMLE — kesinlik sıralamasına girer ──
        if not _has_marker(line):
            continue

        start, end, precision = parse_date_range_tr(line)
        if start is None and end is None:
            continue

        puan = _PRECISION_RANK.get(precision, 0)
        if puan > en_iyi_puan:
            # Kanıt satırın tamamı değil, tarih ifadesinin kendisidir.
            aralik = _date_span_in_line(line)
            if aralik is None:
                en_iyi = CampaignPeriod(start, end, precision, bas, bas + len(line))
            else:
                en_iyi = CampaignPeriod(start, end, precision, bas + aralik[0], bas + aralik[1])
            en_iyi_puan = puan
            if puan == _PRECISION_RANK["exact"]:
                break

    return en_iyi if en_iyi.bulundu else (yedek or en_iyi)


# ── ORTAK DÖNEM ÇÖZÜMÜ ────────────────────────────────────────────────────
#
# Aşağıdaki API, kampanya tarihinin TEK yoldan belirlenmesini sağlar.
#
# Neden gerekti: iki ayrı yol iki ayrı kural işletiyordu. Banka scraper'ları
# kendi `_parse_dates()`'lerinde `parse_date_range_tr()`'ı doğrudan gövdeye
# uyguluyor, YAKINLIK KURALINI HİÇ ÇALIŞTIRMIYORDU; `BaseScraper` yalnızca
# scraper hiçbir şey bulamadığında `find_campaign_period()`'a düşüyor ve orada
# kural işliyordu. Sonuç: yapısal alan bulan bankalarda DAHA GEVŞEK bir kural.
#
# Ölçüldü: 20 Ziraat kampanyasının `end_date` değeri komşu kampanya kartından
# gelmişti (#195 sayfada 09-02-2026 derken veritabanında 31-08-2026 yazıyordu).
# Dört bankada 156 kampanya aynı `2026-08-31` tarihini taşıyordu.


class PeriodSource(StrEnum):
    """Dönemin okunduğu kaynak. `campaigns.date_evidence_source`'a yazılır."""

    STRUCTURED = "structured"  # DOM'da etiketli tarih düğümü
    CONDITIONS = "conditions"  # `extract_section_text` ile alınan koşul bölümü
    BODY = "body"  # temizlenmiş gövde metninin tamamı


# Yapısal alanın üst sınırı; üstünde kalan metin alan değil, yakalanmış
# menü veya gövdedir. Albaraka #290 böyle `2020-01-01`/`exact` kaydedilmişti.
STRUCTURED_MAX_CHARS: Final[int] = 200


@dataclass(frozen=True)
class PeriodResult(CampaignPeriod):
    """Bulunan dönem + hangi kaynaktan ve hangi kanıtla geldiği.

    `evidence_text`, ofsetlerin AKSİNE bayatlamaz: `clean_text` yeniden
    üretildiğinde (bkz. `scripts/reprocess_clean_text.py`) ofsetler kayar ama
    kanıt metni aranarak her zaman yeniden konumlandırılabilir.
    """

    source: PeriodSource | None = None
    evidence_text: str | None = None


def _kesinligi_kanitla(period: PeriodResult) -> PeriodResult:
    """Kanıtsız `exact` iddiasını `inferred`'a düşürür.

    `exact` "kaynakta birebir gördüm" demektir; kanıt yoksa doğrulanamaz.
    Albaraka #290 bu yüzden yanlıştı (2020-01-01, exact, kanıtı menü metni).

    Args:
        period: Ham bulgu.

    Returns:
        Kanıtı varsa değişmemiş, yoksa kesinliği düşürülmüş dönem.
    """
    if period.precision != "exact":
        return period
    if period.evidence_text and period.evidence_text.strip():
        return period
    return replace(period, precision="inferred")


def _kanit_metni(text: str, period: CampaignPeriod) -> str | None:
    """Ofsetlerden kanıt metnini keser.

    Args:
        text: Ofsetlerin ait olduğu metin.
        period: Ofsetleri taşıyan bulgu.

    Returns:
        Kanıt metni; ofsetler geçersizse None.
    """
    if period.evidence_start < 0 or period.evidence_end <= period.evidence_start:
        return None
    return text[period.evidence_start : period.evidence_end].strip() or None


def parse_structured_period(text: str | None) -> PeriodResult:
    """Etiketli DOM alanından dönemi okur.

    Yakınlık kuralı aranmaz: metnin dönem bildirdiğini HTML etiketi söylüyor.
    Alan `STRUCTURED_MAX_CHARS`'tan uzunsa yapısal sayılmaz ve işaretçi
    kuralına düşer.

    Args:
        text: Yapısal alanın metni.

    Returns:
        Bulunan dönem; güvenilir bulgu yoksa `precision="unknown"`.
    """
    if not text or not text.strip():
        return PeriodResult(None, None, "unknown")

    bas_blok = _bas_blok(text)

    if len(bas_blok) > STRUCTURED_MAX_CHARS:
        # Yapısal olmadığı anlaşıldı; ortak kurala METNİN TAMAMINDA düşer.
        return _metinden(text, PeriodSource.STRUCTURED)

    start, end, precision = parse_date_range_tr(bas_blok)
    if start is None and end is None:
        # Baş blokta tarih yok: alan başlığı doğru bulunmuş ama değer başka
        # yerde. Marker kuralıyla metnin tamamı taranır.
        return _metinden(text, PeriodSource.STRUCTURED)

    aralik = _date_span_in_line(bas_blok)
    bas, son = aralik if aralik else (0, len(bas_blok))
    donem = PeriodResult(
        start,
        end,
        precision,
        bas,
        son,
        source=PeriodSource.STRUCTURED,
        evidence_text=bas_blok[bas:son].strip() or None,
    )
    return _kesinligi_kanitla(donem)


def _bas_blok(text: str) -> str:
    """Yapısal alanın değer kısmını, devamındaki bölümlerden ayırır.

    `extract_section_text()` sayfa yapısı bozuksa sonraki bölümü de içine
    alıyor ve tamamı uzunluk eşiğini aştığı için alan yapısal sayılmıyordu:

        "02 Ocak 2026 - 31 Aralık 2026\\n\\nKampanya Koşulları\\n\\n
         Kampanyaya yalnızca bireysel müşterilerimiz katılabilir. ..."

    Değer etiketin hemen ardındadır: ilk boş satıra kadarki blok. Bu daraltma
    olmadan Ziraat'in 209 kampanyasının hiçbirinde yapısal kaynak çalışmıyordu.

    Args:
        text: `extract_section_text()` çıktısı.

    Returns:
        İlk boş satıra kadarki blok (kırpılmış).
    """
    return text.strip().split("\n\n", 1)[0].strip()


def _metinden(text: str, source: PeriodSource) -> PeriodResult:
    """Serbest metinden YAKINLIK KURALIYLA dönem çıkarır.

    Args:
        text: Taranacak metin.
        source: Metnin geldiği kaynak; kanıt kaydına yazılır.

    Returns:
        Bulunan dönem; güvenilir bulgu yoksa `precision="unknown"`.
    """
    ham = find_campaign_period_detailed(text)
    if not ham.bulundu:
        return PeriodResult(None, None, "unknown")

    donem = PeriodResult(
        ham.start,
        ham.end,
        ham.precision,
        ham.evidence_start,
        ham.evidence_end,
        source=source,
        evidence_text=_kanit_metni(text, ham),
    )
    return _kesinligi_kanitla(donem)


def find_period_in_sources(
    sources: Sequence[tuple[PeriodSource, str | None]],
) -> PeriodResult:
    """Sıralı kaynaklardan kampanya dönemini çıkarır — TEK GİRİŞ NOKTASI.

    Yakınlık kuralı `STRUCTURED` dışındaki tüm kaynaklarda zorunludur.
    İlk güvenilir bulgu kazanır, kesinlik yarışı yoktur: koşul metninde dönem
    bulunduysa gövdeye hiç inilmez. Komşu kampanya kartlarından sızmaya karşı
    birinci savunma hattı budur.

    Args:
        sources: (kaynak, metin) ikilileri, güvenilirlik sırasına göre.

    Returns:
        İlk güvenilir bulgu; hiçbiri tutmazsa `precision="unknown"` ve
        alanlar `None` — tarih UYDURULMAZ.
    """
    for source, text in sources:
        if not text or not text.strip():
            continue

        donem = (
            parse_structured_period(text)
            if source is PeriodSource.STRUCTURED
            else _metinden(text, source)
        )
        if donem.bulundu:
            return donem

    return PeriodResult(None, None, "unknown")


def donem_gecerli_mi(
    period: PeriodResult,
    *,
    min_yil: int,
    bugun: date,
) -> tuple[bool, str | None]:
    """Dönemi akıl denetiminden geçirir.

    Bankaların bir kısmı biten kampanyaları sayfadan kaldırmayı unutuyor.

    Args:
        period: Çözülmüş dönem.
        min_yil: Kabul edilen en eski kampanya yılı (`settings.min_campaign_year`).
        bugun: Bugünün tarihi (test edilebilirlik için dışarıdan verilir).

    Returns:
        (kabul, red_nedeni). Kabul edildiyse neden `None`'dır.

        Red nedenleri:
            "ters_aralik"      — bitiş, başlangıçtan önce
            "bitis_esigi_alti" — kampanya `min_yil`'dan ÖNCE bitmiş
            "yil_esigi_alti"   — bitiş YOK ve başlangıç `min_yil`'dan eski
            "gelecek_asiri"    — bitiş, bugünden 3 yıldan fazla ileride

    ⚠️ Eşik BİTİŞ tarihine uygulanır, başlangıca değil: uzun vadeli kampanyalar
    yıllar önce başlayıp hâlâ sürebiliyor (Kuveyt Türk #299 2024-06-21 →
    2027-12-31 bugün canlı). Başlangıç yalnızca bitiş hiç bilinmiyorsa ölçüt olur.
    """
    esik = date(min_yil, 1, 1)

    if period.start is not None and period.end is not None and period.end < period.start:
        return False, "ters_aralik"

    if period.end is not None:
        if period.end < esik:
            return False, "bitis_esigi_alti"
        if period.end.year > bugun.year + 3:
            return False, "gelecek_asiri"
    elif period.start is not None and period.start < esik:
        return False, "yil_esigi_alti"

    return True, None
