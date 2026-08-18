"""Kâr payı oranı ayrıştırma testleri.

TERMİNOLOJİ: Katılım bankacılığında faiz kavramı yoktur; test adları ve
açıklamaları "kâr payı oranı" terimini kullanır.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.normalization.rate import parse_rate, parse_rate_range


class TestParseRate:
    """Şartnamedeki oran ayrıştırma tablosu."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("%2,05", Decimal("2.05")),
            ("% 2.05", Decimal("2.05")),
            ("2.05 %", Decimal("2.05")),
            ("2,05%", Decimal("2.05")),
            ("yüzde 2,05", Decimal("2.05")),
            ("%2.05 oranında", Decimal("2.05")),
            ("%0,10", Decimal("0.10")),
            ("4,15%", Decimal("4.15")),
            ("%50'ye varan", Decimal("50")),
            ("vade farksız", Decimal("0")),
        ],
    )
    def test_oran_ayristirma(self, text: str, expected: Decimal) -> None:
        assert parse_rate(text) == expected

    @pytest.mark.parametrize(
        "text",
        ["avantajlı kâr payı fırsatı", "", None, "kampanya detayları", "hemen başvur"],
    )
    def test_oran_bulunamazsa_none(self, text: str | None) -> None:
        assert parse_rate(text) is None

    def test_ciplak_sayi_oran_sayilmaz(self) -> None:
        """Yüzde işareti olmadan sayı oran kabul edilmez.

        Aksi hâlde SMS numarası, şube kodu ve puan değerleri oran sanılırdı.
        """
        assert parse_rate("2,05") is None
        assert parse_rate("6026'ya SMS gönderin") is None

    def test_pesin_fiyatina_sifir_oran(self) -> None:
        assert parse_rate("peşin fiyatına taksit") == Decimal("0")


class TestParseRateRange:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("%1,89 - %2,45", (Decimal("1.89"), Decimal("2.45"))),
            ("%50'ye varan", (None, Decimal("50"))),
            ("%2,05'ten başlayan", (Decimal("2.05"), None)),
            ("%2,05", (Decimal("2.05"), Decimal("2.05"))),
            ("vade farksız", (Decimal("0"), Decimal("0"))),
            ("kâr payı fırsatı", (None, None)),
        ],
    )
    def test_oran_araligi(self, text: str, expected: tuple[Decimal | None, Decimal | None]) -> None:
        assert parse_rate_range(text) == expected

    def test_bos_girdi(self) -> None:
        assert parse_rate_range(None) == (None, None)


class TestParseProfitSharingRatio:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("90/10", (Decimal("90"), Decimal("10"))),
            ("90 / 10", (Decimal("90"), Decimal("10"))),
            ("%90 - %10", (Decimal("90"), Decimal("10"))),
            ("89.1 / 10.9", (Decimal("89.1"), Decimal("10.9"))),
            ("98/2", (Decimal("98"), Decimal("2"))),
            ("%75", (Decimal("75"), Decimal("25"))),
        ],
    )
    def test_bolusum_orani_ayristirma(
        self, text: str, expected: tuple[Decimal | None, Decimal | None]
    ) -> None:
        from app.core.normalization.rate import parse_profit_sharing_ratio

        assert parse_profit_sharing_ratio(text) == expected

    def test_gecersiz_bolusum_orani(self) -> None:
        from app.core.normalization.rate import parse_profit_sharing_ratio

        assert parse_profit_sharing_ratio(None) == (None, None)
        assert parse_profit_sharing_ratio("metin") == (None, None)
