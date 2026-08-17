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
from app.utils.slugify import slug_from_url_path
from app.utils.urls import is_same_site

logger = get_logger(__name__)

BASE_URL: Final[str] = "https://www.vakifkatilim.com.tr"

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


class VakifKatilimScraper(BaseScraper):
    """Vakıf Katılım kampanya scraper'ı."""

    bank_code = "vakif_katilim"
    version = "1.0.0"

    def discover(self) -> list[DiscoveredUrl]:
        """İki segmentin güncel ve arşiv listelerini tarar.

        Returns:
            Keşfedilen kampanya adresleri (tekilleştirilmiş).
        """
        discovered: list[DiscoveredUrl] = []
        seen: set[str] = set()

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
