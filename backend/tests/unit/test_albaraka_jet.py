"""Albaraka Jet Finansman limit ayrıştırması — ağa çıkmaz."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.scrapers.banks.albaraka import AlbarakaScraper
from app.scrapers.banks.albaraka_jet import (
    FAMILY_IHTIYAC,
    FAMILY_KONUT,
    FAMILY_TASIT,
    SETTINGS_URLS,
    apply_overlay,
    cap_amount_term,
    catalog_from_html_attrs,
    codes_for_url,
    family_code_for_hint,
    overlay_fields,
    parse_jet_subtypes,
    parse_setting_params,
)
from app.scrapers.fetcher import Fetcher
from app.scrapers.models import DiscoveredUrl, RawProduct

JET_URL = "https://www.albaraka.com.tr/tr/bireysel/finansmanlar/ihtiyac/jet-finansman"
EGITIM_URL = "https://www.albaraka.com.tr/tr/bireysel/finansmanlar/ihtiyac/egitim-finansmani"
KONUT_URL = "https://www.albaraka.com.tr/tr/bireysel/finansmanlar/konut-finansmani/konut-finansmani"
TASIT_URL = "https://www.albaraka.com.tr/tr/bireysel/finansmanlar/tasit-finansmani/tasit-finansmani"
MOTOSIKLET_URL = (
    "https://www.albaraka.com.tr/tr/bireysel/finansmanlar/ihtiyac/motosiklet-atv-bisiklet"
)
DENIZ_URL = (
    "https://www.albaraka.com.tr/tr/bireysel/finansmanlar/tasit-finansmani/deniz-tasitlari-finansmani"
)


@pytest.fixture
def settings_json(read_fixture) -> str:  # type: ignore[no-untyped-def]
    return read_fixture("json/albaraka/ws_get_setting_params.json")


@pytest.fixture
def jet_html(read_fixture) -> str:  # type: ignore[no-untyped-def]
    return read_fixture("html/albaraka/jet_finansman.html")


def test_parse_setting_params_aile_tavanlari(settings_json: str) -> None:
    katalog = parse_setting_params(settings_json)
    konut = katalog.families[FAMILY_KONUT]
    tasit = katalog.families[FAMILY_TASIT]
    ihtiyac = katalog.families[FAMILY_IHTIYAC]

    assert konut.amount_max == Decimal("2000000")
    assert konut.term_months_max == 120
    assert konut.ltv_max_pct == Decimal("80.0")
    assert konut.ltv_threshold == Decimal("500001")

    assert tasit.amount_max == Decimal("400000")
    assert tasit.term_months_max == 48
    assert tasit.ltv_max_pct == Decimal("70.0")
    assert tasit.ltv_alt_pct == Decimal("50.0")
    assert tasit.ltv_threshold == Decimal("120000")
    assert tasit.vehicle_year_max == 10

    assert ihtiyac.amount_max == Decimal("100000")
    assert ihtiyac.term_months_max == 36
    assert ihtiyac.ltv_max_pct == Decimal("100.0")


def test_parse_setting_params_alt_tur_vadeleri(settings_json: str) -> None:
    katalog = parse_setting_params(settings_json)
    assert katalog.subtype_term_max["161"] == 6
    assert katalog.subtype_term_max["164"] == 3
    assert katalog.subtype_term_max["145"] == 12
    assert katalog.subtype_term_max["180"] == 4
    assert katalog.subtype_term_min["177"] == 6
    assert katalog.subtype_term_max["177"] == 12


def test_bozuk_json_bos_katalog_doner() -> None:
    assert parse_setting_params("<html>yok</html>").is_empty
    assert parse_setting_params("{}").is_empty


def test_html_option_ve_max_nitelikleri(jet_html: str) -> None:
    altlar = parse_jet_subtypes(jet_html)
    kodlar = {a.code: a.label for a in altlar}
    assert kodlar["161"] == "Tablet Finansmanı"
    assert kodlar["145"] == "Eğitim Finansmanı"

    html_kat = catalog_from_html_attrs(jet_html)
    assert html_kat.families[FAMILY_IHTIYAC].amount_max == Decimal("100000")
    assert html_kat.families[FAMILY_KONUT].term_months_max == 120
    assert html_kat.families[FAMILY_TASIT].ltv_alt_pct == Decimal("50.0")


def test_url_kod_eslemesi() -> None:
    assert codes_for_url(EGITIM_URL) == (FAMILY_IHTIYAC, "145")
    assert codes_for_url(KONUT_URL) == (FAMILY_KONUT, None)
    assert codes_for_url(TASIT_URL) == (FAMILY_TASIT, None)
    assert codes_for_url(JET_URL) == (FAMILY_IHTIYAC, None)
    assert codes_for_url(MOTOSIKLET_URL) == (FAMILY_TASIT, "152")
    assert codes_for_url(DENIZ_URL) == (FAMILY_TASIT, "139")


def test_motosiklet_tasit_ailesi_tavanini_alir(settings_json: str) -> None:
    katalog = parse_setting_params(settings_json)
    family, subtype = codes_for_url(MOTOSIKLET_URL)
    alanlar = overlay_fields(katalog, family_code=family, subtype_code=subtype)
    assert alanlar["amount_max"] == Decimal("400000")
    assert alanlar["term_months_max"] == 48


def test_overlay_taban_tavandan_buyukse_tabani_siler() -> None:
    urun = RawProduct(
        external_key="motosiklet-atv-bisiklet#base",
        name="Motosiklet, ATV , Bisiklet",
        source_url=MOTOSIKLET_URL,
        product_type="tasit_finansmani",
        amount_min=Decimal("125000"),
        amount_max=Decimal("250000"),
    )
    apply_overlay(
        urun,
        {
            "amount_max": Decimal("100000"),
            "limits_source": "html_attr",
            "limits_evidence": "wsGetSettingParams aile=003",
        },
    )
    assert urun.amount_max == Decimal("100000")
    assert urun.amount_min is None


def test_egitim_overlay_aile_degil_alt_tur_vadesi(settings_json: str) -> None:
    katalog = parse_setting_params(settings_json)
    family, subtype = codes_for_url(EGITIM_URL)
    alanlar = overlay_fields(katalog, family_code=family, subtype_code=subtype)
    assert alanlar["amount_max"] == Decimal("100000")
    assert alanlar["term_months_max"] == 12
    assert "MAX_REQESTED_MATURITY_145" in alanlar["limits_evidence"]


def test_tablet_cocugu_ayri_sayfa_olarak_yazilmaz(settings_json: str, jet_html: str) -> None:
    from app.scrapers.banks.albaraka_jet import jet_child_products

    katalog = parse_setting_params(settings_json)
    parent = RawProduct(
        external_key="jet-finansman#base",
        name="Jet Finansman",
        source_url=JET_URL,
        product_type="ihtiyac_finansmani",
        segment="bireysel",
        collateral_type="yok",
    )
    cocuklar = jet_child_products(parent, jet_html, katalog)
    kodlar = {u.external_key.split("jet-")[-1] for u in cocuklar}
    assert "161" in kodlar
    assert "164" in kodlar
    assert "177" in kodlar
    # Eğitim'in ayrı ürün sayfası var; Jet çocuğu olarak çoğalmaz.
    assert "145" not in kodlar

    tablet = next(u for u in cocuklar if u.external_key.endswith("jet-161"))
    assert tablet.term_months_max == 6
    assert tablet.amount_max == Decimal("100000")
    assert tablet.variant_label == "Tablet Finansmanı"
    assert "Sub=161" in (tablet.calculator_url or "")

    kira = next(u for u in cocuklar if u.external_key.endswith("jet-177"))
    assert kira.term_months_min == 6
    assert kira.term_months_max == 12


def test_cap_amount_term_ihtiyac_tavanini_keser(settings_json: str) -> None:
    katalog = parse_setting_params(settings_json)
    tutar, vade = cap_amount_term(
        katalog,
        family_code=family_code_for_hint("ihtiyac_finansmani"),
        amount=Decimal("250000"),
        term_months=48,
    )
    assert tutar == Decimal("100000")
    assert vade == 36


def _scraper(tmp_path: Path, transport: httpx.MockTransport) -> AlbarakaScraper:
    settings = Settings(
        raw_html_dir=str(tmp_path / "raw_html"),
        scraper_request_delay_seconds=0.0,
        scraper_max_retries=2,
        airgap_mode=False,
    )
    client = httpx.Client(transport=transport, follow_redirects=True)
    fetcher = Fetcher("albaraka", settings=settings, client=client)
    return AlbarakaScraper(fetcher=fetcher, settings=settings)


def test_parse_products_jet_sayfasinda_alt_tur_yazar(
    tmp_path: Path,
    jet_html: str,
    settings_json: str,
    make_transport: Callable[..., httpx.MockTransport],
) -> None:
    routes = dict.fromkeys(SETTINGS_URLS, (200, settings_json))
    scraper = _scraper(tmp_path, make_transport(routes))
    try:
        urunler = scraper.parse_products(
            jet_html,
            JET_URL,
            DiscoveredUrl(
                url=JET_URL,
                doc_type="product",
                category_hint="ihtiyac_finansmani",
                segment_hint="bireysel",
            ),
        )
    finally:
        scraper.close()

    kok = next(u for u in urunler if u.parent_external_key is None)
    assert kok.amount_max == Decimal("100000")
    assert kok.term_months_max == 36

    tabletler = [u for u in urunler if (u.variant_label or "").startswith("Tablet")]
    assert tabletler
    assert tabletler[0].term_months_max == 6


def test_parse_products_settings_yoksa_html_niteliklerini_kullanir(
    tmp_path: Path,
    jet_html: str,
    make_transport: Callable[..., httpx.MockTransport],
) -> None:
    scraper = _scraper(tmp_path, make_transport({}))
    try:
        urunler = scraper.parse_products(
            jet_html,
            JET_URL,
            DiscoveredUrl(
                url=JET_URL,
                doc_type="product",
                category_hint="ihtiyac_finansmani",
                segment_hint="bireysel",
            ),
        )
    finally:
        scraper.close()

    kok = next(u for u in urunler if u.parent_external_key is None)
    assert kok.amount_max == Decimal("100000")
    assert kok.term_months_max == 36
