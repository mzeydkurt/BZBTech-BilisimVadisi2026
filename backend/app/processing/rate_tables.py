"""Yapısal kâr payı oranı tablolarının ayrıştırılması.

Bankaların bir kısmı oranı serbest metinde değil, gerçek bir HTML tablosunda
yayımlıyor. Bu tablolar veri setinin EN GÜVENİLİR parçasıdır: bankanın kendi
yayımladığı sayıdır, çıkarım değildir (`rate_source='html_table'`, güven 1.00).

⚠️ `pandas.read_html` KULLANILMAZ. Türkiye Finans'ın tablo başlıklarında
kelimenin İÇİNDE zero-width space (U+200B) ve non-breaking space (U+00A0) var:

    '\\u200bVa\\u200bde'   'Kâr \\u200bPayı\\u00a0Oranı'

`read_html` bu başlıkları olduğu gibi kolon adı yapar ve kolon eşleştirmesi
HATA VERMEDEN başarısız olur. Ayrıştırma elle, `normalize_text()` üzerinden
yapılır.

⚠️ VARYANT BOYUTU TABLONUN DIŞINDADIR. Türkiye Finans aynı sayfada iki tablo
yayımlıyor ve hangisinin hangisi olduğu tablonun ÜSTÜNDEKİ başlıkta yazılı:

    "Sigortalı İhtiyaç Finansmanı ... Kâr Payı Oranları ve Maliyet Tablosu"
    "Sigortasız İhtiyaç Finansmanı ... Kâr Payı Oranları ve Maliyet Tablosu"

Başlık okunmazsa iki tablo tek ürüne ait sanılır ve sigortalı oran sigortasız
oranla karışır — "en düşük kâr payı" karşılaştırması yanlış çıkar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from bs4 import BeautifulSoup, Tag

from app.core.normalization.money import parse_money
from app.core.normalization.rate import parse_rate
from app.core.normalization.term import parse_term_months
from app.core.normalization.text import ascii_fold_tr, lower_tr, normalize_text

# Kolon başlığı → alan adı. Eşleştirme katlanmış metinle yapılır.
COLUMN_ALIASES: Final[dict[str, tuple[str, ...]]] = {
    "term_months": ("vade",),
    "profit_rate_pct": ("kar payi orani", "kar payi", "oran"),
    "allocation_fee_pct": ("tahsis ucreti", "tahsis"),
    "monthly_cost_pct": ("aylik toplam maliyet", "aylik maliyet"),
    "annual_cost_pct": ("yillik toplam maliyet", "yillik maliyet"),
}

# Tablonun üstündeki başlıkta aranan varyant ifadeleri.
VARIANT_MARKERS: Final[tuple[tuple[str, str], ...]] = (
    # ⚠️ SIRA ÖNEMLİ: "sigortasız" içinde "sigortalı" GEÇMEZ ama ters yönde
    # kısmi eşleşme riski var; uzun olan önce denenir.
    ("sigortasiz", "sigortasiz"),
    ("sigortali", "sigortali"),
    ("enerji sinifi a", "enerji_a"),
    ("enerji sinifi b", "enerji_b"),
    ("sifir konut", "sifir_konut"),
    ("ikinci el konut", "ikinci_el_konut"),
    ("sifir arac", "sifir_arac"),
    ("ikinci el arac", "ikinci_el_arac"),
)

# Başlık aramasında tablodan geriye kaç metin düğümü taranacak.
_HEADING_LOOKBACK: Final[int] = 12

# Bir satırın veri satırı sayılması için gereken en az dolu hücre.
_MIN_FILLED_CELLS: Final[int] = 2


# ── LTV (kredi/değer) matrisi ─────────────────────────────
#
# Emlak, Vakıf ve Albaraka konut finansmanı limitini TEK BİR ORAN olarak
# değil, İKİ BOYUTLU MATRİS olarak yayımlıyor: satırda konut değeri bandı,
# sütunda enerji sınıfı.
#
#     |                 | Enerji Sınıfı           |
#     | Konut Değeri    | A-B   | C     | DİĞER   |
#     | Değer <= 5M TL  |  90%  |  80%  |  70%    |
#     | 5M - 7M TL      |  80%  |  70%  |  60%    |
#
# ⚠️ TEK SAYIYA İNDİRGENMEZ. "Bu üründe LTV %90" demek yanlış: %90 yalnızca
# 5 milyon altı A-B sınıfı konutta geçerli, 20 milyon üstü DİĞER sınıfta
# oran %20. Matris satır satır aktarılır (KAPI 5 geçiş koşulu).
#
# ⚠️ SON HARF YOK: Emlak Katılım başlığı "Enerji Sınıf" yazıyor, "Sınıfı"
# değil — bankanın kendi dizgi hatası. "enerji sinifi" aransaydı Emlak'ın
# matrisi hiç bulunamazdı (ölçüldü: 0 hücre).
_ENERGY_HEADER: Final[str] = "enerji sinif"

# Değer bandı biçimleri. Üçü de canlı sayfalarda ölçüldü:
#   "Değer <= 5 Milyon TL"                    → (None, 5.000.000)
#   "5 Milyon - 7 Milyon TL"                  → (5.000.000, 7.000.000)
#   "5 MİLYON TL < DEĞER <= 7 MİLYON TL"      → (5.000.000, 7.000.000)
#   "20 Milyon TL Üzeri"                      → (20.000.000, None)
_BAND_UPPER_ONLY: Final[re.Pattern[str]] = re.compile(r"^\s*deger\s*<=?\s*(.+)$")
_BAND_LOWER_ONLY: Final[re.Pattern[str]] = re.compile(r"^(.+?)\s*(?:uzeri|ve uzeri|<\s*deger)\s*$")
_BAND_BOTH: Final[re.Pattern[str]] = re.compile(
    r"^(.+?)\s*(?:<\s*deger\s*<=?|[-–—])\s*(.+)$",
)

# "Değer x 90%" hücresinden oranı okur.
_LTV_CELL: Final[re.Pattern[str]] = re.compile(r"(\d{1,3}(?:[.,]\d+)?)\s*%")


# ── Ödeme planı (§7.5) ────────────────────────────────────
#
# Albaraka konut finansmanı sayfasında oranı YAZMIYOR; 23 satırlık taksit
# tablosu yayımlıyor ve oran plandan geri hesaplanıyor.
_INSTALLMENT_HEADER: Final[str] = "taksit no"
_TOTAL_ROW: Final[str] = "toplam"

# Ödeme planı kolon başlığı → alan adı.
#
# ⚠️ "Taksit Tutarı" kolonunun TOPLAM satırındaki değeri GERİ ÖDENECEK TOPLAM
# TUTAR'dır (210.888,82 TL); tek taksit tutarı değil.
PLAN_COLUMN_ALIASES: Final[dict[str, tuple[str, ...]]] = {
    "total_repayment": ("taksit tutari",),
    "principal": ("ana para",),
    "profit": ("kar payi",),
}


@dataclass(frozen=True)
class PaymentPlan:
    """Ödeme planının toplam satırı ve vadesi."""

    term_months: int
    principal: Decimal | None = None
    total_repayment: Decimal | None = None
    total_profit: Decimal | None = None
    evidence_text: str | None = None


def _map_plan_columns(header: list[str]) -> dict[int, str]:
    """Ödeme planı başlığından kolon indeksi → alan adı eşlemesi üretir.

    ⚠️ "Kalan Ana Para" ile "Ana Para" AYRI kolonlar ve ikincisi asıl olan.
    Basit `in` araması "Kalan Ana Para"yı da `principal` sanardı; bu yüzden
    daha uzun başlık ELENİR.
    """
    esleme: dict[int, str] = {}
    for indeks, baslik in enumerate(header):
        katlanmis = _fold(baslik)
        if not katlanmis or "kalan" in katlanmis:
            continue
        for alan, adlar in PLAN_COLUMN_ALIASES.items():
            if alan in esleme.values():
                continue
            if any(ad in katlanmis for ad in adlar):
                esleme[indeks] = alan
                break
    return esleme


@dataclass(frozen=True)
class LtvCell:
    """LTV matrisinin tek bir hücresi: (değer bandı × enerji sınıfı) → oran."""

    energy_class: str
    ltv_max_pct: Decimal
    amount_min: Decimal | None = None
    amount_max: Decimal | None = None
    evidence_text: str | None = None


@dataclass(frozen=True)
class LtvMatrix:
    """Tek bir LTV matrisi ve başlığı."""

    cells: tuple[LtvCell, ...]
    caption: str | None = None

    @property
    def is_empty(self) -> bool:
        """Hiç hücre çıkarılamadı mı?"""
        return not self.cells


@dataclass(frozen=True)
class RateRow:
    """Oran tablosunun tek bir satırı."""

    term_months: int | None = None
    profit_rate_pct: Decimal | None = None
    allocation_fee_pct: Decimal | None = None
    monthly_cost_pct: Decimal | None = None
    annual_cost_pct: Decimal | None = None
    evidence_text: str | None = None


@dataclass(frozen=True)
class RateTable:
    """Tek bir oran tablosu ve ait olduğu varyant."""

    rows: tuple[RateRow, ...]
    variant_key: str | None = None
    variant_label: str | None = None
    caption: str | None = None

    @property
    def is_empty(self) -> bool:
        """Hiç veri satırı çıkarılamadı mı?"""
        return not self.rows


def _fold(text: str | None) -> str:
    """Karşılaştırma için metni sadeleştirir (görünmez karakterler dahil)."""
    return ascii_fold_tr(lower_tr(normalize_text(text or "")))


def _cells(row: Tag) -> list[str]:
    """Satırdaki hücrelerin normalize edilmiş metnini döndürür."""
    return [normalize_text(c.get_text(separator=" ")) for c in row.find_all(["th", "td"])]


def _map_columns(header: list[str]) -> dict[int, str]:
    """Başlık satırından kolon indeksi → alan adı eşlemesi üretir.

    ⚠️ Eşleştirme KATLANMIŞ metinle yapılır; ham dize karşılaştırması
    zero-width karakterler yüzünden sessizce başarısız olur.
    """
    esleme: dict[int, str] = {}
    for indeks, baslik in enumerate(header):
        katlanmis = _fold(baslik)
        if not katlanmis:
            continue
        for alan, adlar in COLUMN_ALIASES.items():
            if alan in esleme.values():
                continue
            if any(ad in katlanmis for ad in adlar):
                esleme[indeks] = alan
                break
    return esleme


def _table_caption(table: Tag) -> str | None:
    """Tablonun üstündeki açıklayıcı başlığı bulur.

    Önce `<caption>`, sonra tablodan geriye doğru en yakın anlamlı metin.
    Varyant boyutu (sigortalı/sigortasız) burada yazılı.
    """
    caption = table.find("caption")
    if caption is not None:
        metin = normalize_text(caption.get_text(separator=" "))
        if metin:
            return metin

    node = table
    for _ in range(_HEADING_LOOKBACK):
        node = node.find_previous(string=True)  # type: ignore[assignment]
        if node is None:
            break
        # ⚠️ `<style>` VE `<script>` İÇERİĞİ BAŞLIK DEĞİLDİR. Albaraka'nın
        # konut sayfasında tabloların arasında bir `<style>` bloğu var ve
        # geriye doğru arama ".responsive-table { width: 100% ..." metnini
        # başlık sanıyordu.
        ebeveyn = getattr(node, "parent", None)
        if ebeveyn is not None and ebeveyn.name in {"style", "script", "noscript"}:
            continue
        metin = normalize_text(str(node))
        # Sayı ağırlıklı kısa parçalar tablo hücreleridir, başlık değil.
        if len(metin) >= 20 and not re.fullmatch(r"[\d.,%\s]+", metin):
            return metin
    return None


def _variant_from_caption(caption: str | None) -> tuple[str | None, str | None]:
    """Başlıktan varyant anahtarını çıkarır.

    Returns:
        (kanonik_anahtar, ham_etiket); bulunamazsa (None, None).
    """
    if not caption:
        return None, None

    katlanmis = _fold(caption)
    for isaret, anahtar in VARIANT_MARKERS:
        if isaret in katlanmis:
            return anahtar, caption
    return None, None


def _term_months(raw: str) -> int | None:
    """Vade hücresini ay sayısına çevirir.

    ⚠️ Oran tablolarında vade çoğu zaman BİRİMSİZ yazılıyor ("3", "36").
    `parse_term_months()` birim arayıp bulamayınca `(None, None)` döndürüyor;
    tek başına kullanılırsa tablonun vade kolonu tamamen boş kalır.
    """
    temiz = raw.strip()
    if temiz.isdigit():
        return int(temiz)

    alt, ust = parse_term_months(temiz)
    # Tek satır tek vadeyi temsil eder; aralık gelirse üst sınır kullanılır.
    return ust if ust is not None else alt


def _parse_row(cells: list[str], columns: dict[int, str]) -> RateRow | None:
    """Veri satırını `RateRow`'a çevirir; veri yoksa None."""
    degerler: dict[str, object] = {}

    for indeks, alan in columns.items():
        if indeks >= len(cells):
            continue
        ham = cells[indeks]
        if not ham:
            continue

        if alan == "term_months":
            degerler[alan] = _term_months(ham)
        else:
            # ⚠️ Türkçe ondalık ayracı: "%4,20" -> 4.20
            degerler[alan] = parse_rate(ham)

    dolu = [d for d in degerler.values() if d is not None]
    if len(dolu) < _MIN_FILLED_CELLS:
        return None

    return RateRow(
        term_months=degerler.get("term_months"),  # type: ignore[arg-type]
        profit_rate_pct=degerler.get("profit_rate_pct"),  # type: ignore[arg-type]
        allocation_fee_pct=degerler.get("allocation_fee_pct"),  # type: ignore[arg-type]
        monthly_cost_pct=degerler.get("monthly_cost_pct"),  # type: ignore[arg-type]
        annual_cost_pct=degerler.get("annual_cost_pct"),  # type: ignore[arg-type]
        evidence_text=" | ".join(c for c in cells if c)[:300],
    )


