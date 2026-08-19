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
