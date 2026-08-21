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

import re
from decimal import Decimal, InvalidOperation
from typing import Final
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

from app.core.normalization.text import collapse_whitespace, normalize_text
from app.logging_config import get_logger
from app.processing.cleaner import clean_html, extract_section_text, extract_title
from app.scrapers.base import BaseScraper
from app.scrapers.models import DiscoveredUrl, RawCampaign, RawProduct, RawProductRate
from app.scrapers.products import product_external_key
from app.utils.slugify import slug_from_url_path, slugify
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


# Ürün/finansman sayfaları. Adresler SITEMAP'TEN doğrulandı (17 Ağustos 2026);
# kök sitemap bir INDEX, 8 alt sitemap'e işaret ediyor.
#
# ⚠️ Teminat türü `core.vocab.COLLATERAL_TYPES` sözlüğünden.
# ⚠️ Kategori indeksleri ve yüzde kodlu (`%C3%BC`) çift adresler alınmadı.
_F = "/bireysel/finansman-urunleri"
_H = "/bireysel/hesaplar"
_K = "/bireysel/kartlar"

# ── Ürün ve hizmet ücretleri sayfası (KATİP) ──────────────
#
# Canlı sayfada doğrulandı (21 Ağustos 2026, `robots.txt` engeli YOK): 3
# Bootstrap sekmesi (İhtiyaç/Konut/Taşıt Finansmanı), her sekmede akordeon
# panelleri, her panelin tablosunda "Masraf Adı" hücresi "Kâr oranı (N-M ay
# vade)" ile başlayan satırlar asgari/azami oranı veriyor. Yukarıdaki tanıtım
# sayfaları (`_F/...`) bu oranı YAYIMLAMIYOR — bu sayfa Ziraat'in konut/taşıt/
# ihtiyaç finansmanı için TEK statik oran kaynağı.
FEE_RATE_PATH: Final[str] = "/urun-ve-hizmet-ucretleri/bireysel-krediler"
FEE_RATE_URL: Final[str] = f"{BASE_URL}{FEE_RATE_PATH}"

# Sekme etiketi (nav linkinin metni) -> `core.taxonomy.PRODUCT_TYPES` değeri.
_SEKME_URUN_TURU: Final[dict[str, str]] = {
    "İhtiyaç Finansmanı": "ihtiyac_finansmani",
    "Konut Finansmanı": "konut_finansmani",
    "Taşıt Finansmanı": "tasit_finansmani",
}

# Yalnızca bu önekle başlayan "Masraf Adı" satırları kâr oranıdır; Tahsis
# Ücreti / Ekspertiz Ücreti / İpotek Tesis Ücreti / Hayat Sigortası / DASK /
# Konut Sigortası / Yıllık Maliyet Oranı / Erken Kapama Komisyonu gibi hizmet
# ücreti satırları bu önekle eşleşmediği için kendiliğinden atlanır.
_KAR_ORANI_ONEKLERI: Final[tuple[str, ...]] = ("kâr oran", "kar oran")

# "(1-60 ay vade)" / "Oranı(1-120 ay vade)" (araya boşluksuz) biçimlerini yakalar.
_VADE_RE: Final[re.Pattern[str]] = re.compile(r"\((\d+)\s*-\s*(\d+)\s*ay\s*vade\)", re.IGNORECASE)

# Panel başlığındaki tutar bandını yakalar: "(0-10.000.000 TL'ye kadar)",
# "(0 - 400.000 TL)*", "(400.001- 800.000 TL)*" (boşluk tutarsız).
_TUTAR_BANDI_RE: Final[re.Pattern[str]] = re.compile(
    r"\(\s*([\d.,]+)\s*-\s*([\d.,]+)\s*TL[^)]*\)\*?", re.IGNORECASE
)

