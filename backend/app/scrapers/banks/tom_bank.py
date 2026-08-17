"""T.O.M. Katılım Bankası scraper'ı.

⚠️ PROJENİN EN BÜYÜK VERİ TUZAĞI — DOMAIN SEÇİMİ.
Canlı ölçüm (14 Ağustos 2026):

    tombankhadi.com        -> ✅ ASIL KAYNAK. sitemap.xml 224 kayıt,
                              76 tekil kampanya.
    www.tombank.com.tr     -> kurumsal vitrin. `/kampanyalar` HTTP 404,
                              robots.txt yok. Kampanya listesi bulunamadı.
    tombank.com            -> 114 baytlık park sayfası, `<title>` bile yok.
                              BANKANIN SİTESİ DEĞİLDİR.
    hadiyanindakibanka.com -> AYNA. Aynı liste, `rel=canonical` kendini
                              gösteriyor. Taranmıyor (aşağıda gerekçe).
    haditombank.com        -> ölü, atlanır.

Yalnızca kurumsal siteye bakılırsa kampanyaların neredeyse tamamı kaçırılır.

⚠️ AYNI KAMPANYA İKİ AYRI YOL ÖN EKİYLE YAYIMLANIYOR — ölçüldü:

    /kampanyalar/{slug}                     -> 76 slug
    /cok-kazananlar-kulubu-kampanya/{slug}  -> 76 slug  (76'sı da AYNI)

Örtüşme tam: ikinci ön ekte tek bir özgün kampanya yok. Yol bazında sayılırsa
157 kayıt oluşur, doğrusu 81'dir (76 kampanya + 5 ayrıcalık sayfası). Bu
yüzden tekilleştirme SLUG üzerinden yapılır ve kanonik ön ek `/kampanyalar/`
tercih edilir. Yol bazlı tekilleştirme bu hatayı YAKALAMAZ: adresler farklı.

⚠️ `/hadi-kredi-karti-ayricaliklari/{slug}` sayfaları yalnızca sitemap'ten
bulunuyor; kök sayfasına bağlantı yok.

AYNA DOMAIN NEDEN TARANMIYOR: `hadiyanindakibanka.com` üzerindeki liste
sayfası `tombankhadi.com` ile birebir aynı bağlantıları veriyor ve
`rel=canonical` kendi adresini gösteriyor. Slug tekilleştirmesi zaten
hepsini eleyeceği için taramak yalnızca gereksiz istek üretir. Ayna özgün
içerik yayımlamaya başlarsa `MIRROR_DOMAIN` sabiti üzerinden eklenebilir.

⚠️ Listeleme `/hadi-kazan/kampanyalar` altında ama detaylar `/kampanyalar/`
KÖKÜNDE; göreli adres çözümlemesi buna dikkat etmeli. Keşif sitemap
üzerinden yapıldığı için bu tuzak devre dışı kalıyor.
"""

from __future__ import annotations

from typing import Final
from urllib.parse import urlsplit

from app.core.normalization.text import normalize_text
from app.logging_config import get_logger
from app.processing.cleaner import clean_html, extract_section_text, extract_title
from app.scrapers.base import BaseScraper
from app.scrapers.models import DiscoveredUrl, RawCampaign
from app.scrapers.sitemap import extract_urls
from app.utils.slugify import slug_from_url_path
from app.utils.urls import is_same_site

logger = get_logger(__name__)

BASE_URL: Final[str] = "https://tombankhadi.com"
SITEMAP_URL: Final[str] = f"{BASE_URL}/sitemap.xml"

# Ayna domain — şu an taranmıyor, gerekçe modül başlığında.
MIRROR_DOMAIN: Final[str] = "https://www.hadiyanindakibanka.com"

