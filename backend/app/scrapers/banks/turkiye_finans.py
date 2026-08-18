"""Türkiye Finans scraper'ı.

Yapı canlı sitede doğrulandı (13 Ağustos 2026):

    Kategori sayfaları : /tr-tr/kampanyalar/Sayfalar/{kategori}.aspx   (10 adet)
    Arşiv              : /tr-tr/kampanyalar/Sayfalar/Biten-Kampanyalar.aspx
    Detay              : /tr-tr/kampanyalar/Sayfalar/{slug}.aspx      ← DÜZ

⚠️ DETAY VE KATEGORİ AYNI DİZİNDE. Kampanya detayının kategoriyi içeren bir
yolu yoktur; her ikisi de `/tr-tr/kampanyalar/Sayfalar/*.aspx` kalıbındadır.
Kategori dosya adları elenmezse sayfa kendini ve kardeşlerini "kampanya"
sanar ve keşif çöp kayıtla dolar.

⚠️ AYNI KAMPANYA BİRDEN FAZLA KATEGORİDE görünüyor ve tek sayfada birden çok
bağlantıyla ("Detaylı Bilgi", görsel, başlık) tekrarlanıyor — tekilleştirme
zorunludur.

⚠️ YAPISAL TARİH ALANI YOK — ama METİNDE TARİH VAR. Bu scraper tarihi kendi
başına çıkarmaz; sayfada tarih için ayrılmış bir HTML alanı bulunmuyor.
Tarih, koşul cümlesinin içinde düz metin olarak geçiyor:

    "Kampanya 25 Mayıs - 31 Aralık 2026 tarihleri arasında geçerlidir."
    "Kampanya 31.12.2026 tarihine kadar geçerlidir."

Bu yüzden dönem, `BaseScraper._fill_missing_dates()` tarafından temiz
metinden çıkarılır (`app/processing/dates.py`). Ölçüldü: 22 kampanyanın
16'sının dönemi bu yolla bulunuyor; kalan 6'sında metinde yalnızca uygunluk
koşulu tarihi ya da yılsız aralık var ve `unknown` KALIR — tarih uydurulmaz.

Önceki sürüm burada koşulsuz `date_precision="unknown"` yazıyordu; 22
kampanyanın tamamı tarihsiz kaydedilmişti. "Veri yok" ile "veri okunmadı"
ayrı şeylerdir.

Durum yalnızca tarihten hesaplanır (`compute_status()` tek doğruluk
kaynağıdır); tarihi bulunamayan kampanya "expired" İŞARETLENMEZ. Bitmiş olma
bilgisi `is_archived=True` ile taşınır.

⚠️ GÖRÜNMEZ KARAKTER TUZAĞI — canlı sayfada ölçüldü. Başlıklarda zero-width
space (U+200B) ve non-breaking space (U+00A0) var, hem de kelimenin İÇİNDE:

    '\\u200bVa\\u200bde'  ·  'Kâr \\u200bPayı\\u00a0Oranı'
    '\\u200b\\u200b\\u200b\\u200bİhtiyaç Finansmanı Koşulları:\\u200b'

`normalize_text()` uygulanmadan yapılan kolon/başlık eşleştirmesi HATA
VERMEDEN boş döner. Ayrıştırma `app/processing/cleaner.py` ve
`app/core/normalization/text.py` üzerinden yapılır; ham dize karşılaştırması
kullanılmaz.

📊 ORAN TABLOSU (bu sprintte kampanya tarafında kullanılmıyor, ürün adımında
kullanılacak): `/tr-tr/bireysel/ihtiyac-finansmani/Sayfalar/ihtiyac-finansmani.aspx`
sayfasında İKİ ayrı HTML tablosu var ve varyant boyutu başlıkta yazılı:

    "Sigortalı İhtiyaç Finansmanı ... Kâr Payı Oranları ve Maliyet Tablosu"
    "Sigortasız İhtiyaç Finansmanı ... Kâr Payı Oranları ve Maliyet Tablosu"

Kolonlar: Vade | Kâr Payı Oranı | Tahsis Ücreti | Aylık Toplam Maliyet |
Yıllık Toplam Maliyet. Vadeler 3/12/18/24/35/36.

⚠️ Sitemap KIRIK (302 ile internet şubesi girişine yönleniyor) — kullanılmaz.
"""

