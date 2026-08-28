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
from app.core.normalization.term import parse_term_months
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

# Annüite kökünü bulan ikili aramanın adım sayısı. 80 adım, [0, 1]
# aralığında 1e-24 hassasiyet verir — 4 ondalıklı sonuç için fazlasıyla yeter.
_BISECTION_STEPS: Final[int] = 80

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
# Para birimi işareti taşıyan TEKİL tutar.
#
# ⚠️ ÇARPAN KELİMESİ SAYI İLE BİRİMİN ARASINA GİRER: "azami 1 milyon TL".
# Çarpan atlanırsa şartname örneği (§7.4) eşleşmiyor ve tutar hiç
# okunamıyor — testle yakalandı.
AMOUNT_WITH_CURRENCY_RE: Final[re.Pattern[str]] = re.compile(
    r"[\d][\d.,]*\s*(?:bin|milyon|milyar)?\s*(?:TL|₺)", re.IGNORECASE
)

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

    # ⚠️ TEKİL TUTAR DA PARA BİRİMİ İŞARETİ İSTER — aralıkla aynı gerekçe.
    # `parse_money` sayfanın tamamında çıplak sayı buluyor ve metnin herhangi
    # bir yerinde geçen "kadar" kelimesi onu üst sınır yapıyordu. Ziraat'in
    # arsa/işyeri/ipotekli finansman ürünlerinde ölçüldü: sayfada TEK BİR TL
    # tutarı yokken `amount_max` sırasıyla 36, 60 ve 80 yazılmıştı — bunlar
    # "36 ay", "60 ay" ve "%80" ifadelerinden sızmış sayılardı.
    birimli = AMOUNT_WITH_CURRENCY_RE.search(text)
    if birimli is None:
        return None, None
    tutar = parse_money(birimli.group())
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

    Albaraka ödeme planını sayfada yayımlıyor ama oranı yazmıyor. Oran,
    eşit taksitli ödeme (annüite) denkleminin kökü olarak çözülür:

        ana_para = taksit × [1 − (1 + r)^−vade] / r

    ⚠️ BASİT BÖLME KULLANILMAZ — ÖLÇÜLDÜ. Önceki gerçekleme
    `kâr_payı / ana_para / vade` yazıyordu. Albaraka'nın gerçek planında
    (150.000 TL ana para, 23 taksit × 9.169,06 TL) bu formül aylık %1,7649
    veriyor; annüite denklemi ise **%3,0495**. Basit bölme ana paranın vade
    boyunca sabit kaldığını varsayıyor, oysa her taksitte azalıyor. Fark
    %42'lik bir EKSİK GÖSTERİMDİR ve karşılaştırma motorunda bankayı
    olduğundan ucuz sıralar.

    ⚠️ BU ORAN "YILLIK MALİYET ORANI" DEĞİLDİR. Albaraka sayfasında %82,39
    yazıyor; o değer ÜCRETLER düşüldükten sonra net ele geçen tutar
    üzerinden hesaplanmış bileşik yıllık maliyettir (doğrulandı: aynı planla
    %82,73 çıkıyor). Buradaki değer ücretsiz, aylık kâr payı oranıdır; ikisi
    farklı büyüklüklerdir ve birbirinin yerine yazılmaz.

    ⚠️ `float` KULLANILMAZ (proje kuralı). Kök, `Decimal` üzerinde ikili
    aramayla bulunur.

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

    taksit = total_repayment / Decimal(term_months)

    def _taksit_tutari(oran: Decimal) -> Decimal:
        """Verilen aylık oranda annüite taksitini döndürür."""
        carpan = (Decimal(1) + oran) ** term_months
        return principal * oran * carpan / (carpan - Decimal(1))

    # Aylık oran hiçbir gerçek üründe %100'ü aşmaz; arama aralığı buna göre.
    alt, ust = Decimal("0.0000001"), Decimal("1")
    for _ in range(_BISECTION_STEPS):
        orta = (alt + ust) / Decimal(2)
        if _taksit_tutari(orta) > taksit:
            ust = orta
        else:
            alt = orta

    return ((alt + ust) / Decimal(2) * Decimal(100)).quantize(Decimal("0.0001"))


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
    vade_min, vade_max = parse_term_months(text)
    ltv = parse_ltv(text)

    # Liste varsa o öncelikli; yoksa "120 aya kadar" gibi aralık.
    term_min: int | None
    term_max: int | None
    if vadeler:
        term_min = min(vadeler)
        term_max = max(vadeler)
    else:
        term_min, term_max = vade_min, vade_max

    limitler = ProductLimits(
        amount_min=en_az,
        amount_max=en_cok,
        allowed_terms=vadeler,
        term_months_min=term_min,
        term_months_max=term_max,
        ltv_max_pct=ltv,
        source="text",
        evidence=normalize_text(text)[:300],
    )
    # Hiçbir alan dolmadıysa kaynağı "yok" olarak işaretle: sahte bir
    # `text` kaynağı, veri varmış izlenimi yaratır.
    return limitler if not limitler.is_empty else ProductLimits()


def extract_profit_rate_from_text(text: str | None) -> tuple[Decimal | None, str | None]:
    """Tanıtım metninde açıkça yazılmış aylık kâr oranını yakalar.

    ⚠️ Yalnızca kâr/oran bağlamı olan ifadeler. Kampanya '%20 indirim'
    gibi yüzdeler oran sayılmaz. Uydurma yok.
    """
    if not text:
        return None, None
    katlanmis = _fold(text)

    # ⚠️ "vade farksız" tek başına %0 yazılmaz: pazarlama metinlerinde sık
    # geçer (ör. konut ürünü) ama gerçek kâr payı sıfır değildir. Yalnızca
    # açık "sıfır kâr payı / oranı" ifadeleri oran üretir.
    if re.search(
        r"(sifir|0)\s*(kar\s*oran|kar\s*payi|kar\s*orani)|"
        r"kar\s*(oran|payi)\w*\s*(sifir|%?\s*0([.,]0+)?\b)|"
        r"%\s*0([.,]0+)?\s*(kar\s*(oran|payi)|faiz)",
        katlanmis,
    ):
        return Decimal("0"), "sıfır kâr payı ifadesi"

    # "aylık kâr oranı %3,75" · "kâr payı oranı %4"
    for kalip in (
        r"aylik\s+kar\s+(oran|payi)\w*\s*%?\s*([\d]+[.,]\d+|\d+)",
        r"kar\s+(oran|payi)\w*\s*%?\s*([\d]+[.,]\d+|\d+)",
        r"%\s*([\d]+[.,]\d+|\d+)\s*(aylik\s+)?(kar|kar\s+payi)",
    ):
        m = re.search(kalip, katlanmis)
        if not m:
            continue
        ham = next((g for g in m.groups() if g and re.search(r"\d", g)), None)
        if not ham:
            continue
        oran = parse_rate(ham) or parse_rate(f"%{ham}")
        if oran is None:
            continue
        # Aylık oran bandı; yıllık maliyet (%50+) elenir.
        if Decimal("0") <= oran <= Decimal("15"):
            return oran, m.group(0)[:120]
    return None, None


def rate_from_percent_text(text: str | None) -> Decimal | None:
    """Metindeki yüzde ifadesini orana çevirir ("%4,20" -> 4.20).

    Türkçe ondalık ayracı (virgül) `parse_rate()` tarafından çözülür.
    """
    return parse_rate(text or "")
