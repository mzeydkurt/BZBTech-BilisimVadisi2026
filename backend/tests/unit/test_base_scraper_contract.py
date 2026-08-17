"""Taban sınıf sözleşmesinin bekçisi.

Tarih artık tek ortak yoldan belirleniyor. Bu dosya, kuralın kaynak kod
düzeyinde çiğnenmesini engeller: bir scraper yeniden kendi tarih ayrıştırmasını
yazarsa test düşer.
"""

from __future__ import annotations

import inspect

import pytest

from app.scrapers.base import BaseScraper
from app.scrapers.models import DiscoveredUrl, RawCampaign
from app.scrapers.registry import BANK_REGISTRY

# Alt sınıfın kaynağında görülmemesi gereken atamalar. Tarihi `_apply_period()`
# belirler; scraper yalnızca `structured_period_text()` sağlar.
YASAK_ATAMALAR: tuple[str, ...] = (
    "start_date=",
    "end_date=",
    "date_precision=",
    "date_evidence_text=",
    "date_evidence_source=",
)


@pytest.mark.parametrize("bank_code", sorted(BANK_REGISTRY))
def test_scraper_tarihe_dogrudan_yazmaz(bank_code: str) -> None:
    """Hiçbir banka scraper'ı `RawCampaign`'in tarih alanlarını doldurmaz."""
    kaynak = inspect.getsource(BANK_REGISTRY[bank_code])

    bulunan = [atama for atama in YASAK_ATAMALAR if atama in kaynak]

    assert not bulunan, (
        f"{bank_code} tarih alanına doğrudan yazıyor: {bulunan}. "
        "Tarih `BaseScraper._apply_period()` tarafından belirlenir; "
        "bankaya özgü alan için `structured_period_text()` override edilir."
    )


@pytest.mark.parametrize("bank_code", sorted(BANK_REGISTRY))
def test_scraper_tarih_ayristiricisini_ice_aktarmaz(bank_code: str) -> None:
    """Banka modülü tarih ayrıştırıcısını doğrudan kullanmamalı.

    İçe aktarım denetlenir, metin değil: docstring'de fonksiyon adının geçmesi
    kural ihlali değildir.
    """
    modul = inspect.getmodule(BANK_REGISTRY[bank_code])
    assert modul is not None

    assert not hasattr(modul, "parse_date_range_tr"), (
        f"{bank_code} `parse_date_range_tr`'ı içe aktarıyor. Tarih ayrıştırması "
        "`app/processing/dates.py` içinde tek noktada yapılır."
    )
    assert not hasattr(BANK_REGISTRY[bank_code], "_parse_dates")


@pytest.mark.parametrize("bank_code", sorted(BANK_REGISTRY))
def test_structured_period_text_imzasi_korunur(bank_code: str) -> None:
    """Override edilmişse imza taban sınıfla aynı kalmalı."""
    metod = BANK_REGISTRY[bank_code].structured_period_text
    imza = inspect.signature(metod)

    assert list(imza.parameters) == ["self", "html"]


class TestParsePageAdaptoru:
    """`parse_page()` varsayılanı tek kampanyalı sayfayı sarar."""

    class _SahteScraper(BaseScraper):
        bank_code = "sahte"

        def discover(self) -> list[DiscoveredUrl]:
            return []

        def parse_detail(self, html: str, url: str, hint: DiscoveredUrl) -> RawCampaign | None:
            if "bos" in html:
                return None
            return RawCampaign(external_slug="a", title="A", source_url=url)

    def _hint(self) -> DiscoveredUrl:
        return DiscoveredUrl(url="https://x/y", doc_type="campaign")

    def test_tek_kampanya_listeye_sarilir(self) -> None:
        scraper = self._SahteScraper()
        try:
            sonuc = scraper.parse_page("<html></html>", "https://x/y", self._hint())
        finally:
            scraper.close()

        assert len(sonuc) == 1
        assert sonuc[0].external_slug == "a"

    def test_kampanya_yoksa_bos_liste_doner(self) -> None:
        scraper = self._SahteScraper()
        try:
            sonuc = scraper.parse_page("bos", "https://x/y", self._hint())
        finally:
            scraper.close()

        assert sonuc == []


class TestBosKesif:
    """Sıfır keşif başarı sayılmaz."""

    class _BosScraper(BaseScraper):
        bank_code = "adil_katilim"

        def discover(self) -> list[DiscoveredUrl]:
            return []

        def parse_detail(self, html: str, url: str, hint: DiscoveredUrl) -> RawCampaign | None:
            return None

    def test_sifir_kesif_partial_kapanir(self, seeded_session) -> None:  # type: ignore[no-untyped-def]
        """ÖLÇÜLDÜ: Türkiye Finans `kesif=0` verdi ve `success` kapandı;
        22 kampanya sessizce veri setinden düştü."""
        scraper = self._BosScraper()
        try:
            sonuc = scraper.run(seeded_session, dry_run=True)
        finally:
            scraper.close()

        assert sonuc.urls_discovered == 0
        assert sonuc.status == "partial"
        assert sonuc.errors_count == 1
        assert "sıfır adres" in sonuc.errors[0]
