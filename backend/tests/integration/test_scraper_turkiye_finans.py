"""Türkiye Finans scraper testleri.

Testler ağa çıkmaz: kaydedilmiş HTML fixture'ları `httpx.MockTransport`
üzerinden servis edilir (§13).

Fixture'lar canlı sayfa yapısından (13 Ağustos 2026) alınmıştır; görünmez
karakterler (U+200B, U+00A0) bilinçli olarak korunmuştur.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Campaign
from app.scrapers.banks.turkiye_finans import (
    ARCHIVE_PAGE,
    BASE_URL,
    CAMPAIGN_DIR,
    CATEGORY_PAGES,
    HAPPYCARD_LISTING,
    HUB_PAGE,
    TurkiyeFinansScraper,
)
from app.scrapers.fetcher import Fetcher
from app.scrapers.models import DiscoveredUrl


def _sayfa(dosya: str) -> str:
    return f"{BASE_URL}{CAMPAIGN_DIR}{dosya}"


KART_URL = _sayfa(CATEGORY_PAGES["kart"])
BITEN_URL = _sayfa(ARCHIVE_PAGE)
MASTERCARD_URL = _sayfa("mastercard-business-kart-firsat.aspx")
ERTELEMELI_URL = _sayfa("3-ay-ertelemeli-ihtiyac-finansmani.aspx")
TIP_URL = _sayfa("tip-bayrami.aspx")
BABALAR_URL = _sayfa("babalar-gunu-avantajlar-2026.aspx")


@pytest.fixture
def fixtures(read_fixture) -> dict[str, str]:  # type: ignore[no-untyped-def]
    """Türkiye Finans fixture'larını okur."""
    return {
        "kart": read_fixture("html/turkiye_finans/kart_kampanyalari.html"),
        "biten": read_fixture("html/turkiye_finans/biten_kampanyalar.html"),
        "detay": read_fixture("html/turkiye_finans/kampanya_detay.html"),
    }


def _scraper(
    tmp_path: Path, transport: httpx.MockTransport, **kwargs: object
) -> TurkiyeFinansScraper:
    """Sahte taşıyıcıya bağlı, hız sınırı kapalı scraper üretir."""
    settings = Settings(
        raw_html_dir=str(tmp_path / "raw_html"),
        scraper_request_delay_seconds=0.0,
        scraper_max_retries=2,
        airgap_mode=False,
    )
    client = httpx.Client(transport=transport, follow_redirects=True)
    fetcher = Fetcher("turkiye_finans", settings=settings, client=client)
    return TurkiyeFinansScraper(fetcher=fetcher, settings=settings, **kwargs)  # type: ignore[arg-type]