def _plan_cell(row: list[str], columns: dict[int, str], field: str) -> Decimal | None:
    """Ödeme planı toplam satırından bir alanın tutarını okur.

    Args:
        row: Toplam satırının hücreleri.
        columns: Kolon indeksi → alan adı eşlemesi.
        field: Okunacak alan adı.

    Returns:
        Tutar; kolon yoksa veya ayrıştırılamazsa None.
    """
    indeks = next((i for i, ad in columns.items() if ad == field), None)
    if indeks is None or indeks >= len(row):
        return None
    tutar, _ = parse_money(row[indeks])
    return tutar


def parse_payment_plan(html: str | None) -> PaymentPlan | None:
    """Ödeme planı tablosundan ana para, toplam geri ödeme ve vadeyi okur.

    ⚠️ ALBARAKA ORANI YAZMIYOR, PLANI YAZIYOR. Konut finansmanı sayfasında
    23 satırlık taksit tablosu var ama "kâr payı oranı %X" ifadesi yok.
    Oran §7.5'e göre plandan geri hesaplanır
    (`limits.derive_rate_from_payment_plan`).

    ⚠️ VADE SATIR SAYISINDAN OKUNUR, "Toplam" satırı sayılmaz. Toplam satırı
    taksit sanılırsa vade bir fazla çıkar ve geri hesaplanan oran düşük
    görünür — banka olduğundan ucuz sıralanır.

    ⚠️ ANA PARA "Toplam" SATIRININ ANA PARA HÜCRESİNDEN alınır, ilk satırın
    "Kalan Ana Para" değerinden değil: ikincisi ilk taksit ödenmeden önceki
    bakiye ve bazı bankalarda ücretleri de içeriyor.

    Args:
        html: Ürün sayfasının ham HTML'i.

    Returns:
        Bulunan plan; ödeme planı tablosu yoksa None.
    """
    if not html:
        return None

    soup = BeautifulSoup(html, "lxml")
    for table in soup.find_all("table"):
        satirlar = table.find_all("tr")
        baslik_index = next(
            (i for i, tr in enumerate(satirlar) if _INSTALLMENT_HEADER in _fold(tr.get_text(" "))),
            None,
        )
        if baslik_index is None:
            continue

        basliklar = _cells(satirlar[baslik_index])
        kolonlar = _map_plan_columns(basliklar)
        if "principal" not in kolonlar.values():
            continue

        taksit_sayisi = 0
        toplam_satir: list[str] | None = None
        for satir in satirlar[baslik_index + 1 :]:
            hucre = _cells(satir)
            if not hucre:
                continue
            if _TOTAL_ROW in _fold(hucre[0]):
                toplam_satir = hucre
                break
            taksit_sayisi += 1

        if toplam_satir is None or taksit_sayisi == 0:
            continue

        return PaymentPlan(
            principal=_plan_cell(toplam_satir, kolonlar, "principal"),
            total_repayment=_plan_cell(toplam_satir, kolonlar, "total_repayment"),
            total_profit=_plan_cell(toplam_satir, kolonlar, "profit"),
            term_months=taksit_sayisi,
            evidence_text=normalize_text(" | ".join(toplam_satir)),
        )

    return None


