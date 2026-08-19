"""Gold kanıt bağlama testleri.

⚠️ Bu betiğin en büyük riski FAZLA CÖMERT olmasıdır: çıplak bir rakamı kanıt
sayarsa `gold-durum` raporu yeşile döner ama elde gerçek bir kanıt olmaz.
Testler bu yüzden hem "doğru kanıtı buluyor" hem "yanlış kanıtı REDDEDİYOR"
tarafını ölçer.
"""

from __future__ import annotations

import pytest

from scripts.anchor_gold_evidence import SINIFLANDIRMA_ALANLARI, kanit_bul

METIN = (
    "Emlak Katılım Kartınızla 5.000 TL ve Üzeri Harcamanıza 2.500 TL Hediye! "
    "Kampanya Tarihleri 23.06.2025 - 31.12.2026 arasında geçerlidir. "
    "100.000 TL'ye kadar alışverişlerinizde 6 taksite kadar %2,99 avantajlı "
    "kâr payı oranı sunulmaktadır. Kampanya 1 Haziran 2026 tarihinde başlar."
)


class TestBaglamliKanit:
    """Değer, birimi ve çevresiyle birlikte bulunmalı."""

    def test_tutar_birimiyle_bulunur(self) -> None:
        kanit = kanit_bul("min_spend_try", "5000", METIN)

        assert kanit is not None
        assert "5.000 TL" in kanit

    def test_oran_yuzde_isaretiyle_bulunur(self) -> None:
        """⚠️ Türkçe ondalık ayracı: 2.79 metinde "2,79" yazılır."""
        kanit = kanit_bul("profit_rate_pct", "2.99", METIN)

        assert kanit is not None
        assert "%2,99" in kanit

    def test_taksit_sayisi_baglamiyla_bulunur(self) -> None:
        kanit = kanit_bul("installment_count", "6", METIN)

        assert kanit is not None
        assert "taksit" in kanit

    def test_nokta_ayracli_tarih_bulunur(self) -> None:
        kanit = kanit_bul("start_date", "2025-06-23", METIN)

        assert kanit is not None
        assert "23.06.2025" in kanit

    def test_turkce_ay_adli_tarih_bulunur(self) -> None:
        kanit = kanit_bul("start_date", "2026-06-01", METIN)

        assert kanit is not None
        assert "Haziran 2026" in kanit


class TestCiplakRakamReddedilir:
    """⚠️ Bağlamsız eşleşme kanıt DEĞİLDİR."""

    def test_birimi_olmayan_tutar_reddedilir(self):  # type: ignore[no-untyped-def]
        """Metinde "6" var ama "6 TL" yok; tutar olarak bağlanmamalı."""
        assert kanit_bul("reward_amount_try", "6", "Toplam 6 taksit imkânı sunulur.") is None

    def test_yuzde_isareti_olmayan_oran_reddedilir(self) -> None:
        assert kanit_bul("cashback_pct", "20", "Kampanya 20 ilde geçerlidir.") is None

    def test_metinde_hic_gecmeyen_deger_reddedilir(self) -> None:
        assert kanit_bul("min_spend_try", "77777", METIN) is None

    def test_sayinin_parcasi_eslesme_sayilmaz(self) -> None:
        """⚠️ "75" ile "175 TL" karışmamalı."""
        assert kanit_bul("min_spend_try", "75", "Tutar 175 TL olarak belirlenmiştir.") is None


class TestSiniflandirmaAlanlari:
    """Kategori alanları otomatik bağlanmaz."""

    @pytest.mark.parametrize("alan", sorted(SINIFLANDIRMA_ALANLARI))
    def test_siniflandirma_alani_baglanmaz(self, alan: str) -> None:
        """Metin "seyahat_konaklama" yazmaz; hangi ifadenin o kategoriyi
        doğurduğu insan yargısıdır."""
        assert kanit_bul(alan, "kart", METIN) is None


def test_bos_metin_kanit_uretmez() -> None:
    assert kanit_bul("min_spend_try", "5000", "") is None


def test_kanit_makul_uzunlukta() -> None:
    """Kanıt bağlam taşımalı ama paragrafın tamamı da olmamalı."""
    kanit = kanit_bul("min_spend_try", "5000", METIN)

    assert kanit is not None
    assert 12 <= len(kanit) <= 220


def test_kanit_metinden_birebir_alinir() -> None:
    """⚠️ Kanıt yeniden yazılmaz; metnin dilimi olmalı (§4.5)."""
    kanit = kanit_bul("min_spend_try", "5000", METIN)

    assert kanit is not None
    assert kanit in METIN


