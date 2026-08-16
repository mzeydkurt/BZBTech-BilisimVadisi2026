"""Türkiye Emlak Katılım scraper'ı.

NEDEN İLK BU BANKA: Analizde en erişilebilir hedef. robots.txt tamamen açık
(`Allow: /`, hiç Disallow yok), WAF yok, sayfalar sunucuda render ediliyor,
sayfalama ve filtre yok. Altyapıyı doğrulamak için ideal.

⚠️ ARŞİV YOK: Biten kampanyalar siteden tamamen kalkıyor. Ham HTML arşivi
olmadan o veri bir daha elde edilemez — bu yüzden her yanıt diske yazılır.
"""

from __future__ import annotations

import re
from typing import Final
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from app.core.normalization.date_tr import parse_date_range_tr
from app.core.normalization.text import normalize_text
from app.logging_config import get_logger
from app.processing.cleaner import clean_html, extract_section_text, extract_title
from app.scrapers.base import BaseScraper
from app.scrapers.models import DiscoveredUrl, RawCampaign
from app.utils.slugify import slug_from_url_path
from app.utils.urls import is_same_site

logger = get_logger(__name__)

BASE_URL: Final[str] = "https://www.emlakkatilim.com.tr"

# Keşif yalnızca 2 istek gerektirir; segment bilgisi listeleme adresinden gelir
# çünkü detay sayfasında segment etiketi bulunmuyor.
LISTING_PAGES: Final[tuple[tuple[str, str], ...]] = (
    (f"{BASE_URL}/tr/bireysel/kampanyalar", "bireysel"),
    (f"{BASE_URL}/tr/kurumsal/kampanyalar", "kurumsal"),
)

# SMS ile katılım: "AKARYAKIT yazıp 6026'ya gönderin"
#
# Numaradan sonraki ek `\w{0,3}` ile esnek bırakıldı: Türkçe yönelme eki sesli
# uyumuna göre değişiyor ("6026'ya", "6026'ye", "6026'a"). Tek harflik bir
# kalıp gerçek metinlerin çoğunu kaçırırdı.
#
# Anahtar kelime BÜYÜK HARF olmalıdır (IGNORECASE kullanılmaz): aksi hâlde
# "kodu yazıp ... gönderin" gibi cümlelerde sıradan kelimeler anahtar sanılır.
SMS_RE: Final[re.Pattern[str]] = re.compile(
    r"\b([A-ZÇĞİÖŞÜ]{3,20})\s+[Yy]az\w*\s+(\d{4})['’]?\w{0,3}\s+[Gg][öo]nder"
)

# Kupon/kampanya kodu: "emlak20 kodunu kullanın"
COUPON_RE: Final[re.Pattern[str]] = re.compile(
    r"\b([a-zA-Z][a-zA-Z0-9]{3,19})\s+kod\w*\s+(?:kullan|gir|yaz)",
)

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