def _parse_value_band(text: str) -> tuple[Decimal | None, Decimal | None]:
    """Konut değeri bandını alt/üst uca çevirir.

    ⚠️ `parse_money_range` TEK BAŞINA YETMİYOR: "5 MİLYON TL < DEĞER <= 7
    MİLYON TL" biçiminde iki ucu da `5.000.000` okuyor, çünkü aradaki
    "DEĞER" kelimesini aralık işareti saymıyor. Bant biçimleri burada açıkça
    ayrıştırılır.

    Args:
        text: Bandın hücre metni.

    Returns:
        (alt, üst); belirtilmemiş uç None.
    """
    katlanmis = _fold(text)
    if not katlanmis:
        return None, None

    # ⚠️ SIRA ÖNEMLİ. "Değer <= 5 Milyon" ifadesi `_BAND_BOTH`'un tire
    # koluna da uyabilir; yalnız-üst kalıbı önce denenir.
    ust_tek = _BAND_UPPER_ONLY.match(katlanmis)
    if ust_tek:
        tutar, _ = parse_money(ust_tek.group(1))
        return None, tutar

    iki_uc = _BAND_BOTH.match(katlanmis)
    if iki_uc:
        alt, _ = parse_money(iki_uc.group(1))
        ust, _ = parse_money(iki_uc.group(2))
        if alt is not None and ust is not None:
            return min(alt, ust), max(alt, ust)

    alt_tek = _BAND_LOWER_ONLY.match(katlanmis)
    if alt_tek:
        tutar, _ = parse_money(alt_tek.group(1))
        return tutar, None

    return None, None


