"""Dünya Katılım scraper'ı.

Yapı canlı sitede doğrulandı (14 Ağustos 2026):

    Sitemap : /sitemap.xml        ← ASIL KEŞİF KAYNAĞI, 46 kampanya adresi
    Liste   : /kampanyalar        ← JavaScript, sunucu HTML'inde kampanya YOK
    Detay   : /kampanyalar/{slug}

⚠️ LİSTE SAYFASI KULLANILMAZ. 505 KB'lık sayfada sunucu tarafında tek bir
kampanya bağlantısı yok; kartlar JS ile yükleniyor ve "Daha Fazla" düğmesi
`javascript:void(0)`. Buna karşılık sitemap 46 kampanya adresi veriyor —
tarayıcıya hiç gerek kalmıyor.

⚠️ ÖNCEKİ ANALİZDEN SAPMA: "sitemap.xml gzip kodlanmış" DOĞRU DEĞİL, düz XML
geliyor. Yine de `app/scrapers/sitemap.py` magic byte denetimi yapıyor;
davranış değişirse gzip kendiliğinden açılır.

⚠️ ROBOTS.TXT'TEKİ SITEMAP SATIRI YANLIŞ ALAN ADINI gösteriyor
(`blueprint.com.tr`, HTTP 403). Kullanılmaz; sitemap adresi doğrudan
denenir ve aynı siteye ait olduğu doğrulanır.

⚠️ CAMELCASE SLUG: `altin-kesemTicari` gerçek bir adres. Yol küçük harfe
çevrilirse HTTP 404 alınır. `canonical_key()` yalnızca karşılaştırma için
kullanılır; istek daima özgün yazımla atılır.

⚠️ Sitemap adresleri `www.` ÖN EKSİZ geliyor (`https://dunyakatilim.com.tr/...`).
Aynı site denetimi `www.` yok sayar; aksi hâlde tüm adresler "dış bağlantı"
sayılıp keşif sıfır sonuç verir.

⚠️ KAMPANYA SAYFALARI SİLİNİYOR — ham HTML arşivi kritik.

⚠️ Tarihte SAAT var: "15 Haziran 2026 saat 00.01 – 15 Temmuz 2026 saat 23.59".
Ayrıştırma `parse_date_range_tr()`'a devredilir.

Varyant örnekleri (ürün adımı için): `arac-finansmani` / `cevre-dostu-arac-finansmani`,
`enerya-ihtiyac-finansmani` / `enerya-karz-i-hasen`.
"""

from __future__ import annotations

from datetime import date
from typing import Final
from urllib.parse import urlsplit

from app.core.normalization.date_tr import parse_date_range_tr
from app.core.normalization.text import normalize_text
from app.logging_config import get_logger
from app.processing.cleaner import clean_html, extract_section_text, extract_title
from app.scrapers.base import BaseScraper
from app.scrapers.models import DiscoveredUrl, RawCampaign
from app.scrapers.sitemap import extract_urls
from app.utils.slugify import slug_from_url_path
from app.utils.urls import dedupe_urls, is_same_site

logger = get_logger(__name__)

BASE_URL: Final[str] = "https://www.dunyakatilim.com.tr"
SITEMAP_URL: Final[str] = f"{BASE_URL}/sitemap.xml"

# Kampanya detaylarının yol ön eki.
CAMPAIGN_PREFIX: Final[str] = "/kampanyalar/"

# Sitemap'te İngilizce sürüm de bulunuyor (`/en/campaigns/...`); Türkçe
# içerikle aynı kampanyanın çevirisi olduğu için alınmaz.
EXCLUDED_PREFIXES: Final[tuple[str, ...]] = ("/en/",)

# Açıklama sayılması için gereken en az uzunluk. Bölüm başlıkları
# ("Kampanya Koşulları") ve menü girdileri bu eşiğin altında kalır.
MIN_DESCRIPTION_LENGTH: Final[int] = 80

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


