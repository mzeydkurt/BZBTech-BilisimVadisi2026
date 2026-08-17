"""Dünya Katılım scraper testleri.

Testler ağa çıkmaz (§13). Fixture'lar canlı sayfa yapısından (14 Ağustos 2026)
alınmıştır.
"""

from __future__ import annotations

import gzip
from datetime import date
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Campaign
from app.scrapers.banks.dunya_katilim import SITEMAP_URL, DunyaKatilimScraper
from app.scrapers.fetcher import Fetcher
from app.scrapers.models import DiscoveredUrl

# ⚠️ Sitemap adresleri `www.` ÖN EKSİZ geliyor.
ALTIN_URL = "https://dunyakatilim.com.tr/kampanyalar/altin-kesemTicari"
A101_URL = "https://dunyakatilim.com.tr/kampanyalar/a-101-paraf"
KURLAR_URL = "https://dunyakatilim.com.tr/kampanyalar/avantajli-kurlar"


@pytest.fixture
def sitemap_xml(read_fixture) -> str:  # type: ignore[no-untyped-def]
    return read_fixture("html/dunya_katilim/sitemap.xml")


@pytest.fixture
def detay_html(read_fixture) -> str:  # type: ignore[no-untyped-def]
    return read_fixture("html/dunya_katilim/kampanya_detay.html")


def _transport(
    sitemap_govde: bytes, *, detaylar: dict[str, str] | None = None
) -> httpx.MockTransport:
    """Sitemap'i BAYT olarak servis eden taşıyıcı.

    `make_transport` metin döndürdüğü için gzip senaryosu kurulamaz; bu
    yüzden burada elle yazılmıştır.
    """
    detaylar = detaylar or {}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/robots.txt"):
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if url == SITEMAP_URL:
            return httpx.Response(200, content=sitemap_govde, headers={"content-type": "text/xml"})
        if url in detaylar:
            return httpx.Response(
                200,
                text=detaylar[url],
                headers={"content-type": "text/html; charset=utf-8"},
            )
        return httpx.Response(404, text="<html><title>404</title></html>")

    return httpx.MockTransport(handler)


def _scraper(
    tmp_path: Path, transport: httpx.MockTransport, **kwargs: object
) -> DunyaKatilimScraper:
    settings = Settings(
        raw_html_dir=str(tmp_path / "raw_html"),
        scraper_request_delay_seconds=0.0,
        scraper_max_retries=2,
        airgap_mode=False,
    )
    client = httpx.Client(transport=transport, follow_redirects=True)
    fetcher = Fetcher("dunya_katilim", settings=settings, client=client)
    return DunyaKatilimScraper(fetcher=fetcher, settings=settings, **kwargs)  # type: ignore[arg-type]


class TestKesif:
    """`discover()` — sitemap tek kaynak."""

    def test_sitemapten_kampanyalar_bulunur(self, tmp_path: Path, sitemap_xml: str) -> None:
        scraper = _scraper(tmp_path, _transport(sitemap_xml.encode("utf-8")))
        try:
            adresler = {d.url for d in scraper.discover()}
        finally:
            scraper.close()

        assert adresler == {ALTIN_URL, A101_URL, KURLAR_URL}

    def test_camelcase_slug_bozulmaz(self, tmp_path: Path, sitemap_xml: str) -> None:
        """⚠️ `altin-kesemTicari` küçük harfe çevrilirse HTTP 404."""
        scraper = _scraper(tmp_path, _transport(sitemap_xml.encode("utf-8")))
        try:
            adresler = {d.url for d in scraper.discover()}
        finally:
            scraper.close()

        assert ALTIN_URL in adresler
        assert "kesemTicari" in ALTIN_URL

    def test_www_onaksiz_adresler_dis_baglanti_sayilmaz(
        self, tmp_path: Path, sitemap_xml: str
    ) -> None:
        """⚠️ Ham dize karşılaştırması yapılsaydı keşif SIFIR dönerdi."""
        scraper = _scraper(tmp_path, _transport(sitemap_xml.encode("utf-8")))
        try:
            bulunan = scraper.discover()
        finally:
            scraper.close()

        assert bulunan
        assert all(url.url.startswith("https://dunyakatilim.com.tr/") for url in bulunan)

    def test_ingilizce_surum_ve_dis_site_elenir(self, tmp_path: Path, sitemap_xml: str) -> None:
        scraper = _scraper(tmp_path, _transport(sitemap_xml.encode("utf-8")))
        try:
            adresler = {d.url for d in scraper.discover()}
        finally:
            scraper.close()

        assert not any("/en/" in url for url in adresler)
        assert not any("baska-site.com" in url for url in adresler)

    def test_kampanya_koku_ve_urun_sayfasi_elenir(self, tmp_path: Path, sitemap_xml: str) -> None:
        scraper = _scraper(tmp_path, _transport(sitemap_xml.encode("utf-8")))
        try:
            adresler = {d.url for d in scraper.discover()}
        finally:
            scraper.close()

        assert "https://dunyakatilim.com.tr/kampanyalar" not in adresler
        assert not any("/finansmanlar" in url for url in adresler)

    def test_gzipli_sitemap_de_calisir(self, tmp_path: Path, sitemap_xml: str) -> None:
        """Site gzip'e dönerse davranış kendiliğinden sürmeli."""
        scraper = _scraper(tmp_path, _transport(gzip.compress(sitemap_xml.encode("utf-8"))))
        try:
            adresler = {d.url for d in scraper.discover()}
        finally:
            scraper.close()

        assert adresler == {ALTIN_URL, A101_URL, KURLAR_URL}

    def test_liste_sayfasi_hic_cekilmez(self, tmp_path: Path, sitemap_xml: str) -> None:
        """⚠️ Liste JS ile yükleniyor; çekilse bile sıfır kampanya verirdi."""
        scraper = _scraper(tmp_path, _transport(sitemap_xml.encode("utf-8")))
        try:
            scraper.discover()
            cekilen = {f.url for f in scraper.fetcher.history}
        finally:
            scraper.close()

        assert cekilen == {SITEMAP_URL}

    def test_sitemap_alinamazsa_cokmez(self, tmp_path: Path) -> None:
        scraper = _scraper(tmp_path, _transport(b""))
        try:
            assert scraper.discover() == []
        finally:
            scraper.close()

    def test_bozuk_sitemap_cokmez(self, tmp_path: Path) -> None:
        scraper = _scraper(tmp_path, _transport(b"<urlset><url><loc>yarim"))
        try:
            assert scraper.discover() == []
        finally:
            scraper.close()