def parse_ltv_matrices(html: str | None) -> list[LtvMatrix]:
    """Sayfadaki konut değeri × enerji sınıfı LTV matrislerini ayrıştırır.

    ⚠️ Bir sayfada birden çok matris olabiliyor: Albaraka ve Vakıf "Standart
    Konut Alımı" ve "2. ve Sonraki Konut Alımı" için AYRI tablolar
    yayımlıyor ve oranlar tamamen farklı (%90'a karşı %22,5). Hangi matrisin
    hangisi olduğu tablonun ÜSTÜNDEKİ başlıkta yazılı; `caption` taşınır.

    ⚠️ BANKANIN YAZDIĞI SAYI DÜZELTİLMEZ. Emlak'ın tablosunda B sınıfı için
    "DEĞER x 0%", Vakıf'ınkinde "Değer x 150%" yazıyor; ikisi de büyük
    olasılıkla bankanın dizgi hatası. Kaynak veri değiştirilmez — düzeltmek
    bizim uydurmamız olurdu.

    Args:
        html: Ürün sayfasının ham HTML'i.

    Returns:
        Bulunan matrisler; enerji sınıfı başlığı taşımayan tablolar atlanır.
    """
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    matrisler: list[LtvMatrix] = []

    for table in soup.find_all("table"):
        satirlar = table.find_all("tr")
        baslik_index = next(
            (i for i, tr in enumerate(satirlar) if _ENERGY_HEADER in _fold(tr.get_text(" "))),
            None,
        )
        # Sınıf etiketleri BAŞLIK SATIRININ ALTINDA: "Konut Değeri" hücresi
        # `rowspan=2` ile iki satıra yayılıyor, sınıflar kendi satırında.
        if baslik_index is None or baslik_index + 1 >= len(satirlar):
            continue

        siniflar = [h for h in _cells(satirlar[baslik_index + 1]) if h.strip()]
        if not siniflar:
            continue

        hucreler: list[LtvCell] = []
        for satir in satirlar[baslik_index + 2 :]:
            hucre = _cells(satir)
            if len(hucre) != len(siniflar) + 1:
                continue
            alt, ust = _parse_value_band(hucre[0])
            for sinif, ham in zip(siniflar, hucre[1:], strict=True):
                eslesme = _LTV_CELL.search(ham)
                if eslesme is None:
                    continue
                oran = parse_rate(eslesme.group(0))
                if oran is None:
                    continue
                hucreler.append(
                    LtvCell(
                        energy_class=normalize_text(sinif),
                        ltv_max_pct=oran,
                        amount_min=alt,
                        amount_max=ust,
                        evidence_text=f"{normalize_text(hucre[0])} | {normalize_text(sinif)} | "
                        f"{normalize_text(ham)}",
                    )
                )

        if hucreler:
            matrisler.append(LtvMatrix(cells=tuple(hucreler), caption=_table_caption(table)))

    return matrisler


def parse_rate_tables(html: str | None) -> list[RateTable]:
    """Sayfadaki tüm kâr payı oranı tablolarını ayrıştırır.

    Args:
        html: Ürün sayfasının ham HTML'i.

    Returns:
        Bulunan tablolar; oran kolonu taşımayan tablolar atlanır.
    """
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    tablolar: list[RateTable] = []

    for table in soup.find_all("table"):
        satirlar = table.find_all("tr")
        if len(satirlar) < 2:
            continue

        basliklar = _cells(satirlar[0])
        kolonlar = _map_columns(basliklar)

        # Oran kolonu yoksa bu bir oran tablosu değildir (ör. ücret listesi).
        if "profit_rate_pct" not in kolonlar.values():
            continue

        veri: list[RateRow] = []
        for satir in satirlar[1:]:
            ayristirilan = _parse_row(_cells(satir), kolonlar)
            if ayristirilan is not None:
                veri.append(ayristirilan)

        if not veri:
            continue

        caption = _table_caption(table)
        anahtar, etiket = _variant_from_caption(caption)
        tablolar.append(
            RateTable(
                rows=tuple(veri),
                variant_key=anahtar,
                variant_label=etiket,
                caption=caption,
            )
        )

    return tablolar
