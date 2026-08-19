"""Ürün sıralama servisi testleri (SPRINT2.5 §8.3).

Sıralamanın iki kırılgan noktası ölçülür:
  1. Farklı `rate_type`'lar aynı sıralamaya GİREMEZ.
  2. Değeri olmayan ürün sıralamaya KARIŞMAZ.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.bank import Bank
from app.db.models.product import Product, ProductRate
from app.schemas.compare import RankingWeights
from app.services.comparison_service import RankingError, rank_products


def _oran_ekle(
    session: Session,
    banka_kodu: str,
    ad: str,
    **alanlar: object,
) -> None:
    """Tek oranlı bir ürün ekler."""
    banka = session.scalar(select(Bank).where(Bank.code == banka_kodu))
    assert banka is not None
    urun = Product(
        bank_id=banka.id,
        external_key=f"{banka_kodu}:{ad}",
        name=ad,
        product_type=str(alanlar.pop("product_type", "tasit_finansmani")),
    )
    session.add(urun)
    session.flush()
    session.add(
        ProductRate(
            product_id=urun.id,
            band_key=ad,
            rate_type=str(alanlar.pop("rate_type", "financing_rate")),
            currency=str(alanlar.pop("currency", "TRY")),
            evidence_text=f"{ad} kanıt",
            **alanlar,  # type: ignore[arg-type]
        )
    )
    session.flush()


@pytest.fixture
def finansman_oturumu(seeded_session: Session) -> Session:
    """Üç bankada finansman oranı; birinde tahsis ücreti YOK."""
    _oran_ekle(
        seeded_session,
        "albaraka",
        "Ucuz Taşıt",
        profit_rate_pct=Decimal("3.05"),
        allocation_fee_pct=Decimal("0.50"),
        term_months=36,
    )
    _oran_ekle(
        seeded_session,
        "kuveyt_turk",
        "Pahalı Taşıt",
        profit_rate_pct=Decimal("4.20"),
        allocation_fee_pct=Decimal("0.10"),
        term_months=48,
    )
    _oran_ekle(
        seeded_session,
        "vakif_katilim",
        "Masrafı Bilinmeyen",
        profit_rate_pct=Decimal("3.50"),
        allocation_fee_pct=None,
        term_months=24,
    )
    return seeded_session


def test_en_dusuk_kar_payi_artan_siralar(finansman_oturumu: Session) -> None:
    sonuc = rank_products(
        finansman_oturumu, rate_type="financing_rate", criterion="en_dusuk_kar_payi"
    )

    assert [s.bank_code for s in sonuc.ranked] == ["albaraka", "vakif_katilim", "kuveyt_turk"]
    assert sonuc.winner is not None and sonuc.winner.bank_code == "albaraka"


def test_kazanan_gerekcesi_kazanilan_olcutu_soyler(finansman_oturumu: Session) -> None:
    """⚠️ Gerekçe hangi ölçütle kazanıldığını söylemeli.

    Sabit bir "avantajlı koşulları ile" cümlesi her ölçütte aynı çıkar ve
    kullanıcıya yanlış bilgi verir.
    """
    dusuk = rank_products(
        finansman_oturumu, rate_type="financing_rate", criterion="en_dusuk_kar_payi"
    )
    uzun = rank_products(finansman_oturumu, rate_type="financing_rate", criterion="en_uzun_vade")

    assert dusuk.winner_reason != uzun.winner_reason
    assert "kâr payı" in (dusuk.winner_reason or "")
    assert "vade" in (uzun.winner_reason or "")


def test_verisi_olmayan_urun_siralamaya_girmez(finansman_oturumu: Session) -> None:
    """⚠️ NULL tahsis ücreti "sıfır masraf" DEĞİLDİR.

    Sıfır sayılırsa masrafını yayımlamayan banka birinci olur; bu jüri
    karşısında savunulamaz.
    """
    sonuc = rank_products(
        finansman_oturumu, rate_type="financing_rate", criterion="en_dusuk_masraf"
    )

    assert [s.bank_code for s in sonuc.ranked] == ["kuveyt_turk", "albaraka"]
    assert [s.bank_code for s in sonuc.without_data] == ["vakif_katilim"]
    assert sonuc.without_data[0].missing_reason


def test_veri_yok_grubunun_sirasi_yoktur(finansman_oturumu: Session) -> None:
    sonuc = rank_products(
        finansman_oturumu, rate_type="financing_rate", criterion="en_dusuk_masraf"
    )

    assert all(s.rank is None for s in sonuc.without_data)


def test_rate_type_ile_bagdasmayan_olcut_reddedilir(finansman_oturumu: Session) -> None:
    """⚠️ "En yüksek getiri" finansman oranında ANLAMSIZDIR.

    En pahalı finansmanı "en iyi" ilan ederdi.
    """
    with pytest.raises(RankingError, match="participation_yield"):
        rank_products(finansman_oturumu, rate_type="financing_rate", criterion="en_yuksek_getiri")


def test_gecersiz_rate_type_reddedilir(finansman_oturumu: Session) -> None:
    with pytest.raises(RankingError, match="rate_type"):
        rank_products(finansman_oturumu, rate_type="faiz", criterion="en_dusuk_kar_payi")


def test_farkli_turler_ayni_siralamaya_girmez(seeded_session: Session) -> None:
    """Finansman ve katılma getirisi aynı sütunu paylaşır; karışmamalı."""
    _oran_ekle(
        seeded_session,
        "albaraka",
        "Finansman",
        profit_rate_pct=Decimal("3.05"),
        term_months=36,
    )
    _oran_ekle(
        seeded_session,
        "turkiye_finans",
        "Katılma",
        rate_type="participation_yield",
        profit_rate_pct=Decimal("31.21"),
        term_months=12,
        product_type="birikim_katilma_hesabi",
    )

    sonuc = rank_products(
        seeded_session, rate_type="participation_yield", criterion="en_yuksek_getiri"
    )

    assert [s.bank_code for s in sonuc.ranked] == ["turkiye_finans"]
    assert all(s.rate_type == "participation_yield" for s in sonuc.ranked)


def test_paylasim_orani_azalan_siralar(seeded_session: Session) -> None:
    _oran_ekle(
        seeded_session,
        "ziraat_katilim",
        "Cömert",
        rate_type="profit_sharing_ratio",
        investor_share_pct=Decimal("90"),
        bank_share_pct=Decimal("10"),
        product_type="birikim_katilma_hesabi",
    )
    _oran_ekle(
        seeded_session,
        "kuveyt_turk",
        "Cimri",
        rate_type="profit_sharing_ratio",
        investor_share_pct=Decimal("70"),
        bank_share_pct=Decimal("30"),
        product_type="birikim_katilma_hesabi",
    )

    sonuc = rank_products(
        seeded_session,
        rate_type="profit_sharing_ratio",
        criterion="en_yuksek_paylasim_orani",
    )

    assert [s.bank_code for s in sonuc.ranked] == ["ziraat_katilim", "kuveyt_turk"]


class TestAgirliklar:
    """⚠️ Ağırlıklar GERÇEKTEN hesaba girmeli.

    Şemada durup kullanılmayan ağırlık, kullanıcıya var olmayan bir denetim
    vaat eder.
    """

    def test_oran_agirligi_kazanani_belirler(self, finansman_oturumu: Session) -> None:
        sonuc = rank_products(
            finansman_oturumu,
            rate_type="financing_rate",
            criterion="en_avantajli",
            weights=RankingWeights(
                rate_weight=Decimal("100"), fee_weight=Decimal("0"), term_weight=Decimal("0")
            ),
        )

        assert sonuc.winner is not None
        assert sonuc.winner.bank_code == "albaraka"  # en düşük oran

    def test_vade_agirligi_kazanani_degistirir(self, finansman_oturumu: Session) -> None:
        """Aynı veri, farklı ağırlık → farklı kazanan."""
        sonuc = rank_products(
            finansman_oturumu,
            rate_type="financing_rate",
            criterion="en_avantajli",
            weights=RankingWeights(
                rate_weight=Decimal("0"), fee_weight=Decimal("0"), term_weight=Decimal("100")
            ),
        )

        assert sonuc.winner is not None
        assert sonuc.winner.bank_code == "kuveyt_turk"  # en uzun vade (48 ay)

    def test_eksik_bilesen_paydadan_da_duser(self, finansman_oturumu: Session) -> None:
        """⚠️ Masraf verisi olmayan ürün "masrafsız" sayılmamalı.

        Eksik bileşen yalnızca paydan düşerse o ürün haksız avantaj kazanır.
        """
        sonuc = rank_products(
            finansman_oturumu,
            rate_type="financing_rate",
            criterion="en_avantajli",
            weights=RankingWeights(
                rate_weight=Decimal("0"), fee_weight=Decimal("100"), term_weight=Decimal("0")
            ),
        )

        siralanan = {s.bank_code for s in sonuc.ranked}
        assert "vakif_katilim" not in siralanan
        assert "vakif_katilim" in {s.bank_code for s in sonuc.without_data}

    def test_tum_agirliklar_sifir_reddedilir(self) -> None:
        with pytest.raises(ValueError, match="ağırlık"):
            RankingWeights(
                rate_weight=Decimal("0"), fee_weight=Decimal("0"), term_weight=Decimal("0")
            )