class TestKesif:
    """`discover()` — düz dizin yapısı ve kategori elemesi."""

    def test_kampanya_detaylari_bulunur(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        scraper = _scraper(
            tmp_path, make_transport({KART_URL: (200, fixtures["kart"])}), categories=["kart"]
        )
        try:
            adresler = {d.url for d in scraper.discover()}
        finally:
            scraper.close()

        assert adresler == {MASTERCARD_URL, ERTELEMELI_URL}

    def test_kategori_sayfalari_kampanya_sayilmaz(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        """⚠️ Kategori ve detay aynı dizinde; eleme olmazsa çöp kayıt oluşur."""
        scraper = _scraper(
            tmp_path, make_transport({KART_URL: (200, fixtures["kart"])}), categories=["kart"]
        )
        try:
            adresler = {d.url for d in scraper.discover()}
        finally:
            scraper.close()

        for dosya in (*CATEGORY_PAGES.values(), ARCHIVE_PAGE, "default.aspx"):
            assert _sayfa(dosya) not in adresler

    def test_ayni_kampanyanin_uc_baglantisi_tekillesir(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        """Görsel, başlık ve "Detaylı Bilgi" aynı adrese gidiyor."""
        scraper = _scraper(
            tmp_path, make_transport({KART_URL: (200, fixtures["kart"])}), categories=["kart"]
        )
        try:
            adresler = [d.url for d in scraper.discover()]
        finally:
            scraper.close()

        assert adresler.count(MASTERCARD_URL) == 1

    def test_pdf_ve_dis_baglanti_elenir(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        scraper = _scraper(
            tmp_path, make_transport({KART_URL: (200, fixtures["kart"])}), categories=["kart"]
        )
        try:
            adresler = {d.url for d in scraper.discover()}
        finally:
            scraper.close()

        assert not any(url.lower().endswith(".pdf") for url in adresler)
        assert not any("linkedin.com" in url for url in adresler)

    def test_arsiv_kayitlari_isaretlenir(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        scraper = _scraper(
            tmp_path, make_transport({BITEN_URL: (200, fixtures["biten"])}), categories=["biten"]
        )
        try:
            bulunan = {d.url: d for d in scraper.discover()}
        finally:
            scraper.close()

        assert TIP_URL in bulunan
        assert bulunan[TIP_URL].discovery_method == "archive"
        assert bulunan[TIP_URL].category_hint == "biten"

    def test_guncel_kategori_arsive_baskin(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        """Aynı kampanya iki listede varsa güncel kategorisiyle kaydedilir."""
        transport = make_transport(
            {KART_URL: (200, fixtures["kart"]), BITEN_URL: (200, fixtures["biten"])}
        )
        scraper = _scraper(tmp_path, transport, categories=["kart", "biten"])
        try:
            bulunan = {d.url: d for d in scraper.discover()}
        finally:
            scraper.close()

        assert bulunan[ERTELEMELI_URL].category_hint == "kart"
        assert bulunan[ERTELEMELI_URL].discovery_method == "listing"

    def test_ticari_kategorisi_ticari_segment_alir(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        ticari_url = _sayfa(CATEGORY_PAGES["ticari"])
        scraper = _scraper(
            tmp_path, make_transport({ticari_url: (200, fixtures["kart"])}), categories=["ticari"]
        )
        try:
            bulunan = scraper.discover()
        finally:
            scraper.close()

        assert bulunan
        assert all(d.segment_hint == "ticari" for d in bulunan)

    def test_kategori_verilmezse_hepsi_ve_arsiv_taranir(
        self, tmp_path: Path, make_transport: Callable[..., httpx.MockTransport]
    ) -> None:
        scraper = _scraper(tmp_path, make_transport({}))
        try:
            scraper.discover()
            cekilen = {f.url for f in scraper.fetcher.history}
        finally:
            scraper.close()

        # hub + kategoriler + arşiv + Happy Card
        assert len(cekilen) == len(CATEGORY_PAGES) + 3
        assert BITEN_URL in cekilen
        assert _sayfa(HUB_PAGE) in cekilen
        assert HAPPYCARD_LISTING in cekilen

    def test_sayfa_alinamazsa_digerleri_surer(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        transport = make_transport({KART_URL: (200, fixtures["kart"])})
        scraper = _scraper(tmp_path, transport, categories=["kart", "sigorta"])
        try:
            adresler = {d.url for d in scraper.discover()}
        finally:
            scraper.close()

        assert MASTERCARD_URL in adresler


class TestDetayAyristirma:
    """`parse_detail()` — görünmez karakterler ve tarihsizlik."""

    def _hint(self, *, arsiv: bool = False) -> DiscoveredUrl:
        return DiscoveredUrl(
            url=ERTELEMELI_URL,
            doc_type="campaign",
            category_hint="biten" if arsiv else "kart",
            segment_hint="bireysel",
            discovery_method="archive" if arsiv else "listing",
        )

    def test_tarih_yok_uydurulmaz(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        """⚠️ Hiçbir kampanyada tarih yok; "expired" İŞARETLENMEZ."""
        scraper = _scraper(tmp_path, make_transport({}))
        try:
            ham = scraper.parse_detail(fixtures["detay"], ERTELEMELI_URL, self._hint())
        finally:
            scraper.close()

        assert ham is not None
        assert ham.start_date is None
        assert ham.end_date is None
        assert ham.date_precision == "unknown"

    def test_zero_width_basliga_ragmen_kosullar_cikarilir(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        """⚠️ `<h2>` içinde U+200B var; ham eşleştirme sessizce boş dönerdi."""
        scraper = _scraper(tmp_path, make_transport({}))
        try:
            ham = scraper.parse_detail(fixtures["detay"], ERTELEMELI_URL, self._hint())
        finally:
            scraper.close()

        assert ham is not None
        assert ham.conditions_text is not None
        assert "3,59" in ham.conditions_text

    def test_baslik_og_title_dan_gelir(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        scraper = _scraper(tmp_path, make_transport({}))
        try:
            ham = scraper.parse_detail(fixtures["detay"], ERTELEMELI_URL, self._hint())
        finally:
            scraper.close()

        assert ham is not None
        assert "3 Ay Ertelemeli" in ham.title

    def test_slug_adresten_okunur(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        scraper = _scraper(tmp_path, make_transport({}))
        try:
            ham = scraper.parse_detail(fixtures["detay"], ERTELEMELI_URL, self._hint())
        finally:
            scraper.close()

        assert ham is not None
        assert ham.external_slug == "3-ay-ertelemeli-ihtiyac-finansmani.aspx"

    def test_aciklama_menu_metnini_almaz(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        """Gövde kategori menüsüyle başlıyor; açıklama oradan gelmemeli."""
        scraper = _scraper(tmp_path, make_transport({}))
        try:
            ham = scraper.parse_detail(fixtures["detay"], ERTELEMELI_URL, self._hint())
        finally:
            scraper.close()

        assert ham is not None
        assert ham.description is not None
        assert "Kampanyaları" not in ham.description.split(".")[0]

    def test_arsiv_bayragi_kesiften_gelir(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        scraper = _scraper(tmp_path, make_transport({}))
        try:
            guncel = scraper.parse_detail(fixtures["detay"], ERTELEMELI_URL, self._hint())
            arsiv = scraper.parse_detail(fixtures["detay"], ERTELEMELI_URL, self._hint(arsiv=True))
        finally:
            scraper.close()

        assert guncel is not None and not guncel.is_archived
        assert arsiv is not None and arsiv.is_archived

    def test_baslik_yoksa_none(
        self, tmp_path: Path, make_transport: Callable[..., httpx.MockTransport]
    ) -> None:
        scraper = _scraper(tmp_path, make_transport({}))
        try:
            assert (
                scraper.parse_detail("<html><body></body></html>", ERTELEMELI_URL, self._hint())
                is None
            )
        finally:
            scraper.close()


class TestUctanUcaCalistirma:
    """`run()` — kayıt ve durum."""

    def _transport(
        self, fixtures: dict[str, str], make_transport: Callable[..., httpx.MockTransport]
    ) -> httpx.MockTransport:
        return make_transport(
            {
                KART_URL: (200, fixtures["kart"]),
                BITEN_URL: (200, fixtures["biten"]),
                MASTERCARD_URL: (200, fixtures["detay"]),
                ERTELEMELI_URL: (200, fixtures["detay"]),
                TIP_URL: (200, fixtures["detay"]),
                BABALAR_URL: (200, fixtures["detay"]),
            }
        )

    def test_kampanyalar_kaydedilir(
        self,
        tmp_path: Path,
        seeded_session: Session,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        scraper = _scraper(
            tmp_path, self._transport(fixtures, make_transport), categories=["kart", "biten"]
        )
        try:
            sonuc = scraper.run(seeded_session)
        finally:
            scraper.close()

        assert sonuc.campaigns_new == 4

    def test_durum_unknown_kalir_expired_olmaz(
        self,
        tmp_path: Path,
        seeded_session: Session,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        """⚠️ Tarihi olmayan kampanyayı "süresi dolmuş" göstermek yanlış bilgidir."""
        scraper = _scraper(
            tmp_path, self._transport(fixtures, make_transport), categories=["kart", "biten"]
        )
        try:
            scraper.run(seeded_session)
        finally:
            scraper.close()

        kampanyalar = list(seeded_session.scalars(select(Campaign)))
        assert kampanyalar
        assert all(k.status == "unknown" for k in kampanyalar)
        assert not any(k.status == "expired" for k in kampanyalar)

    def test_arsiv_kayitlari_isaretli(
        self,
        tmp_path: Path,
        seeded_session: Session,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        scraper = _scraper(
            tmp_path, self._transport(fixtures, make_transport), categories=["kart", "biten"]
        )
        try:
            scraper.run(seeded_session)
        finally:
            scraper.close()

        arsivli = list(seeded_session.scalars(select(Campaign).where(Campaign.is_archived)))
        assert {k.external_slug for k in arsivli} == {
            "tip-bayrami.aspx",
            "babalar-gunu-avantajlar-2026.aspx",
        }

    def test_ikinci_calistirma_kayit_cogaltmaz(
        self,
        tmp_path: Path,
        seeded_session: Session,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        for _ in range(2):
            scraper = _scraper(
                tmp_path, self._transport(fixtures, make_transport), categories=["kart", "biten"]
            )
            try:
                scraper.run(seeded_session)
            finally:
                scraper.close()

        assert len(list(seeded_session.scalars(select(Campaign)))) == 4
