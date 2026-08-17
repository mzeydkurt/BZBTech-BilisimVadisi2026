"""Hayat Finans scraper'ının uçtan uca testi — kayıtlı HTML fixture'ları ile.

Odak noktaları:
  - Ön ek filtresi UYGULANMADIĞI için ürün sayfası da keşfedilir
  - Başlangıçta yıl olmayan tarih aralığı ("16 Haziran - 31 Ağustos 2026")
  - Sert 404 alan kampanyanın `expired` işaretlenmesi
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
from app.db.models import Campaign, SourceDocument
from app.scrapers.banks.hayat_finans import BASE_URL, LISTING_URL, HayatFinansScraper
from app.scrapers.fetcher import Fetcher

KAMPANYA_URL = f"{BASE_URL}/kampanyalar/katilma-hesabina-ozel-kar-payi-firsati"
BITEN_URL = f"{BASE_URL}/kampanyalar/suresi-dolmus-kampanya"
URUN_URL = f"{BASE_URL}/hesaplar/avantajli-hesap"
SITEMAP_URL = f"{BASE_URL}/sitemap.xml"

SITEMAP_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>{KAMPANYA_URL}</loc></url>
  <url><loc>{BITEN_URL}</loc></url>
  <url><loc>{BASE_URL}/kvkk</loc></url>
</urlset>
"""


@pytest.fixture
def scraper_ortami(
    tmp_path: Path,
    read_fixture: Callable[[str], str],
    make_transport: Callable[..., httpx.MockTransport],
) -> tuple[HayatFinansScraper, Settings]:
    """Sahte taşıyıcıya bağlı Hayat Finans scraper'ı."""
    listing = read_fixture("html/hayat_finans/kampanyalar.html")
    detay = read_fixture("html/hayat_finans/kampanya_detay.html")

    transport = make_transport(
        {
            LISTING_URL: (200, listing),
            SITEMAP_URL: (200, SITEMAP_XML),
            KAMPANYA_URL: (200, detay),
            URUN_URL: (200, "<html><body><main><h1>Avantajlı Hesap</h1></main></body></html>"),
            # BITEN_URL bilinçli olarak yok: sert 404 döner.
        }
    )

    settings = Settings(
        raw_html_dir=str(tmp_path / "raw_html"),
        scraper_request_delay_seconds=0.0,
        scraper_max_retries=1,
        database_url="sqlite:///:memory:",
    )
    client = httpx.Client(transport=transport, follow_redirects=True)
    fetcher = Fetcher("hayat_finans", settings=settings, client=client)
    return HayatFinansScraper(fetcher=fetcher, settings=settings), settings


class TestKesif:
    def test_urun_sayfasi_kaybedilmez_urun_kancasina_gider(
        self, scraper_ortami: tuple[HayatFinansScraper, Settings]
    ) -> None:
        """⚠️ Ön ek filtresi uygulanırsa bu bağlantı kaybedilirdi.

        Adres kaybolmuyor ama artık `discover()` değil `discover_products()`
        döndürüyor: eskiden `parse_detail` ürün sayfalarına sessizce `None`
        veriyordu ve 80 belge arşivlenip sıfır ürün üretiliyordu.
        """
        scraper, _ = scraper_ortami

        kampanyalar = {item.url for item in scraper.discover()}
        urunler = {item.url: item for item in scraper.discover_products()}

        assert URUN_URL not in kampanyalar
        assert URUN_URL in urunler
        assert urunler[URUN_URL].doc_type == "product"

    def test_kampanya_kesfi_yalnizca_kampanya_dondurur(
        self, scraper_ortami: tuple[HayatFinansScraper, Settings]
    ) -> None:
        """`parse_detail`'in sessizce `None` dönmesi imkânsız hâle geldi."""
        scraper, _ = scraper_ortami

        assert {item.doc_type for item in scraper.discover()} == {"campaign"}

    def test_kampanya_sayfalari_kesfedilir(
        self, scraper_ortami: tuple[HayatFinansScraper, Settings]
    ) -> None:
        scraper, _ = scraper_ortami
        keşifler = {item.url: item for item in scraper.discover()}

        assert keşifler[KAMPANYA_URL].doc_type == "campaign"
        assert BITEN_URL in keşifler

    def test_kurumsal_sayfalar_elenir(
        self, scraper_ortami: tuple[HayatFinansScraper, Settings]
    ) -> None:
        scraper, _ = scraper_ortami
        urls = {item.url for item in scraper.discover()}

        assert f"{BASE_URL}/kvkk" not in urls
        assert f"{BASE_URL}/iletisim" not in urls

    def test_sitemap_birincil_kaynaktir(
        self, scraper_ortami: tuple[HayatFinansScraper, Settings]
    ) -> None:
        scraper, _ = scraper_ortami
        keşifler = {item.url: item for item in scraper.discover()}
        assert keşifler[KAMPANYA_URL].discovery_method == "sitemap"