from __future__ import annotations

from typing import Final
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from app.core.normalization.text import normalize_text
from app.logging_config import get_logger
from app.processing.cleaner import clean_html, extract_section_text, extract_title
from app.scrapers.base import BaseScraper
from app.scrapers.models import DiscoveredUrl, RawCampaign
from app.utils.slugify import slug_from_url_path
from app.utils.urls import is_same_site

logger = get_logger(__name__)

BASE_URL: Final[str] = "https://www.turkiyefinans.com.tr"

# Kampanya sayfalarının tamamı bu dizinde — kategori de detay da.
CAMPAIGN_DIR: Final[str] = "/tr-tr/kampanyalar/Sayfalar/"

# Kategori adı → dosya adı. Kategori, kampanyanın hangi sayfada bulunduğundan
# çıkarılır; detay sayfası kategori bilgisi taşımıyor.
CATEGORY_PAGES: Final[dict[str, str]] = {
    "finansman": "finansman-kampanyalari.aspx",
    "kart": "kart-kampanyalari.aspx",
    "ticari": "ticari-kampanyalar.aspx",
    "dijital_bankacilik": "dijital-bankacilik-kampanyalari.aspx",
    "odeme": "odeme-kampanyalari.aspx",
    "yatirim": "yatirim-kampanyalari.aspx",
    "birikim_fon": "birikim-fon-kampanyalari.aspx",
    "sigorta": "sigorta-kampanyalari.aspx",
    "diger": "diger-kampanyalar.aspx",
}

# Arşiv sayfası. Ayrı tutulur: buradan gelen kayıtlar `is_archived=True` olur.
ARCHIVE_PAGE: Final[str] = "Biten-Kampanyalar.aspx"
ARCHIVE_CATEGORY: Final[str] = "biten"

# ⚠️ Detay sayısılırken elenecek dosya adları. Kategori sayfaları detayla aynı
# dizinde durduğu için bu liste olmadan sayfalar birbirini kampanya sanar.
# Karşılaştırma küçük harfle yapılır (site `biten-kampanyalar` ve
# `Biten-Kampanyalar` yazımlarının ikisini de kullanıyor); ADRESİN KENDİSİ
# değiştirilmez.
NON_CAMPAIGN_PAGES: Final[frozenset[str]] = frozenset(
    {"default.aspx", ARCHIVE_PAGE.lower(), *(ad.lower() for ad in CATEGORY_PAGES.values())}
)

# Ürün sayfaları — yapısal oran tablolarının kaynağı.
#
# ⚠️ SITEMAP KULLANILAMAZ. `/sitemap.xml` bir index ve `sitemap0.xml`'e
# işaret ediyor, ama o adres XML değil HTML döndürüyor ("junk after document
# element"). Liste ana sayfa gezintisinden doğrulandı (17 Ağustos 2026).
#
# ⚠️ `Kar-Payi-Oranlari.aspx` §7.6'nın ⭐ kaynağı: `Vade | Kâr Payı | Tahsis
# Ücreti | Aylık Maliyet | Yıllık Maliyet` tablosu ve sigortalı/sigortasız
# ayrımı burada.
#
# (yol, ürün türü, teminat türü) — teminat `COLLATERAL_TYPES` sözlüğünden.
_B = "/tr-tr/bireysel"

