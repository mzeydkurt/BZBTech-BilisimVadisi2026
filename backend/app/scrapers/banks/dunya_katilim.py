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

from typing import Final
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from app.core.normalization.text import normalize_text
from app.logging_config import get_logger
from app.processing.cleaner import clean_html, extract_section_text, extract_title
from app.scrapers.base import BaseScraper
from app.scrapers.calculator_inventory import (
    find_legal_notice,
    parse_form_controls,
    variant_candidates,
)
from app.scrapers.models import DiscoveredUrl, RawCampaign, RawProduct
from app.scrapers.products import limits_from_page, product_external_key, rates_from_tables
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

# Ürün/finansman sayfaları. Listeleme sayfası sunucu HTML'i olarak geliyor ve
# üç kategori altında altı ürüne bağlanıyor; sayısal özellikler ve hesaplayıcı
# DETAY sayfalarında. Elle whitelist tutulur: 40 civarı adres için otomatik
# keşfin kırılganlığı, listenin bakım maliyetinden pahalı.
PRODUCT_LISTING: Final[str] = f"{BASE_URL}/kendim-icin/finansmanlar"

# (yol, ürün türü, teminat türü)
PRODUCT_PAGES: Final[tuple[tuple[str, str, str | None], ...]] = (
    ("/kendim-icin/finansmanlar/ihtiyac-finansmani", "ihtiyac_finansmani", "teminatsiz"),
    ("/kendim-icin/finansmanlar/arac-finansmani", "tasit_finansmani", "arac_ipotegi"),
    ("/kendim-icin/finansmanlar/konut-finansmani", "konut_finansmani", "ipotek"),
)

# Ürün listeleme sayfasındaki bağlantıları ayırt eden yol ön eki.
PRODUCT_PREFIX: Final[str] = "/kendim-icin/finansmanlar/"

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

    # ── ÜRÜN / FİNANSMAN TARAFI ───────────────────────────

    def discover_products(self) -> list[DiscoveredUrl]:
        """Whitelist'teki finansman sayfalarını döndürür.

        Listeleme sayfası da çekilip whitelist dışı ADAY adresler loglanır;
        otomatik eklenmez. Yanlış bir sayfayı ürün saymak `parse_rate_tables`'a
        alakasız bir ücret tablosunu oran tablosu olarak yazdırır.

        Returns:
            Ürün detay adresleri.
        """
        hedefler = [
            DiscoveredUrl(
                url=f"{BASE_URL}{yol}",
                doc_type="product",
                category_hint=urun_turu,
                segment_hint="bireysel",
                discovery_method="whitelist",
            )
            for yol, urun_turu, _ in PRODUCT_PAGES
        ]
        self._log_product_candidates({h.url for h in hedefler})
        return hedefler

    def _log_product_candidates(self, bilinen: set[str]) -> None:
        """Listeleme sayfasındaki whitelist dışı ürün adreslerini loglar."""
        fetch = self.fetcher.fetch(PRODUCT_LISTING)
        if not fetch.is_success or not fetch.html:
            logger.warning("urun_listesi_alinamadi", banka=self.bank_code, url=PRODUCT_LISTING)
            return

        soup = BeautifulSoup(fetch.html, "lxml")
        adaylar: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            mutlak = urljoin(PRODUCT_LISTING, str(anchor["href"]).strip())
            if not is_same_site(mutlak, BASE_URL):
                continue
            yol = urlsplit(mutlak).path.rstrip("/")
            if yol.startswith(PRODUCT_PREFIX) and yol != PRODUCT_PREFIX.rstrip("/"):
                adaylar.add(mutlak)

        yeni = sorted(adaylar - bilinen)
        if yeni:
            logger.info("urun_adayi_bulundu", banka=self.bank_code, adaylar=yeni)

    def parse_products(self, html: str, url: str, hint: DiscoveredUrl) -> list[RawProduct]:
        """Finansman detay sayfasından ürün, limit ve oranları çıkarır.

        Args:
            html: Sayfanın HTML'i.
            url: Sayfanın adresi.
            hint: Keşiften gelen ürün türü ve segment.

        Returns:
            Tek ürün (varsa varyantlarıyla); başlık bulunamazsa boş liste.
        """
        title = extract_title(html)
        if not title:
            return []

        body_text = clean_html(html, bank_code=self.bank_code, title=title)
        slug = slug_from_url_path(url)
        teminat = next((t for yol, _, t in PRODUCT_PAGES if yol.endswith(slug)), None)

        limitler, limit_kaynagi = limits_from_page(html, body_text)
        form = parse_form_controls(html)

        ana = RawProduct(
            external_key=product_external_key(slug, None),
            name=title,
            source_url=url,
            product_type=hint.category_hint,
            segment=hint.segment_hint,
            description=self._first_paragraph(body_text, title),
            collateral_type=teminat,
            limits_source=limit_kaynagi,
            limits_evidence=None if limit_kaynagi == "none" else body_text[:400],
            has_calculator=bool(form.input_fields),
            calculator_url=url if form.input_fields else None,
            non_binding_notice=find_legal_notice(html),
            rates=rates_from_tables(html),
            **limitler,  # type: ignore[arg-type]
        )

        urunler: list[RawProduct] = [ana]

        # Hesaplayıcı dropdown'ındaki her seçenek bir ürün varyantıdır.
        # ⚠️ Hesaplayıcıya istek ATILMAZ; yalnızca form nitelikleri okunur.
        for aday in variant_candidates(form):
            urunler.append(
                RawProduct(
                    external_key=product_external_key(slug, aday.variant_key or aday.label),
                    name=f"{title} — {aday.label}",
                    source_url=url,
                    product_type=hint.category_hint,
                    segment=hint.segment_hint,
                    parent_external_key=ana.external_key,
                    # Eşleşme yoksa anahtar UYDURULMAZ; ham etiket saklanır.
                    variant_key=aday.variant_key,
                    variant_label=aday.label,
                    variant_dimension=aday.variant_dimension,
                    variant_source="dropdown_option",
                    collateral_type=teminat,
                    limits_source=limit_kaynagi,
                    has_calculator=True,
                    calculator_url=url,
                    non_binding_notice=ana.non_binding_notice,
                    **limitler,  # type: ignore[arg-type]
                )
            )

        return urunler