class TestSayiSiniri:
    """⚠️ Sayı sınırı, ondalık ayracı ile NOKTALAMA'yı ayırt etmeli."""

    def test_ardindan_virgul_gelen_oran_bulunur(self) -> None:
        r"""Metin: "işlemlerinizde %10, toplam 500 TL ...".

        Önceki kalıp `(?![\d.,])` idi ve buradaki virgülü ondalık ayracı
        sanıp satırı reddediyordu. Ölçüldü: 5 `cashback_pct` etiketi bu
        yüzden kanıtsız kalmıştı.
        """
        metin = "Bilet alma işlemlerinizde %10, toplam 500 TL Bankkart Lira kazanın."

        kanit = kanit_bul("cashback_pct", "10", metin)

        assert kanit is not None
        assert "%10" in kanit

    def test_ardindan_nokta_gelen_tutar_bulunur(self) -> None:
        metin = "Kampanya kapsamında en az 5.000 TL harcamalısınız."

        assert kanit_bul("min_spend_try", "5000", metin) is not None

    def test_ondalik_ayraci_hala_reddedilir(self) -> None:
        """⚠️ "10,5" içindeki "10" hâlâ eşleşmemeli."""
        assert kanit_bul("cashback_pct", "10", "Oran %10,5 olarak uygulanır.") is None

    def test_buyuk_sayinin_parcasi_hala_reddedilir(self) -> None:
        assert kanit_bul("min_spend_try", "500", "Tutar 10.500 TL üzerindedir.") is None


class TestSadakatMarkalari:
    """⚠️ Bankalar "puan" demez, MARKA ADI kullanır."""

    @pytest.mark.parametrize(
        "metin",
        [
            "Seyahat Alışverişlerinize 3.500 TL'ye varan ParafPara!",
            "Harcamanıza 3.500 TL Bankkart Lira hediye!",
            "Kampanyada 3.500 WorldPuan kazanın!",
        ],
    )
    def test_marka_adi_baglam_sayilir(self, metin: str) -> None:
        assert kanit_bul("loyalty_points", "3500", metin) is not None

    def test_baglamsiz_sayi_hala_reddedilir(self) -> None:
        assert kanit_bul("loyalty_points", "3500", "Kampanyaya 3.500 kişi katıldı.") is None


class TestTarihYazimlari:
    """⚠️ Bankalar başındaki sıfırı atıyor."""

    @pytest.mark.parametrize(
        ("metin", "deger"),
        [
            ("Kampanya Tarihleri 13.08.2024 - 1.01.2027 arasındadır.", "2027-01-01"),
            ("Kampanya 9 Haziran 2026 tarihinde başlar.", "2026-06-09"),
            ("Dönem 01.09.2026 - 30.09.2026", "2026-09-01"),
            ("Bitiş 8-06-2026 tarihidir.", "2026-06-08"),
        ],
    )
    def test_sifirsiz_ve_sifirli_bicimler_bulunur(self, metin: str, deger: str) -> None:
        assert kanit_bul("start_date", deger, metin) is not None

    def test_aralikta_yilsiz_baslangic_bulunur(self) -> None:
        """⚠️ Yıl YALNIZCA ikinci tarihte yazılıyor.

        "Kampanya, 17 Ağustos - 17 Eylül 2026 tarihleri arasında" — başlangıç
        yılsız. Ölçüldü: 4 `start_date` etiketi bu yüzden kanıtsız kalmıştı.
        """
        metin = "Kampanya, 17 Ağustos - 17 Eylül 2026 tarihleri arasında geçerlidir."

        kanit = kanit_bul("start_date", "2026-08-17", metin)

        assert kanit is not None
        assert "17 Ağustos" in kanit

    def test_yilli_bicim_yilsizdan_once_denenir(self) -> None:
        """Yıllı yazım varsa o seçilmeli; yılsız yalnızca son çaredir."""
        metin = "Dönem 01.09.2026 - 30.09.2026 arasındadır."

        kanit = kanit_bul("start_date", "2026-09-01", metin)

        assert kanit is not None
        assert "01.09.2026" in kanit


class TestBankaYazimlari:
    """Bankanın kendi ifade biçimleri kalıba girmeli."""

    def test_bolusum_orani_egik_cizgiyle_yazilir(self) -> None:
        """⚠️ "%2" değil "98/2 paylaşım oranlı" yazılıyor."""
        metin = "Albaraka Mobil'den 98/2 paylaşım oranlı Dijital Katılma hesabı açın."

        kanit = kanit_bul("profit_share_rate_pct", "2", metin)

        assert kanit is not None
        assert "98/2" in kanit

    def test_taksit_ifadesi_vade_sayilir(self) -> None:
        """⚠️ "6 taksite kadar" bir vadedir; banka "6 ay" demiyor."""
        metin = "100.000 TL'ye kadar alışverişlerinizde 6 taksite kadar imkân."

        kanit = kanit_bul("term_months_max", "6", metin)

        assert kanit is not None
        assert "taksit" in kanit
