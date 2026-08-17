"""Limit çıkarımı testleri.

Şartnamedeki tüm örnekler burada kilitlidir. En kritik davranış: yön belirsizse
DEĞER ATANMAZ — "50.000 TL" tek başına ne alt ne üst sınırdır ve tahmin
edilirse bankanın asgari tutarı azami gibi kaydedilir.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.processing.limits import (
    derive_rate_from_payment_plan,
    extract_limits_from_text,
    parse_allowed_terms,
    parse_amount_limit,
    parse_ltv,
    parse_vehicle_age,
)


class TestTutarLimiti:
    """`parse_amount_limit` — şartnamedeki dört örnek."""

    @pytest.mark.parametrize(
        ("metin", "beklenen"),
        [
            ("50.000 TL'ye kadar", (None, Decimal("50000"))),
            ("10.000 TL'den başlayan", (Decimal("10000"), None)),
            ("50.000 - 2.000.000 TL arası", (Decimal("50000"), Decimal("2000000"))),
            ("asgari 5.000 TL", (Decimal("5000"), None)),
            ("azami 1 milyon TL", (None, Decimal("1000000"))),
        ],
    )
    def test_sartname_ornekleri(
        self, metin: str, beklenen: tuple[Decimal | None, Decimal | None]
    ) -> None:
        assert parse_amount_limit(metin) == beklenen

    def test_yon_belirsizse_deger_atanmaz(self) -> None:
        """⚠️ Tahmin edilirse asgari tutar azami gibi kaydedilir."""
        assert parse_amount_limit("Finansman tutarı 50.000 TL") == (None, None)

    def test_tutar_yoksa_bos_doner(self) -> None:
        assert parse_amount_limit("Kampanya koşulları geçerlidir.") == (None, None)
        assert parse_amount_limit(None) == (None, None)

    def test_turkce_binlik_ayraci_dogru_okunur(self) -> None:
        """⚠️ `5.000` beş bindir, beş değil."""
        _, en_cok = parse_amount_limit("5.000 TL'ye kadar")
        assert en_cok == Decimal("5000")


class TestLtv:
    """`parse_ltv` — kredi/değer oranı."""

    def test_ekspertiz_degeri_ifadesi(self) -> None:
        assert parse_ltv("ekspertiz değerinin %80'ine kadar") == Decimal("80")

    def test_gayrimenkul_degeri_ifadesi(self) -> None:
        assert parse_ltv("gayrimenkul değerinin %75'i oranında finansman") == Decimal("75")

    def test_yuzde_yuzun_ustu_reddedilir(self) -> None:
        """%100'ün üstü LTV olamaz; büyük olasılıkla başka bir yüzde."""
        assert parse_ltv("ekspertiz değerinin %150'si") is None

    def test_bulunamazsa_none(self) -> None:
        assert parse_ltv("Kampanya %20 indirim sağlar.") is None
        assert parse_ltv(None) is None


class TestAracYasi:
    """`parse_vehicle_age` — şartnamedeki üç örnek."""

    @pytest.mark.parametrize(
        ("metin", "beklenen"),
        [
            ("0-3 yaş araçlarda", (0, 3)),
            ("sıfır araç", (0, 0)),
            ("ikinci el", (1, None)),
            ("2. el araçlarda", (1, None)),
            ("5 yaşına kadar", (None, 5)),
        ],
    )
    def test_sartname_ornekleri(self, metin: str, beklenen: tuple[int | None, int | None]) -> None:
        assert parse_vehicle_age(metin) == beklenen

    def test_ilgisiz_metin(self) -> None:
        assert parse_vehicle_age("Konut finansmanı kampanyası") == (None, None)


class TestIzinliVadeler:
    """⚠️ `allowed_terms` en değerli limit alanıdır."""

    def test_liste_okunur(self) -> None:
        assert parse_allowed_terms("3, 6, 12 ve 24 ay vade seçenekleri") == [3, 6, 12, 24]

    def test_aralik_ifadesi_liste_uretmez(self) -> None:
        """ "3-36 ay arası" hangi vadelerin sunulduğunu SÖYLEMEZ."""
        assert parse_allowed_terms("36 aya kadar vade") is None

    def test_bulunamazsa_none(self) -> None:
        assert parse_allowed_terms("Kampanya koşulları") is None


