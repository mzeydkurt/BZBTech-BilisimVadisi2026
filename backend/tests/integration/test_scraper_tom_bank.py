"""T.O.M. Bank scraper testleri.

Testler ağa çıkmaz (§13). Fixture canlı sitemap yapısından (14 Ağustos 2026)
alınmıştır.

En kritik test `test_ayni_slug_iki_onekte_tekillesir`: canlı ölçümde 76
kampanyanın 76'sı da ikinci yol ön ekinde tekrar ediyordu. Yol bazlı
tekilleştirme bu hatayı yakalamaz — adresler farklı.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Campaign
from app.scrapers.banks.tom_bank import BASE_URL, SITEMAP_URL, TomBankScraper
from app.scrapers.fetcher import Fetcher
from app.scrapers.models import DiscoveredUrl

VERGI_URL = f"{BASE_URL}/kampanyalar/vergi-kampanyasi"
A101_URL = f"{BASE_URL}/kampanyalar/a101lerde-sut-urunleri-harcamalarinda-50-hediye-bakiye-kazan"
AYRICALIK_URL = f"{BASE_URL}/hadi-kredi-karti-ayricaliklari/restoran-ayricaliklari"

KULUP_VERGI_URL = f"{BASE_URL}/cok-kazananlar-kulubu-kampanya/vergi-kampanyasi"


@pytest.fixture
def sitemap_xml(read_fixture) -> str:  # type: ignore[no-untyped-def]
    return read_fixture("html/tom_bank/sitemap.xml")


@pytest.fixture
def detay_html(read_fixture) -> str:  # type: ignore[no-untyped-def]
    return read_fixture("html/tom_bank/kampanya_detay.html")


def _transport(sitemap: bytes, *, detaylar: dict[str, str] | None = None) -> httpx.MockTransport:
    detaylar = detaylar or {}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/robots.txt"):
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if url == SITEMAP_URL:
            return httpx.Response(200, content=sitemap, headers={"content-type": "text/xml"})
        if url in detaylar:
            return httpx.Response(
                200, text=detaylar[url], headers={"content-type": "text/html; charset=utf-8"}
            )
        return httpx.Response(404, text="<html><title>404</title></html>")

    return httpx.MockTransport(handler)


def _scraper(tmp_path: Path, transport: httpx.MockTransport, **kwargs: object) -> TomBankScraper:
    settings = Settings(
        raw_html_dir=str(tmp_path / "raw_html"),
        scraper_request_delay_seconds=0.0,
        scraper_max_retries=2,
        airgap_mode=False,
    )
    client = httpx.Client(transport=transport, follow_redirects=True)
    fetcher = Fetcher("tom_bank", settings=settings, client=client)
    return TomBankScraper(fetcher=fetcher, settings=settings, **kwargs)  # type: ignore[arg-type]


class TestKesif:
    """`discover()` — sitemap ve slug tekilleştirmesi."""

    def test_ayni_slug_iki_onekte_tekillesir(self, tmp_path: Path, sitemap_xml: str) -> None:
        """⚠️ Aynı kampanya `/kampanyalar/` ve `/cok-kazananlar-kulubu-kampanya/` altında."""
        scraper = _scraper(tmp_path, _transport(sitemap_xml.encode("utf-8")))
        try:
            adresler = {d.url for d in scraper.discover()}
        finally:
            scraper.close()

        assert VERGI_URL in adresler
        assert KULUP_VERGI_URL not in adresler
        # 2 kampanya + 1 ayrıcalık; kopyalar elendi.
        assert len(adresler) == 3

    def test_kanonik_onek_tercih_edilir(self, tmp_path: Path, sitemap_xml: str) -> None:
        """Aynı slug iki ön ekte varsa `/kampanyalar/` yazımı korunur."""
        scraper = _scraper(tmp_path, _transport(sitemap_xml.encode("utf-8")))
        try:
            adresler = {d.url for d in scraper.discover()}
        finally:
            scraper.close()

        vergi = [u for u in adresler if u.endswith("/vergi-kampanyasi")]
        assert vergi == [VERGI_URL]

    def test_ayricalik_sayfalari_da_alinir(self, tmp_path: Path, sitemap_xml: str) -> None:
        """Bu sayfalara kök sayfadan bağlantı yok; yalnızca sitemap'te var."""
        scraper = _scraper(tmp_path, _transport(sitemap_xml.encode("utf-8")))
        try:
            adresler = {d.url for d in scraper.discover()}
        finally:
            scraper.close()

        assert AYRICALIK_URL in adresler

    def test_liste_ve_kok_sayfalari_kampanya_sayilmaz(
        self, tmp_path: Path, sitemap_xml: str
    ) -> None:
        scraper = _scraper(tmp_path, _transport(sitemap_xml.encode("utf-8")))
        try:
            adresler = {d.url for d in scraper.discover()}
        finally:
            scraper.close()

        assert f"{BASE_URL}/kampanyalar" not in adresler
        assert f"{BASE_URL}/hadi-kazan/kampanyalar" not in adresler
        assert not any("/sozlesme-ve-formlar/" in u for u in adresler)

    def test_ayna_domain_alinmaz(self, tmp_path: Path, sitemap_xml: str) -> None:
        """`hadiyanindakibanka.com` ayna; aynı site denetimi eler."""
        scraper = _scraper(tmp_path, _transport(sitemap_xml.encode("utf-8")))
        try:
            adresler = {d.url for d in scraper.discover()}
        finally:
            scraper.close()

        assert not any("hadiyanindakibanka.com" in u for u in adresler)

    def test_tek_istek_yapilir(self, tmp_path: Path, sitemap_xml: str) -> None:
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