class DunyaKatilimScraper(BaseScraper):
    """Dünya Katılım kampanya scraper'ı."""

    bank_code = "dunya_katilim"
    version = "1.0.0"

    def discover(self) -> list[DiscoveredUrl]:
        """Sitemap'ten kampanya adreslerini toplar.

        Tek istek yapılır. Liste sayfası JS ile yüklendiği için hiç
        çekilmez — çekilse bile sıfır kampanya döndürürdü.

        Returns:
            Keşfedilen kampanya adresleri (tekilleştirilmiş).
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

        # ⚠️ Ham BAYT verilir, metin değil: gzip denetimi baytlara bakıyor.
        adresler = extract_urls(fetch.content, same_site_as=BASE_URL)
        kampanyalar = [url for url in adresler if self._is_campaign_url(url)]

        if not kampanyalar:
            logger.warning(
                "sitemapte_kampanya_yok", banka=self.bank_code, adres_sayisi=len(adresler)
            )

        return [
            DiscoveredUrl(
                url=url,
                doc_type="campaign",
                segment_hint="bireysel",
                discovery_method="sitemap",
            )
            for url in dedupe_urls(kampanyalar)
        ]

    @staticmethod
    def _is_campaign_url(url: str) -> bool:
        """Adres bir kampanya detay sayfası mı?

        ⚠️ Yol küçük harfe ÇEVRİLMEZ: `altin-kesemTicari` gerçek bir slug.
        """
        if not is_same_site(url, BASE_URL):
            return False

        path = urlsplit(url).path.rstrip("/")
        if any(path.startswith(onek) for onek in EXCLUDED_PREFIXES):
            return False
        if not path.startswith(CAMPAIGN_PREFIX):
            return False
        # `/kampanyalar` kökünün kendisi kampanya değildir.
        return bool(path[len(CAMPAIGN_PREFIX) :])

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
        start_date, end_date, precision = self._parse_dates(conditions, body_text)

        return RawCampaign(
            external_slug=slug_from_url_path(url),
            title=title,
            source_url=url,
            description=self._first_paragraph(body_text, title),
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
        conditions: str | None, body_text: str
    ) -> tuple[date | None, date | None, str]:
        """Tarihi çıkarır; saat içeren biçim de kütüphaneye devredilir.

        Ör. "15 Haziran 2026 saat 00.01 – 15 Temmuz 2026 saat 23.59".
        """
        for kaynak in (conditions, body_text):
            if not kaynak:
                continue
            start, end, precision = parse_date_range_tr(kaynak)
            if precision != "unknown":
                return start, end, precision
        return None, None, "unknown"

    @staticmethod
    def _first_paragraph(text: str, title: str, *, max_length: int = 500) -> str | None:
        """Gövdenin ilk anlamlı paragrafını açıklama olarak döndürür.

        ⚠️ Sayfalarda ~800-1.500 kelimelik ağır boilerplate var; başlığın
        kendisi ve tek satırlık bölüm başlıkları açıklama sayılmaz.

        ⚠️ ARDIŞIK SATIRLAR BİRLEŞTİRİLİR. Kaynak HTML'de paragraf birden çok
        satıra sarılmış olabiliyor ve temizleyici bu satır sonlarını koruyor;
        satır satır bakan bir arama, uzun bir paragrafı "çok kısa" sayıp
        atlar ve açıklama boş kalır.
        """
        basliksiz = normalize_text(title)
        paragraf: list[str] = []

        for line in text.split("\n"):
            aday = normalize_text(line)
            if not aday or aday == basliksiz:
                # Boş satır paragrafı bitirir; biriken yeterliyse döndürülür.
                if len(" ".join(paragraf)) >= MIN_DESCRIPTION_LENGTH:
                    break
                paragraf.clear()
                continue

            paragraf.append(aday)
            if len(" ".join(paragraf)) >= MIN_DESCRIPTION_LENGTH:
                break

        birlesik = " ".join(paragraf)
        return birlesik[:max_length] if len(birlesik) >= MIN_DESCRIPTION_LENGTH else None
