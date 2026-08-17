"""Ziraat Katılım scraper testleri.

Testler ağa çıkmaz: kaydedilmiş HTML fixture'ları `httpx.MockTransport`
üzerinden servis edilir (§13).

Fixture'lar canlı sayfa yapısından (13 Ağustos 2026) alınmıştır:
giriş noktası `/kart-kampanyalari`, kart yapısı `item-category` + `item-title`.
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
from app.db.models import Campaign, ScrapeRun, SourceDocument
from app.scrapers.banks.ziraat_katilim import (
    ARCHIVE_URL,
    BASE_URL,
    LISTING_URL,
    ZiraatKatilimScraper,
)
from app.scrapers.fetcher import Fetcher
from app.scrapers.models import DiscoveredUrl
from app.utils.hashing import sha256_text

ZEN_URL = f"{BASE_URL}/kart-kampanyalari/zen-pirlantada-3-taksit"
TEKNOSA_URL = f"{BASE_URL}/kart-kampanyalari/teknosada-3-taksit"
AILE_URL = f"{BASE_URL}/kart-kampanyalari/aile-karta-ozel-2000-tlye-varan-bankkart-lira-2"


@pytest.fixture
def fixtures(read_fixture) -> dict[str, str]:  # type: ignore[no-untyped-def]
    """Ziraat fixture'larını okur."""
    return {
        "liste": read_fixture("html/ziraat_katilim/kampanyalar_kart.html"),
        "donem": read_fixture("html/ziraat_katilim/kampanya_donem.html"),
        "son_gun": read_fixture("html/ziraat_katilim/kampanya_son_gun.html"),
        "aralik": read_fixture("html/ziraat_katilim/kampanya_aralik.html"),
        "marka_h1": read_fixture("html/ziraat_katilim/kampanya_marka_h1.html"),
        "bulunamadi": read_fixture("html/ziraat_katilim/sayfa_bulunamadi.html"),
    }


def _scraper(
    tmp_path: Path, transport: httpx.MockTransport, **kwargs: object
) -> ZiraatKatilimScraper:
    """Sahte taşıyıcıya bağlı, hız sınırı kapalı scraper üretir."""
    settings = Settings(
        raw_html_dir=str(tmp_path / "raw_html"),
        scraper_request_delay_seconds=0.0,
        scraper_max_retries=2,
        airgap_mode=False,
    )
    client = httpx.Client(transport=transport, follow_redirects=True)
    fetcher = Fetcher("ziraat_katilim", settings=settings, client=client)
    return ZiraatKatilimScraper(fetcher=fetcher, settings=settings, **kwargs)  # type: ignore[arg-type]


def _tam_transport(
    fixtures: dict[str, str], make_transport: Callable[..., httpx.MockTransport]
) -> httpx.MockTransport:
    """Liste, arşiv ve üç detay sayfasını servis eden taşıyıcı."""
    return make_transport(
        {
            LISTING_URL: (200, fixtures["liste"]),
            ARCHIVE_URL: (200, fixtures["liste"]),
            ZEN_URL: (200, fixtures["donem"]),
            TEKNOSA_URL: (200, fixtures["son_gun"]),
            AILE_URL: (200, fixtures["aralik"]),
        }
    )


