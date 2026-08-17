"""Vakıf Katılım scraper'ı.

Yapı canlı sitede doğrulandı (14 Ağustos 2026):

    Güncel liste : /tr/{segment}/kampanyalar/mevcut-kampanyalar
    Arşiv        : /tr/{segment}/kampanyalar/gecmis-kampanyalar
    Detay        : /tr/{segment}/kampanyalar/detay/{slug}

    segment: kendim-icin -> bireysel  ·  isim-icin -> kurumsal

✅ SEGMENT ADRESTEN BEDAVA. Detay sayfası segment bilgisi taşımıyor; adresteki
`kendim-icin` / `isim-icin` parçası tek kaynaktır ve keşifte taşınır.

⚠️ ÖNCEKİ ANALİZDEN İKİ SAPMA — canlı sitede ölçüldü, kod buna göre yazıldı:

  1. "Liste JavaScript ile yükleniyor, httpx ile 0 kampanya" DOĞRU DEĞİL.
     Sunucu HTML'i kampanya bağlantılarını içeriyor. Tarayıcı gerekmiyor.
     Yine de sayfada JS ile eklenen kampanyalar olabilir; SSR'de görünen
     kayıtlar alınır, eksik kalırsa çalıştırma `partial` olur — banka
     tamamen boş kalmaz.

  2. "Geçersiz slug HTTP 200 + '404' başlıklı sayfa döndürüyor (soft-404)"
     ARTIK GEÇERLİ DEĞİL. Site gerçek HTTP 404 döndürüyor. `Fetcher`'ın
     soft-404 denetimi yine de devrede: davranış geri dönerse çöp kayıt
     oluşmaz.

⚠️ Aynı kampanya sayfada birden çok bağlantıyla (görsel + başlık + açıklama)
tekrarlanıyor; tekilleştirme zorunlu.

Koşullar accordion içinde ama içerik SUNUCU HTML'İNDE: tıklama gerekmez,
gizli içerik de ayrıştırılır.
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
from app.scrapers.sitemap import extract_urls
from app.utils.slugify import slug_from_url_path
from app.utils.urls import dedupe_urls, is_same_site

logger = get_logger(__name__)

BASE_URL: Final[str] = "https://www.vakifkatilim.com.tr"

# ⚠️ ASIL KEŞİF KAYNAĞI. Liste sayfası SSR'de 3 kampanya veriyor, sitemap 99.
# robots.txt bu adresi kendisi yayımlıyor.
SITEMAP_URL: Final[str] = f"{BASE_URL}/sitemap-tr.xml"

# Adresteki segment parçası → veri modelindeki segment değeri.
SEGMENTS: Final[dict[str, str]] = {
    "kendim-icin": "bireysel",
    "isim-icin": "kurumsal",
}

# Liste sayfaları: (yol parçası, arşiv mi).
LISTING_PAGES: Final[tuple[tuple[str, bool], ...]] = (
    ("mevcut-kampanyalar", False),
    ("gecmis-kampanyalar", True),
)

# Detay adreslerini ayırt eden yol parçası.
DETAIL_MARKER: Final[str] = "/kampanyalar/detay/"

CONDITION_KEYWORDS: Final[tuple[str, ...]] = (
    "kampanya koşul",
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

# Tarih bu başlığın altında duruyor:
#   "Kampanya Geçerlilik Tarihi: 02 Ocak 2026 - 31 Aralık 2026"
DATE_SECTION_KEYWORDS: Final[tuple[str, ...]] = (
    "kampanya geçerlilik tarihi",
    "geçerlilik tarihi",
    "kampanya tarihi",
)


# Ürün sayfaları — arşivlenmiş sitemap'ten doğrulandı (17 Ağustos 2026).
# `kar-paylasim-oranlari` §7.6'daki yapısal oran tablosunun kaynağıdır.
_F = "/tr/kendim-icin/finansmanlar"
_H = "/tr/kendim-icin/hesaplar"
_K = "/tr/kendim-icin/kartlar"

PRODUCT_PAGES: Final[tuple[tuple[str, str, str | None], ...]] = (
    (f"{_F}/konut-finansmani", "konut_finansmani", "konut"),
    (f"{_F}/arsa-finansmani", "konut_finansmani", "konut"),
    (f"{_F}/kentsel-donusum-finansmani", "konut_finansmani", "konut"),
    (f"{_F}/is-yeri-finansmani", "isyeri_finansmani", "konut"),
    (f"{_F}/tasit-finansmani", "tasit_finansmani", "tasit"),
    (f"{_F}/motosiklet-finansmani", "tasit_finansmani", "tasit"),
    (f"{_F}/ihtiyac-finansmani", "ihtiyac_finansmani", "yok"),
    (f"{_H}/katilma-hesaplari/kar-paylasim-oranlari", "birikim_katilma_hesabi", "yok"),
    (f"{_H}/katilma-hesaplari/katilma-hesabi", "birikim_katilma_hesabi", "yok"),
    (
        f"{_H}/katilma-hesaplari/ara-donem-kar-payi-odemeli-katilma-hesabi",
        "birikim_katilma_hesabi",
        "yok",
    ),
    (f"{_H}/katilma-hesaplari/kazandiran-hesap", "birikim_katilma_hesabi", "yok"),
    (f"{_H}/katilma-hesaplari/gunluk-hesap", "birikim_katilma_hesabi", "yok"),
    (f"{_H}/katilma-hesaplari/ceyiz-hesabi", "birikim_katilma_hesabi", "yok"),
    (f"{_H}/katilma-hesaplari/konut-hesabi", "birikim_katilma_hesabi", "yok"),
    (f"{_H}/katilma-hesaplari/yuvam-hesap", "birikim_katilma_hesabi", "yok"),
    (f"{_H}/katilma-hesaplari/altin-katilma-hesabi", "yatirim_urunu", "diger"),
    (f"{_H}/ceyrek-altin-hesabi", "yatirim_urunu", "diger"),
    (f"{_K}/kredi-karti/troy-dijital-kredi-karti", "kart", "yok"),
    (f"{_K}/banka-karti/vkart-debit", "kart", "yok"),
    (f"{_K}/banka-karti/temassiz-vkart-debit", "kart", "yok"),
)


class VakifKatilimScraper(BaseScraper):
    """Vakıf Katılım kampanya scraper'ı."""

    bank_code = "vakif_katilim"
    version = "1.0.0"
    product_base_url = BASE_URL
    product_pages = PRODUCT_PAGES

    def discover(self) -> list[DiscoveredUrl]:
        """Sitemap'i ve iki segmentin liste sayfalarını tarar.

        ⚠️ ASIL KAYNAK SITEMAP. Liste sayfası sunucu HTML'inde yalnızca 3
        kampanya veriyor; sitemap 99 kampanya adresi veriyor. Ölçüldü.

        JSON ucu (`/plugins/CampaignListJson`) sayfa başına 9 kayıt döndürüyor
        ama `robots.txt` `/plugins/` yolunu KAPATIYOR. Sitemap hem izinli
        (`Allow: /`, robots.txt sitemap adresini kendisi yayımlıyor) hem daha
        kapsamlı; uca hiç istek atılmaz.

        Returns:
            Keşfedilen kampanya adresleri (tekilleştirilmiş).
        """
        discovered: list[DiscoveredUrl] = []
        seen: set[str] = set()

        for url in self._sitemap_links():
            if url in seen:
                continue
            seen.add(url)
            discovered.append(
                DiscoveredUrl(
                    url=url,
                    doc_type="campaign",
                    segment_hint=self.segment_from_url(url),
                    discovery_method="sitemap",
                )
            )

        for segment_yolu, segment in self._selected_segments():
            for sayfa, arsiv in LISTING_PAGES:
                listing_url = f"{BASE_URL}/tr/{segment_yolu}/kampanyalar/{sayfa}"
                for url in self._campaign_links(listing_url):
                    if url in seen:
                        continue
                    seen.add(url)
                    discovered.append(
                        DiscoveredUrl(
                            url=url,
                            doc_type="campaign",
                            # ✅ Segment yalnızca adresten elde edilebiliyor.
                            segment_hint=segment,
                            discovery_method="archive" if arsiv else "listing",
                        )
                    )

        return discovered

    def _sitemap_links(self) -> list[str]:
        """Sitemap'teki kampanya detay adreslerini döndürür.

        Returns:
            Mutlak kampanya adresleri; sitemap alınamazsa boş liste.
        """
        fetch = self.fetcher.fetch(SITEMAP_URL)
        if not fetch.content:
            logger.warning(
                "sitemap_alinamadi",
                banka=self.bank_code,
                url=SITEMAP_URL,
                durum=fetch.status_code,
                hata=fetch.error,
            )
            return []

        # ⚠️ Ham BAYT verilir: gzip denetimi baytlara bakıyor.
        adresler = extract_urls(fetch.content, same_site_as=BASE_URL)
        kampanyalar = [url for url in adresler if self._is_campaign_url(url)]

        if not kampanyalar:
            logger.warning(
                "sitemapte_kampanya_yok", banka=self.bank_code, adres_sayisi=len(adresler)
            )
        return dedupe_urls(kampanyalar)

    def _selected_segments(self) -> list[tuple[str, str]]:
        """Taranacak (yol parçası, segment) çiftlerini belirler."""
        if not self.categories:
            return list(SEGMENTS.items())

        istenen = {k.casefold() for k in self.categories}
        secilen = [
            (yol, segment)
            for yol, segment in SEGMENTS.items()
            # Hem "kendim-icin" hem "bireysel" yazımı kabul edilir.
            if yol.casefold() in istenen or segment.casefold() in istenen
        ]
        if not secilen:
            logger.warning(
                "bilinmeyen_segment",
                banka=self.bank_code,
                istenen=sorted(istenen),
                gecerli_secenekler=[*SEGMENTS, *SEGMENTS.values()],
            )
            return list(SEGMENTS.items())
        return secilen

    def _campaign_links(self, listing_url: str) -> list[str]:
        """Liste sayfasındaki kampanya detay adreslerini çıkarır.

        Args:
            listing_url: Güncel veya arşiv liste adresi.

        Returns:
            Mutlak kampanya adresleri; sayfa alınamazsa boş liste.
        """
        fetch = self.fetcher.fetch(listing_url)
        if not fetch.is_success or not fetch.html:
            # Bir segmentin veya arşivin alınamaması diğerlerini durdurmaz.
            logger.warning(
                "liste_alinamadi",
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
            if not self._is_campaign_url(absolute) or absolute in gorulen:
                continue
            gorulen.add(absolute)
            links.append(absolute)

        if not links:
            # JS ile yüklenen kampanyalar olabilir; sessiz kalmaz.
            logger.warning("listede_kampanya_yok", banka=self.bank_code, url=listing_url)

        return links

    @staticmethod
    def _is_campaign_url(url: str) -> bool:
        """Adres bir kampanya detay sayfası mı?"""
        if not is_same_site(url, BASE_URL):
            return False
        path = urlsplit(url).path.rstrip("/")
        if DETAIL_MARKER not in path:
            return False
        # `/detay/` sonrasında slug bulunmalı.
        return bool(path.split(DETAIL_MARKER, 1)[1])

    @staticmethod
    def segment_from_url(url: str) -> str | None:
        """Adresteki segment parçasını veri modeli değerine çevirir."""
        parcalar = [p for p in urlsplit(url).path.split("/") if p]
        for parca in parcalar:
            if parca in SEGMENTS:
                return SEGMENTS[parca]
        return None

    def parse_detail(self, html: str, url: str, hint: DiscoveredUrl) -> RawCampaign | None:
        """Kampanya detay sayfasını ayrıştırır.

        Args:
            html: Detay sayfasının HTML'i.
            url: Sayfanın adresi.
            hint: Keşiften gelen segment bilgisi.

        Returns:
            Çıkarılan kampanya; başlık bulunamazsa None.
        """
        title = extract_title(html)
        if not title:
            return None

        body_text = clean_html(html, bank_code=self.bank_code, title=title)
        conditions = extract_section_text(html, CONDITION_KEYWORDS)

        return RawCampaign(
            external_slug=slug_from_url_path(url),
            title=title,
            source_url=url,
            description=self._first_paragraph(body_text),
            conditions_text=conditions,
            exclusions_text=extract_section_text(html, EXCLUSION_KEYWORDS),
            category=None,
            bank_category=hint.category_hint,
            # Keşiften gelmediyse adresten yeniden çıkarılır.
            segment=hint.segment_hint or self.segment_from_url(url),
            is_archived=hint.discovery_method == "archive",
        )

    def structured_period_text(self, html: str) -> str | None:
        """ "Kampanya Geçerlilik Tarihi" bölümünün metni.

        Biçim Türkçe ay adlı:
            "Kampanya Geçerlilik Tarihi: 02 Ocak 2026 - 31 Aralık 2026"
        """
        return extract_section_text(html, DATE_SECTION_KEYWORDS)

    @staticmethod
    def _first_paragraph(text: str, *, max_length: int = 500) -> str | None:
        """Gövde metninin ilk anlamlı paragrafını açıklama olarak döndürür."""
        for line in text.split("\n"):
            aday = normalize_text(line)
            if len(aday) >= 60:
                return aday[:max_length]
        return None
