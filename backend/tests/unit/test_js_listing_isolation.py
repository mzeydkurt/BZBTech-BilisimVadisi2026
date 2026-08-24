"""js_listing banka scraper'larına gömülmez; isolation korunur."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from app.scrapers.registry import available_banks


def test_js_listing_ayri_modul() -> None:
    import app.scrapers.js_listing as js

    assert hasattr(js, "expand_listing")
    assert hasattr(js, "JS_LISTING_TARGETS")
    assert hasattr(js, "ListingResult")


def test_banka_scraperlarda_js_listing_yok() -> None:
    import importlib

    for kod in available_banks():
        modul = importlib.import_module(f"app.scrapers.banks.{kod}")
        kaynak = Path(str(modul.__file__)).read_text(encoding="utf-8")
        assert "js_listing" not in kaynak
        assert "browser_page" not in kaynak


def test_js_listing_hedefleri_vakif_tf_happycard() -> None:
    from app.scrapers.js_listing import JS_LISTING_TARGETS

    urls = [t.listing_url for t in JS_LISTING_TARGETS]
    assert any("/tr/kendim-icin/kampanyalar" in u for u in urls)
    # Vakıf eski /tr/bireysel yolu kırık — yalnızca vakıf için yasak.
    vakif = [u for u in urls if "vakifkatilim" in u]
    assert not any("/tr/bireysel/" in u for u in vakif)
    assert any("turkiyefinans.com.tr" in u and "default.aspx" in u for u in urls)
    assert any("happycard.com.tr" in u for u in urls)
    assert any("albaraka.com.tr/tr/kampanyalar" in u for u in urls)


def test_js_listing_ek_hedefler() -> None:
    from app.scrapers.js_listing import JS_LISTING_TARGETS

    bankalar = {t.bank_code for t in JS_LISTING_TARGETS}
    assert "ziraat_katilim" in bankalar
    assert "tom_bank" in bankalar
    assert "emlak_katilim" in bankalar
    assert "hayat_finans" in bankalar
    urls = [t.listing_url for t in JS_LISTING_TARGETS]
    assert any("seyahat-kampanyalari" in u for u in urls)
    assert any("isletmem-icin" in u for u in urls)


def test_happycard_kampanya_url_kabul() -> None:
    from app.scrapers.banks.turkiye_finans import TurkiyeFinansScraper

    assert TurkiyeFinansScraper._is_campaign_url(
        "https://www.happycard.com.tr/kampanyalar/Sayfalar/world-puan.aspx"
    )
    assert not TurkiyeFinansScraper._is_campaign_url(
        "https://www.happycard.com.tr/kampanyalar/Sayfalar/default.aspx"
    )
    assert not TurkiyeFinansScraper._is_campaign_url(
        "https://www.turkiyefinans.com.tr/tr-tr/kampanyalar/Sayfalar/default.aspx"
    )


def test_daha_fazla_ve_sonraki_metin() -> None:
    from app.scrapers.js_listing import _daha_fazla_metni_mi, _sonraki_metni_mi

    assert _daha_fazla_metni_mi("Daha Fazla Göster")
    assert _daha_fazla_metni_mi("Load more")
    assert not _daha_fazla_metni_mi("Sonraki")
    assert _sonraki_metni_mi("Sonraki")
    assert _sonraki_metni_mi("3")
    assert _sonraki_metni_mi("", rel="next")
    assert not _sonraki_metni_mi("kampanya detayı")


def test_detay_mi_liste_koku_red() -> None:
    from app.scrapers.js_listing import _detay_mi

    liste = "https://www.example.com/kampanyalar"
    assert not _detay_mi("/kampanyalar", "/kampanyalar/", liste)
    assert _detay_mi("/kampanyalar/yaz-indirimi", "/kampanyalar/", liste)


def _sahte_sayfa(*, linkler: list[str], dugmeler: list[dict]) -> MagicMock:
    """Playwright page benzeri sahte nesne."""
    page = MagicMock()
    scroll_h = {"v": 1000}

    def query_selector_all(sel: str):
        if sel.startswith("a[href]") and "button" not in sel:
            els = []
            for href in linkler:
                el = MagicMock()
                el.get_attribute.side_effect = lambda a, h=href: h if a == "href" else None
                els.append(el)
            return els
        els = []
        for d in dugmeler:
            el = MagicMock()
            el.inner_text.return_value = d.get("text", "")
            el.is_visible.return_value = True

            def _attr(name: str, d=d):
                if name == "rel":
                    return d.get("rel")
                if name == "aria-current":
                    return d.get("aria_current")
                if name == "class":
                    return d.get("cls", "")
                return None

            el.get_attribute.side_effect = _attr
            els.append(el)
        return els

    page.query_selector_all.side_effect = query_selector_all

    def evaluate(js: str):
        if "scrollHeight" in js and "scrollTo" not in js:
            return scroll_h["v"]
        if "scrollTo" in js:
            scroll_h["v"] += 200
            return None
        return None

    page.evaluate.side_effect = evaluate
    page.wait_for_timeout = MagicMock()
    return page


def test_genislet_scroll_link_artirir() -> None:
    from app.scrapers.js_listing import JsListingTarget, _genislet_sayfada

    target = JsListingTarget(
        bank_code="test",
        listing_url="https://www.example.com/kampanyalar",
        detail_marker="/kampanyalar/",
        max_tur=25,
        scroll=True,
    )
    page = _sahte_sayfa(
        linkler=["https://www.example.com/kampanyalar/a"],
        dugmeler=[],
    )
    cagri = {"n": 0}
    gercek_qsa = page.query_selector_all.side_effect
    scroll_say = {"n": 0}

    def evaluate(js: str):
        if "scrollHeight" in js and "scrollTo" not in js:
            # İlk ölçüm 1000; bir kez büyüt; sonra sabit (sonsuz döngü yok).
            return 1000 + (200 if scroll_say["n"] == 0 else 0)
        if "scrollTo" in js:
            scroll_say["n"] += 1
            return None
        return None

    page.evaluate.side_effect = evaluate

    def qsa_degisken(sel: str):
        cagri["n"] += 1
        if sel.startswith("a[href]") and "button" not in sel and cagri["n"] > 2:
            els = []
            for href in (
                "https://www.example.com/kampanyalar/a",
                "https://www.example.com/kampanyalar/b",
            ):
                el = MagicMock()
                el.get_attribute.side_effect = (
                    lambda a, h=href: h if a == "href" else None
                )
                els.append(el)
            return els
        return gercek_qsa(sel)

    page.query_selector_all.side_effect = qsa_degisken
    sonuc = _genislet_sayfada(page, target)
    assert sonuc.strateji == "scroll"
    assert "kampanyalar/b" in " ".join(sonuc.urls)
    assert sonuc.limit_doldu is False


def test_genislet_limit_doldu() -> None:
    from app.scrapers.js_listing import JsListingTarget, _genislet_sayfada

    target = JsListingTarget(
        bank_code="test",
        listing_url="https://www.example.com/kampanyalar",
        detail_marker="/kampanyalar/",
        max_tur=2,
        scroll=False,
    )
    # Her tıklamada yeni link + sürekli "Daha fazla".
    sayac = {"i": 0}

    page = MagicMock()
    page.wait_for_timeout = MagicMock()

    def qsa(sel: str):
        if sel.startswith("a[href]") and "button" not in sel:
            els = []
            for i in range(sayac["i"] + 1):
                href = f"https://www.example.com/kampanyalar/k{i}"
                el = MagicMock()
                el.get_attribute.side_effect = (
                    lambda a, h=href: h if a == "href" else None
                )
                els.append(el)
            return els
        el = MagicMock()
        el.inner_text.return_value = "Daha fazla"
        el.is_visible.return_value = True
        el.get_attribute.return_value = None

        def click(*_a, **_k):
            sayac["i"] += 1

        el.click.side_effect = click
        return [el]

    page.query_selector_all.side_effect = qsa
    sonuc = _genislet_sayfada(page, target)
    assert sonuc.strateji == "daha_fazla"
    assert sonuc.tur_sayisi == 2
    assert sonuc.limit_doldu is True


def test_genislet_sayfalama() -> None:
    from app.scrapers.js_listing import JsListingTarget, _genislet_sayfada

    target = JsListingTarget(
        bank_code="test",
        listing_url="https://www.example.com/kampanyalar",
        detail_marker="/kampanyalar/",
        max_tur=5,
        scroll=False,
    )
    sayac = {"i": 0}
    page = MagicMock()
    page.wait_for_timeout = MagicMock()

    def qsa(sel: str):
        if sel == "a[href]":
            els = []
            for i in range(sayac["i"] + 1):
                href = f"https://www.example.com/kampanyalar/p{i}"
                el = MagicMock()
                el.get_attribute.side_effect = (
                    lambda a, h=href: h if a == "href" else None
                )
                els.append(el)
            return els
        # sayfalama seçici
        el = MagicMock()
        el.inner_text.return_value = "Sonraki"
        el.is_visible.return_value = True
        el.get_attribute.side_effect = lambda _a: None

        def click(*_a, **_k):
            sayac["i"] += 1

        el.click.side_effect = click
        return [el]

    page.query_selector_all.side_effect = qsa
    sonuc = _genislet_sayfada(page, target)
    assert sonuc.strateji == "sayfalama"
    assert sonuc.tur_sayisi >= 1
    assert any("p1" in u for u in sonuc.urls)


def test_expand_listing_playwright_yok() -> None:
    from unittest.mock import patch

    from app.scrapers.js_listing import JsListingTarget, expand_listing

    target = JsListingTarget(
        bank_code="test",
        listing_url="https://www.example.com/kampanyalar",
        detail_marker="/kampanyalar/",
    )
    with patch("app.scrapers.js_listing.is_playwright_available", return_value=False):
        sonuc = expand_listing(target)
    assert sonuc.urls == ()
    assert sonuc.limit_doldu is False
    assert sonuc.strateji == "none"