PRODUCT_PAGES: Final[tuple[tuple[str, str, str | None], ...]] = (
    # ── Konut ve gayrimenkul ──
    (f"{_F}/konut-gayrimenkul-finansmani", "konut_finansmani", "konut"),
    (f"{_F}/konut-gayrimenkul-finansmani/bireysel-arsa-finansmani", "konut_finansmani", "konut"),
    (
        f"{_F}/konut-gayrimenkul-finansmani/bireysel-is-yeri-finansmani",
        "isyeri_finansmani",
        "konut",
    ),
    (f"{_F}/konut-finansmani/kentsel-donusum-finansmani", "konut_finansmani", "konut"),
    # ── Taşıt ──
    (f"{_F}/tasit-finansmani/tasit-finansmani", "tasit_finansmani", "tasit"),
    (f"{_F}/tasit-finansmani/togg-finansmani", "tasit_finansmani", "tasit"),
    # ── İhtiyaç ──
    (f"{_F}/ihtiyac-finansmani", "ihtiyac_finansmani", "yok"),
    (f"{_F}/ihtiyac-finansmani/aninda-finansman", "ihtiyac_finansmani", "yok"),
    (f"{_F}/ihtiyac-finansmani/egitim-finansmani", "ihtiyac_finansmani", "yok"),
    (f"{_F}/ihtiyac-finansmani/hac-ve-umre-finansmani", "ihtiyac_finansmani", "yok"),
    (f"{_F}/ihtiyac-finansmani/dayanikli-tuketim-finansmani", "ihtiyac_finansmani", "yok"),
    (f"{_F}/ihtiyac-finansmani/dogal-gaz-donusum-finansmani", "ihtiyac_finansmani", "yok"),
    (f"{_F}/ihtiyac-finansmani/ipotekli-bireysel-finansman", "ihtiyac_finansmani", "konut"),
    (f"{_F}/alisveris-finansmani", "ihtiyac_finansmani", "yok"),
    # ── Katılma hesapları ──
    (f"{_H}/katilma-hesaplari/katilma-hesabi", "birikim_katilma_hesabi", "yok"),
    (f"{_H}/katilma-hesaplari/tl-katilma-hesabi", "birikim_katilma_hesabi", "yok"),
    (
        f"{_H}/katilma-hesaplari/ara-donem-kar-payi-odemeli-katilma-hesabi",
        "birikim_katilma_hesabi",
        "yok",
    ),
    (f"{_H}/katilma-hesaplari/birikimli-tasarruf-hesabi", "birikim_katilma_hesabi", "yok"),
    (f"{_H}/katilma-hesaplari/eli-bol-hesap", "birikim_katilma_hesabi", "yok"),
    (f"{_H}/katilma-hesaplari/konut-hesabi", "birikim_katilma_hesabi", "yok"),
    (f"{_H}/katilma-hesaplari/Yuvam-hesap", "birikim_katilma_hesabi", "yok"),
    (f"{_H}/aninda-gunluk-hesap", "birikim_katilma_hesabi", "yok"),
    (f"{_H}/altin-hesaplar/altin-katilma-hesabi", "yatirim_urunu", "diger"),
    (f"{_H}/altin-hesaplar/altin-depo-hesabi", "yatirim_urunu", "diger"),
    # ── Kartlar ──
    (f"{_K}/kredi-karti", "kart", "yok"),
    (f"{_K}/banka-karti", "kart", "yok"),
    (f"{_K}/aile-kart-troy", "kart", "yok"),
    (f"{_K}/bankkart-sanal-kart", "kart", "yok"),
    # ── Ürün ve hizmet ücretleri (KATİP) — konut/taşıt/ihtiyaç finansmanının
    # GERÇEK kâr oranı asgari/azami değerleri yalnızca burada, statik bir
    # tabloda yayımlanıyor; yukarıdaki tanıtım sayfalarında oran yok. `hint`
    # üçüncü alanı (`product_type`/teminat) burada KULLANILMAZ —
    # `parse_products()` override'ı üç sekmeyi ayrı ayrı sınıflandırır; ilk
    # değer yalnızca whitelist biçimini sağlamak için var.
    (FEE_RATE_PATH, "finansman", None),
)