# Kampanya taşıyan yol ön ekleri. SIRA ÖNEMLİDİR: aynı slug birden fazla
# ön ekte geçtiğinde listedeki İLK ön ek kanonik sayılır.
CAMPAIGN_PREFIXES: Final[tuple[str, ...]] = (
    "/kampanyalar/",
    "/cok-kazananlar-kulubu-kampanya/",
    "/hadi-kredi-karti-ayricaliklari/",
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


# Ürün sayfaları — arşivlenmiş sitemap'ten doğrulandı (17 Ağustos 2026).
PRODUCT_PAGES: Final[tuple[tuple[str, str, str | None], ...]] = (
    ("/hadi-hesap/hadi-hesap", "birikim_katilma_hesabi", "yok"),
    ("/hadi-hesap/gunluk-kazandiran-hesap", "birikim_katilma_hesabi", "yok"),
    ("/hadi-vadeli-hesap", "birikim_katilma_hesabi", "yok"),
    ("/hadi-hesap/altin-biriktiren-hesap", "yatirim_urunu", "diger"),
    ("/hadi-hesap/gumus-hesabi", "yatirim_urunu", "diger"),
    ("/hadi-kartlarim/hadi-kredi-karti", "kart", "yok"),
    ("/hadi-kartlarim/hadi-black-kredi-karti", "kart", "yok"),
    ("/hadi-kartlarim/hadi-banka-karti", "kart", "yok"),
    ("/hadi-kartlarim/hadi-sanal-kart", "kart", "yok"),
)


class TomBankScraper(BaseScraper):
    """T.O.M. Katılım Bankası kampanya scraper'ı."""

    bank_code = "tom_bank"
    version = "1.0.0"
    product_base_url = BASE_URL
    product_pages = PRODUCT_PAGES

    def discover(self) -> list[DiscoveredUrl]:
        """Sitemap'ten kampanya adreslerini toplar ve SLUG bazında tekilleştirir.

        Tek istek yapılır.

        Returns:
            Keşfedilen kampanya adresleri.
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

        adresler = extract_urls(fetch.content, same_site_as=BASE_URL)
        return self._dedupe_by_slug(adresler)

    def _dedupe_by_slug(self, adresler: list[str]) -> list[DiscoveredUrl]:
        """Aynı kampanyanın farklı ön eklerdeki kopyalarını teke indirir.

        ⚠️ Yol bazlı tekilleştirme YETMEZ: `/kampanyalar/x` ile
        `/cok-kazananlar-kulubu-kampanya/x` farklı adreslerdir ama aynı
        kampanyadır. Ölçümde 76 kampanyanın tamamı ikinci ön ekte de vardı.

        Args:
            adresler: Sitemap'ten gelen adresler.

        Returns:
            Slug başına tek kayıt; kanonik ön eki olan yazım tercih edilir.
        """
        # slug -> (ön ek sırası, adres)
        secilen: dict[str, tuple[int, str]] = {}

        for url in adresler:
            onek_sirasi = self._prefix_rank(url)
            if onek_sirasi is None:
                continue
            slug = self._slug(url)
            if not slug:
                continue

            mevcut = secilen.get(slug)
            if mevcut is None or onek_sirasi < mevcut[0]:
                secilen[slug] = (onek_sirasi, url)

        atlanan = len(adresler) - len(secilen)
        if atlanan > 0:
            logger.info(
                "slug_tekillestirme",
                banka=self.bank_code,
                gelen=len(adresler),
                tekil=len(secilen),
            )

        return [
            DiscoveredUrl(
                url=url,
                doc_type="campaign",
                segment_hint="bireysel",
                discovery_method="sitemap",
            )
            for _, url in sorted(secilen.values())
        ]

    @staticmethod
    def _prefix_rank(url: str) -> int | None:
        """Adresin kampanya ön eki sırasını döndürür; kampanya değilse None."""
        if not is_same_site(url, BASE_URL):
            return None
        path = urlsplit(url).path.rstrip("/")
        for sira, onek in enumerate(CAMPAIGN_PREFIXES):
            # Ön ekin KÖKÜ (ör. `/kampanyalar`) kampanya değildir.
            if path.startswith(onek) and path != onek.rstrip("/"):
                return sira
        return None

    @staticmethod
    def _slug(url: str) -> str:
        """Adresin son yol parçasını döndürür."""
        return urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]

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
            is_archived=False,
        )

    @staticmethod
    def _first_paragraph(text: str, title: str, *, max_length: int = 500) -> str | None:
        """Gövdenin ilk anlamlı paragrafını açıklama olarak döndürür."""
        basliksiz = normalize_text(title)
        for line in text.split("\n"):
            aday = normalize_text(line)
            if len(aday) >= 60 and aday != basliksiz:
                return aday[:max_length]
        return None
