"""Katılma sohbet yanıtı — Katılım Hesabı pivot kaynağı."""

from __future__ import annotations

from decimal import Decimal

from app.core.normalization.text import ascii_fold_tr, lower_tr, normalize_text
from app.retrieval.query import (
    parse_katilma_vade,
    parse_katilma_vadeler,
    parse_katilma_varyant,
    parse_query,
)
from app.schemas.katilim_hesabi import KatilimHesabiRow
from app.services.chat_service import _katilma_cevap_metni, _yuzde_yaz, sirala_katilma_satirlari


def _fold(text: str) -> str:
    return ascii_fold_tr(lower_tr(normalize_text(text)))


def test_kullanici_sorgusu_katilma_alani() -> None:
    plan = parse_query(
        "Bana katılma hesapları hakkında bilgi verir misin birde şuan "
        "aylık standart katılım hesabından en ideal hangisi"
    )
    assert plan.source_domain == "katilma"
    folded = _fold(plan.raw)
    assert parse_katilma_vade(folded) == 1
    assert parse_katilma_varyant(folded) == "normal"


def test_yuzde_yaz_kirpma() -> None:
    assert _yuzde_yaz(Decimal("40.000")) == "%40"
    assert _yuzde_yaz(Decimal("31.35")) == "%31,35"
    assert _yuzde_yaz(Decimal("31.3500")) == "%31,35"


def test_sirala_banka_basi_tek_ve_en_yuksek() -> None:
    satirlar = [
        KatilimHesabiRow(
            bank_code="a",
            bank_name="A Bank",
            values={"aylik|TRY": Decimal("20.5")},
            data_source="tkbb_veripetegi",
        ),
        KatilimHesabiRow(
            bank_code="b",
            bank_name="B Bank",
            values={"aylik|TRY": Decimal("35.1")},
            data_source="tkbb_veripetegi",
        ),
        KatilimHesabiRow(
            bank_code="c",
            bank_name="C Bank",
            values={"aylik|TRY": Decimal("30.0"), "3_aylik|TRY": Decimal("99")},
            data_source="bank_site",
        ),
    ]
    sonuc = sirala_katilma_satirlari(satirlar, hucre="aylik|TRY", limit=3)
    assert [s.bank_code for s, _ in sonuc] == ["b", "c", "a"]
    assert sonuc[0][1] == Decimal("35.1")


def test_coklu_vade_aylik_haric_tutulmaz() -> None:
    folded = _fold(
        "aylık 3 aylık 6 aylık ve 1 yıllık katılma hesapları varmış "
        "hangi aylığa göre hangi banka daha iyi"
    )
    assert parse_katilma_vadeler(folded) == (1, 3, 6, 12)
    assert parse_katilma_vade(folded) == 3  # uzun kalıp önce


def test_merhaba_dogal_coklu_vade_yaniti() -> None:
    folded = _fold(
        "Merhaba ben katılma hesabı açacağım sence hangi bankadan açmalıyım"
    )
    a = KatilimHesabiRow(
        bank_code="tom",
        bank_name="T.O.M. Katılım Bankası",
        values={},
        data_source="tkbb_veripetegi",
    )
    b = KatilimHesabiRow(
        bank_code="hayat",
        bank_name="Hayat Finans",
        values={},
        data_source="tkbb_veripetegi",
    )
    c = KatilimHesabiRow(
        bank_code="kt",
        bank_name="Kuveyt Türk",
        values={},
        data_source="tkbb_veripetegi",
    )
    metin = _katilma_cevap_metni(
        folded=folded,
        giris_gerekli=False,
        sirala=True,
        currency="TRY",
        oran_etiketi="dağıtılan kâr payı (getiri)",
        urun_adi="Standart Katılma Hesabı",
        vade_siralar=[
            (1, [(a, Decimal("31.1")), (b, Decimal("30")), (c, Decimal("29"))]),
            (3, [(a, Decimal("42.74")), (b, Decimal("39.31")), (c, Decimal("34.42"))]),
            (6, [(a, Decimal("40")), (b, Decimal("38")), (c, Decimal("33"))]),
            (12, [(a, Decimal("39")), (b, Decimal("37")), (c, Decimal("32"))]),
        ],
    )
    assert metin.startswith("Merhaba.")
    assert "karıştırılmamalıdır" not in metin
    assert "3 Aylık vadede" in metin or "3 aylık vadede" in metin
    assert "T.O.M. Katılım Bankası" in metin
    assert "%42,74" in metin
