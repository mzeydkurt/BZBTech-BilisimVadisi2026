"""Kuveyt Türk scraper'ı.

Yapı canlı sitede doğrulandı (14 Ağustos 2026):

    Liste : /kampanyalar/{segment}/{kategori}
    Arşiv : /kampanyalar/kampanya-arsivi
    Detay : /kampanyalar/{segment}/{kategori}/{slug}   ← ÜÇ SEVİYE

    segment: kendim-icin -> bireysel  ·  isim-icin -> kurumsal

✅ SEGMENT VE KATEGORİ ADRESTEN BEDAVA. Detay adresinin kendisi hem segmenti
hem bankanın kendi kategori etiketini taşıyor; ikisi de çıkarım değil,
kaynak veridir.

⚠️ SAYFALAMA YOK. Her liste sayfası tam 9 kampanya gösteriyor, gerisi
"Daha Fazla Yükle" düğmesinin arkasında ve `?page=2` çalışmıyor. Sunucu
HTML'inden alınabilecek kayıtlar alınır; tarayıcı gerektiren kısım
kapsam dışıdır ve eksik kalırsa çalıştırma `partial` olur.

⚠️ SITEMAP'TE `/kampanyalar/` YOK — yedek keşif yolu bulunmuyor. Liste
sayfaları tek kaynaktır.

⚠️ Slug'lar 100+ karakter olabiliyor
(`mobilden-kuveyt-turklu-olan-esnaf-ciftci-ve-sahis-firmalarina-ozel-1000-tl-hediye`).
Başlıktan türetme denemesi anlamsız; `href` birebir okunur.

⚠️ ORAN TABLOSU YOK. Oran ve taksit bilgisi serbest metinde geçiyor;
`conditions_text` içinde ham olarak saklanır.
"""

from __future__ import annotations

import json
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

BASE_URL: Final[str] = "https://www.kuveytturk.com.tr"

# JSON kampanya ucu. Liste sayfası "Daha Fazla Yükle" arkasındaki kayıtları
# vermiyor ve kategori başına tam 9'da kesiliyordu; bu uç `StartDate`/`EndDate`
# alanlarını YAPISAL olarak döndürüyor.
#
# ⚠️ Adres WAF arkasında ve hex token taşıyor; rotasyona girerse uç sessizce
# boşa döner. Bu yüzden YEDEKLİ kullanılır: uç çalışmazsa liste sayfası
# yolunun tamamı yine işler. robots.txt bu yolu engellemiyor (ölçüldü).
CAMPAIGN_API_URL: Final[str] = (
    f"{BASE_URL}/ck0d84?12078A5155AB8EB05557BBCAD58BCB84&p1=1176&p2=&p5=false&p6=&p7=&p8=false"
)

CAMPAIGN_ROOT: Final[str] = "/kampanyalar"

# Adresteki segment parçası → (veri modeli segmenti, o segmentin kategorileri).
SEGMENTS: Final[dict[str, tuple[str, tuple[str, ...]]]] = {
    "kendim-icin": (
        "bireysel",
        (
            "seyahat-kampanyalari",
            "kart-kampanyalari",
            "musteri-ol-kampanyalari",
            "finansman-kampanyalari",
        ),
    ),
    "isim-icin": (
        "kurumsal",
        (
            "kart-kampanyalari",
            "kobi-kampanyalari",
            "musteri-ol-kampanyalari",
            "pos-kampanyalari",
        ),
    ),
}

# Arşiv sayfası — önceki analizde yoktu, canlı sitede bulundu.
ARCHIVE_PATH: Final[str] = f"{CAMPAIGN_ROOT}/kampanya-arsivi"