class TestGirisNoktasi:
    """⚠️ Canlı sitede ölçüldü: tek çalışan giriş noktası `/kart-kampanyalari`."""

    def test_yalnizca_iki_liste_istegi_yapilir(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        """Sektör kartta yazılı; 14 süzgeç sayfası GEZİLMEZ."""
        scraper = _scraper(tmp_path, make_transport({LISTING_URL: (200, fixtures["liste"])}))
        try:
            scraper.discover()
            liste_istekleri = [
                f.url for f in scraper.fetcher.history if "/kart-kampanyalari" in f.url
            ]
        finally:
            scraper.close()

        assert set(liste_istekleri) == {LISTING_URL, ARCHIVE_URL}

    def test_493_donduren_adrese_istek_atilmaz(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        """`/kampanyalar` WAF'a takılıyor, `/kampanyalar/{sektor}` 404 veriyor."""
        scraper = _scraper(tmp_path, make_transport({LISTING_URL: (200, fixtures["liste"])}))
        try:
            scraper.discover()
            cekilen = {f.url for f in scraper.fetcher.history}
        finally:
            scraper.close()

        assert f"{BASE_URL}/kampanyalar" not in cekilen
        assert not any(u.startswith(f"{BASE_URL}/kampanyalar/") for u in cekilen)


class TestKesif:
    """`discover()` — kart tabanlı okuma."""

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

        assert adresler == {ZEN_URL, TEKNOSA_URL, AILE_URL}

    def test_cevrilen_kart_tekillesir(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        """Aynı kampanya kartın iki yüzünde de basılıyor."""
        scraper = _scraper(tmp_path, make_transport({LISTING_URL: (200, fixtures["liste"])}))
        try:
            adresler = [d.url for d in scraper.discover()]
        finally:
            scraper.close()

        assert len(adresler) == len(set(adresler))

    def test_sektor_etiketi_karttan_okunur(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        """🎁 Bankanın kendi sınıflandırması — çıkarım değil, kaynak veri."""
        scraper = _scraper(tmp_path, make_transport({LISTING_URL: (200, fixtures["liste"])}))
        try:
            sektorler = {d.url: d.category_hint for d in scraper.discover()}
        finally:
            scraper.close()

        assert sektorler[ZEN_URL] == "Kuyum, Optik ve Saat"
        assert sektorler[TEKNOSA_URL] == "Elektronik ve Telekomünikasyon"
        assert sektorler[AILE_URL] == "Genel Kampanyalar"

    def test_donem_eki_korunur(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        """⚠️ Slug sonundaki `-2` yeni dönem yayınıdır, kırpılmaz."""
        scraper = _scraper(tmp_path, make_transport({LISTING_URL: (200, fixtures["liste"])}))
        try:
            adresler = {d.url for d in scraper.discover()}
        finally:
            scraper.close()

        assert any(url.endswith("bankkart-lira-2") for url in adresler)

    def test_sektor_suzgeci_calisir(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        scraper = _scraper(
            tmp_path,
            make_transport({LISTING_URL: (200, fixtures["liste"])}),
            categories=["Kuyum, Optik ve Saat"],
        )
        try:
            adresler = {d.url for d in scraper.discover()}
        finally:
            scraper.close()

        assert adresler == {ZEN_URL}

    def test_suzgec_ve_dis_baglantilar_elenir(
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

        assert not any("/kampanyalar/" in url for url in adresler)
        assert not any("instagram.com" in url for url in adresler)
        assert LISTING_URL not in adresler

    def test_arsiv_kaynagi_isaretlenir(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        """Yalnızca arşiv sayfasından gelenler arşiv sayılır."""
        scraper = _scraper(tmp_path, make_transport({ARCHIVE_URL: (200, fixtures["liste"])}))
        try:
            bulunan = scraper.discover()
        finally:
            scraper.close()

        assert bulunan
        assert all(d.discovery_method == "archive" for d in bulunan)

    def test_liste_alinamazsa_cokmez(
        self, tmp_path: Path, make_transport: Callable[..., httpx.MockTransport]
    ) -> None:
        scraper = _scraper(tmp_path, make_transport({}))
        try:
            assert scraper.discover() == []
        finally:
            scraper.close()


class TestDetayAyristirma:
    """`parse_detail()` — dört tarih biçimi ve metin alanları."""

    def _hint(self, url: str = ZEN_URL, *, arsiv: bool = False) -> DiscoveredUrl:
        return DiscoveredUrl(
            url=url,
            doc_type="campaign",
            category_hint="Kuyum, Optik ve Saat",
            segment_hint="bireysel",
            discovery_method="archive" if arsiv else "listing",
        )

    def test_kampanya_donemi_tam_aralik_verir(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
        donem_uygula,  # type: ignore[no-untyped-def]
    ) -> None:
        """ "Kampanya Dönemi 11-08-2026 - 31-08-2026" — canlı sayfadaki biçim."""
        scraper = _scraper(tmp_path, make_transport({}))
        try:
            ham = scraper.parse_detail(fixtures["donem"], ZEN_URL, self._hint())
            donem_uygula(scraper, fixtures["donem"], ham)
        finally:
            scraper.close()

        assert ham is not None
        assert ham.start_date == date(2026, 8, 11)
        assert ham.end_date == date(2026, 8, 31)
        assert ham.date_precision == "exact"

    def test_son_gun_bicimi_yalnizca_bitis_verir(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
        donem_uygula,  # type: ignore[no-untyped-def]
    ) -> None:
        """⚠️ Başlangıç UYDURULMAZ; `partial` kalır."""
        scraper = _scraper(tmp_path, make_transport({}))
        try:
            ham = scraper.parse_detail(fixtures["son_gun"], TEKNOSA_URL, self._hint(TEKNOSA_URL))
            donem_uygula(scraper, fixtures["son_gun"], ham)
        finally:
            scraper.close()

        assert ham is not None
        assert ham.end_date == date(2026, 9, 7)
        assert ham.start_date is None
        assert ham.date_precision == "partial"

    def test_aralik_biciminde_yil_devralinir(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
        donem_uygula,  # type: ignore[no-untyped-def]
    ) -> None:
        """⚠️ "10 Temmuz – 7 Ağustos 2026" — başlangıçta yıl yazılı değil."""
        scraper = _scraper(tmp_path, make_transport({}))
        try:
            ham = scraper.parse_detail(fixtures["aralik"], AILE_URL, self._hint(AILE_URL))
            donem_uygula(scraper, fixtures["aralik"], ham)
        finally:
            scraper.close()

        assert ham is not None
        assert ham.start_date == date(2026, 7, 10)
        assert ham.end_date == date(2026, 8, 7)

    def test_tarih_yoksa_uydurulmaz(
        self,
        tmp_path: Path,
        make_transport: Callable[..., httpx.MockTransport],
        donem_uygula,  # type: ignore[no-untyped-def]
    ) -> None:
        html = "<html><body><h1>Tarihsiz Kampanya</h1><p>Koşullar burada.</p></body></html>"
        scraper = _scraper(tmp_path, make_transport({}))
        try:
            ham = scraper.parse_detail(html, ZEN_URL, self._hint())
            donem_uygula(scraper, html, ham)
        finally:
            scraper.close()

        assert ham is not None
        assert (ham.start_date, ham.end_date, ham.date_precision) == (None, None, "unknown")

    def test_baslik_h1_den_okunur(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        """`<title>` tüm kampanyalarda aynı; `<h1>` kullanılmalı."""
        scraper = _scraper(tmp_path, make_transport({}))
        try:
            ham = scraper.parse_detail(fixtures["donem"], ZEN_URL, self._hint())
        finally:
            scraper.close()

        assert ham is not None
        assert ham.title == "Zen Pırlanta'da 3 Taksit"

    def test_marka_h1_baslik_olarak_alinmaz(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        """⚠️ Canlı çekimde 209 kampanyanın 209'u "Ziraat Katılım Bankası" olmuştu."""
        scraper = _scraper(tmp_path, make_transport({}))
        try:
            ham = scraper.parse_detail(fixtures["marka_h1"], ZEN_URL, self._hint())
        finally:
            scraper.close()

        assert ham is not None
        assert ham.title == "Sosyopix'te %20 İndirim"

    def test_sayfa_bulunamadi_kampanya_olarak_kaydedilmez(
        self,
        tmp_path: Path,
        seeded_session: Session,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        """⚠️ Canlı çekimde 2 "sayfa yok" yanıtı kampanya olarak kaydedilmişti.

        Sayfanın görünen ilk başlığı logo metni olduğu için soft-404 sezgisi
        hata ifadesini göremiyordu.
        """
        transport = make_transport(
            {
                LISTING_URL: (200, fixtures["liste"]),
                ZEN_URL: (200, fixtures["bulunamadi"]),
                TEKNOSA_URL: (200, fixtures["donem"]),
                AILE_URL: (200, fixtures["donem"]),
            }
        )
        scraper = _scraper(tmp_path, transport)
        try:
            sonuc = scraper.run(seeded_session)
        finally:
            scraper.close()

        assert sonuc.campaigns_new == 2
        basliklar = {k.title for k in seeded_session.scalars(select(Campaign))}
        assert "Ziraat Katılım Bankası" not in basliklar

    def test_slug_adresten_birebir_okunur(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        """⚠️ Başlıktan türetilmez: "Zen Pırlanta'da" içindeki kesme işareti tahmin edilemez."""
        scraper = _scraper(tmp_path, make_transport({}))
        try:
            ham = scraper.parse_detail(fixtures["donem"], ZEN_URL, self._hint())
        finally:
            scraper.close()

        assert ham is not None
        assert ham.external_slug == "zen-pirlantada-3-taksit"

    def test_kosullar_cikarilir(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        scraper = _scraper(tmp_path, make_transport({}))
        try:
            ham = scraper.parse_detail(fixtures["donem"], ZEN_URL, self._hint())
        finally:
            scraper.close()

        assert ham is not None
        assert ham.conditions_text and "Bankkart POS" in ham.conditions_text

    def test_arsiv_bayragi_kesiften_gelir(
        self,
        tmp_path: Path,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        scraper = _scraper(tmp_path, make_transport({}))
        try:
            guncel = scraper.parse_detail(fixtures["donem"], ZEN_URL, self._hint())
            arsiv = scraper.parse_detail(fixtures["donem"], ZEN_URL, self._hint(arsiv=True))
        finally:
            scraper.close()

        assert guncel is not None and not guncel.is_archived
        assert arsiv is not None and arsiv.is_archived

    def test_baslik_yoksa_none_doner(
        self, tmp_path: Path, make_transport: Callable[..., httpx.MockTransport]
    ) -> None:
        scraper = _scraper(tmp_path, make_transport({}))
        try:
            assert scraper.parse_detail("<html><body></body></html>", ZEN_URL, self._hint()) is None
        finally:
            scraper.close()


class TestUctanUcaCalistirma:
    """`run()` — keşif, çekim, arşiv ve kayıt."""

    def test_kampanyalar_kaydedilir(
        self,
        tmp_path: Path,
        seeded_session: Session,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        scraper = _scraper(tmp_path, _tam_transport(fixtures, make_transport))
        try:
            sonuc = scraper.run(seeded_session)
        finally:
            scraper.close()

        assert sonuc.campaigns_new == 3
        assert seeded_session.scalar(select(Campaign).where(Campaign.title.like("Zen%")))

    def test_limit_cekimi_daraltir_ama_kesfi_gizlemez(
        self,
        tmp_path: Path,
        seeded_session: Session,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        """Pilot doğrulama: sınırlı çekim, gerçek keşif sayısı raporda kalır."""
        scraper = _scraper(tmp_path, _tam_transport(fixtures, make_transport), limit=2)
        try:
            sonuc = scraper.run(seeded_session)
        finally:
            scraper.close()

        assert sonuc.urls_discovered == 3
        assert sonuc.campaigns_new == 2

    def test_ikinci_calistirma_kayit_cogaltmaz(
        self,
        tmp_path: Path,
        seeded_session: Session,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        """⚠️ Upsert: aynı komut iki kez çalışınca kayıt sayısı ARTMAZ."""
        for _ in range(2):
            scraper = _scraper(tmp_path, _tam_transport(fixtures, make_transport))
            try:
                scraper.run(seeded_session)
            finally:
                scraper.close()

        assert len(list(seeded_session.scalars(select(Campaign)))) == 3

    def test_ham_html_arsivlenir_ve_ozet_tutar(
        self,
        tmp_path: Path,
        seeded_session: Session,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        scraper = _scraper(tmp_path, _tam_transport(fixtures, make_transport))
        try:
            scraper.run(seeded_session)
        finally:
            scraper.close()

        belgeler = list(
            seeded_session.scalars(
                select(SourceDocument).where(SourceDocument.raw_html_path.isnot(None))
            )
        )
        assert belgeler

        arsiv_kok = tmp_path / "raw_html"
        for belge in belgeler:
            dosya = arsiv_kok / str(belge.raw_html_path)
            assert dosya.is_file()
            assert sha256_text(dosya.read_bytes().decode("utf-8")) == belge.raw_html_sha256

    def test_calistirma_kaydi_dogru_sayilarla_kapanir(
        self,
        tmp_path: Path,
        seeded_session: Session,
        fixtures: dict[str, str],
        make_transport: Callable[..., httpx.MockTransport],
    ) -> None:
        scraper = _scraper(tmp_path, _tam_transport(fixtures, make_transport))
        try:
            sonuc = scraper.run(seeded_session)
        finally:
            scraper.close()

        kayit = seeded_session.scalar(select(ScrapeRun).where(ScrapeRun.id == sonuc.run_id))
        assert kayit is not None
        assert kayit.finished_at is not None
        assert kayit.campaigns_new == 3
        assert kayit.status in ("success", "partial")