class TestDetayAyristirma:
    """`parse_detail()` — saatli tarih ve ağır boilerplate."""

    def _hint(self) -> DiscoveredUrl:
        return DiscoveredUrl(
            url=ALTIN_URL,
            doc_type="campaign",
            segment_hint="bireysel",
            discovery_method="sitemap",
        )

    def test_saatli_tarih_cozulur(
        self,
        tmp_path: Path,
        sitemap_xml: str,
        detay_html: str,
        donem_uygula,  # type: ignore[no-untyped-def]
    ) -> None:
        """⚠️ "15 Haziran 2026 saat 00.01 – 15 Temmuz 2026 saat 23.59"."""
        scraper = _scraper(tmp_path, _transport(sitemap_xml.encode("utf-8")))
        try:
            ham = scraper.parse_detail(detay_html, ALTIN_URL, self._hint())
            donem_uygula(scraper, detay_html, ham)
        finally:
            scraper.close()

        assert ham is not None
        assert ham.start_date == date(2026, 6, 15)
        assert ham.end_date == date(2026, 7, 15)

    def test_slug_camelcase_korunur(
        self, tmp_path: Path, sitemap_xml: str, detay_html: str
    ) -> None:
        scraper = _scraper(tmp_path, _transport(sitemap_xml.encode("utf-8")))
        try:
            ham = scraper.parse_detail(detay_html, ALTIN_URL, self._hint())
        finally:
            scraper.close()

        assert ham is not None
        assert ham.external_slug == "altin-kesemTicari"

    def test_aciklama_boilerplate_almaz(
        self, tmp_path: Path, sitemap_xml: str, detay_html: str
    ) -> None:
        scraper = _scraper(tmp_path, _transport(sitemap_xml.encode("utf-8")))
        try:
            ham = scraper.parse_detail(detay_html, ALTIN_URL, self._hint())
        finally:
            scraper.close()

        assert ham is not None
        assert ham.description is not None
        assert "genel bilgilendirme amaçlıdır" not in ham.description


class TestUctanUca:
    """`run()`."""

    def test_kampanyalar_kaydedilir_ve_arsivlenir(
        self,
        tmp_path: Path,
        seeded_session: Session,
        sitemap_xml: str,
        detay_html: str,
    ) -> None:
        """⚠️ Kampanya sayfaları siliniyor; ham HTML arşivi kritik."""
        transport = _transport(
            sitemap_xml.encode("utf-8"),
            detaylar={ALTIN_URL: detay_html, A101_URL: detay_html, KURLAR_URL: detay_html},
        )
        scraper = _scraper(tmp_path, transport)
        try:
            sonuc = scraper.run(seeded_session)
        finally:
            scraper.close()

        assert sonuc.campaigns_new == 3
        assert list(seeded_session.scalars(select(Campaign)))
        assert list((tmp_path / "raw_html" / "dunya_katilim").glob("*.html"))
