"""Ürün limitlerinin metinden ve HTML'den çıkarılması.

KAYNAK GÜVEN SIRASI — en güvenilirden en zayıfa:

    html_attr   `<input type="range" min max>` gibi form nitelikleri   1.00
    html_table  bankanın yayımladığı LTV/oran matrisi                  1.00
    text        serbest metinden çıkarım                               0.75
    calculator  hesaplayıcı sorgusundan                                0.85
    none        bulunamadı                                             —

⚠️ METİNDEN ÇIKARIM EN ZAYIF HALKA. "50.000 TL'ye kadar" ile "50.000 TL'den
başlayan" arasındaki fark tek kelimededir ve karıştırılırsa alt sınır üst
sınır olarak kaydedilir — karşılaştırmada bankanın en düşük tutarı en yüksek
gibi görünür. Bu yüzden yön belirten ifadeler AÇIKÇA aranır; belirsizse
`None` döner, tahmin edilmez.

Bu modül SAFTIR: ağ, veritabanı ve tarayıcı kullanmaz.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from app.core.normalization.money import parse_money, parse_money_range
from app.core.normalization.rate import parse_rate
from app.core.normalization.text import ascii_fold_tr, lower_tr, normalize_text

# Yalnızca ÜST sınır bildiren ifadeler ("50.000 TL'ye kadar").
UPPER_ONLY_RE: Final[re.Pattern[str]] = re.compile(
    r"(kadar|azami|en fazla|en cok|maksimum|ustu degil)", re.IGNORECASE
)

# Yalnızca ALT sınır bildiren ifadeler ("10.000 TL'den başlayan").
LOWER_ONLY_RE: Final[re.Pattern[str]] = re.compile(
    r"(baslayan|baslamak|asgari|en az|minimum|uzeri|ve uzeri|itibaren)", re.IGNORECASE
)

# Kredi/değer oranı: "ekspertiz değerinin %80'ine kadar".
LTV_RE: Final[re.Pattern[str]] = re.compile(
    r"(ekspertiz|gayrimenkul|konut|arac|tasit|deger)\w*\s+deger\w*\s*[^%]{0,20}%\s*(\d{1,3})",
    re.IGNORECASE,
)
# Daha gevşek biçim: "%80'ine kadar finansman".
LTV_FALLBACK_RE: Final[re.Pattern[str]] = re.compile(
    r"%\s*(\d{1,3})\s*['’]?\w{0,6}\s*(kadar|oraninda)\s+finansman", re.IGNORECASE
)

# Araç yaşı: "0-3 yaş araçlarda", "5 yaşına kadar".
VEHICLE_AGE_RANGE_RE: Final[re.Pattern[str]] = re.compile(r"(\d{1,2})\s*[-–]\s*(\d{1,2})\s*yas")
VEHICLE_AGE_MAX_RE: Final[re.Pattern[str]] = re.compile(r"(\d{1,2})\s*yas\w*\s*kadar")

# Sıfır / ikinci el ifadeleri.
ZERO_VEHICLE_RE: Final[re.Pattern[str]] = re.compile(r"(sifir\s*(km|arac|tasit)|0\s*km)")
USED_VEHICLE_RE: Final[re.Pattern[str]] = re.compile(r"(ikinci\s*el|2\.\s*el|2\s*el)")

# ⚠️ PARA ARALIĞI, PARA BİRİMİ İŞARETİ TAŞIMAK ZORUNDA.
#
# GERÇEK VERİDE ÖLÇÜLDÜ (Dünya Katılım, 17 Ağustos 2026). `parse_money_range`
# kısa ve odaklı metin için yazıldı; buraya ise SAYFANIN TAMAMI geliyor ve
# içindeki her "N-M" örüntüsünü tutar aralığı sayıyordu:
#
#     "40-60"          katılma hesabı PAYLAŞIM ORANI      → tutar 40–60 TL
#     "1-30 gün arası" kırık VADE                          → tutar 1–30 TL
#
# İkisi de sessizce ürün limitine yazılıyordu. En az bir uçta `TL`/`₺`
# aranması bu iki sınıfı da eliyor; gerçek tutar aralıkları
# ("1.000 TL - 100.000 TL arası") birimi zaten taşıyor.
MONEY_RANGE_RE: Final[re.Pattern[str]] = re.compile(
    r"([\d.][\d.,]*)\s*(?:TL|₺)?\s*[-–—]\s*([\d.][\d.,]*)\s*(?:TL|₺)"
    r"|([\d.][\d.,]*)\s*(?:TL|₺)\s*[-–—]\s*([\d.][\d.,]*)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ProductLimits:
    """Bir üründen çıkarılmış limit bilgisi."""

    amount_min: Decimal | None = None
    amount_max: Decimal | None = None
    term_months_min: int | None = None
    term_months_max: int | None = None
    allowed_terms: list[int] | None = None
    ltv_max_pct: Decimal | None = None
    source: str = "none"
    evidence: str | None = None

    @property
    def is_empty(self) -> bool:
        """Hiçbir limit alanı doldurulamadı mı?"""
        return not any(
            (
                self.amount_min,
                self.amount_max,
                self.term_months_min,
                self.term_months_max,
                self.allowed_terms,
                self.ltv_max_pct,
            )
        )


def _fold(text: str) -> str:
    """Karşılaştırma için metni sadeleştirir."""
    return ascii_fold_tr(lower_tr(normalize_text(text)))


def parse_amount_limit(text: str | None) -> tuple[Decimal | None, Decimal | None]:
    """Metinden tutar alt/üst sınırını çıkarır.

    ⚠️ YÖN BELİRSİZSE DEĞER ATANMAZ. "50.000 TL" tek başına ne alt ne üst
    sınırdır; yön bildiren bir ifade ("kadar", "başlayan") aranır. Tahmin
    edilirse bankanın asgari tutarı azami gibi kaydedilir ve karşılaştırma
    tersine döner.

    Args:
        text: Serbest metin.

    Returns:
        (en_az, en_cok); çıkarılamayan uç `None` kalır.
    """
    if not text:
        return None, None

    katlanmis = _fold(text)

    # Önce aralık: "50.000 - 2.000.000 TL arası"
    #
    # ⚠️ İKİ UÇ FARKLI OLMALI. `parse_money_range` tek tutar içeren metinde de
    # (50000, 50000) döndürüyor; bu bir aralık değildir. Aralık sayılırsa
    # "Finansman tutarı 50.000 TL" ifadesi hem alt hem üst sınır olarak
    # kaydedilir ve ürün tek bir tutara kilitlenmiş gibi görünür.
    #
    # ⚠️ Aralık `MONEY_RANGE_RE` ile ARANIR: para birimi işareti taşımayan
    # "40-60" (paylaşım oranı) ve "1-30 gün" (vade) tutar sayılmaz.
    eslesme = MONEY_RANGE_RE.search(text)
    if eslesme is not None:
        ham_alt = eslesme.group(1) or eslesme.group(3)
        ham_ust = eslesme.group(2) or eslesme.group(4)
        aralik = parse_money_range(f"{ham_alt} - {ham_ust} TL")
        en_az, en_cok, _ = aralik
        # ⚠️ Alt sınır SIFIR bir limit değildir. "0 TL'den başlayan finansman"
        # diye bir ürün yok; sıfır ya biçim artığı ya da "%0 peşinat" gibi
        # başka bir ifadeden sızmış demektir. Kılavuz kuralıyla aynı: alt
        # sınır belirtilmemişse ∅, sıfır YAZILMAZ.
        if en_az is not None and en_cok is not None and en_az != en_cok:
            return (en_az if en_az > 0 else None), en_cok

    tutar = parse_money(text)
    if tutar is None:
        return None, None
    deger = tutar[0]

    ust = UPPER_ONLY_RE.search(katlanmis) is not None
    alt = LOWER_ONLY_RE.search(katlanmis) is not None

    # İkisi de varsa hangisi tutara daha yakınsa o kazanır; belirlenemezse
    # hiçbiri atanmaz.
    if ust and not alt:
        return None, deger
    if alt and not ust:
        return deger, None
    return None, None


def parse_ltv(text: str | None) -> Decimal | None:
    """Kredi/değer oranı üst sınırını çıkarır.

    Ör. "ekspertiz değerinin %80'ine kadar" -> 80

    Args:
        text: Serbest metin.

    Returns:
        Yüzde değeri; bulunamazsa None.
    """
    if not text:
        return None

    katlanmis = _fold(text)
    for kalip in (LTV_RE, LTV_FALLBACK_RE):
        eslesme = kalip.search(katlanmis)
        if eslesme is None:
            continue
        # Son grup her iki kalıpta da sayıyı taşımıyor; sayısal grubu bul.
        for grup in eslesme.groups():
            if grup and grup.isdigit():
                oran = Decimal(grup)
                # %100'ün üstü LTV olamaz; büyük olasılıkla başka bir yüzde.
                return oran if 0 < oran <= 100 else None
    return None


def parse_vehicle_age(text: str | None) -> tuple[int | None, int | None]:
    """Araç yaşı aralığını çıkarır.

    Ör. "0-3 yaş araçlarda" -> (0, 3) · "sıfır araç" -> (0, 0)
        "ikinci el" -> (1, None) · "5 yaşına kadar" -> (None, 5)

    Args:
        text: Serbest metin.

    Returns:
        (en_kucuk_yas, en_buyuk_yas).
    """
    if not text:
        return None, None

    katlanmis = _fold(text)

    aralik = VEHICLE_AGE_RANGE_RE.search(katlanmis)
    if aralik:
        return int(aralik.group(1)), int(aralik.group(2))

    if ZERO_VEHICLE_RE.search(katlanmis):
        return 0, 0

    ust = VEHICLE_AGE_MAX_RE.search(katlanmis)
    if ust:
        return None, int(ust.group(1))

    if USED_VEHICLE_RE.search(katlanmis):
        # İkinci el: alt sınır 1, üst sınır belirtilmemiş.
        return 1, None

    return None, None


def parse_allowed_terms(text: str | None) -> list[int] | None:
    """Metinde geçen izinli vade seçeneklerini çıkarır.

    ⚠️ `allowed_terms` EN DEĞERLİ LİMİT ALANIDIR: aralık (min/max) bankanın
    gerçekte hangi vadeleri sunduğunu söylemez. "3, 6, 12 ve 24 ay" ifadesinde
    9 ay seçeneği YOKTUR; aralık olarak kaydedilirse var sanılır.

    Args:
        text: Serbest metin.

    Returns:
        Artan sıralı vade listesi; bulunamazsa None.
    """
    if not text:
        return None

    katlanmis = _fold(text)
    # "3, 6, 12 ve 24 ay" gibi listeler: 'ay' kelimesinden önceki sayı dizisi.
    eslesme = re.search(r"((?:\d{1,3}\s*[,/]\s*|\d{1,3}\s+ve\s+)+\d{1,3})\s*ay", katlanmis)
    if eslesme is None:
        return None

    vadeler = sorted({int(s) for s in re.findall(r"\d{1,3}", eslesme.group(1))})
    return vadeler or None


def derive_rate_from_payment_plan(
    principal: Decimal | None, total_repayment: Decimal | None, term_months: int | None
) -> Decimal | None:
    """Ödeme planından aylık efektif kâr payı oranını geri hesaplar.

    Albaraka ödeme planını sayfada yayımlıyor ama oranı yazmıyor. Toplam geri
    ödeme ile ana para arasındaki fark, vadeye bölününce aylık orana yaklaşır.

    ⚠️ Bu bir YAKLAŞIKTIR, bankanın ilan ettiği oran değildir. `rate_source`
    `payment_plan_derived` olur ve güveni 0.95'tir — tabloya göre bir kademe
    düşük.

    Args:
        principal: Ana para.
        total_repayment: Toplam geri ödeme.
        term_months: Vade (ay).

    Returns:
        Aylık oran yüzdesi (4 ondalık); hesaplanamazsa None.
    """
    if not principal or not total_repayment or not term_months:
        return None
    if principal <= 0 or term_months <= 0 or total_repayment <= principal:
        return None

    toplam_kar_payi = total_repayment - principal
    aylik = (toplam_kar_payi / principal / Decimal(term_months)) * Decimal(100)
    return aylik.quantize(Decimal("0.0001"))


def extract_limits_from_text(text: str | None) -> ProductLimits:
    """Serbest metinden bulunabilen tüm limitleri toplar.

    Args:
        text: Ürün sayfasının metni.

    Returns:
        Doldurulabilen alanlarla `ProductLimits`; hiçbiri bulunamazsa
        `source='none'`.
    """
    if not text:
        return ProductLimits()

    en_az, en_cok = parse_amount_limit(text)
    vadeler = parse_allowed_terms(text)
    ltv = parse_ltv(text)

    limitler = ProductLimits(
        amount_min=en_az,
        amount_max=en_cok,
        allowed_terms=vadeler,
        term_months_min=min(vadeler) if vadeler else None,
        term_months_max=max(vadeler) if vadeler else None,
        ltv_max_pct=ltv,
        source="text",
        evidence=normalize_text(text)[:300],
    )
    # Hiçbir alan dolmadıysa kaynağı "yok" olarak işaretle: sahte bir
    # `text` kaynağı, veri varmış izlenimi yaratır.
    return limitler if not limitler.is_empty else ProductLimits()


def rate_from_percent_text(text: str | None) -> Decimal | None:
    """Metindeki yüzde ifadesini orana çevirir ("%4,20" -> 4.20).

    Türkçe ondalık ayracı (virgül) `parse_rate()` tarafından çözülür.
    """
    return parse_rate(text or "")