PRODUCT_PAGES: Final[tuple[tuple[str, str, str | None], ...]] = (
    # ── Yapısal oran tabloları ──
    (f"{_B}/Sayfalar/Kar-Payi-Oranlari.aspx", "finansman", None),
    (f"{_B}/Sayfalar/Kar-Paylasim-Oranlari.aspx", "birikim_katilma_hesabi", "yok"),
    (f"{_B}/Sayfalar/urun-hizmet-ucretleri.aspx", "finansman", None),
    # ── Finansman ──
    (f"{_B}/konut-finansmani/Sayfalar/konut-finansmani.aspx", "konut_finansmani", "konut"),
    # ⚠️ Küçük 't', büyük 'F' bilinçli: yol küçük harfe çevrilirse adres bozulur.
    (f"{_B}/tasit-finansmani/Sayfalar/tasit-Finansmani.aspx", "tasit_finansmani", "tasit"),
    (f"{_B}/ihtiyac-finansmani/Sayfalar/ihtiyac-finansmani.aspx", "ihtiyac_finansmani", "yok"),
    (f"{_B}/ihtiyac-finansmani/Sayfalar/hazir-limit.aspx", "ihtiyac_finansmani", "yok"),
    (f"{_B}/Sayfalar/arsa-finansmani.aspx", "konut_finansmani", "konut"),
    (f"{_B}/Sayfalar/isyeri-finansmani.aspx", "isyeri_finansmani", "konut"),
    # ── Hesaplar ──
    (f"{_B}/katilma-hesaplari/Sayfalar/katilma-hesaplari.aspx", "birikim_katilma_hesabi", "yok"),
    (f"{_B}/katilma-hesaplari/Sayfalar/e-katilma-hesabi.aspx", "birikim_katilma_hesabi", "yok"),
    (f"{_B}/katilma-hesaplari/Sayfalar/bol-kepce-hesap.aspx", "birikim_katilma_hesabi", "yok"),
    (f"{_B}/Sayfalar/gunluk-hesap.aspx", "birikim_katilma_hesabi", "yok"),
    (f"{_B}/Sayfalar/yedek-hesap.aspx", "birikim_katilma_hesabi", "yok"),
    (f"{_B}/cari-hesaplar/Sayfalar/cari-hesaplar.aspx", "birikim_katilma_hesabi", "yok"),
    (f"{_B}/altin-urunleri/Sayfalar/altin-hesap.aspx", "yatirim_urunu", "diger"),
    (f"{_B}/altin-urunleri/Sayfalar/gumus-hesap.aspx", "yatirim_urunu", "diger"),
    # ── Kartlar ──
    (f"{_B}/Sayfalar/kredi-kartlari.aspx", "kart", "yok"),
    (f"{_B}/banka-kartlari/Sayfalar/default.aspx", "kart", "yok"),
)

CONDITION_KEYWORDS: Final[tuple[str, ...]] = (
    "koşullar",
    "kampanya detay",
    "katılım koşul",
)

EXCLUSION_KEYWORDS: Final[tuple[str, ...]] = (
    "kampanya dışı",
    "hariç",
    "kapsam dışı",
    "istisna",
)


