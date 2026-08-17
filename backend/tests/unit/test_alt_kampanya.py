"""Alt kampanya modeli: upsert, tekillik ve sayım semantiği."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Bank, Campaign, SourceDocument
from app.scrapers.base import BaseScraper
from app.scrapers.models import DiscoveredUrl, RawCampaign, ScrapeRunResult
from app.services.bank_service import list_banks


class _CokKampanyaliScraper(BaseScraper):
    """Tek sayfada bir kök ve iki alt kampanya yayımlayan sahte banka."""

    bank_code = "emlak_katilim"

    def discover(self) -> list[DiscoveredUrl]:
        return []

    def parse_detail(self, html: str, url: str, hint: DiscoveredUrl) -> RawCampaign | None:
        return next(iter(self._bloklar(url)), None)

    def parse_page(self, html: str, url: str, hint: DiscoveredUrl) -> list[RawCampaign]:
        return self._bloklar(url)

    @staticmethod
    def _bloklar(url: str) -> list[RawCampaign]:
        kok = RawCampaign(external_slug="finansmanlar", title="Finansmanlar", source_url=url)
        return [
            kok,
            RawCampaign(
                external_slug="finansmanlar#konut",
                title="Konut Finansmanı",
                source_url=url,
                parent_slug="finansmanlar",
                block_index=0,
                slug_source="href",
            ),
            RawCampaign(
                external_slug="finansmanlar#arac",
                title="Araç Finansmanı",
                source_url=url,
                parent_slug="finansmanlar",
                block_index=1,
                slug_source="anchor",
            ),
        ]


@pytest.fixture
def belge(seeded_session: Session) -> SourceDocument:
    """Kampanyaların bağlanacağı kaynak belge."""
    bank = seeded_session.scalar(select(Bank).where(Bank.code == "emlak_katilim"))
    assert bank is not None
    doc = SourceDocument(
        bank_id=bank.id,
        url="https://x/finansmanlar",
        url_hash="a" * 64,
        doc_type="campaign",
        http_status=200,
    )
    seeded_session.add(doc)
    seeded_session.flush()
    return doc


def _yaz(session: Session, belge: SourceDocument, raws: list[RawCampaign]) -> ScrapeRunResult:
    scraper = _CokKampanyaliScraper()
    bank = session.scalar(select(Bank).where(Bank.code == "emlak_katilim"))
    assert bank is not None
    sonuc = ScrapeRunResult(bank_code="emlak_katilim")
    try:
        scraper._upsert_campaigns(session, bank, raws, belge, sonuc, dry_run=False)
    finally:
        scraper.close()
    session.flush()
    return sonuc


class TestUpsert:
    def test_kok_ve_alt_kampanyalar_baglanir(
        self, seeded_session: Session, belge: SourceDocument
    ) -> None:
        _yaz(seeded_session, belge, _CokKampanyaliScraper._bloklar("https://x/finansmanlar"))

        kok = seeded_session.scalar(
            select(Campaign).where(Campaign.external_slug == "finansmanlar")
        )
        assert kok is not None
        assert kok.parent_campaign_id is None
        assert len(kok.sub_campaigns) == 2
        assert {alt.slug_source for alt in kok.sub_campaigns} == {"href", "anchor"}

    def test_ikinci_calistirma_satir_cogaltmaz(
        self, seeded_session: Session, belge: SourceDocument
    ) -> None:
        bloklar = _CokKampanyaliScraper._bloklar("https://x/finansmanlar")
        _yaz(seeded_session, belge, bloklar)
        _yaz(seeded_session, belge, bloklar)

        toplam = seeded_session.scalar(select(func.count()).select_from(Campaign))
        assert toplam == 3

    def test_ebeveynsiz_alt_kampanya_atilmaz(
        self, seeded_session: Session, belge: SourceDocument
    ) -> None:
        """⚠️ Kök bulunamazsa çocuk kök olarak yazılır; veri kaybedilmez."""
        oksuz = RawCampaign(
            external_slug="bilinmeyen#alt",
            title="Öksüz Alt Kampanya",
            source_url="https://x/y",
            parent_slug="hic-yok",
        )
        _yaz(seeded_session, belge, [oksuz])

        kayit = seeded_session.scalar(
            select(Campaign).where(Campaign.external_slug == "bilinmeyen#alt")
        )
        assert kayit is not None
        assert kayit.parent_campaign_id is None

    def test_ayni_slug_iki_kez_yazilamaz(
        self, seeded_session: Session, belge: SourceDocument
    ) -> None:
        """`(bank_id, external_slug)` tekilliği alt kampanyalarda da geçerli."""
        bank = seeded_session.scalar(select(Bank).where(Bank.code == "emlak_katilim"))
        assert bank is not None
        for _ in range(2):
            seeded_session.add(
                Campaign(
                    bank_id=bank.id,
                    external_slug="ayni#alt",
                    title="T",
                    source_url="https://x/y",
                    date_precision="unknown",
                    status="unknown",
                )
            )
        with pytest.raises(IntegrityError):
            seeded_session.flush()


class TestSayimSemantigi:
    """Alt kampanyalar bankalar arası karşılaştırmayı bozmamalı."""

    def test_banka_sayimi_yalnizca_kokleri_sayar(
        self, seeded_session: Session, belge: SourceDocument
    ) -> None:
        _yaz(seeded_session, belge, _CokKampanyaliScraper._bloklar("https://x/finansmanlar"))
        seeded_session.commit()

        sayimlar = {bank.code: adet for bank, adet in list_banks(seeded_session)}

        assert sayimlar["emlak_katilim"] == 1


class TestKisitlar:
    def test_kampanya_kendisinin_ebeveyni_olamaz(self, seeded_session: Session) -> None:
        bank = seeded_session.scalar(select(Bank).where(Bank.code == "emlak_katilim"))
        assert bank is not None
        kampanya = Campaign(
            bank_id=bank.id,
            external_slug="kendi",
            title="T",
            source_url="https://x/y",
            date_precision="unknown",
            status="unknown",
        )
        seeded_session.add(kampanya)
        seeded_session.flush()

        kampanya.parent_campaign_id = kampanya.id
        with pytest.raises(IntegrityError):
            seeded_session.flush()

    def test_gecersiz_slug_source_reddedilir(self, seeded_session: Session) -> None:
        bank = seeded_session.scalar(select(Bank).where(Bank.code == "emlak_katilim"))
        assert bank is not None
        seeded_session.add(
            Campaign(
                bank_id=bank.id,
                external_slug="x",
                title="T",
                source_url="https://x/y",
                date_precision="unknown",
                status="unknown",
                slug_source="baslik",
            )
        )
        with pytest.raises(IntegrityError):
            seeded_session.flush()
