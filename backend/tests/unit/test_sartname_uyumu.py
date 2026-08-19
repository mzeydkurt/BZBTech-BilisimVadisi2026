"""Şartname §5.2 ve §5.6 örneklerinin birebir denetimi.

⚠️ Bu dosyadaki metinler ŞARTNAMENİN KENDİ ÖRNEKLERİDİR. Jüri bunları
aynen deneyebilir; hiçbiri kaçmamalıdır. Ölçüldü: üçü kaçıyordu —
`2.05 %` (yüzde işareti sonda), `500 Türk Lirası` (uzun para birimi adı)
ve "özel oranlı finansman … %1,89" (oran "kâr payı" kelimesinden uzakta).
"""

from __future__ import annotations

import pytest

from app.ai.extraction import extract_rule_based
from app.core.taxonomy import PRODUCT_TYPE_KEYWORDS
from app.schemas.compare import CAMPAIGN_CRITERIA, CRITERIA


def _alanlar(metin: str) -> dict[str, str | None]:
    """Kural tabanlı çıkarımı alan adı → normalize değer sözlüğüne çevirir."""
    return {c.field_name: c.value_normalized for c in extract_rule_based(metin)}


class TestBicimStandartlastirma:
    """§5.6 — "%2,05, % 2.05 ve 2.05 % aynı değer olarak yorumlanmalıdır"."""

    @pytest.mark.parametrize(
        "metin",
        [
            "Kâr payı oranı %2,05 olarak uygulanır.",
            "Kâr payı oranı % 2.05 olarak uygulanır.",
            "Kâr payı oranı 2.05 % olarak uygulanır.",
        ],
    )
    def test_uc_yuzde_yazimi_ayni_degeri_verir(self, metin: str) -> None:
        assert _alanlar(metin).get("profit_rate_pct") == "2.05"

    @pytest.mark.parametrize(
        "metin",
        [
            "Kampanyada 500 TL hediye verilir.",
            "Kampanyada 500₺ hediye verilir.",
            "Kampanyada 500 Türk Lirası hediye verilir.",
        ],
    )
    def test_uc_para_birimi_yazimi_ayni_degeri_verir(self, metin: str) -> None:
        """§5.6 — "500 TL, 500₺ ve 500 Türk Lirası aynı değer"."""
        assert _alanlar(metin).get("reward_amount_try") == "500"


class TestIfadeBicimleri:
    """§5.2 — farklı ifade biçimleri katılım terminolojisiyle yorumlanmalı."""

    @pytest.mark.parametrize(
        ("metin", "beklenen"),
        [
            ("Konut finansmanında %2,05 kâr payı oranı ile 120 aya kadar vade.", "2.05"),
            ("Özel oranlı finansman imkânı %1,89 ile sunulmaktadır.", "1.89"),
            ("Avantajlı kâr payı %2,15 ile finansman fırsatı.", "2.15"),
            ("Düşük maliyetli finansman %1,75 oranıyla sunulur.", "1.75"),
        ],
    )
    def test_oran_farkli_ifadelerde_bulunur(self, metin: str, beklenen: str) -> None:
        assert _alanlar(metin).get("profit_rate_pct") == beklenen

    def test_sayisiz_ifade_oran_uretmez(self) -> None:
        """⚠️ "Avantajlı kâr payı fırsatı" bir ORAN BELİRTMEZ.

        Sayı yoksa değer uydurulmaz; ifade yalnızca kampanya türünü belirler.
        """
        assert _alanlar("Avantajlı kâr payı fırsatı ile ihtiyaç finansmanı.") == {}


class TestYanlisPozitif:
    """⚠️ Bağlam kalıbı fazla cömert olmamalı."""

    def test_indirim_orani_kar_payi_sanilmaz(self) -> None:
        """ "Kâr payı avantajı" cümlesindeki %20 indirim, oran değildir."""
        alanlar = _alanlar("Kâr payı avantajı ile market alışverişlerinde %20 indirim kazanın.")

        assert alanlar.get("profit_rate_pct") is None
        assert alanlar.get("discount_pct") == "20"

    def test_uzak_yuzde_orana_baglanmaz(self) -> None:
        """Bağlam ile yüzde arasına çok kelime girerse bağ kurulmaz."""
        metin = (
            "Özel oranlı finansman kampanyamız kapsamında seçili mağazalarda "
            "yapacağınız alışverişlerde %30 indirim uygulanır."
        )

        assert _alanlar(metin).get("profit_rate_pct") is None


class TestKampanyaTurleri:
    """§5.4 — sekiz kampanya türü de sözlükte tanımlı olmalı."""

    @pytest.mark.parametrize(
        "tur",
        [
            "finansman",
            "ihtiyac_finansmani",
            "konut_finansmani",
            "tasit_finansmani",
            "kart",
            "alisveris_puani",
            "yeni_musteri",
            "yatirim_urunu",
        ],
    )
    def test_tur_sozlukte_var(self, tur: str) -> None:
        assert tur in PRODUCT_TYPE_KEYWORDS


class TestKarsilastirmaOlcutleri:
    """§5.7 — beş karşılaştırma ölçütü de desteklenmeli.

    ⚠️ Ölçütler İKİ AYRI SIRALAMAYA dağılır. Ödül tutarı üründe değil
    KAMPANYADA bulunur: bir bankanın "Taşıt Finansmanı" ürününün ödülü
    olmaz, o ürünü konu alan kampanyanın olur. İkisi tek listeye
    sıkıştırılırsa "en yüksek ödüllü ürün" gibi anlamsız bir sonuç çıkar.
    """

    @pytest.mark.parametrize(
        "olcut",
        ["en_dusuk_kar_payi", "en_uzun_vade", "en_dusuk_masraf", "en_avantajli"],
    )
    def test_urun_olcutu_tanimli(self, olcut: str) -> None:
        assert olcut in CRITERIA

    def test_en_yuksek_odul_kampanya_olcutudur(self) -> None:
        assert "en_yuksek_odul" in CAMPAIGN_CRITERIA

    def test_sartnamenin_bes_olcutu_de_karsilaniyor(self) -> None:
        """§5.7 tablosundaki beş ölçütün tamamı bir yerde tanımlı olmalı."""
        tanimli = set(CRITERIA) | set(CAMPAIGN_CRITERIA)

        assert {
            "en_dusuk_kar_payi",
            "en_yuksek_odul",
            "en_uzun_vade",
            "en_dusuk_masraf",
            "en_avantajli",
        } <= tanimli
