"""Kuveyt Türk scraper testleri.

Testler ağa çıkmaz (§13). Fixture'lar canlı sayfa yapısından (14 Ağustos 2026)
alınmıştır.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Campaign
from app.scrapers.banks.kuveyt_turk import (
    ARCHIVE_PATH,
    BASE_URL,
    CAMPAIGN_API_URL,
    KuveytTurkScraper,
)
from app.scrapers.fetcher import Fetcher
from app.scrapers.models import DiscoveredUrl

KART_LISTE = f"{BASE_URL}/kampanyalar/kendim-icin/kart-kampanyalari"
ARSIV_URL = f"{BASE_URL}{ARCHIVE_PATH}"

BARCIN_URL = f"{BASE_URL}/kampanyalar/kendim-icin/kart-kampanyalari/barcin-sporda-4-taksit-firsati"
COLINS_URL = (
    f"{BASE_URL}/kampanyalar/kendim-icin/kart-kampanyalari/"
    "colinsde-vade-farksiz-4-aya-varan-taksit-firsati"
)
ESNAF_URL = (
    f"{BASE_URL}/kampanyalar/isim-icin/musteri-ol-kampanyalari/"
    "mobilden-kuveyt-turklu-olan-esnaf-ciftci-ve-sahis-firmalarina-ozel-1000-tl-hediye"
)


@pytest.fixture
def fixtures(read_fixture) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return {
        "liste": read_fixture("html/kuveyt_turk/kart_kampanyalari.html"),
        "detay": read_fixture("html/kuveyt_turk/kampanya_detay.html"),
    }


def _scraper(tmp_path: Path, transport: httpx.MockTransport, **kwargs: object) -> KuveytTurkScraper:
    settings = Settings(
        raw_html_dir=str(tmp_path / "raw_html"),
        scraper_request_delay_seconds=0.0,
        scraper_max_retries=2,
        airgap_mode=False,
    )
    client = httpx.Client(transport=transport, follow_redirects=True)
    fetcher = Fetcher("kuveyt_turk", settings=settings, client=client)
    return KuveytTurkScraper(fetcher=fetcher, settings=settings, **kwargs)  # type: ignore[arg-type]


class TestKesif:
    """`discover()` — üç seviyeli detay kalıbı."""

    def test_uc_seviyeli_detaylar_bulunur(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        scraper = _scraper(
            tmp_path,
            make_transport({KART_LISTE: (200, fixtures["liste"])}),
            categories=["kart-kampanyalari"],
        )
        try:
            adresler = {d.url for d in scraper.discover()}
        finally:
            scraper.close()

        assert BARCIN_URL in adresler
        assert COLINS_URL in adresler
        assert ESNAF_URL in adresler

    def test_segment_ve_kategori_kokleri_kampanya_sayilmaz(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        """`/kampanyalar/kendim-icin` liste sayfasıdır, kampanya değil."""
        scraper = _scraper(
            tmp_path,
            make_transport({KART_LISTE: (200, fixtures["liste"])}),
            categories=["kart-kampanyalari"],
        )
        try:
            adresler = {d.url for d in scraper.discover()}
        finally:
            scraper.close()

        for yol in ("/kampanyalar/kendim-icin", "/kampanyalar/isim-icin", ARCHIVE_PATH):
            assert f"{BASE_URL}{yol}" not in adresler

    def test_kampanya_disi_baglantilar_elenir(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        scraper = _scraper(
            tmp_path,
            make_transport({KART_LISTE: (200, fixtures["liste"])}),
            categories=["kart-kampanyalari"],
        )
        try:
            adresler = {d.url for d in scraper.discover()}
        finally:
            scraper.close()

        assert not any("/finansmanlar/" in url for url in adresler)

    def test_segment_ve_kategori_adresten_okunur(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        """✅ İkisi de çıkarım değil, kaynak veri."""
        scraper = _scraper(
            tmp_path,
            make_transport({KART_LISTE: (200, fixtures["liste"])}),
            categories=["kart-kampanyalari"],
        )
        try:
            bulunan = {d.url: d for d in scraper.discover()}
        finally:
            scraper.close()

        assert bulunan[BARCIN_URL].segment_hint == "bireysel"
        assert bulunan[BARCIN_URL].category_hint == "kart-kampanyalari"
        assert bulunan[ESNAF_URL].segment_hint == "kurumsal"
        assert bulunan[ESNAF_URL].category_hint == "musteri-ol-kampanyalari"

    def test_uzun_slug_kirpilmaz(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        """⚠️ 80+ karakterlik slug; başlıktan türetme denemesi anlamsız."""
        scraper = _scraper(
            tmp_path,
            make_transport({KART_LISTE: (200, fixtures["liste"])}),
            categories=["kart-kampanyalari"],
        )
        try:
            adresler = {d.url for d in scraper.discover()}
        finally:
            scraper.close()

        assert ESNAF_URL in adresler
        assert len(ESNAF_URL.rsplit("/", 1)[-1]) > 70

    def test_arsiv_sayfasi_gezilmez(
        self, tmp_path: Path, make_transport: Callable[..., httpx.MockTransport]
    ) -> None:
        """⚠️ Arşiv BİLEREK eklenmiyor (`_listing_pages` son satırı).

        Süresi dolmuş kampanyalar yeniden çekilmesin. Eski test arşivin
        "daima taranır" olduğunu bekliyordu; beklenti kod kararıyla birlikte
        güncellenmemişti.
        """
        scraper = _scraper(tmp_path, make_transport({}), categories=["kart-kampanyalari"])
        try:
            scraper.discover()
            cekilen = {f.url for f in scraper.fetcher.history}
        finally:
            scraper.close()

        assert ARSIV_URL not in cekilen

    def test_kategori_verilmezse_sekiz_liste_taranir(
        self, tmp_path: Path, make_transport: Callable[..., httpx.MockTransport]
    ) -> None:
        """2 segment × 4 kategori = 8 liste; arşiv YOK (bkz. üstteki test)."""
        scraper = _scraper(tmp_path, make_transport({}))
        try:
            scraper.discover()
            cekilen = {f.url for f in scraper.fetcher.history if "/kampanyalar" in f.url}
        finally:
            scraper.close()

        assert len(cekilen) == 8
        assert ARSIV_URL not in cekilen

    def test_url_yardimcilari(self) -> None:
        assert KuveytTurkScraper.segment_from_url(BARCIN_URL) == "bireysel"
        assert KuveytTurkScraper.segment_from_url(ESNAF_URL) == "kurumsal"
        assert KuveytTurkScraper.category_from_url(BARCIN_URL) == "kart-kampanyalari"


class TestDetayAyristirma:
    """`parse_detail()` — oran metinde, tablo yok."""

    def _hint(self) -> DiscoveredUrl:
        return DiscoveredUrl(
            url=BARCIN_URL,
            doc_type="campaign",
            category_hint="kart-kampanyalari",
            segment_hint="bireysel",
            discovery_method="listing",
        )

    def test_tarih_kosullardan_cozulur(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
        donem_uygula,  # type: ignore[no-untyped-def]
    ) -> None:
        scraper = _scraper(tmp_path, make_transport({}))
        try:
            ham = scraper.parse_detail(fixtures["detay"], BARCIN_URL, self._hint())
            donem_uygula(scraper, fixtures["detay"], ham)
        finally:
            scraper.close()

        assert ham is not None
        assert ham.start_date == date(2026, 8, 1)
        assert ham.end_date == date(2026, 9, 30)

    def test_taksit_bilgisi_kosul_metninde_saklanir(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        """⚠️ Yapısal oran tablosu yok; bilgi ham metinde kalır."""
        scraper = _scraper(tmp_path, make_transport({}))
        try:
            ham = scraper.parse_detail(fixtures["detay"], BARCIN_URL, self._hint())
        finally:
            scraper.close()

        assert ham is not None
        assert ham.conditions_text and "1.500 TL" in ham.conditions_text

    def test_slug_adresten_okunur(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        scraper = _scraper(tmp_path, make_transport({}))
        try:
            ham = scraper.parse_detail(fixtures["detay"], ESNAF_URL, self._hint())
        finally:
            scraper.close()

        assert ham is not None
        assert ham.external_slug.startswith("mobilden-kuveyt-turklu-olan-esnaf")


class TestUctanUca:
    """`run()`."""

    def test_kampanyalar_kaydedilir(
        self,
        tmp_path: Path,
        seeded_session: Session,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        transport = make_transport(
            {
                KART_LISTE: (200, fixtures["liste"]),
                BARCIN_URL: (200, fixtures["detay"]),
                COLINS_URL: (200, fixtures["detay"]),
                ESNAF_URL: (200, fixtures["detay"]),
            }
        )
        scraper = _scraper(tmp_path, transport, categories=["kart-kampanyalari"])
        try:
            sonuc = scraper.run(seeded_session)
        finally:
            scraper.close()

        assert sonuc.campaigns_new == 3
        segmentler = {k.segment for k in seeded_session.scalars(select(Campaign))}
        assert segmentler == {"bireysel", "kurumsal"}


class TestKampanyaUcu:
    """JSON ucu ve YEDEKLİ davranışı.

    Liste sayfası "Daha Fazla Yükle" arkasındaki kayıtları veremiyor ve
    kategori başına tam 9'da kesiliyordu. Uç `StartDate`/`EndDate` alanlarını
    yapısal olarak döndürüyor, ama WAF yolunda olduğu için kırılgan.
    """

    def test_uctan_kampanyalar_kesfedilir(
        self,
        tmp_path: Path,
        read_fixture,  # type: ignore[no-untyped-def]
        make_transport,  # type: ignore[no-untyped-def]
    ) -> None:
        govde = read_fixture("json/kuveyt_turk_campaign_list.json")
        scraper = _scraper(tmp_path, make_transport({CAMPAIGN_API_URL: (200, govde)}))
        try:
            bulunan = scraper.discover()
        finally:
            scraper.close()

        sluglar = {u.url.rsplit("/", 1)[-1] for u in bulunan}
        assert "colinsde-vade-farksiz-4-aya-varan-taksit-firsati" in sluglar
        assert "barcin-sporda-4-taksit-firsati" in sluglar
        # Göreli `Url` mutlaklaştırıldı.
        assert all(u.url.startswith(BASE_URL) for u in bulunan)

    def test_uc_dususe_liste_yolu_calisir(
        self, tmp_path: Path, make_transport: Callable[..., httpx.MockTransport]
    ) -> None:
        """⚠️ WAF yolu rotasyona girerse banka boş kalmamalı."""
        scraper = _scraper(tmp_path, make_transport({}))
        try:
            # Uç 404, liste sayfaları da boş → hata değil, yalnızca sonuç yok.
            bulunan = scraper.discover()
        finally:
            scraper.close()

        assert bulunan == []

    def test_bozuk_json_cokertmez(
        self, tmp_path: Path, make_transport: Callable[..., httpx.MockTransport]
    ) -> None:
        scraper = _scraper(tmp_path, make_transport({CAMPAIGN_API_URL: (200, "<html>bozuk")}))
        try:
            assert scraper.discover() == []
        finally:
            scraper.close()
