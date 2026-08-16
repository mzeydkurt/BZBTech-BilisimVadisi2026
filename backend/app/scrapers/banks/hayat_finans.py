"""Hayat Finans Katılım Bankası scraper'ı.

Dijital banka olmasına rağmen içerik zengin. İki özel durumu var:

  1. KEŞİF: Kampanya listesi istemci tarafında oluşuyor. Birincil kaynak
     sitemap.xml'dir; sitemap ⚠️ GZIP KODLU gelir ve açılması gerekir.
     Sitemap alınamazsa listeleme sayfasındaki bağlantılara düşülür.

  2. ⚠️ SLUG ÖN EKİNE GÖRE FİLTRELEME YAPILMAZ. Analizde doğrulandı: kampanya
     listesindeki bir kart /hesaplar/avantajli-hesap ürün sayfasına gidiyor.
     Ön ek filtresi uygulanırsa veri kaybedilir. Tüm bağlantılar alınır,
     `doc_type` hedefin yoluna göre belirlenir.

  3. ⚠️ BİTEN KAMPANYALAR SERT 404: Sayfa tamamen kalkıyor ve geri gelmiyor.
     404 yönetimi `BaseScraper` içinde yapılır (kayıt `expired` işaretlenir,
     ham HTML arşivde kalır).
"""

from __future__ import annotations

import gzip
import re
from typing import Final
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from app.core.normalization.date_tr import parse_date_range_tr
from app.core.normalization.text import normalize_text
from app.logging_config import get_logger
from app.processing.cleaner import (
    clean_html,
    extract_section_text,
    extract_tables,
    extract_title,
    render_table_text,
)
from app.scrapers.base import BaseScraper
from app.scrapers.models import DiscoveredUrl, RawCampaign
from app.utils.slugify import slug_from_url_path
from app.utils.urls import is_same_site

logger = get_logger(__name__)

BASE_URL: Final[str] = "https://www.hayatfinans.com.tr"
LISTING_URL: Final[str] = f"{BASE_URL}/kampanyalar"
SITEMAP_URL: Final[str] = f"{BASE_URL}/sitemap.xml"

# Kampanya sayfası olduğunu gösteren yol parçaları.
CAMPAIGN_PATH_HINTS: Final[tuple[str, ...]] = ("/kampanya",)
# Ürün sayfası olduğunu gösteren yol parçaları — bunlar da toplanır,
# yalnızca doc_type farklı olur.
PRODUCT_PATH_HINTS: Final[tuple[str, ...]] = (
    "/hesaplar",
    "/kartlar",
    "/finansman",
    "/urunler",
)

# İçerik taşımayan yollar keşif dışında bırakılır.
SKIP_PATH_HINTS: Final[tuple[str, ...]] = (
    "/iletisim",
    "/kvkk",
    "/cerez",
    "/gizlilik",
    "/sikca-sorulan",
    "/hakkimizda",
    "/bilgi-toplumu",
)

CONDITION_KEYWORDS: Final[tuple[str, ...]] = (
    "kampanya koşul",
    "koşullar",
    "katılım koşul",
    "kampanya detay",
)

EXCLUSION_KEYWORDS: Final[tuple[str, ...]] = ("kampanya dışı", "hariç", "kapsam dışı")

_LOC_RE: Final[re.Pattern[str]] = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.IGNORECASE)


