"""JS liste genişletme — Playwright ile \"Daha fazla\" / kaydırma / sayfalama.

⚠️ Banka scraper modüllerine `browser_page` GÖMÜLMEZ
(`test_hicbir_scraper_playwright_gerektirmez`). Bu katman ayrı koşucudur;
detay çekimi yine httpx + `parse_detail` ile yapılır.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from urllib.parse import urljoin, urlsplit

from app.logging_config import get_logger
from app.scrapers.browser import (
    NETWORK_IDLE_MS,
    browser_page,
    is_playwright_available,
    playwright_kurulum_mesaji,
)

logger = get_logger(__name__)

# Düğme metinleri (büyük/küçük harf duyarsız kısmi eşleşme).
_DAHA_FAZLA: Final[tuple[str, ...]] = (
    "daha fazla",
    "daha fazla yükle",
    "daha fazla kampanya",
    "daha fazla kampanya göster",
    "load more",
    "show more",
)

_SONRAKI: Final[tuple[str, ...]] = (
    "sonraki",
    "ileri",
    "next",
    "›",
    "»",
)

_MAX_TIK_VARSAYILAN: Final[int] = 25
_SCROLL_TUR_VARSAYILAN: Final[int] = 20


@dataclass(frozen=True)
class JsListingTarget:
    """Bir bankanın JS ile genişletilecek liste sayfası."""

    bank_code: str
    listing_url: str
    # Detay URL'sinde bulunması gereken yol parçası.
    detail_marker: str
    # Liste / kategori dosya adları (detay sanılmasın).
    skip_files: tuple[str, ...] = ()
    max_tur: int = _MAX_TIK_VARSAYILAN
    scroll: bool = True


@dataclass(frozen=True)
class ListingResult:
    """Tek bir liste sayfasının genişletme sonucu.

    ⚠️ `limit_doldu` True ise sessiz kırpma YASAK — çağıran raporlamalıdır.
    """

    urls: tuple[str, ...]
    strateji: str  # daha_fazla | scroll | sayfalama | none
    tur_sayisi: int
    limit_doldu: bool
    bank_code: str
    listing_url: str


# SharePoint tarzı TF liste sayfaları — detayla aynı dizinde.
_TF_LISTE_DOSYALARI: Final[tuple[str, ...]] = (
    "default.aspx",
    "finansman-kampanyalari.aspx",
    "kart-kampanyalari.aspx",
    "ticari-kampanyalar.aspx",
    "dijital-bankacilik-kampanyalari.aspx",
    "odeme-kampanyalari.aspx",
    "yatirim-kampanyalari.aspx",
    "birikim-fon-kampanyalari.aspx",
    "sigorta-kampanyalari.aspx",
    "diger-kampanyalar.aspx",
    "biten-kampanyalar.aspx",
)


# Öncelik: Kuveyt, Dünya, Albaraka, Vakıf, Türkiye Finans (+ Happy Card)
# + banka scraper'larında belgelenmiş ek listeler (Ziraat, TOM, Emlak, Hayat).
JS_LISTING_TARGETS: Final[tuple[JsListingTarget, ...]] = (
    JsListingTarget(
        bank_code="kuveyt_turk",
        listing_url="https://www.kuveytturk.com.tr/kampanyalar/kendim-icin/kart-kampanyalari",
        detail_marker="/kampanyalar/",
    ),
    JsListingTarget(
        bank_code="kuveyt_turk",
        listing_url=(
            "https://www.kuveytturk.com.tr/kampanyalar/kendim-icin/finansman-kampanyalari"
        ),
        detail_marker="/kampanyalar/",
    ),
    JsListingTarget(
        bank_code="kuveyt_turk",
        listing_url=(
            "https://www.kuveytturk.com.tr/kampanyalar/kendim-icin/musteri-ol-kampanyalari"
        ),
        detail_marker="/kampanyalar/",
    ),
    JsListingTarget(
        bank_code="kuveyt_turk",
        listing_url=("https://www.kuveytturk.com.tr/kampanyalar/kendim-icin/seyahat-kampanyalari"),
        detail_marker="/kampanyalar/",
    ),
    JsListingTarget(
        bank_code="kuveyt_turk",
        listing_url=("https://www.kuveytturk.com.tr/kampanyalar/isletmem-icin/kart-kampanyalari"),
        detail_marker="/kampanyalar/",
    ),
    JsListingTarget(
        bank_code="kuveyt_turk",
        listing_url=("https://www.kuveytturk.com.tr/kampanyalar/isletmem-icin/kobi-kampanyalari"),
        detail_marker="/kampanyalar/",
    ),
    JsListingTarget(
        bank_code="kuveyt_turk",
        listing_url=(
            "https://www.kuveytturk.com.tr/kampanyalar/isletmem-icin/musteri-ol-kampanyalari"
        ),
        detail_marker="/kampanyalar/",
    ),
    JsListingTarget(
        bank_code="kuveyt_turk",
        listing_url=("https://www.kuveytturk.com.tr/kampanyalar/isletmem-icin/pos-kampanyalari"),
        detail_marker="/kampanyalar/",
    ),
    JsListingTarget(
        bank_code="dunya_katilim",
        listing_url="https://www.dunyakatilim.com.tr/kampanyalar",
        detail_marker="/kampanyalar/",
    ),
    JsListingTarget(
        bank_code="albaraka",
        listing_url="https://www.albaraka.com.tr/tr/kampanyalar",
        detail_marker="/kampanyalar/detay/",
    ),
    # Canlı yol: /tr/kendim-icin/... (bireysel yönlendirme; eski /tr/bireysel kırık).
    JsListingTarget(
        bank_code="vakif_katilim",
        listing_url="https://www.vakifkatilim.com.tr/tr/kendim-icin/kampanyalar",
        detail_marker="/kampanyalar/detay/",
    ),
    JsListingTarget(
        bank_code="vakif_katilim",
        listing_url=(
            "https://www.vakifkatilim.com.tr/tr/kendim-icin/kampanyalar/mevcut-kampanyalar"
        ),
        detail_marker="/kampanyalar/detay/",
    ),
    JsListingTarget(
        bank_code="turkiye_finans",
        listing_url=("https://www.turkiyefinans.com.tr/tr-tr/kampanyalar/Sayfalar/default.aspx"),
        detail_marker="/kampanyalar/Sayfalar/",
        skip_files=_TF_LISTE_DOSYALARI,
    ),
    # TF kredi kartı kampanyaları (ayrı origin, TF markası).
    JsListingTarget(
        bank_code="turkiye_finans",
        listing_url="https://www.happycard.com.tr/kampanyalar/Sayfalar/default.aspx",
        detail_marker="/kampanyalar/Sayfalar/",
        skip_files=("default.aspx",),
    ),
    # Ziraat: tek HTML sayfasında 209 kart; yine de kaydırma/load-more kaçmasın.
    JsListingTarget(
        bank_code="ziraat_katilim",
        listing_url="https://www.ziraatkatilim.com.tr/kart-kampanyalari",
        detail_marker="/kart-kampanyalari/",
    ),
    # T.O.M. Hadi — liste JS; detaylar /kampanyalar/{slug}.
    JsListingTarget(
        bank_code="tom_bank",
        listing_url="https://tombankhadi.com/hadi-kazan/kampanyalar",
        detail_marker="/kampanyalar/",
    ),
    JsListingTarget(
        bank_code="emlak_katilim",
        listing_url="https://www.emlakkatilim.com.tr/tr/bireysel/kampanyalar",
        detail_marker="/kampanya",
    ),
    JsListingTarget(
        bank_code="emlak_katilim",
        listing_url="https://www.emlakkatilim.com.tr/tr/kurumsal/kampanyalar",
        detail_marker="/kampanya",
    ),
    JsListingTarget(
        bank_code="hayat_finans",
        listing_url="https://www.hayatfinans.com.tr/kampanyalar",
        detail_marker="/kampanya",
    ),
)


def _detay_mi(
    href: str,
    marker: str,
    listing_url: str,
    *,
    skip_files: tuple[str, ...] = (),
) -> bool:
    if not href or href.startswith("#") or href.lower().startswith("javascript:"):
        return False
    mutlak = urljoin(listing_url, href)
    yol = urlsplit(mutlak).path.rstrip("/")
    if marker.rstrip("/") not in yol:
        return False
    # Liste kökünün kendisi detay değildir.
    if yol.endswith(marker.rstrip("/")):
        return False
    listing_path = urlsplit(listing_url).path.rstrip("/").lower()
    if yol.lower() == listing_path:
        return False
    dosya = yol.rsplit("/", 1)[-1].lower()
    return dosya not in {s.lower() for s in skip_files}


def _linkleri_topla(page: object, target: JsListingTarget) -> set[str]:
    hrefs: set[str] = set()
    for el in page.query_selector_all("a[href]"):  # type: ignore[attr-defined]
        href = el.get_attribute("href") or ""
        if _detay_mi(
            href,
            target.detail_marker,
            target.listing_url,
            skip_files=target.skip_files,
        ):
            hrefs.add(urljoin(target.listing_url, href).split("#", 1)[0])
    return hrefs


def _daha_fazla_metni_mi(metin: str) -> bool:
    """Düğme metni \"Daha fazla\" ailesinden mi?"""
    temiz = (metin or "").strip().lower()
    if not temiz:
        return False
    return any(ipucu in temiz for ipucu in _DAHA_FAZLA)


