"""Albaraka Türk scraper testleri.

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
from app.scrapers.banks.albaraka import (
    BASE_URL,
    LISTING_URL,
    SITEMAP_URL,
    AlbarakaScraper,
)
from app.scrapers.fetcher import Fetcher
from app.scrapers.models import DiscoveredUrl

FATURA_URL = f"{BASE_URL}/tr/kampanyalar/detay/agustos-ayina-ozel-fatura-kampanyasi"
ISPARK_URL = f"{BASE_URL}/tr/kampanyalar/detay/albarakalilara-ozel-ucretsiz-ispark-kampanyasi-1"
PAYLASIM_URL = f"{BASE_URL}/tr/kampanyalar/detay/dijital-katilma-hesabina-ozel-paylasim-oranlari-10"


@pytest.fixture
def fixtures(read_fixture) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return {
        "liste": read_fixture("html/albaraka/kampanyalar.html"),
        "detay": read_fixture("html/albaraka/kampanya_detay.html"),
    }


def _scraper(tmp_path: Path, transport: httpx.MockTransport, **kwargs: object) -> AlbarakaScraper:
    settings = Settings(
        raw_html_dir=str(tmp_path / "raw_html"),
        scraper_request_delay_seconds=0.0,
        scraper_max_retries=2,
        airgap_mode=False,
    )
    client = httpx.Client(transport=transport, follow_redirects=True)
    fetcher = Fetcher("albaraka", settings=settings, client=client)
    return AlbarakaScraper(fetcher=fetcher, settings=settings, **kwargs)  # type: ignore[arg-type]


class TestKesif:
    """`discover()` — sabit liste, robots yasağı."""

    def test_kampanyalar_bulunur(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        scraper = _scraper(tmp_path, make_transport({LISTING_URL: (200, fixtures["liste"])}))
        try:
            adresler = {d.url for d in scraper.discover()}
        finally:
            scraper.close()

        assert adresler == {FATURA_URL, ISPARK_URL, PAYLASIM_URL}

    def test_slug_sonekleri_korunur(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        """⚠️ `-1` ve `-10` farklı dönem; kırpılırsa kayıtlar üst üste yazılır."""
        scraper = _scraper(tmp_path, make_transport({LISTING_URL: (200, fixtures["liste"])}))
        try:
            adresler = {d.url for d in scraper.discover()}
        finally:
            scraper.close()

        assert any(url.endswith("-1") for url in adresler)
        assert any(url.endswith("-10") for url in adresler)

    def test_robots_yasakli_adresler_kesfe_girmez(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        """⚠️ `Disallow: /*slug` ve `/tr/ticari-ve-kurumsal*` — uyulur, aşılmaz."""
        scraper = _scraper(tmp_path, make_transport({LISTING_URL: (200, fixtures["liste"])}))
        try:
            adresler = {d.url for d in scraper.discover()}
            cekilen = {f.url for f in scraper.fetcher.history}
        finally:
            scraper.close()

        assert not any("slug=" in url for url in adresler)
        assert not any("/tr/ticari-ve-kurumsal" in url for url in adresler)
        assert not any("slug=" in url for url in cekilen)

    def test_detay_koku_kampanya_sayilmaz(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        scraper = _scraper(tmp_path, make_transport({LISTING_URL: (200, fixtures["liste"])}))
        try:
            adresler = {d.url for d in scraper.discover()}
        finally:
            scraper.close()

        assert f"{BASE_URL}/tr/kampanyalar/detay" not in adresler

    def test_liste_sabitse_iki_turda_durur(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        """⚠️ Rotasyon ölçümde bulunmadı; döngü boşuna dönmemeli."""
        scraper = _scraper(tmp_path, make_transport({LISTING_URL: (200, fixtures["liste"])}))
        try:
            scraper.discover()
            liste_istekleri = [f for f in scraper.fetcher.history if f.url == LISTING_URL]
        finally:
            scraper.close()

        # 1. tur yeni slug getirir, 2. tur getirmez -> DRY_ROUNDS=2 ile 3. turda durur.
        assert len(liste_istekleri) <= 3

    def test_liste_alinamazsa_cokmez(
        self, tmp_path: Path, make_transport: Callable[..., httpx.MockTransport]
    ) -> None:
        scraper = _scraper(tmp_path, make_transport({}))
        try:
            assert scraper.discover() == []
        finally:
            scraper.close()


class TestDetayAyristirma:
    """`parse_detail()` — standart başlık blokları, tek ve temiz tarih."""

    def _hint(self) -> DiscoveredUrl:
        return DiscoveredUrl(
            url=FATURA_URL,
            doc_type="campaign",
            segment_hint="bireysel",
            discovery_method="listing",
        )

    def test_tarih_exact_cozulur(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
        donem_uygula,  # type: ignore[no-untyped-def]
    ) -> None:
        scraper = _scraper(tmp_path, make_transport({}))
        try:
            ham = scraper.parse_detail(fixtures["detay"], FATURA_URL, self._hint())
            donem_uygula(scraper, fixtures["detay"], ham)
        finally:
            scraper.close()

        assert ham is not None
        assert ham.start_date == date(2026, 8, 1)
        assert ham.end_date == date(2026, 8, 31)
        assert ham.date_precision == "exact"

    def test_katilim_adimlari_kosullara_girer(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        scraper = _scraper(tmp_path, make_transport({}))
        try:
            ham = scraper.parse_detail(fixtures["detay"], FATURA_URL, self._hint())
        finally:
            scraper.close()

        assert ham is not None
        assert ham.conditions_text and "Albaraka Mobil" in ham.conditions_text

    def test_slug_soneki_kayitta_korunur(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        scraper = _scraper(tmp_path, make_transport({}))
        try:
            ham = scraper.parse_detail(fixtures["detay"], PAYLASIM_URL, self._hint())
        finally:
            scraper.close()

        assert ham is not None
        assert ham.external_slug.endswith("-10")


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
                LISTING_URL: (200, fixtures["liste"]),
                FATURA_URL: (200, fixtures["detay"]),
                ISPARK_URL: (200, fixtures["detay"]),
                PAYLASIM_URL: (200, fixtures["detay"]),
            }
        )
        scraper = _scraper(tmp_path, transport)
        try:
            sonuc = scraper.run(seeded_session)
        finally:
            scraper.close()

        assert sonuc.campaigns_new == 3
        sluglar = {k.external_slug for k in seeded_session.scalars(select(Campaign))}
        assert len(sluglar) == 3


class TestSitemapKesfi:
    """Sitemap ASIL keşif kaynağıdır; liste sayfası 12 slug veriyor.

    Canlı sitede ölçüldü: sitemap 1457 adres / 40 kampanya. JSON ucu
    (`/plugins/GetCampaigns`) `Disallow: /plugins/` kapsamında olduğu için
    hiç kullanılmaz.
    """

    def _scraper_sitemapli(
        self,
        tmp_path: Path,
        read_fixture,  # type: ignore[no-untyped-def]
        make_transport,  # type: ignore[no-untyped-def]
    ) -> AlbarakaScraper:
        sitemap = read_fixture("html/albaraka/sitemap.xml")
        return _scraper(tmp_path, make_transport({SITEMAP_URL: (200, sitemap)}))

    def test_sitemapten_kampanyalar_kesfedilir(
        self,
        tmp_path: Path,
        read_fixture,  # type: ignore[no-untyped-def]
        make_transport,  # type: ignore[no-untyped-def]
    ) -> None:
        scraper = self._scraper_sitemapli(tmp_path, read_fixture, make_transport)
        try:
            sluglar = {u.url.rsplit("/", 1)[-1] for u in scraper.discover()}
        finally:
            scraper.close()

        assert "biletcom-ucak-bileti-kampanyasi" in sluglar
        assert "kahve-keyfiniz-albarakadan" in sluglar
        # Sonek korunur; farklı dönem demektir.
        assert "ispark-kampanyasi-1" in sluglar

    def test_yil_indeksi_kampanya_sayilmaz(
        self,
        tmp_path: Path,
        read_fixture,  # type: ignore[no-untyped-def]
        make_transport,  # type: ignore[no-untyped-def]
    ) -> None:
        """⚠️ `/detay/2026` yıl indeksidir; kampanya adresi değil."""
        scraper = self._scraper_sitemapli(tmp_path, read_fixture, make_transport)
        try:
            adresler = {u.url for u in scraper.discover()}
        finally:
            scraper.close()

        assert f"{BASE_URL}/tr/kampanyalar/detay/2026" not in adresler
        assert LISTING_URL not in adresler

    def test_robots_yasakli_adresler_alinmaz(
        self,
        tmp_path: Path,
        read_fixture,  # type: ignore[no-untyped-def]
        make_transport,  # type: ignore[no-untyped-def]
    ) -> None:
        """Sitemap'te olsa bile yasağa uyulur; keşif o adresleri önermez."""
        scraper = self._scraper_sitemapli(tmp_path, read_fixture, make_transport)
        try:
            adresler = {u.url for u in scraper.discover()}
        finally:
            scraper.close()

        assert not any("ticari-ve-kurumsal" in u for u in adresler)
        assert not any("slug=" in u for u in adresler)