class TestAyristirma:
    @pytest.fixture
    def kampanyalar(
        self,
        scraper_ortami: tuple[HayatFinansScraper, Settings],
        seeded_session: Session,
    ) -> dict[str, Campaign]:
        scraper, _ = scraper_ortami
        scraper.run(seeded_session)
        return {c.external_slug: c for c in seeded_session.scalars(select(Campaign)).all()}

    def test_baslangicta_yil_yoksa_bitisten_devralinir(
        self, kampanyalar: dict[str, Campaign]
    ) -> None:
        """ "16 Haziran - 31 Ağustos 2026" — başlangıçta yıl yazmıyor."""
        kampanya = kampanyalar["katilma-hesabina-ozel-kar-payi-firsati"]
        assert kampanya.start_date == date(2026, 6, 16)
        assert kampanya.end_date == date(2026, 8, 31)
        assert kampanya.date_precision == "inferred"

    def test_oran_tablosu_kosullara_eklenir(self, kampanyalar: dict[str, Campaign]) -> None:
        """PART 1'de tablo metin olarak saklanır; yapısal ayrıştırma PART 2'de."""
        kampanya = kampanyalar["katilma-hesabina-ozel-kar-payi-firsati"]
        assert kampanya.conditions_text is not None
        assert "Vade | Kâr Payı Oranı" in kampanya.conditions_text
        assert "32 Gün | %4,15" in kampanya.conditions_text

    def test_urun_sayfasindan_kampanya_uretilmez(self, kampanyalar: dict[str, Campaign]) -> None:
        """Ürün sayfası arşivlenir ama kampanya olarak kaydedilmez."""
        assert "avantajli-hesap" not in kampanyalar


class TestSert404:
    def test_404_kaydedilir_ve_arsivlenir(
        self,
        scraper_ortami: tuple[HayatFinansScraper, Settings],
        seeded_session: Session,
    ) -> None:
        """Biten kampanyalar geri gelmiyor; 404 gövdesi tek kalan kanıttır."""
        scraper, settings = scraper_ortami
        scraper.run(seeded_session)

        doc = seeded_session.scalar(select(SourceDocument).where(SourceDocument.url == BITEN_URL))
        assert doc is not None
        assert doc.http_status == 404
        assert doc.raw_html_path is not None
        assert (settings.raw_html_path / doc.raw_html_path).exists()

    def test_mevcut_kampanya_404_alinca_expired_olur(
        self,
        scraper_ortami: tuple[HayatFinansScraper, Settings],
        seeded_session: Session,
    ) -> None:
        from app.db.models import Bank

        bank = seeded_session.scalar(select(Bank).where(Bank.code == "hayat_finans"))
        assert bank is not None

        # Daha önceki bir çalıştırmada kaydedilmiş, hâlâ aktif görünen kampanya.
        seeded_session.add(
            Campaign(
                bank_id=bank.id,
                external_slug="suresi-dolmus-kampanya",
                title="Süresi Dolmuş Kampanya",
                source_url=BITEN_URL,
                status="active",
            )
        )
        seeded_session.flush()

        scraper, _ = scraper_ortami
        scraper.run(seeded_session)

        kampanya = seeded_session.scalar(
            select(Campaign).where(Campaign.external_slug == "suresi-dolmus-kampanya")
        )
        assert kampanya is not None
        assert kampanya.status == "expired"