class TestDetayAyristirma:
    """`parse_detail()`."""

    def _hint(self) -> DiscoveredUrl:
        return DiscoveredUrl(
            url=VERGI_URL,
            doc_type="campaign",
            segment_hint="bireysel",
            discovery_method="sitemap",
        )

    def test_tarih_ve_kosullar_cikarilir(
        self,
        tmp_path: Path,
        sitemap_xml: str,
        detay_html: str,
        donem_uygula,  # type: ignore[no-untyped-def]
    ) -> None:
        scraper = _scraper(tmp_path, _transport(sitemap_xml.encode("utf-8")))
        try:
            ham = scraper.parse_detail(detay_html, VERGI_URL, self._hint())
            donem_uygula(scraper, detay_html, ham)
        finally:
            scraper.close()

        assert ham is not None
        assert ham.start_date == date(2026, 8, 1)
        assert ham.end_date == date(2026, 9, 30)
        assert ham.conditions_text and "5.000 TL" in ham.conditions_text

    def test_slug_adresten_okunur(self, tmp_path: Path, sitemap_xml: str, detay_html: str) -> None:
        scraper = _scraper(tmp_path, _transport(sitemap_xml.encode("utf-8")))
        try:
            ham = scraper.parse_detail(detay_html, VERGI_URL, self._hint())
        finally:
            scraper.close()

        assert ham is not None
        assert ham.external_slug == "vergi-kampanyasi"


class TestUctanUca:
    """`run()`."""

    def test_kampanyalar_bir_kez_kaydedilir(
        self,
        tmp_path: Path,
        seeded_session: Session,
        sitemap_xml: str,
        detay_html: str,
    ) -> None:
        """⚠️ Tekilleştirme çalışmazsa aynı kampanya iki kez yazılırdı."""
        transport = _transport(
            sitemap_xml.encode("utf-8"),
            detaylar={
                VERGI_URL: detay_html,
                A101_URL: detay_html,
                AYRICALIK_URL: detay_html,
            },
        )
        scraper = _scraper(tmp_path, transport)
        try:
            sonuc = scraper.run(seeded_session)
        finally:
            scraper.close()

        assert sonuc.campaigns_new == 3
        sluglar = [k.external_slug for k in seeded_session.scalars(select(Campaign))]
        assert len(sluglar) == len(set(sluglar))
