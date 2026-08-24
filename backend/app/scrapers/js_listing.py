"""JS liste genişletme — Playwright ile \"Daha fazla\" tıklama.

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

_MAX_TIK: Final[int] = 25


@dataclass(frozen=True)
class JsListingTarget:
    """Bir bankanın JS ile genişletilecek liste sayfası."""

    bank_code: str
    listing_url: str
    # Detay URL'sinde bulunması gereken yol parçası.
    detail_marker: str
    # Liste / kategori dosya adları (detay sanılmasın).
    skip_files: tuple[str, ...] = ()


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


# Öncelik: Kuveyt, Dünya, Albaraka, Vakıf, Türkiye Finans (+ Happy Card).
JS_LISTING_TARGETS: Final[tuple[JsListingTarget, ...]] = (
    JsListingTarget(
        bank_code="kuveyt_turk",
        listing_url="https://www.kuveytturk.com.tr/kampanyalar/kendim-icin/kart-kampanyalari",
        detail_marker="/kampanyalar/",
    ),
    JsListingTarget(
        bank_code="kuveyt_turk",
        listing_url="https://www.kuveytturk.com.tr/kampanyalar/kendim-icin/finansman-kampanyalari",
        detail_marker="/kampanyalar/",
    ),
    JsListingTarget(
        bank_code="kuveyt_turk",
        listing_url="https://www.kuveytturk.com.tr/kampanyalar/kendim-icin/musteri-ol-kampanyalari",
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
        listing_url="https://www.vakifkatilim.com.tr/tr/kendim-icin/kampanyalar/mevcut-kampanyalar",
        detail_marker="/kampanyalar/detay/",
    ),
    JsListingTarget(
        bank_code="turkiye_finans",
        listing_url=(
            "https://www.turkiyefinans.com.tr/tr-tr/kampanyalar/Sayfalar/default.aspx"
        ),
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
    if dosya in {s.lower() for s in skip_files}:
        return False
    return True


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


def _daha_fazla_tikla(page: object) -> bool:
    """Görünür bir \"Daha fazla\" düğmesine tıklar. Başarılıysa True."""
    for el in page.query_selector_all("button, a, [role='button']"):  # type: ignore[attr-defined]
        try:
            metin = (el.inner_text() or "").strip().lower()
        except Exception:
            continue
        if not metin:
            continue
        if not any(ipucu in metin for ipucu in _DAHA_FAZLA):
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


def expand_listing(target: JsListingTarget) -> list[str]:
    """Liste sayfasında \"Daha fazla\" tükenene kadar tıklar; detay URL'lerini döner.

    Playwright yoksa boş liste + uyarı (çökmez).
    """
    if not is_playwright_available():
        logger.warning("js_listing_playwright_yok", mesaj=playwright_kurulum_mesaji())
        return []

    toplanan: set[str] = set()
    try:
        with browser_page() as page:
            page.goto(target.listing_url, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(NETWORK_IDLE_MS)
            toplanan |= _linkleri_topla(page, target)
            for _ in range(_MAX_TIK):
                onceki = len(toplanan)
                if not _daha_fazla_tikla(page):
                    break
                toplanan |= _linkleri_topla(page, target)
                if len(toplanan) == onceki:
                    # Tıklandı ama yeni link yok — yeter.
                    break
    except Exception as exc:
        logger.warning(
            "js_listing_basarisiz",
            banka=target.bank_code,
            url=target.listing_url,
            hata=str(exc),
        )
        return sorted(toplanan)

    logger.info(
        "js_listing_tamam",
        banka=target.bank_code,
        url=target.listing_url,
        adres=len(toplanan),
    )
    return sorted(toplanan)


def expand_all(*, bank_codes: set[str] | None = None) -> dict[str, list[str]]:
    """Hedef bankalar için URL haritası: bank_code → detay URL listesi."""
    sonuc: dict[str, list[str]] = {}
    for target in JS_LISTING_TARGETS:
        if bank_codes and target.bank_code not in bank_codes:
            continue
        urls = expand_listing(target)
        if not urls:
            continue
        mevcut = sonuc.setdefault(target.bank_code, [])
        for u in urls:
            if u not in mevcut:
                mevcut.append(u)
    return sonuc


__all__ = [
    "JS_LISTING_TARGETS",
    "JsListingTarget",
    "expand_all",
    "expand_listing",
]