class EmlakKatilimScraper(BaseScraper):
    """Türkiye Emlak Katılım kampanya scraper'ı."""

    bank_code = "emlak_katilim"
    version = "1.0.0"

    def discover(self) -> list[DiscoveredUrl]:
        """Bireysel ve kurumsal listeleme sayfalarından kampanya adreslerini toplar.

        ⚠️ Slug BAŞLIKTAN ÜRETİLMEZ. Analizde doğrulandı: başlıklarda Türkçe
        karakter ve kesme işareti var, bankanın normalize etme kuralı tahmin
        edilemiyor ve üretilen adres 404 veriyor. `<a href>` değeri birebir okunur.

        Returns:
            Keşfedilen kampanya adresleri (tekilleştirilmiş).
        """
        discovered: list[DiscoveredUrl] = []
        seen: set[str] = set()

        for listing_url, segment in LISTING_PAGES:
            fetch = self.fetcher.fetch(listing_url)
            if not fetch.is_success or not fetch.html:
                logger.warning(
                    "listeleme_alinamadi",
                    banka=self.bank_code,
                    url=listing_url,
                    durum=fetch.status_code,
                    hata=fetch.error,
                )
                continue

            for url in self._extract_campaign_links(fetch.html, listing_url):
                if url in seen:
                    continue
                seen.add(url)
                discovered.append(
                    DiscoveredUrl(
                        url=url,
                        doc_type="campaign",
                        segment_hint=segment,
                        discovery_method="listing",
                    )
                )

        return discovered

    def _extract_campaign_links(self, html: str, listing_url: str) -> list[str]:
        """Listeleme sayfasındaki kampanya bağlantılarını çıkarır.

        Args:
            html: Listeleme sayfasının HTML'i.
            listing_url: Göreli adreslerin çözümleneceği temel adres.

        Returns:
            Mutlak kampanya adresleri.
        """
        soup = BeautifulSoup(html, "lxml")
        listing_path = urlsplit(listing_url).path.rstrip("/")
        links: list[str] = []

        for anchor in soup.find_all("a", href=True):
            href = str(anchor["href"]).strip()
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue

            absolute = urljoin(listing_url, href)
            parts = urlsplit(absolute)

            # Yalnızca aynı sitedeki kampanya detay sayfaları.
            # Karşılaştırma `www.` ön ekini yok sayar: banka eski alan adından
            # (emlakbank.com.tr) yönlendirme yapıyor ve yönlendirme sonrası
            # adres ön ekli/ön eksiz farklılık gösterebiliyor.
            if not is_same_site(absolute, BASE_URL):
                continue
            path = parts.path.rstrip("/")
            if "kampanya" not in path or path == listing_path:
                continue
            # Listeleme sayfasının kendisine dönen bağlantılar elenir.
            if path.endswith("/kampanyalar"):
                continue

            links.append(absolute)

        return links

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
        exclusions = extract_section_text(html, EXCLUSION_KEYWORDS)

        # Tarih yapısal alanda DEĞİL, koşul metninin içinde serbest metin olarak
        # geçiyor. Önce koşullar taranır, bulunamazsa tüm gövdeye bakılır.
        start_date, end_date, precision = parse_date_range_tr(conditions or "")
        if precision == "unknown":
            start_date, end_date, precision = parse_date_range_tr(body_text)

        sms_keyword, sms_number = self._parse_sms(body_text)
        coupon = self._parse_coupon(body_text)

        participation_method: str | None = None
        if sms_number:
            participation_method = "sms"
        elif coupon:
            participation_method = "kod"

        return RawCampaign(
            external_slug=slug_from_url_path(url),
            title=title,
            source_url=url,
            description=self._first_paragraph(body_text),
            conditions_text=conditions,
            exclusions_text=exclusions,
            # Sitede kategori etiketi YOK — PART 3'te sınıflandırılacak.
            category=None,
            bank_category=hint.category_hint,
            segment=hint.segment_hint,
            start_date=start_date,
            end_date=end_date,
            date_precision=precision,
            participation_method=participation_method,
            sms_keyword=sms_keyword,
            sms_number=sms_number,
            coupon_code=coupon,
        )

    @staticmethod
    def _parse_sms(text: str) -> tuple[str | None, str | None]:
        """SMS ile katılım bilgisini çıkarır ("AKARYAKIT yazıp 6026'ya gönderin")."""
        match = SMS_RE.search(text)
        if not match:
            return None, None
        return match.group(1).upper(), match.group(2)

    @staticmethod
    def _parse_coupon(text: str) -> str | None:
        """Kupon/kampanya kodunu çıkarır."""
        match = COUPON_RE.search(text)
        return match.group(1) if match else None

    @staticmethod
    def _first_paragraph(text: str, *, max_length: int = 500) -> str | None:
        """Gövde metninin ilk anlamlı paragrafını açıklama olarak döndürür."""
        for line in text.split("\n"):
            candidate = normalize_text(line)
            if len(candidate) >= 40:
                return candidate[:max_length]
        return None