def _sonraki_metni_mi(metin: str, *, rel: str | None = None) -> bool:
    """Sayfalama \"Sonraki\" / rel=next mi?"""
    if (rel or "").lower() == "next":
        return True
    temiz = (metin or "").strip().lower()
    if not temiz:
        return False
    if temiz.isdigit():
        return True
    return any(ipucu == temiz or ipucu in temiz for ipucu in _SONRAKI)


def _daha_fazla_tikla(page: object) -> bool:
    """Görünür bir \"Daha fazla\" düğmesine tıklar. Başarılıysa True."""
    for el in page.query_selector_all("button, a, [role='button']"):  # type: ignore[attr-defined]
        try:
            metin = (el.inner_text() or "").strip()
        except Exception:
            continue
        if not _daha_fazla_metni_mi(metin):
            continue
        try:
            if not el.is_visible():
                continue
            el.click(timeout=5_000)
            page.wait_for_timeout(NETWORK_IDLE_MS)  # type: ignore[attr-defined]
            return True
        except Exception:
            continue
    return False


def _sonsuza_kaydir(page: object) -> bool:
    """Sayfa sonuna kaydırır; scrollHeight büyüdüyse True."""
    try:
        onceki = int(page.evaluate("() => document.body.scrollHeight") or 0)  # type: ignore[attr-defined]
        page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")  # type: ignore[attr-defined]
        page.wait_for_timeout(NETWORK_IDLE_MS)  # type: ignore[attr-defined]
        sonraki = int(page.evaluate("() => document.body.scrollHeight") or 0)  # type: ignore[attr-defined]
        return sonraki > onceki
    except Exception:
        return False


