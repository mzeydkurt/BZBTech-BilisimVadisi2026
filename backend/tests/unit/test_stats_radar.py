"""Rekabet radarı testleri.

⚠️ Radar panonun İLK görülen grafiğidir; jüri "bu puan nereden geliyor?" diye
sorduğunda her eksenin bir kaynağı olmalı. Önceki sürüm bankaları üç kovaya
ayırıp sabit puan veriyordu ("Ziraat → şeffaflık 95") — bu testler o sürüme
dönüşü engeller.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.bank import Bank
from app.db.models.campaign import Campaign
from app.db.models.product import Product, ProductRate
from app.services.stats_service import _ortanca, get_stats


def _urun_orani(session: Session, banka_kodu: str, ad: str, oran: Decimal, vade: int) -> None:
    banka = session.scalar(select(Bank).where(Bank.code == banka_kodu))
    assert banka is not None
    urun = Product(
        bank_id=banka.id,
        external_key=f"{banka_kodu}:{ad}",
        name=ad,
        product_type="tasit_finansmani",
    )
    session.add(urun)
    session.flush()
    session.add(
        ProductRate(
            product_id=urun.id,
            band_key=ad,
            rate_type="financing_rate",
            profit_rate_pct=oran,
            term_months=vade,
            currency="TRY",
            evidence_text=f"{ad} | %{oran}",
        )
    )
    session.flush()


def _kampanya(session: Session, banka_kodu: str, slug: str) -> None:
    banka = session.scalar(select(Bank).where(Bank.code == banka_kodu))
    assert banka is not None
    session.add(
        Campaign(
            bank_id=banka.id,
            external_slug=slug,
            title=slug,
            source_url=f"https://ornek.com.tr/{slug}",
        )
    )
    session.flush()


@pytest.fixture
def radarli_oturum(seeded_session: Session) -> Session:
    """İki bankada oran, birinde hiç veri yok."""
    _urun_orani(seeded_session, "albaraka", "Ucuz", Decimal("3.05"), 36)
    _urun_orani(seeded_session, "kuveyt_turk", "Pahalı", Decimal("4.20"), 12)
    _kampanya(seeded_session, "albaraka", "kampanya-a")
    _kampanya(seeded_session, "kuveyt_turk", "kampanya-b")
    return seeded_session


def _radar(session: Session, kod: str):  # type: ignore[no-untyped-def]
    return next(r for r in get_stats(session).radar_scores if r.bank_code == kod)


class TestGercekOlcum:
    def test_dusuk_oranli_banka_yuksek_puan_alir(self, radarli_oturum: Session) -> None:
        """⚠️ Düşük kâr payı İYİDİR; eksen ters çevrilmeli."""
        ucuz = _radar(radarli_oturum, "albaraka")
        pahali = _radar(radarli_oturum, "kuveyt_turk")

        assert ucuz.rate_competitiveness is not None
        assert pahali.rate_competitiveness is not None
        assert ucuz.rate_competitiveness > pahali.rate_competitiveness

    def test_uzun_vadeli_banka_yuksek_puan_alir(self, radarli_oturum: Session) -> None:
        uzun = _radar(radarli_oturum, "albaraka")
        kisa = _radar(radarli_oturum, "kuveyt_turk")

        assert uzun.term_flexibility is not None
        assert kisa.term_flexibility is not None
        assert uzun.term_flexibility > kisa.term_flexibility

    def test_puanlar_banka_adina_gore_sabit_degil(self, radarli_oturum: Session) -> None:
        """⚠️ Eski sürüm Kuveyt Türk'e daima 88 veriyordu; veriyle değişmeliydi."""
        onceki = _radar(radarli_oturum, "kuveyt_turk").rate_competitiveness

        _urun_orani(radarli_oturum, "kuveyt_turk", "Çok Ucuz", Decimal("0.50"), 12)
        sonraki = _radar(radarli_oturum, "kuveyt_turk").rate_competitiveness

        assert onceki != sonraki


class TestVeriYoklugu:
    """⚠️ Ölçülemeyen eksen SIFIR DEĞİL `None`."""

    def test_orani_olmayan_banka_null_alir(self, radarli_oturum: Session) -> None:
        """Sıfır "kötü oran" demektir; veri yokluğu "bilmiyoruz" demektir."""
        veriyoksa = _radar(radarli_oturum, "adil_katilim")

        assert veriyoksa.rate_competitiveness is None
        assert veriyoksa.term_flexibility is None

    def test_olculen_eksen_sayisi_bildirilir(self, radarli_oturum: Session) -> None:
        """Arayüz kaç eksenin gerçek olduğunu göstermeli."""
        dolu = _radar(radarli_oturum, "albaraka")
        bos = _radar(radarli_oturum, "adil_katilim")

        assert dolu.measured_axes > bos.measured_axes
        assert bos.measured_axes >= 1  # kampanya hacmi daima ölçülür

    def test_kampanya_hacmi_daima_sayidir(self, radarli_oturum: Session) -> None:
        """Kampanyası olmayan banka 0 hacim alır — bu gerçek bir ölçüm."""
        assert _radar(radarli_oturum, "adil_katilim").campaign_volume == 0.0


class TestSeffaflikEkseni:
    def test_orani_olan_urun_orani_olculur(self, radarli_oturum: Session) -> None:
        """Şeffaflık = ürünlerin yüzde kaçının yayımlanmış oranı var."""
        skor = _radar(radarli_oturum, "albaraka")

        assert skor.transparency_index == 100.0  # tek ürün, oranı var

    def test_urunu_olmayan_banka_null_alir(self, radarli_oturum: Session) -> None:
        assert _radar(radarli_oturum, "adil_katilim").transparency_index is None


class TestOrtanca:
    """⚠️ Ortalama değil ortanca: tek büyük ödül tipik cömertliği bozmamalı."""

    def test_tek_aykiri_deger_ortancayi_savurmaz(self) -> None:
        assert _ortanca([100.0, 200.0, 300.0, 22000.0]) == 250.0

    def test_tek_sayida_eleman(self) -> None:
        assert _ortanca([10.0, 30.0, 20.0]) == 20.0


def test_sektor_dagilimi_campaign_categories_okur(seeded_session: Session) -> None:
    """⚠️ `Campaign.category` sütunu HİÇ dolmuyor; sınıflandırma ayrı tabloda.

    Eski sorgu `Campaign.category` okuduğu için sektör grafiği daima boştu.
    """
    from app.db.models.campaign_category import CampaignCategory

    banka = seeded_session.scalar(select(Bank).where(Bank.code == "albaraka"))
    assert banka is not None
    kampanya = Campaign(
        bank_id=banka.id,
        external_slug="s",
        title="s",
        source_url="https://ornek.com.tr/s",
    )
    seeded_session.add(kampanya)
    seeded_session.flush()
    seeded_session.add(
        CampaignCategory(
            campaign_id=kampanya.id,
            axis="sector",
            value="market_gida",
            confidence=Decimal("0.9"),
            source="keyword",
        )
    )
    seeded_session.flush()

    dagilim = get_stats(seeded_session).sector_distribution

    assert [s.sector for s in dagilim] == ["market_gida"]
