"""Ziraat Katılım scraper'ı.

⚠️ GİRİŞ NOKTASI — canlı sitede ölçüldü (13 Ağustos 2026), üç aday denendi:

    /kampanyalar                     -> HTTP 493 (WAF).      Kullanılmaz.
    /kampanyalar/kart-kampanyalari   -> HTTP 404.            Kullanılmaz.
    /kart-kampanyalari               -> HTTP 200, 872 KB.    ✅ TEK GİRİŞ NOKTASI

`/kart-kampanyalari` bir kategori değil, TÜM kampanyaların tek sayfada
listelendiği ana sayfadır: tek istekte 209 tekil kampanya adresi veriyor.
Pagination yoktur.

`/kampanyalar/{sektor}` adresleri (14 adet) sektöre göre süzülmüş listelerdir.
GEZİLMELERİNE GEREK YOKTUR: sektör etiketi zaten her kartın içinde
`<span class="item-category">` olarak duruyor. 14 sayfa gezmek 14 gereksiz
istek demektir; kart yapısı aynı bilgiyi bedavaya veriyor.

🎁 BEDAVA TAKSONOMİ: Kartta sektör etiketi (`item-category`) ve bitiş tarihi
(`campaign-date`) hazır geliyor. Sektör, bankanın kendi sınıflandırmasıdır —
çıkarım değil, kaynak veridir; güveni 1.0'dır.

⚠️ HTTP 493 kalıcı hata DEĞİLDİR: WAF'ın standart dışı kodudur, `Fetcher`
yeniden dener. Kalıcı sayılırsa banka tamamen boş döner.
"""

from __future__ import annotations

from datetime import date
from typing import Final
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

from app.core.normalization.date_tr import parse_date_range_tr
from app.core.normalization.text import collapse_whitespace, normalize_text
from app.logging_config import get_logger
from app.processing.cleaner import clean_html, extract_section_text, extract_title
from app.scrapers.base import BaseScraper
from app.scrapers.models import DiscoveredUrl, RawCampaign
from app.utils.slugify import slug_from_url_path
from app.utils.urls import is_same_site

logger = get_logger(__name__)

BASE_URL: Final[str] = "https://www.ziraatkatilim.com.tr"

# Tüm kampanyaların listelendiği tek sayfa.
LISTING_PATH: Final[str] = "/kart-kampanyalari"
LISTING_URL: Final[str] = f"{BASE_URL}{LISTING_PATH}"

# Süresi dolmuş kampanyalar bu parametreyle açılır.
ARCHIVE_PARAM: Final[str] = "IsArchived=true"
ARCHIVE_URL: Final[str] = f"{LISTING_URL}?{ARCHIVE_PARAM}"

# Kampanya detayının kanonik yol ön eki.
DETAIL_PREFIX: Final[str] = f"{LISTING_PATH}/"

# Sektöre göre süzülmüş listeler. Kazımada KULLANILMAZ (sektör kartta zaten
# var); sektör sözlüğünün kaynağı olarak belgeleme amacıyla tutulur.
SECTOR_PATHS: Final[tuple[str, ...]] = (
    "kuyum-optik-ve-saat",
    "market-ve-gida",
    "e-ticaret",
    "elektronik-ve-telekomunikasyon",
    "yapi-sektoru-ve-iklimlendirme",
    "akaryakit",
    "diger-kampanyalar",
    "egitim-kitap-ve-kirtasiye",
    "genel-kampanyalar",
    "turizm-ve-seyahat",
    "hobi-ve-oyuncak",
    "mobilya-ve-dekorasyon",
    "beyaz-esya-ve-ev-aletleri",
    "giyim-ve-aksesuar",
)

# Ürün sayfaları — oran ve varyant çıkarımında kullanılacak.
PRODUCT_LISTING: Final[str] = f"{BASE_URL}/bireysel/finansman-urunleri"

# Kart içindeki alanların CSS sınıfları (canlı sayfadan doğrulandı).
CARD_LINK_CLASS: Final[str] = "item-title"
CARD_CATEGORY_CLASS: Final[str] = "item-category"

