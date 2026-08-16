"""HTML → temiz metin dönüşümü ve boilerplate ayıklama.

Neden gerekli: Dünya Katılım'ın her sayfasında 800-1500 kelimelik çerez ve
footer metni bulunuyor; bu, kampanya metninden uzun olabiliyor. Temizlenmezse
hem içerik özeti (soft-404 tespiti) hem de metin ayrıştırma bozulur.

Tablolar özel olarak ele alınır: Türkiye Finans'ın oran tabloları ve Hayat
Finans'ın kademe tabloları düz metne çevrilirken satır/sütun yapısı `|` ile
korunur. Yapısal tablo ayrıştırması PART 2'de gelir; PART 1'de metin olarak
saklanması yeterlidir.
"""

from __future__ import annotations

import re
import warnings
from collections.abc import Sequence
from typing import Final

from bs4 import BeautifulSoup, NavigableString, Tag, XMLParsedAsHTMLWarning

from app.core.normalization.text import (
    ascii_fold_tr,
    collapse_whitespace,
    lower_tr,
    normalize_text,
    strip_boilerplate,
)
from app.processing.boilerplate import strip_boilerplate_sections

# İçerik taşımayan, tamamen kaldırılan etiketler.
#
# ⚠️ `<form>` bilinçli olarak BU LİSTEDE DEĞİLDİR. ASP.NET WebForms ile üretilen
# sayfalar (Emlak Katılım dahil) SAYFANIN TAMAMINI tek bir `<form runat="server">`
# içine sarar. Formu silmek, kampanya metninin tamamını silmek demektir:
# ölçtüğümüzde 3222 karakterlik gövde 102 karaktere düşüyor ve tarih/tutar
# çıkarımı hiçbir hata üretmeden başarısız oluyordu.
# Bunun yerine yalnızca metin taşımayan form KONTROLLERİ kaldırılır.
REMOVE_TAGS: Final[tuple[str, ...]] = (
    "script",
    "style",
    "noscript",
    "iframe",
    "svg",
    "canvas",
    "template",
    "input",
    "button",
    "select",
    "option",
    "textarea",
)

# Yapısal gürültü etiketleri: normalde gezinme/altbilgi taşırlar ama
# KOŞULSUZ SİLİNMEZLER.
#
# ⚠️ Gerekçe (gerçek veriyle ölçüldü): Emlak Katılım'ın kampanya sayfalarında
# bozuk HTML nedeniyle ayrıştırıcı, kampanya metninin tamamını `<nav>` ve
# `<header>` etiketlerinin İÇİNE yerleştiriyor. Koşulsuz silme, 6308 karakterlik
# gövdeyi 771 karaktere düşürüyor ve tarih/tutar çıkarımı hiçbir hata üretmeden
# başarısız oluyordu.
#
# Kural: 5000 karakterlik bir `<nav>` gezinme menüsü değildir. Bu etiketler
# yalnızca gövdenin küçük bir bölümünü kapsıyorlarsa silinir.
STRUCTURAL_NOISE_TAGS: Final[tuple[str, ...]] = ("nav", "footer", "header", "aside")

# Yapısal etiket, gövde metninin bu oranından fazlasını kapsıyorsa korunur.
STRUCTURAL_NOISE_MAX_RATIO: Final[float] = 0.4

# class/id değerlerinde geçtiğinde elemanı kaldıran kalıplar.
# Not: "menu", "header" gibi çok genel sözcükler bilinçli olarak DIŞARIDA bırakıldı;
# bazı sitelerde kampanya içeriği bu adları taşıyan kapsayıcılarda bulunuyor.
BOILERPLATE_ATTR_RE: Final[re.Pattern[str]] = re.compile(
    r"cookie|consent|kvkk|gdpr|cerez|çerez|breadcrumb|social-share|share-button"
    r"|newsletter|popup|modal|back-to-top|skip-link|site-footer|site-header",
    re.IGNORECASE,
)

