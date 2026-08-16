"""Albaraka Türk scraper'ı.

Yapı canlı sitede doğrulandı (14 Ağustos 2026):

    Liste : /tr/kampanyalar
    Detay : /tr/kampanyalar/detay/{slug}

⚠️ ÖNCEKİ ANALİZDEN SAPMA — ÖLÇÜLDÜ: "Liste rotasyonlu, aynı adres her
istekte farklı kart seti döndürüyor, 12-15 kez çekip birleşimini al"
DOĞRU DEĞİL. Aynı adres arka arkaya üç kez çekildi; üçünde de AYNI 12 slug
geldi (birleşim = kesişim = 12). Bu yüzden tek istek yapılır.

Rotasyon geri gelirse sessizce veri kaybetmemek için `MAX_LISTING_ROUNDS`
tur desteği bırakıldı: yeni slug gelmeyi kesene kadar tekrar çekilir,
`DRY_ROUNDS` tur boyunca yeni slug gelmezse durulur. Varsayılan davranışta
ikinci tur yeni slug getirmediği için tek ek istekle biter.

⚠️ ROBOTS ENGELİ — UYULUR, AŞILMAZ: `Disallow: /*slug` kuralı geçmiş
kampanya arşivini (`?slug=` parametreli adresler) kapatıyor. Bu adreslere
HİÇ istek atılmaz; kapsam daralması `data/robots_report.md`'de
gerekçelendirilir. `Disallow: /tr/ticari-ve-kurumsal*` nedeniyle kurumsal
ürün sayfaları da kapsam dışıdır.

⚠️ `albarakaturk.com.tr` adresi 302 ile `albaraka.com.tr` adresine
yönleniyor; `Fetcher` cross-host yönlendirmeyi takip eder.

⚠️ SLUG SONEKLERİ NORMALİZE EDİLMEZ: `-1`, `_1`, `-14`, `-1_1` gibi ekler
farklı kampanya dönemlerini ayırt ediyor (`...ispark-kampanyasi-1`,
`...paylasim-oranlari-10`). Kırpılırsa kayıtlar birbirinin üzerine yazılır.

Tarih tek ve temiz: `DD.MM.YYYY - DD.MM.YYYY` → `date_precision="exact"`.
"""

from __future__ import annotations

from datetime import date
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

BASE_URL: Final[str] = "https://www.albaraka.com.tr"
LISTING_URL: Final[str] = f"{BASE_URL}/tr/kampanyalar"

# Detay adreslerini ayırt eden yol.
DETAIL_PREFIX: Final[str] = "/tr/kampanyalar/detay/"

# Rotasyon güvenlik ağı: en fazla bu kadar tur çekilir.
MAX_LISTING_ROUNDS: Final[int] = 12
# Bu kadar tur üst üste yeni slug gelmezse durulur.
DRY_ROUNDS: Final[int] = 2

# ⚠️ robots.txt yasağı. Bu parça geçen hiçbir adrese istek atılmaz; `Fetcher`
# zaten robots'a uyuyor, burada ayrıca elenmesi keşfin boşuna istek
# üretmesini engeller.
ROBOTS_BLOCKED_MARKERS: Final[tuple[str, ...]] = ("slug=", "/tr/ticari-ve-kurumsal")

CONDITION_KEYWORDS: Final[tuple[str, ...]] = (
    "kampanyaya katılım adımları",
    "kampanyadan kimler faydalanabilir",
    "ek kampanya detayları",
    "kampanya koşul",
    "koşullar",
)

EXCLUSION_KEYWORDS: Final[tuple[str, ...]] = (
    "kampanya dışı",
    "hariç",
    "kapsam dışı",
    "istisna",
)

DATE_SECTION_KEYWORDS: Final[tuple[str, ...]] = (
    "kampanya başlangıç ve bitiş tarihi",
    "başlangıç ve bitiş tarihi",
    "kampanya tarihi",
)