class ZiraatKatilimScraper(BaseScraper):
    """Ziraat Katılım kampanya scraper'ı."""

    bank_code = "ziraat_katilim"
    version = "2.0.0"
    product_base_url = BASE_URL
    product_pages = PRODUCT_PAGES
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
            is_archived=hint.discovery_method == "archive" or ARCHIVE_PARAM in urlsplit(url).query,
        )

    def structured_period_text(self, html: str) -> str | None:
        """ "Kampanya Dönemi" / "Son Gün" bölümünün metni.

        Canlı sayfalarda dört biçim görüldü; dördü de ortak tarih yolunda
        çözülüyor, scraper içinde tarih regex'i yazılmaz:

            "Kampanya Dönemi 11-08-2026 - 31-08-2026" -> tam aralık
            "Son Gün 31.08.2026"                      -> yalnızca bitiş
            "10 Temmuz – 7 Ağustos 2026"              -> yıl devralma
            "07-08-2026 Tarihinde Sona Ermiştir"      -> tire ayraçlı bitiş

        ⚠️ Bu bölüm komşu kampanya KARTLARINI da yakalayabiliyor: liste
        sayfasından gelen kartların her birinde "Son Gün" satırı var ve
        ayrıştırıcı bunları kampanyanın kendi bölümü sanabiliyordu. Ölçüldü —
        20 kampanyanın `end_date` değeri komşu karttan gelmişti (#195 sayfada
        09-02-2026, veritabanında 31-08-2026). `dates.STRUCTURED_MAX_CHARS`
        eşiği bu durumu yakalar ve bölümü yakınlık kuralına düşürür.
        """
        return extract_section_text(html, DATE_SECTION_KEYWORDS)

    @staticmethod
    def _first_paragraph(text: str, *, max_length: int = 500) -> str | None:
        """Gövde metninin ilk anlamlı paragrafını açıklama olarak döndürür."""
        for line in text.split("\n"):
            candidate = normalize_text(line)
            if len(candidate) >= 40:
                return candidate[:max_length]
        return None

    def parse_products(self, html: str, url: str, hint: DiscoveredUrl) -> list[RawProduct]:
        """Genel ayrıştırıcıyı çalıştırır; ücret/oran sayfası için özel ayrıştırıcıya döner.

        ⚠️ Ücret sayfası (`FEE_RATE_PATH`) yukarıdaki tanıtım sayfalarıyla
        AYNI ürünü zenginleştirmez — her panel kendi bağımsız `RawProduct`'ı
        olarak yazılır. Sebep: `ProductRunner._upsert_product` mevcut bir
        ürünü güncellerken TÜM alanları (ad, tür, tutar/vade limitleri) kör
        biçimde üstüne yazıyor; bu sayfanın ayrıştırıcısı tanıtım sayfasının
        bildiği limit/varyant bilgisini bilmediği için "birleştirme" denemesi
        o veriyi sessizce SİLERDİ. Ayrı ürün olarak tutmak, iki farklı
        yayının (tanıtım metni / resmî ücret tablosu) ikisini de korur.
        """
        if urlsplit(url).path.rstrip("/") == FEE_RATE_PATH:
            return _parse_fee_rate_page(html, url)
        return super().parse_products(html, url, hint)


def _tl_sayi(ham: str) -> Decimal:
    """`"10.000.000"` gibi Türkçe biçimli bir TL tutarını `Decimal`'a çevirir."""
    return Decimal(ham.strip().replace(".", "").replace(",", "."))


def _oran_decimal(ham: str) -> Decimal | None:
    """`"4,99 %"` gibi bir oranı `Decimal("4.99")`'a çevirir; ayrıştırılamazsa None."""
    temiz = ham.strip().replace("%", "").strip().replace(".", "").replace(",", ".")
    try:
        return Decimal(temiz)
    except InvalidOperation:
        return None


def _panel_adi_ve_tutar_bandi(baslik: str) -> tuple[str, Decimal | None, Decimal | None]:
    """Panel başlığından tutar bandını ayrıştırır; başlık BİREBİR korunur.

    Args:
        baslik: Akordeon başlığı, ör. `"Taşıt Finansmanı (Kaskolu) (0 - 400.000 TL)*"`.

    Returns:
        (başlık BİREBİR, alt tutar, üst tutar) — tutar parenteze yoksa ikisi de None.
    """
    eslesme = _TUTAR_BANDI_RE.search(baslik)
    if eslesme is None:
        return baslik, None, None
    try:
        return baslik, _tl_sayi(eslesme.group(1)), _tl_sayi(eslesme.group(2))
    except InvalidOperation:
        return baslik, None, None


def _kar_orani_satiri_mi(masraf_adi: str) -> bool:
    """ "Masraf Adı" hücresi bir kâr oranı satırı mı (ücret satırı değil)?"""
    normalized = masraf_adi.strip().lower()
    return normalized.startswith(_KAR_ORANI_ONEKLERI)