class TurkiyeFinansScraper(BaseScraper):
    """Türkiye Finans kampanya scraper'ı."""

    bank_code = "turkiye_finans"
    version = "1.0.0"
    product_base_url = BASE_URL
    product_pages = PRODUCT_PAGES

    def discover(self) -> list[DiscoveredUrl]:
        """Kategori ve arşiv sayfalarından kampanya adreslerini toplar.

        Returns:
            Keşfedilen kampanya adresleri (tekilleştirilmiş).
        """
        sayfalar = self._selected_pages()
        discovered: list[DiscoveredUrl] = []
        seen: set[str] = set()

        for kategori, dosya in sayfalar:
            listing_url = f"{BASE_URL}{CAMPAIGN_DIR}{dosya}"
            arsiv = kategori == ARCHIVE_CATEGORY

            for url in self._campaign_links(listing_url):
                if url in seen:
                    # ⚠️ Aynı kampanya birden fazla kategoride görünüyor.
                    # İlk bulunduğu kategori korunur.
                    continue
                seen.add(url)
                discovered.append(
                    DiscoveredUrl(
                        url=url,
                        doc_type="campaign",
                        category_hint=kategori,
                        segment_hint="ticari" if kategori == "ticari" else "bireysel",
                        discovery_method="archive" if arsiv else "listing",
                    )
                )

        return discovered

    def _selected_pages(self) -> list[tuple[str, str]]:
        """Taranacak (kategori, dosya) çiftlerini belirler.

        Arşiv daima EN SONA konur: böylece bir kampanya hem güncel hem biten
        listede görünürse güncel kategorisiyle kaydedilir.
        """
        tumu = [*CATEGORY_PAGES.items(), (ARCHIVE_CATEGORY, ARCHIVE_PAGE)]
        if not self.categories:
            return tumu

        istenen = {k.casefold() for k in self.categories}
        secilen = [(ad, dosya) for ad, dosya in tumu if ad.casefold() in istenen]
        if not secilen:
            logger.warning(
                "bilinmeyen_kategori",
                banka=self.bank_code,
                istenen=sorted(istenen),
                gecerli_secenekler=[ad for ad, _ in tumu],
            )
            return tumu
        return secilen

    def _campaign_links(self, listing_url: str) -> list[str]:
        """Tek bir listeleme sayfasından kampanya detay adreslerini çıkarır.

        Args:
            listing_url: Kategori veya arşiv sayfasının adresi.

        Returns:
            Mutlak kampanya adresleri; sayfa alınamazsa boş liste.
        """
        fetch = self.fetcher.fetch(listing_url)
        if not fetch.is_success or not fetch.html:
            # Tek kategorinin alınamaması diğerlerini durdurmaz.
            logger.warning(
                "kategori_alinamadi",
                banka=self.bank_code,
                url=listing_url,
                durum=fetch.status_code,
                hata=fetch.error,
            )
            return []

        soup = BeautifulSoup(fetch.html, "lxml")
        links: list[str] = []
        gorulen: set[str] = set()

        for anchor in soup.find_all("a", href=True):
            href = str(anchor["href"]).strip()
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue

            absolute = urljoin(listing_url, href)
            if not self._is_campaign_url(absolute):
                continue
            if absolute in gorulen:
                # Aynı kampanya bir sayfada birden çok bağlantıyla geçiyor
                # (görsel, başlık, "Detaylı Bilgi").
                continue
            gorulen.add(absolute)
            links.append(absolute)

        return links

    @staticmethod
    def _is_campaign_url(url: str) -> bool:
        """Adres bir kampanya DETAY sayfası mı?

        Kategori sayfaları detayla aynı dizinde olduğu için dosya adına
        bakılarak elenir.
        """
        if not is_same_site(url, BASE_URL):
            return False

        path = urlsplit(url).path
        if not path.startswith(CAMPAIGN_DIR):
            return False
        if not path.lower().endswith(".aspx"):
            return False

        dosya = path.rsplit("/", 1)[-1]
        # Alt dizin yok: detaylar doğrudan bu klasörde duruyor.
        if "/" in path[len(CAMPAIGN_DIR) :]:
            return False
        return dosya.lower() not in NON_CAMPAIGN_PAGES

    def parse_detail(self, html: str, url: str, hint: DiscoveredUrl) -> RawCampaign | None:
        """Kampanya detay sayfasını ayrıştırır.

        Args:
            html: Detay sayfasının HTML'i.
            url: Sayfanın adresi.
            hint: Keşiften gelen kategori ve segment bilgisi.

        Returns:
            Çıkarılan kampanya; başlık bulunamazsa None.
        """
        title = extract_title(html)
        if not title:
            return None

        body_text = clean_html(html, bank_code=self.bank_code, title=title)

        return RawCampaign(
            external_slug=slug_from_url_path(url),
            title=title,
            source_url=url,
            description=self._first_paragraph(body_text, title),
            conditions_text=extract_section_text(html, CONDITION_KEYWORDS),
            exclusions_text=extract_section_text(html, EXCLUSION_KEYWORDS),
            category=None,
            bank_category=hint.category_hint,
            segment=hint.segment_hint,
            # ⚠️ Yapısal tarih alanı YOK. Dönem, varsa, koşul metninde serbest
            # biçimde geçer ve `BaseScraper._apply_period()` tarafından ortak
            # yakınlık kuralıyla çözülür. Bulunamazsa NULL kalır — uydurulmaz.
            is_archived=hint.discovery_method == "archive",
        )

    @staticmethod
    def _first_paragraph(text: str, title: str, *, max_length: int = 500) -> str | None:
        """Gövdenin ilk anlamlı paragrafını açıklama olarak döndürür.

        Sayfa gövdesi kategori menüsüyle (ve başlığın kendisiyle) başlıyor;
        bunlar açıklama sayılmaz.
        """
        kategori_adlari = {normalize_text(ad) for ad in CATEGORY_PAGES}
        basliksiz = normalize_text(title)

        for line in text.split("\n"):
            aday = normalize_text(line)
            if len(aday) < 60:
                continue
            if aday == basliksiz or aday in kategori_adlari:
                continue
            return aday[:max_length]
        return None
