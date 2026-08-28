"""Para tutarı ayrıştırma testleri.

Türkçe sayı biçimi İngilizce'nin tersidir; bu testlerin çoğu o ayrımı korur.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.normalization.money import (
    detect_currency,
    parse_decimal_tr,
    parse_money,
    parse_money_range,
    parse_tier_structure,
)


class TestParseDecimalTr:
    """Türkçe sayı biçimi: nokta binlik, virgül ondalık."""

    @pytest.mark.parametrize(
        ("token", "expected"),
        [
            ("5.000", Decimal("5000")),  # nokta = binlik
            ("5,000", Decimal("5")),  # virgül = ondalık
            ("1.250,50", Decimal("1250.50")),
            ("2.000.000", Decimal("2000000")),
            ("2.05", Decimal("2.05")),  # 3 hane değil -> ondalık
            ("2,05", Decimal("2.05")),
            ("100", Decimal("100")),
            ("0,10", Decimal("0.10")),
            ("1,250.50", Decimal("1250.50")),  # İngilizce biçim de tanınır
            ("1234.567", Decimal("1234.567")),  # baş grup 3 haneden uzun -> ondalık
        ],
    )
    def test_sayi_ayristirma(self, token: str, expected: Decimal) -> None:
        assert parse_decimal_tr(token) == expected

    @pytest.mark.parametrize("token", [None, "", "abc", "  ", "TL"])
    def test_gecersiz_girdi_none_dondurur(self, token: str | None) -> None:
        assert parse_decimal_tr(token) is None

    def test_sondaki_ayirici_kirpilir(self) -> None:
        assert parse_decimal_tr("5.000,") == Decimal("5000")


class TestParseMoney:
    """Şartnamedeki para ayrıştırma tablosu."""

    @pytest.mark.parametrize(
        ("text", "amount", "currency"),
        [
            ("500 TL", Decimal("500"), "TRY"),
            ("500₺", Decimal("500"), "TRY"),
            ("500 Türk Lirası", Decimal("500"), "TRY"),
            ("5.000 TL", Decimal("5000"), "TRY"),
            ("5.000,50 TL", Decimal("5000.50"), "TRY"),
            ("5 bin TL", Decimal("5000"), "TRY"),
            ("1 milyon TL", Decimal("1000000"), "TRY"),
            ("2.000.000 TL", Decimal("2000000"), "TRY"),
            ("100 USD", Decimal("100"), "USD"),
            ("50.000 TL'ye kadar", Decimal("50000"), "TRY"),
            ("masrafsız", Decimal("0"), "TRY"),
        ],
    )
    def test_tutar_ve_para_birimi(self, text: str, amount: Decimal, currency: str) -> None:
        assert parse_money(text) == (amount, currency)

    @pytest.mark.parametrize("text", ["belirtilmemiş", "", None, "kampanya detayları"])
    def test_tutar_bulunamazsa_none(self, text: str | None) -> None:
        parsed, currency = parse_money(text)
        assert parsed is None
        assert currency == "TRY"

    def test_sms_numarasi_tutar_sanilmaz(self) -> None:
        """Para birimine bitişik sayı önceliklidir; SMS numarası tutar değildir."""
        assert parse_money("6026'ya SMS gönderin, 500 TL kazanın") == (Decimal("500"), "TRY")

    def test_tutar_varken_masrafsiz_ifadesi_ezmez(self) -> None:
        parsed, _ = parse_money("masrafsız 50.000 TL finansman")
        assert parsed == Decimal("50000")

    def test_vade_tutar_sanilmaz(self) -> None:
        assert parse_money("Bana 120 ay vadeli bir konut finansmanı önerir misin") == (
            None,
            "TRY",
        )
        assert parse_money("36 aylık taşıt") == (None, "TRY")
        assert parse_money("400.000 TL 48 ay vadeli") == (Decimal("400000"), "TRY")


class TestDetectCurrency:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("500 TL", "TRY"),
            ("500 ₺", "TRY"),
            ("100 USD", "USD"),
            ("100 $", "USD"),
            ("100 EUR", "EUR"),
            ("100 €", "EUR"),
            ("100 Sterlin", "GBP"),
            ("tutar yok", "TRY"),
        ],
    )
    def test_para_birimi_tespiti(self, text: str, expected: str) -> None:
        assert detect_currency(text) == expected


class TestParseMoneyRange:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("50.000 - 2.000.000 TL", (Decimal("50000"), Decimal("2000000"), "TRY")),
            ("50.000 TL - 2.000.000 TL", (Decimal("50000"), Decimal("2000000"), "TRY")),
            ("5 bin ile 10 bin TL", (Decimal("5000"), Decimal("10000"), "TRY")),
            ("50.000 TL'ye kadar", (None, Decimal("50000"), "TRY")),
            ("5.000 TL ve üzeri", (Decimal("5000"), None, "TRY")),
            ("500 TL", (Decimal("500"), Decimal("500"), "TRY")),
            ("belirtilmemiş", (None, None, "TRY")),
        ],
    )
    def test_aralik(self, text: str, expected: tuple[Decimal | None, Decimal | None, str]) -> None:
        assert parse_money_range(text) == expected

    def test_bos_girdi(self) -> None:
        assert parse_money_range(None) == (None, None, "TRY")


class TestParseTierStructure:
    def test_kademeli_odul(self) -> None:
        sonuc = parse_tier_structure("5.000 TL ve üzeri 250 TL, 10.000 TL ve üzeri 500 TL")
        assert sonuc == [
            {"threshold": Decimal("5000"), "reward": Decimal("250")},
            {"threshold": Decimal("10000"), "reward": Decimal("500")},
        ]

    def test_tek_kademe(self) -> None:
        assert parse_tier_structure("1.500 TL ve üzeri harcamaya 200 TL") == [
            {"threshold": Decimal("1500"), "reward": Decimal("200")}
        ]

    @pytest.mark.parametrize("text", [None, "", "kademe yok"])
    def test_kademe_yoksa_bos_liste(self, text: str | None) -> None:
        assert parse_tier_structure(text) == []
