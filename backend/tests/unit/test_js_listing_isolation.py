"""js_listing banka scraper'larına gömülmez; isolation korunur."""

from __future__ import annotations

from pathlib import Path

from app.scrapers.registry import available_banks


def test_js_listing_ayri_modul() -> None:
    import app.scrapers.js_listing as js

    assert hasattr(js, "expand_listing")
    assert hasattr(js, "JS_LISTING_TARGETS")


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
    assert not any("/tr/bireysel/" in u for u in urls)
    assert any("turkiyefinans.com.tr" in u and "default.aspx" in u for u in urls)
    assert any("happycard.com.tr" in u for u in urls)
    assert any("albaraka.com.tr/tr/kampanyalar" in u for u in urls)


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