# Kampanya detayı SAYILMAYAN yollar: segment kökleri ve arşiv listesi.
NON_DETAIL_PATHS: Final[frozenset[str]] = frozenset(
    {CAMPAIGN_ROOT, ARCHIVE_PATH, *(f"{CAMPAIGN_ROOT}/{s}" for s in SEGMENTS)}
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


# Ürün/finansman sayfaları. Adresler SITEMAP'TEN doğrulandı (17 Ağustos 2026);
# düz sitemap, 3480 adres.
#
# ⚠️ Yalnızca `/kendim-icin/` (bireysel) alındı; `/isim-icin/` ticari taraf
# şartname kapsamının dışında tutuldu.
_F = "/kendim-icin/finansmanlar"
_H = "/kendim-icin/hesaplar"

PRODUCT_PAGES: Final[tuple[tuple[str, str, str | None], ...]] = (
    # ── Konut ──
    (f"{_F}/konut-finansmanlari/konut-finansmani", "konut_finansmani", "konut"),
    (f"{_F}/konut-finansmanlari/ilk-evim-konut-finansmani", "konut_finansmani", "konut"),
    (f"{_F}/konut-finansmanlari/arsa-finansmani", "konut_finansmani", "konut"),
    (f"{_F}/konut-finansmanlari/2b-finansmani", "konut_finansmani", "konut"),
    (f"{_F}/konut-finansmanlari/is-yeri-finansmani", "isyeri_finansmani", "konut"),
    (
        f"{_F}/konut-finansmanlari/gurbetten-silaya-gayrimenkul-finansmani",
        "konut_finansmani",
        "konut",
    ),
    (f"{_F}/surdurulebilir-finansmanlar/yesil-konut-finansmani", "konut_finansmani", "konut"),
    # ── Taşıt ──
    (f"{_F}/arac-finansmanlari/arac-finansmani", "tasit_finansmani", "tasit"),
    (f"{_F}/arac-finansmanlari/dijital-arac-finansmani", "tasit_finansmani", "tasit"),
    (f"{_F}/arac-finansmanlari/motosiklet-finansmani", "tasit_finansmani", "tasit"),
    (f"{_F}/arac-finansmanlari/dijital-motosiklet-finansmani", "tasit_finansmani", "tasit"),
    (f"{_F}/arac-finansmanlari/togg-finansmani", "tasit_finansmani", "tasit"),
    (
        f"{_F}/surdurulebilir-finansmanlar/surdurulebilir-arac-finansmani",
        "tasit_finansmani",
        "tasit",
    ),
    # ── İhtiyaç ──
    (f"{_F}/ihtiyac-finansmanlari/ihtiyac-kart", "ihtiyac_finansmani", "yok"),
    (f"{_F}/ihtiyac-finansmanlari/egitim-finansmani", "ihtiyac_finansmani", "yok"),
    (f"{_F}/ihtiyac-finansmanlari/hac-umre-finansmani", "ihtiyac_finansmani", "yok"),
    (f"{_F}/ihtiyac-finansmanlari/kira-finansmani", "ihtiyac_finansmani", "yok"),
    (f"{_F}/ihtiyac-finansmanlari/seyahat-finansmani", "ihtiyac_finansmani", "yok"),
    (f"{_F}/ihtiyac-finansmanlari/bisiklet-finansmani", "ihtiyac_finansmani", "yok"),
    (f"{_F}/ihtiyac-finansmanlari/kazancli-fon-finansmani", "ihtiyac_finansmani", "diger"),
    (f"{_F}/ihtiyac-finansmanlari/tekne-tuketici-finansmani", "ihtiyac_finansmani", "diger"),
    (
        f"{_F}/ihtiyac-finansmanlari/elektrikli-arac-sarj-unitesi-finansmani",
        "ihtiyac_finansmani",
        "yok",
    ),
    (f"{_F}/surdurulebilir-finansmanlar/cati-ges-finansmani", "ihtiyac_finansmani", "diger"),
    # ── Alışveriş finansmanı ──
    (f"{_F}/alisveris-finansmanlari/alisveris-finansmani", "ihtiyac_finansmani", "yok"),
    (f"{_F}/alisveris-finansmanlari/taksitlio-alisveris-finansmani", "ihtiyac_finansmani", "yok"),
    (f"{_F}/alisveris-finansmanlari/trendyol-alisveris-finansmani", "ihtiyac_finansmani", "yok"),
    (f"{_F}/alisveris-finansmanlari/hepsiburada-alisveris-finansmani", "ihtiyac_finansmani", "yok"),
    (f"{_F}/alisveris-finansmanlari/teknosa-alisveris-finansmani", "ihtiyac_finansmani", "yok"),
    (f"{_F}/alisveris-finansmanlari/lc-waikiki-alisveris-finansmani", "ihtiyac_finansmani", "yok"),
    # ── Katılma hesapları ──
    (f"{_H}/katilma-hesaplari/katilma-hesabi", "birikim_katilma_hesabi", "yok"),
    (f"{_H}/katilma-hesaplari/dijital-katilma-hesabi", "birikim_katilma_hesabi", "yok"),
    (f"{_H}/katilma-hesaplari/birikimli-katilma-hesabi", "birikim_katilma_hesabi", "yok"),
    (
        f"{_H}/katilma-hesaplari/ara-donem-kar-payi-odemeli-hesaplar",
        "birikim_katilma_hesabi",
        "yok",
    ),
    (f"{_H}/katilma-hesaplari/guvenceli-birikim-hesabi", "birikim_katilma_hesabi", "yok"),
    (f"{_H}/katilma-hesaplari/hos-geldin-katilma-hesabi", "birikim_katilma_hesabi", "yok"),
    (f"{_H}/katilma-hesaplari/ceyiz-hesabi", "birikim_katilma_hesabi", "yok"),
    (f"{_H}/katilma-hesaplari/konut-hesabi", "birikim_katilma_hesabi", "yok"),
    (f"{_H}/katilma-hesaplari/yuvam-tl-katilma-hesabi", "birikim_katilma_hesabi", "yok"),
    (f"{_H}/katilma-hesaplari/sepet-hesap", "birikim_katilma_hesabi", "yok"),
    (f"{_H}/katilma-hesaplari/incir-katilma-hesabi", "birikim_katilma_hesabi", "yok"),
    (f"{_H}/diger-kiymetli-maden-hesaplari/gumus-hesap", "yatirim_urunu", "diger"),
    (f"{_H}/diger-kiymetli-maden-hesaplari/platin-hesap", "yatirim_urunu", "diger"),
)


class KuveytTurkScraper(BaseScraper):
    """Kuveyt Türk kampanya scraper'ı."""

    bank_code = "kuveyt_turk"
    version = "1.0.0"
    product_base_url = BASE_URL
    product_pages = PRODUCT_PAGES

    def discover(self) -> list[DiscoveredUrl]:
        """Segment × kategori liste sayfalarını ve arşivi tarar.

        Returns:
            Keşfedilen kampanya adresleri (tekilleştirilmiş).
        """
        discovered: list[DiscoveredUrl] = []
        seen: set[str] = set()

        for url in self._api_links():
            if url in seen:
                continue
            seen.add(url)
            discovered.append(
                DiscoveredUrl(
                    url=url,
                    doc_type="campaign",
                    category_hint=self.category_from_url(url),
                    segment_hint=self.segment_from_url(url),
                    discovery_method="listing",
                )
            )

        for listing_url, arsiv in self._listing_pages():
            for url in self._campaign_links(listing_url):
                if url in seen:
                    continue
                seen.add(url)
                discovered.append(
                    DiscoveredUrl(
                        url=url,
                        doc_type="campaign",
                        # ✅ İkisi de adresten okunur.
                        category_hint=self.category_from_url(url),
                        segment_hint=self.segment_from_url(url),
                        discovery_method="archive" if arsiv else "listing",
                    )
                )

        return discovered

    def _api_links(self) -> list[str]:
        """JSON ucundaki kampanya adreslerini döndürür.

        ⚠️ Uç çalışmazsa (WAF yolu rotasyona girdiyse, JSON bozuksa) BOŞ LİSTE
        döner ve liste sayfası yolu devreye girer. Banka hiçbir durumda boş
        kalmaz; eksiklik `partial` olarak değil, daha az kayıt olarak görünür.

        Returns:
            Mutlak kampanya adresleri; uç kullanılamazsa boş liste.
        """
        fetch = self.fetcher.fetch(CAMPAIGN_API_URL)
        if not fetch.is_success or not fetch.html:
            logger.info(
                "kampanya_ucu_kullanilamadi",
                banka=self.bank_code,
                durum=fetch.status_code,
                hata=fetch.error,
            )
            return []

        try:
            govde = json.loads(fetch.html)
        except json.JSONDecodeError as exc:
            logger.warning("kampanya_ucu_json_degil", banka=self.bank_code, hata=str(exc))
            return []

        if not isinstance(govde, list):
            logger.warning("kampanya_ucu_beklenmeyen_yapi", banka=self.bank_code)
            return []

        bulunan: list[str] = []
        for kayit in govde:
            if not isinstance(kayit, dict):
                continue
            yol = kayit.get("Url")
            if not isinstance(yol, str) or not yol.strip():
                continue
            mutlak = urljoin(BASE_URL, yol.strip())
            if self._is_campaign_url(mutlak):
                bulunan.append(mutlak)

        if not bulunan:
            logger.info("kampanya_ucu_bos", banka=self.bank_code, kayit=len(govde))
        return bulunan

    def _listing_pages(self) -> list[tuple[str, bool]]:
        """Taranacak (adres, arşiv mi) çiftlerini üretir.

        Arşiv EN SONA konur: bir kampanya hem güncel listede hem arşivde
        görünürse güncel kaydı korunur.
        """
        istenen = {k.casefold() for k in self.categories} if self.categories else None
        sayfalar: list[tuple[str, bool]] = []

        for segment_yolu, (segment, kategoriler) in SEGMENTS.items():
            for kategori in kategoriler:
                if istenen is not None and not (
                    kategori.casefold() in istenen
                    or segment_yolu.casefold() in istenen
                    or segment.casefold() in istenen
                ):
                    continue
                sayfalar.append((f"{BASE_URL}{CAMPAIGN_ROOT}/{segment_yolu}/{kategori}", False))

        if not sayfalar:
            if istenen is not None:
                logger.warning("bilinmeyen_kategori", banka=self.bank_code, istenen=sorted(istenen))
            sayfalar = [
                (f"{BASE_URL}{CAMPAIGN_ROOT}/{yol}/{kategori}", False)
                for yol, (_, kategoriler) in SEGMENTS.items()
                for kategori in kategoriler
            ]

        sayfalar.append((f"{BASE_URL}{ARCHIVE_PATH}", True))
        return sayfalar

    def _campaign_links(self, listing_url: str) -> list[str]:
        """Liste sayfasındaki kampanya detay adreslerini çıkarır."""
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
            if not self._is_campaign_url(absolute) or absolute in gorulen:
                continue
            gorulen.add(absolute)
            links.append(absolute)

        return links

    @staticmethod
    def _is_campaign_url(url: str) -> bool:
        """Adres bir kampanya DETAY sayfası mı?

        Detay üç seviyelidir: `/kampanyalar/{segment}/{kategori}/{slug}`.
        Segment ve kategori kökleri liste sayfasıdır, kampanya değildir.
        """
        if not is_same_site(url, BASE_URL):
            return False

        path = urlsplit(url).path.rstrip("/")
        if not path.startswith(f"{CAMPAIGN_ROOT}/"):
            return False
        if path in NON_DETAIL_PATHS:
            return False

        parcalar = [p for p in path.split("/") if p]
        # ["kampanyalar", segment, kategori, slug]
        if len(parcalar) != 4:
            return False
        return parcalar[1] in SEGMENTS

    @staticmethod
    def segment_from_url(url: str) -> str | None:
        """Adresteki segment parçasını veri modeli değerine çevirir."""
        parcalar = [p for p in urlsplit(url).path.split("/") if p]
        if len(parcalar) >= 2 and parcalar[1] in SEGMENTS:
            return SEGMENTS[parcalar[1]][0]
        return None

    @staticmethod
    def category_from_url(url: str) -> str | None:
        """Adresteki kategori parçasını döndürür (bankanın kendi etiketi)."""
        parcalar = [p for p in urlsplit(url).path.split("/") if p]
        return parcalar[2] if len(parcalar) >= 3 else None

    def parse_detail(self, html: str, url: str, hint: DiscoveredUrl) -> RawCampaign | None:
        """Kampanya detay sayfasını ayrıştırır.

        Args:
            html: Detay sayfasının HTML'i.
            url: Sayfanın adresi.
            hint: Keşiften gelen segment ve kategori bilgisi.

        Returns:
            Çıkarılan kampanya; başlık bulunamazsa None.
        """
        title = extract_title(html)
        if not title:
            return None

        body_text = clean_html(html, bank_code=self.bank_code, title=title)
        # ⚠️ Oran/taksit bilgisi yapısal alanda değil, koşul metninde geçiyor.
        conditions = extract_section_text(html, CONDITION_KEYWORDS)

        return RawCampaign(
            # ⚠️ Slug 100+ karakter olabiliyor; href'ten birebir okunur.
            external_slug=slug_from_url_path(url),
            title=title,
            source_url=url,
            description=self._first_paragraph(body_text),
            conditions_text=conditions,
            exclusions_text=extract_section_text(html, EXCLUSION_KEYWORDS),
            category=None,
            bank_category=hint.category_hint,
            segment=hint.segment_hint or self.segment_from_url(url),
            is_archived=hint.discovery_method == "archive",
        )

    @staticmethod
    def _first_paragraph(text: str, *, max_length: int = 500) -> str | None:
        """Gövde metninin ilk anlamlı paragrafını açıklama olarak döndürür."""
        for line in text.split("\n"):
            aday = normalize_text(line)
            if len(aday) >= 60:
                return aday[:max_length]
        return None