# Ana içerik kapsayıcısı adayları — sırayla denenir.
MAIN_CONTENT_SELECTORS: Final[tuple[str, ...]] = (
    "main",
    "article",
    "[role='main']",
    "#main-content",
    "#content",
    ".campaign-detail",
    ".kampanya-detay",
    ".content-detail",
    ".page-content",
)

# Metinde satır ayrımı oluşturması gereken blok etiketleri.
_BLOCK_LEVEL_TAGS: Final[tuple[str, ...]] = (
    "p",
    "div",
    "section",
    "article",
    "li",
    "tr",
    "br",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "blockquote",
    "dt",
    "dd",
    "ul",
    "ol",
    "table",
)

_HTML_PARSER: Final[str] = "lxml"

# Ana içerik adayının, gövde metninin en az bu oranını kapsaması beklenir.
# Altında kalan adaylar (ör. yalnızca afiş içeren bir <main>) yok sayılır.
MAIN_CONTENT_MIN_RATIO: Final[float] = 0.3

# Sunucuda render edilmemiş şablon parçaları başlık olarak kullanılmaz.
_JS_PLACEHOLDER_RE: Final[re.Pattern[str]] = re.compile(r'\{\{|\}\}|\$\{|["\']\s*\+|\+\s*["\']')

# Bölüm başlıkları kampanya adı değildir.
_SECTION_HEADING_RE: Final[re.Pattern[str]] = re.compile(
    r"kampanya koşul|koşullar|kampanya dışı|sıkça sorulan|nasıl katıl|başvuru|detaylar",
    re.IGNORECASE,
)

# Bölüm başlığı sayılan ama içeriği kendi kardeşlerinde DURMAYAN satır içi
# etiketler. Bunlar için blok atasına çıkılır (bkz. `_section_anchor`).
_INLINE_HEADING_TAGS: Final[frozenset[str]] = frozenset({"strong", "b", "dt", "span", "em"})

# Blok atası ararken çıkılacak en fazla katman. Sınırsız tırmanma bölümü tüm
# sayfa gövdesine genişletir ve koşul metnini boilerplate'e boğar.
_ANCHOR_CLIMB_LIMIT: Final[int] = 3


def _make_soup(html: str) -> BeautifulSoup:
    """HTML'i ayrıştırır; lxml yoksa yerleşik ayrıştırıcıya düşer.

    Bu fonksiyona bazen XML de gelir (sitemap.xml soft-404 denetiminden geçer).
    Bu bilinçlidir ve zararsızdır; BeautifulSoup'un ilgili uyarısı bastırılır,
    aksi hâlde her kazımada anlamsız uyarı yığını üretilir.
    """
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
        try:
            return BeautifulSoup(html, _HTML_PARSER)
        except Exception:  # pragma: no cover - lxml kurulu olmayan ortam
            return BeautifulSoup(html, "html.parser")


def _drop_noise(soup: BeautifulSoup) -> None:
    """Gürültü etiketlerini ve boilerplate kapsayıcılarını ağaçtan siler.

    Yapısal etiketler (`nav`, `header`, `footer`, `aside`) yalnızca gövdenin
    küçük bir bölümünü kapsıyorlarsa silinir; içerik taşıyan büyük bloklar
    korunur (bkz. `STRUCTURAL_NOISE_TAGS`).
    """
    for tag_name in REMOVE_TAGS:
        for element in soup.find_all(tag_name):
            element.decompose()

    body = soup.find("body")
    body_length = len(body.get_text(strip=True)) if isinstance(body, Tag) else 0

    for tag_name in STRUCTURAL_NOISE_TAGS:
        for element in soup.find_all(tag_name):
            length = len(element.get_text(strip=True))
            if body_length and length > body_length * STRUCTURAL_NOISE_MAX_RATIO:
                # Bu etiket gerçekte içerik taşıyor; silinmesi veri kaybı olurdu.
                continue
            element.decompose()

    for element in soup.find_all(attrs={"class": BOILERPLATE_ATTR_RE}):
        element.decompose()
    for element in soup.find_all(attrs={"id": BOILERPLATE_ATTR_RE}):
        element.decompose()


