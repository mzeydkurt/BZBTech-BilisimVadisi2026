"""Vakıf Katılım scraper testleri.

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
from app.scrapers.banks.vakif_katilim import BASE_URL, VakifKatilimScraper
from app.scrapers.fetcher import Fetcher
from app.scrapers.models import DiscoveredUrl

BIREYSEL_LISTE = f"{BASE_URL}/tr/kendim-icin/kampanyalar/mevcut-kampanyalar"
BIREYSEL_ARSIV = f"{BASE_URL}/tr/kendim-icin/kampanyalar/gecmis-kampanyalar"
KURUMSAL_LISTE = f"{BASE_URL}/tr/isim-icin/kampanyalar/mevcut-kampanyalar"

TAMAMLA_URL = f"{BASE_URL}/tr/kendim-icin/kampanyalar/detay/tamamla-kazan"
VCLUB_URL = f"{BASE_URL}/tr/kendim-icin/kampanyalar/detay/vclub-dunyasi-artik-vakif-katilim-mobilde"


@pytest.fixture
def fixtures(read_fixture) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return {
        "liste": read_fixture("html/vakif_katilim/mevcut_kampanyalar.html"),
        "detay": read_fixture("html/vakif_katilim/kampanya_detay.html"),
    }


def _scraper(
    tmp_path: Path, transport: httpx.MockTransport, **kwargs: object
) -> VakifKatilimScraper:
    settings = Settings(
        raw_html_dir=str(tmp_path / "raw_html"),
        scraper_request_delay_seconds=0.0,
        scraper_max_retries=2,
        airgap_mode=False,
    )
    client = httpx.Client(transport=transport, follow_redirects=True)
    fetcher = Fetcher("vakif_katilim", settings=settings, client=client)
    return VakifKatilimScraper(fetcher=fetcher, settings=settings, **kwargs)  # type: ignore[arg-type]


class TestKesif:
    """`discover()` — sunucu HTML'i yeterli, tarayıcı gerekmiyor."""

    def test_kampanyalar_sunucu_htmlinden_bulunur(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        """⚠️ Önceki analiz "httpx ile 0 kampanya" diyordu; ölçüm aksini gösterdi."""
        scraper = _scraper(
            tmp_path,
            make_transport({BIREYSEL_LISTE: (200, fixtures["liste"])}),
            categories=["bireysel"],
        )
        try:
            adresler = {d.url for d in scraper.discover()}
        finally:
            scraper.close()

        assert adresler == {TAMAMLA_URL, VCLUB_URL}

    def test_uc_baglanti_tekillesir(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        scraper = _scraper(
            tmp_path,
            make_transport({BIREYSEL_LISTE: (200, fixtures["liste"])}),
            categories=["bireysel"],
        )
        try:
            adresler = [d.url for d in scraper.discover()]
        finally:
            scraper.close()

        assert adresler.count(TAMAMLA_URL) == 1

    def test_liste_ve_arsiv_sayfalari_kampanya_sayilmaz(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        scraper = _scraper(
            tmp_path,
            make_transport({BIREYSEL_LISTE: (200, fixtures["liste"])}),
            categories=["bireysel"],
        )
        try:
            adresler = {d.url for d in scraper.discover()}
        finally:
            scraper.close()

        assert BIREYSEL_LISTE not in adresler
        assert BIREYSEL_ARSIV not in adresler

    def test_segment_adresten_gelir(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        """✅ Segment yalnızca adresten elde edilebiliyor."""
        scraper = _scraper(
            tmp_path,
            make_transport({BIREYSEL_LISTE: (200, fixtures["liste"])}),
            categories=["bireysel"],
        )
        try:
            bulunan = scraper.discover()
        finally:
            scraper.close()

        assert all(d.segment_hint == "bireysel" for d in bulunan)

    def test_kurumsal_segment_de_taranir(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        scraper = _scraper(tmp_path, make_transport({}))
        try:
            scraper.discover()
            cekilen = {f.url for f in scraper.fetcher.history}
        finally:
            scraper.close()

        assert KURUMSAL_LISTE in cekilen
        assert BIREYSEL_ARSIV in cekilen

    def test_arsiv_isaretlenir(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        scraper = _scraper(
            tmp_path,
            make_transport({BIREYSEL_ARSIV: (200, fixtures["liste"])}),
            categories=["bireysel"],
        )
        try:
            bulunan = scraper.discover()
        finally:
            scraper.close()

        assert bulunan
        assert all(d.discovery_method == "archive" for d in bulunan)

    def test_gercek_404_cop_kayit_uretmez(
        self, tmp_path: Path, make_transport: Callable[..., httpx.MockTransport]
    ) -> None:
        """⚠️ Site artık gerçek 404 döndürüyor; soft-404 denetimi yine devrede."""
        scraper = _scraper(tmp_path, make_transport({}), categories=["bireysel"])
        try:
            assert scraper.discover() == []
        finally:
            scraper.close()

    def test_segment_url_yardimcisi(self) -> None:
        assert VakifKatilimScraper.segment_from_url(TAMAMLA_URL) == "bireysel"
        assert (
            VakifKatilimScraper.segment_from_url(f"{BASE_URL}/tr/isim-icin/kampanyalar/detay/x")
            == "kurumsal"
        )
        assert VakifKatilimScraper.segment_from_url(f"{BASE_URL}/tr/diger/x") is None


class TestDetayAyristirma:
    """`parse_detail()` — Türkçe ay adlı tarih ve gizli accordion içeriği."""

    def _hint(self) -> DiscoveredUrl:
        return DiscoveredUrl(
            url=TAMAMLA_URL,
            doc_type="campaign",
            segment_hint="bireysel",
            discovery_method="listing",
        )

    def test_turkce_ay_adli_tarih_cozulur(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
        donem_uygula,  # type: ignore[no-untyped-def]
    ) -> None:
        """ "02 Ocak 2026 - 31 Aralık 2026"."""
        scraper = _scraper(tmp_path, make_transport({}))
        try:
            ham = scraper.parse_detail(fixtures["detay"], TAMAMLA_URL, self._hint())
            donem_uygula(scraper, fixtures["detay"], ham)
        finally:
            scraper.close()

        assert ham is not None
        assert ham.start_date == date(2026, 1, 2)
        assert ham.end_date == date(2026, 12, 31)

    def test_gizli_accordion_icerigi_ayristirilir(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        """Koşullar `display:none` içinde ama sunucu HTML'inde var."""
        scraper = _scraper(tmp_path, make_transport({}))
        try:
            ham = scraper.parse_detail(fixtures["detay"], TAMAMLA_URL, self._hint())
        finally:
            scraper.close()

        assert ham is not None
        assert ham.conditions_text and "altı kriter" in ham.conditions_text.casefold()

    def test_slug_adresten_okunur(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        scraper = _scraper(tmp_path, make_transport({}))
        try:
            ham = scraper.parse_detail(fixtures["detay"], TAMAMLA_URL, self._hint())
        finally:
            scraper.close()

        assert ham is not None
        assert ham.external_slug == "tamamla-kazan"

    def test_segment_ipucu_yoksa_adresten_turetilir(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        bos_hint = DiscoveredUrl(url=TAMAMLA_URL, doc_type="campaign")
        scraper = _scraper(tmp_path, make_transport({}))
        try:
            ham = scraper.parse_detail(fixtures["detay"], TAMAMLA_URL, bos_hint)
        finally:
            scraper.close()

        assert ham is not None
        assert ham.segment == "bireysel"


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
                BIREYSEL_LISTE: (200, fixtures["liste"]),
                TAMAMLA_URL: (200, fixtures["detay"]),
                VCLUB_URL: (200, fixtures["detay"]),
            }
        )
        scraper = _scraper(tmp_path, transport, categories=["bireysel"])
        try:
            sonuc = scraper.run(seeded_session)
        finally:
            scraper.close()

        assert sonuc.campaigns_new == 2
        kayitlar = list(seeded_session.scalars(select(Campaign)))
        assert all(k.segment == "bireysel" for k in kayitlar)
        assert all(k.status == "active" for k in kayitlar)