class AlbarakaScraper(BaseScraper):
    """Albaraka Türk kampanya scraper'ı."""

    bank_code = "albaraka"
    version = "1.0.0"

    def discover(self) -> list[DiscoveredUrl]:
        """Liste sayfasını yeni kampanya gelmeyi kesene kadar tarar.

        Ölçülen davranışta liste sabittir; döngü ikinci turda biter. Rotasyon
        geri gelirse aynı döngü kendiliğinden birleşimi toplar.

        Returns:
            Keşfedilen kampanya adresleri (tekilleştirilmiş).
        """
        discovered: list[DiscoveredUrl] = []
        seen: set[str] = set()
        kuru_tur = 0

        for tur in range(1, MAX_LISTING_ROUNDS + 1):
            yeni = 0
            for url in self._campaign_links(LISTING_URL):
                if url in seen:
                    continue
                seen.add(url)
                yeni += 1
                discovered.append(
                    DiscoveredUrl(
                        url=url,
                        doc_type="campaign",
                        segment_hint="bireysel",
                        discovery_method="listing",
                    )
                )

            if yeni == 0:
                kuru_tur += 1
                if kuru_tur >= DRY_ROUNDS:
                    logger.info(
                        "liste_durdu", banka=self.bank_code, tur=tur, toplam=len(discovered)
                    )
                    break
            else:
                kuru_tur = 0
                logger.info("liste_turu", banka=self.bank_code, tur=tur, yeni=yeni)

        return discovered

    def _campaign_links(self, listing_url: str) -> list[str]:
        """Liste sayfasındaki kampanya detay adreslerini çıkarır."""
        fetch = self.fetcher.fetch(listing_url)
        if not fetch.is_success or not fetch.html:
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

        return links

    @staticmethod
    def _is_campaign_url(url: str) -> bool:
        """Adres bir kampanya detay sayfası mı?

        robots.txt ile yasaklanmış kalıplar burada da elenir: yasağa uymak
        yalnızca `Fetcher`'ın işi değil, keşfin de o adresleri hiç
        önermemesi gerekir.
        """
        if not is_same_site(url, BASE_URL):
            return False
        if any(isaret in url for isaret in ROBOTS_BLOCKED_MARKERS):
            return False

        path = urlsplit(url).path.rstrip("/")
        if not path.startswith(DETAIL_PREFIX):
            return False
        # `/detay` kökünün kendisi kampanya değildir.
        return bool(path[len(DETAIL_PREFIX) :])

    def parse_detail(self, html: str, url: str, hint: DiscoveredUrl) -> RawCampaign | None:
        """Kampanya detay sayfasını ayrıştırır.

        Args:
            html: Detay sayfasının HTML'i.
            url: Sayfanın adresi.
            hint: Keşiften gelen bağlam.

        Returns:
            Çıkarılan kampanya; başlık bulunamazsa None.
        """
        title = extract_title(html)
        if not title:
            return None

        body_text = clean_html(html, bank_code=self.bank_code, title=title)
        conditions = extract_section_text(html, CONDITION_KEYWORDS)
        start_date, end_date, precision = self._parse_dates(html, conditions, body_text)

        return RawCampaign(
            # ⚠️ Sonekler (-1, _1, -14) korunur; farklı dönem demektir.
            external_slug=slug_from_url_path(url),
            title=title,
            source_url=url,
            description=self._first_paragraph(body_text),
            conditions_text=conditions,
            exclusions_text=extract_section_text(html, EXCLUSION_KEYWORDS),
            category=None,
            bank_category=hint.category_hint,
            segment=hint.segment_hint,
            start_date=start_date,
            end_date=end_date,
            date_precision=precision,
            is_archived=False,
        )

    @staticmethod
    def _parse_dates(
        html: str, conditions: str | None, body_text: str
    ) -> tuple[date | None, date | None, str]:
        """Tarihi "Kampanya Başlangıç ve Bitiş Tarihi" bölümünden çıkarır."""
        for kaynak in (extract_section_text(html, DATE_SECTION_KEYWORDS), conditions, body_text):
            if not kaynak:
                continue
            start, end, precision = parse_date_range_tr(kaynak)
            if precision != "unknown":
                return start, end, precision
        return None, None, "unknown"

    @staticmethod
    def _first_paragraph(text: str, *, max_length: int = 500) -> str | None:
        """Gövde metninin ilk anlamlı paragrafını açıklama olarak döndürür."""
        for line in text.split("\n"):
            aday = normalize_text(line)
            if len(aday) >= 60:
                return aday[:max_length]
        return None