def _usable_heading(text: str) -> bool:
    """Metin, sayfa başlığı olarak kullanılabilir mi?

    Elenen iki durum:
      - JavaScript şablon parçaları (`" + pageTitle + "`, `{{ baslik }}`)
      - Bölüm başlıkları ("Kampanya Koşulları" bir kampanya adı değildir)
    """
    if len(text) < 3:
        return False
    if _JS_PLACEHOLDER_RE.search(text):
        return False
    return not _SECTION_HEADING_RE.search(text)


def extract_title(html: str | None, *, ignore_headings: Sequence[str] = ()) -> str | None:
    """Sayfa başlığını döndürür.

    Sıra: `<h1>` → `<h2>` → `og:title` → `<title>`.

    ⚠️ `<h2>` bilinçli olarak zincire dahildir. Emlak Katılım'ın kampanya
    sayfalarında `<h1>` içeriği JavaScript ile üretiliyor ve HTML'de yalnızca
    şablon dizesi (`" + pageTitle + "`) bulunuyor; `<title>` ve `og:title` ise
    TÜM kampanyalarda aynı ("Kampanya | Türkiye Emlak Katılım Bankası").
    Yalnızca `<h1>`/`<title>` zincirine güvenilirse 65 kampanyanın hepsi aynı
    başlıkla kaydedilir. Gerçek kampanya adı `<h2>` içindedir.

    ⚠️ `ignore_headings` — MARKA BAŞLIĞI TUZAĞI. Bazı sitelerde sayfanın
    tepesinde logo metni de `<h1>` olarak işaretlenmiş oluyor ve gerçek
    kampanya adı İKİNCİ `<h1>`'de kalıyor. Ziraat Katılım'da ölçüldü:
    209 kampanyanın 209'u da "Ziraat Katılım Bankası" başlığıyla kaydedilmişti.
    Marka metni burada bildirilirse o başlık atlanır ve zincir devam eder.

    Args:
        html: Ham HTML.
        ignore_headings: Başlık sayılmayacak metinler (büyük/küçük harf ve
            Türkçe karakter farkı gözetilmez).

    Returns:
        Normalize edilmiş başlık veya bulunamazsa None.
    """
    if not html:
        return None

    soup = _make_soup(html)
    yok_sayilan = {ascii_fold_tr(lower_tr(metin)) for metin in ignore_headings}

    for tag_name in ("h1", "h2"):
        for heading in soup.find_all(tag_name):
            text = normalize_text(heading.get_text(separator=" "))
            if not text or not _usable_heading(text):
                continue
            if ascii_fold_tr(lower_tr(text)) in yok_sayilan:
                continue
            return text

    meta = soup.find("meta", attrs={"property": "og:title"})
    if isinstance(meta, Tag):
        text = normalize_text(str(meta.get("content") or ""))
        if text:
            return text

    title_tag = soup.find("title")
    if title_tag:
        text = normalize_text(title_tag.get_text(separator=" "))
        if text:
            return text

    return None


def extract_tables(html: str | None) -> list[list[list[str]]]:
    """Sayfadaki tabloları satır/hücre matrisleri olarak döndürür.

    Args:
        html: Ham HTML.

    Returns:
        Her tablo için satır listesi, her satır için hücre metinleri.
    """
    if not html:
        return []

    soup = _make_soup(html)
    tables: list[list[list[str]]] = []

    for table in soup.find_all("table"):
        rows: list[list[str]] = []
        for row in table.find_all("tr"):
            cells = [
                normalize_text(cell.get_text(separator=" ")) for cell in row.find_all(["th", "td"])
            ]
            if any(cells):
                rows.append(cells)
        if rows:
            tables.append(rows)

    return tables


def render_table_text(rows: list[list[str]]) -> str:
    """Tablo matrisini `|` ayırıcılı düz metne çevirir.

    Args:
        rows: Satır ve hücrelerden oluşan matris.

    Returns:
        Satır başına bir metin satırı içeren blok.
    """
    return "\n".join(" | ".join(cell for cell in row if cell) for row in rows)


