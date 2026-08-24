"""rate_direction — tek kaynak yön kuralı."""

from __future__ import annotations

from app.core.rate_direction import avantajli_yon, yon_notu
from app.retrieval.answer import check_direction


def test_finansman_dusuk_iyi() -> None:
    assert avantajli_yon("financing_rate") is False


def test_katilma_getiri_yuksek_iyi() -> None:
    assert avantajli_yon("participation_yield") is True


def test_paylasim_yuksek_iyi() -> None:
    assert avantajli_yon("profit_sharing_ratio") is True


def test_karz_yon_yok() -> None:
    assert avantajli_yon("interest_free_benevolent_loan") is None
    assert yon_notu("interest_free_benevolent_loan") is None


def test_ters_yon_tespit() -> None:
    """Finansmanda 'daha yüksek avantajlı' → bozuk."""
    assert check_direction(
        "Bu banka daha yüksek oranla daha avantajlıdır [1].",
        "financing_rate",
    )


def test_dogru_yon_gecer() -> None:
    assert not check_direction(
        "Bu banka daha düşük kâr payı ile avantajlıdır [1].",
        "financing_rate",
    )


def test_karz_avantaj_cumlesi_bozuk() -> None:
    assert check_direction("Bu ürün daha avantajlıdır [1].", "interest_free_benevolent_loan")