# ⚠️ MARKA BAŞLIĞI TUZAĞI — canlı çekimde ölçüldü.
#
# Detay sayfalarında İKİ `<h1>` var:
#     <h1>Ziraat Katılım Bankası</h1>      <- logo metni, her sayfada aynı
#     <h1>Sosyopix'te %20 İndirim</h1>     <- gerçek kampanya adı
#
# Başlık zinciri ilk `<h1>`'i aldığı için 209 kampanyanın 209'u da
# "Ziraat Katılım Bankası" adıyla kaydedilmişti. Aynı nedenle 2 "sayfa yok"
# yanıtı da geçerli kampanya sanılmıştı: hata ifadesi ikinci `<h1>`'de kalıyor.
#
# Emlak Katılım'dan farkı: orada `og:title` TÜM kampanyalarda aynıydı ve
# işe yaramıyordu; Ziraat'te kampanyaya özgü ve doğru. Bu yüzden marka
# `<h1>`'i elendiğinde zincir doğru başlığa ulaşıyor.
#
# Bu sabit kaldırılırsa hata sessizce geri döner; regresyon testi:
# `tests/unit/test_marka_basligi_regresyonu.py`.
BRAND_HEADINGS: Final[tuple[str, ...]] = (
    "Ziraat Katılım Bankası",
    "Ziraat Katılım",
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

# Detay sayfasında tarih bu başlığın altında duruyor:
#   "Kampanya Dönemi  11-08-2026 - 31-08-2026"
DATE_SECTION_KEYWORDS: Final[tuple[str, ...]] = ("kampanya dönemi", "son gün")


class ZiraatKatilimScraper(BaseScraper):
    """Ziraat Katılım kampanya scraper'ı."""

    bank_code = "ziraat_katilim"
    version = "2.0.0"
    brand_headings = BRAND_HEADINGS

    def discover(self) -> list[DiscoveredUrl]:
        """Ana liste ve arşiv sayfasından kampanya adreslerini toplar.

        Toplam İKİ istek yapılır. Sektör etiketi kartın içinden okunur;
        `categories` verilmişse yalnızca o sektörlerin kartları alınır.

        Returns:
            Keşfedilen kampanya adresleri (tekilleştirilmiş).
        """
        discovered: list[DiscoveredUrl] = []
        seen: set[str] = set()

        for listing_url, is_archived in ((LISTING_URL, False), (ARCHIVE_URL, True)):
            for hint in self._cards(listing_url, is_archived=is_archived):
                if hint.url in seen:
                    continue
                seen.add(hint.url)
                discovered.append(hint)

        return discovered

    def _cards(self, listing_url: str, *, is_archived: bool) -> list[DiscoveredUrl]:
        """Liste sayfasındaki kampanya kartlarını okur.

        Args:
            listing_url: Ana liste veya arşiv adresi.
            is_archived: Arşiv sayfasından mı okunuyor.

        Returns:
            Karttan çıkarılan adresler; sayfa alınamazsa boş liste.
        """
        fetch = self.fetcher.fetch(listing_url)
        if not fetch.is_success or not fetch.html:
            # Arşivin alınamaması güncel kampanyaları etkilemez.
            logger.warning(
                "liste_alinamadi",
                banka=self.bank_code,
                url=listing_url,
                durum=fetch.status_code,
                hata=fetch.error,
            )
            return []

        soup = BeautifulSoup(fetch.html, "lxml")
        secilen = {c.casefold() for c in self.categories} if self.categories else None
        bulunan: list[DiscoveredUrl] = []

        for anchor in soup.find_all("a", class_=CARD_LINK_CLASS, href=True):
            url = urljoin(listing_url, str(anchor["href"]).strip())
            if not self._is_campaign_url(url):
                continue

            sektor = self._card_category(anchor)
            if secilen is not None and (sektor or "").casefold() not in secilen:
                continue

            bulunan.append(
                DiscoveredUrl(
                    url=url,
                    doc_type="campaign",
                    # 🎁 Bankanın kendi sektör etiketi — çıkarım değil, kaynak veri.
                    category_hint=sektor,
                    segment_hint="bireysel",
                    discovery_method="archive" if is_archived else "listing",
                )
            )

        if secilen is not None and not bulunan:
            logger.warning(
                "kategori_eslesmedi",
                banka=self.bank_code,
                istenen=sorted(secilen),
                url=listing_url,
            )

        return bulunan

    @staticmethod
    def _is_campaign_url(url: str) -> bool:
        """Adres bir kampanya detay sayfası mı?"""
        if not is_same_site(url, BASE_URL):
            return False
        path = urlsplit(url).path.rstrip("/")
        # Liste sayfasının kendisi kampanya değildir.
        return path.startswith(DETAIL_PREFIX) and path != LISTING_PATH

    @staticmethod
    def _card_category(anchor: Tag) -> str | None:
        """Kartın sektör etiketini okur (`<span class="item-category">`).

        Etiket bağlantının kardeşi değil, üst kutunun içindedir; bu yüzden
        kart kapsayıcısına çıkılıp aranır.
        """
        kapsayici = anchor.find_parent(class_="item-content") or anchor.parent
        for _ in range(3):
            if kapsayici is None:
                return None
            etiket = kapsayici.find("span", class_=CARD_CATEGORY_CLASS)
            if etiket is not None:
                return collapse_whitespace(etiket.get_text()) or None
            kapsayici = kapsayici.parent
        return None

    def parse_detail(self, html: str, url: str, hint: DiscoveredUrl) -> RawCampaign | None:
        """Kampanya detay sayfasını ayrıştırır.

        Args:
            html: Detay sayfasının HTML'i.
            url: Sayfanın adresi.
            hint: Keşiften gelen sektör ve segment bilgisi.

        Returns:
            Çıkarılan kampanya; başlık bulunamazsa None.
        """
        # ⚠️ Marka `<h1>`'i atlanır; gerekçe `BRAND_HEADINGS` açıklamasında.
        title = extract_title(html, ignore_headings=BRAND_HEADINGS)
        if not title:
            return None

        body_text = clean_html(html, bank_code=self.bank_code, title=title)
        conditions = extract_section_text(html, CONDITION_KEYWORDS)
        exclusions = extract_section_text(html, EXCLUSION_KEYWORDS)

        start_date, end_date, precision = self._parse_dates(html, conditions, body_text)

        return RawCampaign(
            # ⚠️ Slug href'ten birebir okunur. Sondaki `-0`, `-1`, `-2` ekleri
            # yeni dönem yayınlarını ayırt eder ve KORUNUR.
            external_slug=slug_from_url_path(url),
            title=title,
            source_url=url,
            description=self._first_paragraph(body_text),
            conditions_text=conditions,
            exclusions_text=exclusions,
            # Kanonik sınıflandırma ayrı adımda yapılır; bankanın ham sektör
            # etiketi `hint.category_hint` üzerinden taşınır.
            category=None,
            bank_category=hint.category_hint,
            segment=hint.segment_hint,
            start_date=start_date,
            end_date=end_date,
            date_precision=precision,
            is_archived=hint.discovery_method == "archive" or ARCHIVE_PARAM in urlsplit(url).query,
        )

    @staticmethod
    def _parse_dates(
        html: str, conditions: str | None, body_text: str
    ) -> tuple[date | None, date | None, str]:
        """Tarihi çıkarır; ayrıştırmayı normalizasyon kütüphanesine devreder.

        Canlı sayfalarda dört biçim görüldü, dördü de `parse_date_range_tr()`
        ile çözülüyor — scraper içinde tarih regex'i YAZILMAZ:

            "Kampanya Dönemi 11-08-2026 - 31-08-2026" -> tam aralık
            "Son Gün 31.08.2026"                      -> yalnızca bitiş
            "10 Temmuz – 7 Ağustos 2026"              -> yıl devralma
            "07-08-2026 Tarihinde Sona Ermiştir"      -> tire ayraçlı bitiş

        Önce "Kampanya Dönemi" bölümü, sonra koşul metni, en son tüm gövde
        taranır: gövdede yayın/duyuru tarihleri de bulunuyor ve önce
        denenirse yanlış eşleşme üretiyor.

        Returns:
            (başlangıç, bitiş, kesinlik).
        """
        donem = extract_section_text(html, DATE_SECTION_KEYWORDS)
        for kaynak in (donem, conditions, body_text):
            if not kaynak:
                continue
            start, end, precision = parse_date_range_tr(kaynak)
            if precision != "unknown":
                return start, end, precision

        # ⚠️ Bulunamadıysa UYDURULMAZ: NULL kalır, durum `unknown` olur.
        return None, None, "unknown"

    @staticmethod
    def _first_paragraph(text: str, *, max_length: int = 500) -> str | None:
        """Gövde metninin ilk anlamlı paragrafını açıklama olarak döndürür."""
        for line in text.split("\n"):
            candidate = normalize_text(line)
            if len(candidate) >= 40:
                return candidate[:max_length]
        return None