def _replace_tables_with_text(soup: BeautifulSoup) -> None:
    """Tabloları, yapısı korunmuş düz metin düğümleriyle değiştirir.

    Aksi hâlde `get_text()` hücreleri ayırt edilemez biçimde birleştirir ve
    "Vade | Kâr Payı Oranı" ilişkisi kaybolur.
    """
    for table in soup.find_all("table"):
        rows: list[list[str]] = []
        for row in table.find_all("tr"):
            cells = [
                normalize_text(cell.get_text(separator=" ")) for cell in row.find_all(["th", "td"])
            ]
            if any(cells):
                rows.append(cells)
        table.replace_with(NavigableString("\n" + render_table_text(rows) + "\n"))


def _insert_block_breaks(node: Tag) -> None:
    """Blok etiketlerinden sonra satır sonu ekler.

    Böylece satır içi etiketler (`<b>`, `<span>`) cümleyi bölmez ama paragraf
    ve liste öğeleri ayrı satırlarda kalır.

    `BeautifulSoup` da bir `Tag` alt sınıfı olduğundan hem tüm belge hem de
    tek bir düğüm için çağrılabilir.
    """
    for element in node.find_all(_BLOCK_LEVEL_TAGS):
        element.insert_after(NavigableString("\n"))


def _select_main_node(soup: BeautifulSoup) -> Tag | BeautifulSoup:
    """Ana içerik kapsayıcısını seçer; uygun aday yoksa gövdeyi döndürür.

    ⚠️ Aday kapsayıcı BOŞ OLMADIĞI İÇİN değil, GÖVDENİN ANLAMLI BİR BÖLÜMÜNÜ
    kapsadığı için seçilir. Emlak Katılım'ın kampanya sayfalarında `<main>`
    etiketi yalnızca mobil uygulama afişini içeriyor; asıl kampanya metni
    dışarıda kalıyor. İlk dolu adayı seçen bir kural, 20 bin karakterlik
    içerik yerine 100 karakterlik afişi döndürür ve tarih/tutar çıkarımı
    sessizce başarısız olur.
    """
    body = soup.find("body")
    fallback: Tag | BeautifulSoup = body if isinstance(body, Tag) else soup
    fallback_length = len(fallback.get_text(strip=True))

    best: Tag | None = None
    best_length = 0

    for selector in MAIN_CONTENT_SELECTORS:
        for node in soup.select(selector):
            length = len(node.get_text(strip=True))
            if length > best_length:
                best, best_length = node, length

    if best is None or best_length < fallback_length * MAIN_CONTENT_MIN_RATIO:
        return fallback
    return best


def extract_main_text(html: str | None) -> str:
    """Ana içerik metnini çıkarır (boilerplate ayıklaması yapılmadan).

    Args:
        html: Ham HTML.

    Returns:
        Blok yapısı korunmuş düz metin.
    """
    if not html:
        return ""

    soup = _make_soup(html)
    _drop_noise(soup)
    _replace_tables_with_text(soup)
    _insert_block_breaks(soup)

    node = _select_main_node(soup)
    text = node.get_text(separator=" ")
    return collapse_whitespace(normalize_text(text))