def _sonraki_sayfa_tikla(page: object) -> bool:
    """Numaralı / \"Sonraki\" sayfalama düğmesine tıklar."""
    for el in page.query_selector_all("a[href], button, [role='button']"):  # type: ignore[attr-defined]
        try:
            metin = (el.inner_text() or "").strip()
            rel = el.get_attribute("rel")
        except Exception:
            continue
        if not _sonraki_metni_mi(metin, rel=rel):
            continue
        # "Daha fazla" sayfalama değil.
        if _daha_fazla_metni_mi(metin):
            continue
        try:
            if not el.is_visible():
                continue
            aria = (el.get_attribute("aria-current") or "").lower()
            if aria in {"page", "true"}:
                continue
            cls = (el.get_attribute("class") or "").lower()
            # Aktif / disabled düğme — tıklanmaz.
            if "disabled" in cls or "aria-disabled" in cls:
                continue
            if metin.isdigit() and ("active" in cls or "current" in cls):
                continue
            el.click(timeout=5_000)
            page.wait_for_timeout(NETWORK_IDLE_MS)  # type: ignore[attr-defined]
            return True
        except Exception:
            continue
    return False


def _genislet_sayfada(page: object, target: JsListingTarget) -> ListingResult:
    """Açık bir sayfada üç stratejiyi sırayla dener."""
    toplanan = _linkleri_topla(page, target)
    strateji = "none"
    tur = 0
    limit_doldu = False
    max_tur = max(1, target.max_tur)

    # 1) Daha fazla düğmesi
    while tur < max_tur:
        onceki = len(toplanan)
        if not _daha_fazla_tikla(page):
            break
        strateji = "daha_fazla"
        tur += 1
        toplanan |= _linkleri_topla(page, target)
        if len(toplanan) == onceki:
            break
    else:
        if tur >= max_tur:
            limit_doldu = True

    # 2) Sonsuz kaydırma
    if target.scroll and not limit_doldu:
        scroll_tur = 0
        while scroll_tur < _SCROLL_TUR_VARSAYILAN and tur < max_tur:
            onceki = len(toplanan)
            buyudu = _sonsuza_kaydir(page)
            toplanan |= _linkleri_topla(page, target)
            if not buyudu and len(toplanan) == onceki:
                break
            if len(toplanan) > onceki:
                strateji = "scroll" if strateji == "none" else strateji
            tur += 1
            scroll_tur += 1
        if tur >= max_tur:
            limit_doldu = True

    # 3) Numaralı sayfalama
    if not limit_doldu:
        while tur < max_tur:
            onceki = len(toplanan)
            if not _sonraki_sayfa_tikla(page):
                break
            strateji = "sayfalama" if strateji == "none" else strateji
            tur += 1
            toplanan |= _linkleri_topla(page, target)
            if len(toplanan) == onceki:
                break
        else:
            if tur >= max_tur:
                limit_doldu = True

    return ListingResult(
        urls=tuple(sorted(toplanan)),
        strateji=strateji,
        tur_sayisi=tur,
        limit_doldu=limit_doldu,
        bank_code=target.bank_code,
        listing_url=target.listing_url,
    )