def _panel_urunu_olustur(
    *, sekme_urun_turu: str, panel_baslik: str, panel_index: int, satirlar: list[Tag], url: str
) -> RawProduct | None:
    """Bir akordeon panelinin "Kâr oranı" satırlarından tek bir `RawProduct` üretir.

    Returns:
        Panelde en az bir kâr oranı satırı varsa ürün; yoksa None (panel
        yalnızca hizmet ücreti içeriyor demektir — atlanır, hata sayılmaz).
    """
    baslik, tutar_min, tutar_max = _panel_adi_ve_tutar_bandi(panel_baslik)
    oranlar: list[RawProductRate] = []

    for satir in satirlar:
        hucreler = satir.find_all("td")
        if len(hucreler) < 6:
            continue
        masraf_adi = collapse_whitespace(hucreler[0].get_text())
        if not masraf_adi or not _kar_orani_satiri_mi(masraf_adi):
            continue

        vade_eslesme = _VADE_RE.search(masraf_adi)
        asgari = _oran_decimal(hucreler[2].get_text())
        azami = _oran_decimal(hucreler[4].get_text())
        aciklama = collapse_whitespace(hucreler[5].get_text())
        if asgari is None and azami is None:
            logger.warning(
                "ziraat_ucret_sayfasi_oran_ayristirilamadi", panel=baslik, masraf_adi=masraf_adi
            )
            continue

        oranlar.append(
            RawProductRate(
                rate_source="html_table",
                rate_type="financing_rate",
                # ⚠️ Gözlemde asgari == azami her satırda; farklı olsalar bile
                # `ProductRate.profit_rate_pct` tek değer taşıdığı için asgari
                # alınır — azami her iki alanda da `evidence_text`'te BİREBİR
                # görünür kalır.
                profit_rate_pct=asgari if asgari is not None else azami,
                term_months=int(vade_eslesme.group(2)) if vade_eslesme else None,
                term_label=(
                    f"{vade_eslesme.group(1)}-{vade_eslesme.group(2)} ay vade"
                    if vade_eslesme
                    else None
                ),
                amount_min=tutar_min,
                amount_max=tutar_max,
                # ⚠️ Kaynak hücreleri zaten "%" işaretini içeriyor ("3,49 %");
                # ayrıca "%" eklemek "Asgari %3,49 %" gibi çift işarete yol
                # açardı — kanıt metni birebir olmalı, gürültülü değil.
                evidence_text=f"{masraf_adi} — Asgari {hucreler[2].get_text().strip()}, "
                f"Azami {hucreler[4].get_text().strip()}. {aciklama}".strip(),
            )
        )

    if not oranlar:
        return None

    slug = f"{slug_from_url_path(url)}-{panel_index}-{slugify(baslik)}"
    return RawProduct(
        # ⚠️ Ayrı bir ad alanı: tanıtım sayfalarındaki AYNI isimli ürünle
        # ÇAKIŞMAZ (`parse_products` docstring'indeki gerekçe).
        external_key=product_external_key(slug, None),
        name=baslik,
        source_url=url,
        product_type=sekme_urun_turu,
        amount_min=tutar_min,
        amount_max=tutar_max,
        rates=oranlar,
        limits_source="none",
    )


def _parse_fee_rate_page(html: str, url: str) -> list[RawProduct]:
    """`/urun-ve-hizmet-ucretleri/bireysel-krediler` sayfasını ayrıştırır.

    Üç Bootstrap sekmesi (İhtiyaç/Konut/Taşıt Finansmanı) × akordeon paneli
    × "Kâr oranı (N-M ay vade)" satırları. Hizmet ücreti satırları (Tahsis
    Ücreti, Ekspertiz Ücreti, İpotek Tesis Ücreti, Hayat/Konut Sigortası,
    DASK, Yıllık Maliyet Oranı, Erken Kapama Komisyonu) `_kar_orani_satiri_mi`
    ile elenir — bilinçli olarak yazılmaz (KATİP: yalnızca kâr oranı istendi).

    Args:
        html: Sayfanın ham HTML'i.
        url: Sayfanın adresi (`RawProduct.source_url` için).

    Returns:
        Her panel için bir ürün; hiçbir kâr oranı satırı bulunamazsa boş liste.
    """
    soup = BeautifulSoup(html, "lxml")
    urunler: list[RawProduct] = []
    panel_index = 0

    sekme_etiketleri: dict[str, str] = {}
    for anchor in soup.select("ul.nav-pills a[href^='#']"):
        etiket = collapse_whitespace(anchor.get_text())
        if etiket:
            sekme_etiketleri[str(anchor["href"]).lstrip("#")] = etiket

    for sekme_id, etiket in sekme_etiketleri.items():
        urun_turu = _SEKME_URUN_TURU.get(etiket)
        if urun_turu is None:
            logger.warning("ziraat_ucret_sayfasi_bilinmeyen_sekme", etiket=etiket)
            continue
        pane = soup.find(id=sekme_id)
        if not isinstance(pane, Tag):
            continue

        for buton in pane.find_all("button", class_="custom-accordion__title"):
            panel_index += 1
            # ⚠️ `<i class="zk-arrow">&nbsp;</i>` alt öğesi de metne dahil
            # oluyor; `collapse_whitespace` sondaki NBSP'yi zaten kırpar.
            panel_baslik = collapse_whitespace(buton.get_text())
            hedef_id = str(buton.get("data-target", "")).lstrip("#")
            gövde = soup.find(id=hedef_id) if hedef_id else None
            if not panel_baslik or not isinstance(gövde, Tag):
                continue

            satirlar = gövde.find_all("tr")
            urun = _panel_urunu_olustur(
                sekme_urun_turu=urun_turu,
                panel_baslik=panel_baslik,
                panel_index=panel_index,
                satirlar=satirlar,
                url=url,
            )
            if urun is not None:
                urunler.append(urun)

    if not urunler:
        logger.warning("ziraat_ucret_sayfasi_hic_oran_bulunamadi", url=url)
    return urunler