class TestOdemePlanindanOran:
    """`derive_rate_from_payment_plan` — Albaraka, sorgulamasız."""

    def test_aylik_oran_hesaplanir(self) -> None:
        # 100.000 ana para, 124.000 geri ödeme, 12 ay -> aylık %2
        oran = derive_rate_from_payment_plan(Decimal("100000"), Decimal("124000"), 12)
        assert oran == Decimal("2.0000")

    def test_dort_ondalige_yuvarlanir(self) -> None:
        oran = derive_rate_from_payment_plan(Decimal("100000"), Decimal("113333"), 12)
        assert oran is not None
        assert oran.as_tuple().exponent == -4

    @pytest.mark.parametrize(
        ("ana", "toplam", "vade"),
        [
            (None, Decimal("120000"), 12),
            (Decimal("100000"), None, 12),
            (Decimal("100000"), Decimal("120000"), None),
            (Decimal("0"), Decimal("120000"), 12),
            # Geri ödeme ana paradan küçükse veri bozuktur.
            (Decimal("100000"), Decimal("90000"), 12),
        ],
    )
    def test_eksik_veya_bozuk_veride_none(
        self, ana: Decimal | None, toplam: Decimal | None, vade: int | None
    ) -> None:
        assert derive_rate_from_payment_plan(ana, toplam, vade) is None


class TestMetindenLimitToplama:
    """`extract_limits_from_text`."""

    def test_birden_fazla_alan_doldurulur(self) -> None:
        limitler = extract_limits_from_text(
            "Finansman tutarı 50.000 TL'ye kadar, 3, 6 ve 12 ay vade seçenekleriyle. "
            "Ekspertiz değerinin %80'ine kadar finansman sağlanır."
        )
        assert limitler.amount_max == Decimal("50000")
        assert limitler.allowed_terms == [3, 6, 12]
        assert limitler.term_months_min == 3
        assert limitler.term_months_max == 12
        assert limitler.ltv_max_pct == Decimal("80")
        assert limitler.source == "text"

    def test_hicbir_alan_dolmazsa_kaynak_none(self) -> None:
        """⚠️ Sahte bir `text` kaynağı veri varmış izlenimi yaratır."""
        limitler = extract_limits_from_text("Kampanya koşulları geçerlidir.")
        assert limitler.is_empty
        assert limitler.source == "none"

    def test_bos_girdi(self) -> None:
        assert extract_limits_from_text(None).is_empty
        assert extract_limits_from_text("").source == "none"

    def test_kanit_metni_saklanir(self) -> None:
        limitler = extract_limits_from_text("Azami 1 milyon TL finansman.")
        assert limitler.evidence
        assert "milyon" in limitler.evidence


# ── Para birimi işareti taşımayan aralık (gerçek veri regresyonu) ──


@pytest.mark.parametrize(
    "metin",
    [
        # Katılma hesabı PAYLAŞIM ORANI tablosu — tutar değil.
        "Türk Lirası | 1 Aylık | 3 Aylık 250 | 250 | 40-60 | 40-60 | 40-60",
        # Kırık VADE — gün cinsinden, tutar değil.
        "1-30 gün arası kırık vadede açılabilen günlük hesap türüdür.",
    ],
)
def test_para_birimi_olmayan_aralik_tutar_sayilmaz(metin: str) -> None:
    """⚠️ GERÇEK VERİDE ÖLÇÜLDÜ (Dünya Katılım).

    Sayfanın tamamı verildiğinde her "N-M" örüntüsü tutar aralığı sanılıyordu;
    paylaşım oranı 40-60 TL, kırık vade 1-30 TL olarak ürün limitine yazıldı.
    """
    assert parse_amount_limit(metin) == (None, None)


def test_sifir_alt_sinir_yazilmaz() -> None:
    """⚠️ "0 TL'den başlayan finansman" diye bir ürün yok.

    Sıfır ya biçim artığıdır ya da "%0 peşinat" gibi başka bir ifadeden
    sızmıştır. Kılavuz kuralı: alt sınır belirtilmemişse ∅, sıfır YAZILMAZ.
    """
    en_az, en_cok = parse_amount_limit("0 - 400.000 TL arası araç finansmanı")

    assert en_az is None
    assert en_cok == Decimal("400000")


def test_birimli_aralik_okunmaya_devam_ediyor() -> None:
    """Düzeltme gerçek tutar aralıklarını bozmamalı."""
    assert parse_amount_limit("1.000 TL - 100.000 TL arası") == (
        Decimal("1000"),
        Decimal("100000"),
    )