def extract_section_text(html: str | None, keywords: Sequence[str]) -> str | None:
    """Başlığı verilen anahtar kelimeleri içeren bölümün metnini döndürür.

    Kampanya sayfalarında koşullar "Kampanya Koşulları" gibi bir başlığın
    ardından liste olarak veriliyor; bu bölüm gövdenin geri kalanından ayrı
    saklanmalıdır. Bölüm, bir sonraki aynı düzey başlığa kadar sürer.

    Args:
        html: Ham HTML.
        keywords: Başlıkta aranacak küçük harfli anahtar kelimeler.

    Returns:
        Bölümün düz metni; bölüm bulunamazsa None.
    """
    if not html:
        return None

    soup = _make_soup(html)
    _drop_noise(soup)
    _replace_tables_with_text(soup)

    heading_tags = ("h1", "h2", "h3", "h4", "h5", "h6", "strong", "b", "dt")
    lowered_keywords = [lower_tr(keyword) for keyword in keywords]

    for heading in soup.find_all(heading_tags):
        heading_text = lower_tr(normalize_text(heading.get_text(separator=" ")))
        if not any(keyword in heading_text for keyword in lowered_keywords):
            continue

        collected: list[str] = []
        for sibling in _section_anchor(heading).find_next_siblings():
            if not isinstance(sibling, Tag):
                continue
            # Sonraki başlıkta bölüm biter.
            if sibling.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
                break
            _insert_block_breaks(sibling)
            collected.append(sibling.get_text(separator=" "))

        text = collapse_whitespace(normalize_text("\n".join(collected)))
        if text:
            return text

    return None


def _section_anchor(heading: Tag) -> Tag:
    """Bölüm içeriğinin kardeşi olduğu düğümü döndürür.

    ⚠️ SATIR İÇİ BAŞLIK TUZAĞI — canlı veride ölçüldü.

    Bankaların çoğu bölüm başlığını `<h2>` yerine bir paragrafın içine
    koyuyor:

        <p><strong>Kampanya Koşulları:</strong></p>
        <ul> ... 15 madde ... </ul>

    Burada maddeler `<p>`'nin kardeşidir, `<strong>`'un DEĞİL. `<strong>`
    üzerinden kardeş aramak boş liste döndürür ve koşullar sessizce kaybolur —
    ölçüldü: Ziraat'te 209 kampanyanın 209'unda, Emlak'ta 66'nın 66'sında
    `conditions_text` boş kalmıştı.

    Bu yüzden satır içi bir başlık kardeşsizse, kardeşi olan en yakın blok
    atasına çıkılır.

    Args:
        heading: Anahtar kelimeyle eşleşen başlık düğümü.

    Returns:
        Kardeşleri toplanacak düğüm.
    """
    if heading.name not in _INLINE_HEADING_TAGS:
        return heading

    node: Tag = heading
    for _ in range(_ANCHOR_CLIMB_LIMIT):
        if any(isinstance(s, Tag) for s in node.find_next_siblings()):
            return node
        parent = node.parent
        if not isinstance(parent, Tag) or parent.name in ("body", "html", "[document]"):
            break
        node = parent
    return node


def clean_html(
    html: str | None,
    *,
    remove_boilerplate: bool = True,
    bank_code: str | None = None,
    title: str | None = None,
) -> str:
    """HTML'i analiz edilebilir temiz metne çevirir.

    Sırasıyla: gürültü etiketleri silinir, tablolar metne çevrilir, blok
    yapısı satırlara dönüştürülür, ana içerik seçilir, unicode normalizasyonu
    uygulanır, tekrar eden boilerplate satırları atılır ve — banka kodu
    verildiyse — yabancı kampanya blokları ayıklanır.

    ⚠️ `bank_code` verilmedikçe bölüm ayıklaması ÇALIŞMAZ. Bu bilinçlidir:
    soft-404 denetimi (`scrapers/soft404.py`) bu fonksiyonun çıktısını
    içerik parmak izi olarak kullanıyor ve davranışının değişmemesi gerekir.
    Kampanya metni üreten çağrılar banka kodunu geçer.

    Args:
        html: Ham HTML.
        remove_boilerplate: Çerez/KVKK/telif satırlarının atılıp atılmayacağı.
        bank_code: Bankaya özel bölüm ayıklaması için banka kodu.
        title: Kampanya başlığı; gezinme bloğu kesiminin çıpası
            (bkz. `boilerplate.strip_leading_navigation`).

    Returns:
        Temizlenmiş metin; girdi boşsa boş dize.
    """
    text = extract_main_text(html)
    if not text:
        return ""
    if remove_boilerplate:
        text = strip_boilerplate(text)
    if bank_code is not None:
        text = strip_boilerplate_sections(text, bank_code=bank_code, title=title)
    return text