class HayatFinansScraper(BaseScraper):
    """Hayat Finans kampanya scraper'ı."""

    bank_code = "hayat_finans"
    version = "1.0.0"

    def discover(self) -> list[DiscoveredUrl]:
        """sitemap.xml ve listeleme sayfasından adresleri toplar.

        Returns:
            Keşfedilen adresler (tekilleştirilmiş).
        """
        discovered: dict[str, DiscoveredUrl] = {}

        for url in self._discover_from_sitemap():
            entry = self._classify(url, discovery_method="sitemap")
            if entry:
                discovered[entry.url] = entry

        for url in self._discover_from_listing():
            entry = self._classify(url, discovery_method="listing")
            if entry and entry.url not in discovered:
                discovered[entry.url] = entry

        return list(discovered.values())

    def _discover_from_sitemap(self) -> list[str]:
        """sitemap.xml'den adresleri okur.

        Sitemap gzip kodlu gelir. Açılamazsa hata YUTULUR ve listeleme
        kaynağına düşülür — sitemap ikincil bir kolaylıktır, zorunluluk değil.
        """
        fetch = self.fetcher.fetch(SITEMAP_URL)
        if not fetch.html:
            logger.info("sitemap_alinamadi", banka=self.bank_code, hata=fetch.error)
            return []

        content = fetch.html
        # Gövde gzip ise metne çevrilirken bozulmuş olabilir; ham baytları dener.
        if "<loc" not in content.lower():
            try:
                content = gzip.decompress(content.encode("latin-1")).decode("utf-8")
            except Exception as exc:
                logger.info("sitemap_gzip_acilamadi", banka=self.bank_code, hata=str(exc))
                return []

        return _LOC_RE.findall(content)

    def _discover_from_listing(self) -> list[str]:
        """Kampanya listeleme sayfasındaki tüm bağlantıları döndürür."""
        fetch = self.fetcher.fetch(LISTING_URL)
        if not fetch.is_success or not fetch.html:
            logger.warning(
                "listeleme_alinamadi",
                banka=self.bank_code,
                durum=fetch.status_code,
                hata=fetch.error,
            )
            return []

        soup = BeautifulSoup(fetch.html, "lxml")
        # Göreli adresler YÖNLENDİRME SONRASI adrese göre çözülür; aksi hâlde
        # yönlendirilmiş bir sayfada yanlış alan adı üretilir.
        base = fetch.final_url or LISTING_URL

        links: list[str] = []
        for anchor in soup.find_all("a", href=True):
            href = str(anchor["href"]).strip()
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            links.append(urljoin(base, href))
        return links

    def _classify(self, url: str, *, discovery_method: str) -> DiscoveredUrl | None:
        """Adresi sınıflandırır; ilgisizse None döndürür.

        ⚠️ Ön ek filtresi UYGULANMAZ; yalnızca açıkça içerik taşımayan
        kurumsal sayfalar elenir.

        ⚠️ Alan adı karşılaştırması `www.` ön ekini yok sayar: site
        `www.hayatfinans.com.tr` adresinden `hayatfinans.com.tr` adresine
        yönlendiriyor ve sitemap'teki adreslerin tamamı ön eksiz yazılmış.
        Ham dize karşılaştırması bu adresleri dış bağlantı sayar ve keşif
        sessizce sıfır sonuç verir.
        """
        if not is_same_site(url, BASE_URL):
            return None

        parts = urlsplit(url)
        path = parts.path.rstrip("/").lower()
        if not path or path in ("/kampanyalar", "/sitemap.xml"):
            return None
        if any(skip in path for skip in SKIP_PATH_HINTS):
            return None

        if any(hint in path for hint in CAMPAIGN_PATH_HINTS):
            doc_type = "campaign"
        elif any(hint in path for hint in PRODUCT_PATH_HINTS):
            doc_type = "product"
        else:
            return None

        # Adres, sitenin kendi yazdığı biçimde korunur; böylece her istekte
        # gereksiz bir yönlendirme adımı yaşanmaz.
        absolute = url if parts.netloc else urljoin(BASE_URL, parts.path)
        return DiscoveredUrl(
            url=absolute.split("?")[0].split("#")[0],
            doc_type=doc_type,
            discovery_method=discovery_method,
        )

    def parse_detail(self, html: str, url: str, hint: DiscoveredUrl) -> RawCampaign | None:
        """Detay sayfasını ayrıştırır.

        Args:
            html: Sayfanın HTML'i.
            url: Sayfanın adresi.
            hint: Keşiften gelen bağlam.

        Returns:
            Kampanya verisi; sayfa kampanya değilse veya başlık yoksa None.
        """
        if hint.doc_type != "campaign":
            # Ürün sayfaları PART 2'de işlenecek; ham HTML yine de arşivlendi.
            return None

        title = extract_title(html)
        if not title:
            return None

        body_text = clean_html(html, bank_code=self.bank_code, title=title)
        conditions = extract_section_text(html, CONDITION_KEYWORDS)
        exclusions = extract_section_text(html, EXCLUSION_KEYWORDS)

        # Oran/kademe tabloları PART 1'de yapısal olarak ayrıştırılmaz;
        # koşul metnine eklenerek veri kaybı önlenir (PART 2'de tabloya dönecek).
        table_text = self._tables_as_text(html)
        if table_text:
            conditions = f"{conditions}\n\n{table_text}" if conditions else table_text

        # Tarih gövde metninde serbest biçimde geçiyor ve başlangıçta çoğunlukla
        # yıl yazılmıyor ("16 Haziran - 31 Ağustos 2026"); bu durumda yıl bitişten
        # devralınır ve kesinlik "inferred" olur.
        start_date, end_date, precision = parse_date_range_tr(body_text)
        if precision == "unknown" and conditions:
            start_date, end_date, precision = parse_date_range_tr(conditions)

        return RawCampaign(
            external_slug=slug_from_url_path(url),
            title=title,
            source_url=url,
            description=self._first_paragraph(body_text),
            conditions_text=conditions,
            exclusions_text=exclusions,
            category=None,
            bank_category=hint.category_hint,
            segment=hint.segment_hint,
            start_date=start_date,
            end_date=end_date,
            date_precision=precision,
        )

    @staticmethod
    def _tables_as_text(html: str) -> str | None:
        """Sayfadaki tabloları `|` ayırıcılı metne çevirir."""
        tables = extract_tables(html)
        if not tables:
            return None
        return "\n\n".join(render_table_text(rows) for rows in tables)

    @staticmethod
    def _first_paragraph(text: str, *, max_length: int = 500) -> str | None:
        """Gövde metninin ilk anlamlı paragrafını açıklama olarak döndürür."""
        for line in text.split("\n"):
            candidate = normalize_text(line)
            if len(candidate) >= 40:
                return candidate[:max_length]
        return None