def expand_listing(target: JsListingTarget) -> ListingResult:
    """Liste sayfasında genişletme stratejilerini dener; detay URL'lerini döner.

    Playwright yoksa boş sonuç + uyarı (çökmez).
    """
    if not is_playwright_available():
        logger.warning("js_listing_playwright_yok", mesaj=playwright_kurulum_mesaji())
        return ListingResult(
            urls=(),
            strateji="none",
            tur_sayisi=0,
            limit_doldu=False,
            bank_code=target.bank_code,
            listing_url=target.listing_url,
        )

    try:
        with browser_page() as page:
            page.goto(target.listing_url, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(NETWORK_IDLE_MS)
            sonuc = _genislet_sayfada(page, target)
    except Exception as exc:
        logger.warning(
            "js_listing_basarisiz",
            banka=target.bank_code,
            url=target.listing_url,
            hata=str(exc),
        )
        return ListingResult(
            urls=(),
            strateji="none",
            tur_sayisi=0,
            limit_doldu=False,
            bank_code=target.bank_code,
            listing_url=target.listing_url,
        )

    if sonuc.limit_doldu:
        logger.warning(
            "js_listing_limit_doldu",
            banka=target.bank_code,
            url=target.listing_url,
            tur=sonuc.tur_sayisi,
            adres=len(sonuc.urls),
            strateji=sonuc.strateji,
        )
    else:
        logger.info(
            "js_listing_tamam",
            banka=target.bank_code,
            url=target.listing_url,
            adres=len(sonuc.urls),
            strateji=sonuc.strateji,
            tur=sonuc.tur_sayisi,
        )
    return sonuc


def expand_all(*, bank_codes: set[str] | None = None) -> dict[str, list[str]]:
    """Hedef bankalar için URL haritası: bank_code → detay URL listesi."""
    sonuc: dict[str, list[str]] = {}
    for target in JS_LISTING_TARGETS:
        if bank_codes and target.bank_code not in bank_codes:
            continue
        result = expand_listing(target)
        if not result.urls:
            continue
        mevcut = sonuc.setdefault(target.bank_code, [])
        for u in result.urls:
            if u not in mevcut:
                mevcut.append(u)
    return sonuc


def expand_all_detailed(*, bank_codes: set[str] | None = None) -> list[ListingResult]:
    """Her hedef için ayrı ListingResult listesi (kapsama raporu için)."""
    ciktilar: list[ListingResult] = []
    for target in JS_LISTING_TARGETS:
        if bank_codes and target.bank_code not in bank_codes:
            continue
        ciktilar.append(expand_listing(target))
    return ciktilar


__all__ = [
    "JS_LISTING_TARGETS",
    "JsListingTarget",
    "ListingResult",
    "_daha_fazla_metni_mi",
    "_detay_mi",
    "_genislet_sayfada",
    "_sonraki_metni_mi",
    "expand_all",
    "expand_all_detailed",
    "expand_listing",
]
