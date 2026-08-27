"""Paraf değişmezliği — regresyon kapısı (E2).

⚠️ BU DOSYA HEM ÖLÇÜM HEM KORUMA. `scripts/paraphrase_invariance.py` raporu
üretir, buradaki testler o raporun bir daha kötüleşmemesini garanti eder.
Kalıp dosyasında yapılan her daraltma bu testlerden birini kırar.

⚠️ SAYI SABİTİ (`ASGARI_DEGISMEZLIK`) BİLEREK YÜKSEK. Eşiği "şu an neyse o"
yerine biraz altına koymak, sessiz gerilemeye izin verir: iki varyant
kaybedilir, test yeşil kalır. Eşik mevcut değere EŞİT tutulur ve bilinçli bir
karar olmadan düşürülemez.
"""

from __future__ import annotations

import pytest

from scripts.paraphrase_invariance import (
    GrupSonucu,
    _alan_gruplari,
    _etiket_gruplari,
    _ozet,
)

# Ölçülen değer: 86/87. Eşik buna EŞİT — gerileme testi kırar.
ASGARI_DEGISMEZLIK: float = 86 / 87


@pytest.fixture(scope="module")
def alan_gruplari() -> list[GrupSonucu]:
    """Alan çıkarımı değişmezlik ölçümü (bir kez koşar)."""
    return _alan_gruplari()


@pytest.fixture(scope="module")
def etiket_gruplari() -> list[GrupSonucu]:
    """Sınıflandırma değişmezlik ölçümü (bir kez koşar)."""
    return _etiket_gruplari()


class TestKumeSagligi:
    """Küme kendisi bozulmuş olmasın."""

    def test_alan_kumesi_bos_degil(self, alan_gruplari: list[GrupSonucu]) -> None:
        """En az 12 olgu ve 60 varyant olmalı (şartname örnek yoğunluğu)."""
        toplam, _, _, _ = _ozet(alan_gruplari)
        assert len(alan_gruplari) >= 12
        assert toplam >= 60

    def test_her_grupta_en_az_iki_yazim(self, alan_gruplari: list[GrupSonucu]) -> None:
        """⚠️ Tek yazımlı bir grup DEĞİŞMEZLİK ÖLÇMEZ; küme hatasıdır."""
        tekil = [g.grup for g in alan_gruplari if g.toplam < 2]
        assert not tekil, f"Tek yazımlı grup(lar): {tekil}"

    def test_etiket_kumesi_dort_ekseni_de_kapsar(self, etiket_gruplari: list[GrupSonucu]) -> None:
        """Sınıflandırma ekseni tek eksenden ölçülemez."""
        eksenler = {g.hedef for g in etiket_gruplari}
        assert {"audience", "product_type", "sector"} <= eksenler


class TestSurprizYok:
    """Gerekçesi yazılmamış başarısızlık kalmamalı."""

    def test_alan_cikariminda_surpriz_yok(self, alan_gruplari: list[GrupSonucu]) -> None:
        """⚠️ Sürpriz hata = kümede bekleneni yazdığımız ama çözülmeyen yazım.

        Yeni bir kalıp daraltması buraya düşer. Kabul edilebilir tek durum,
        boşluğun `beklenen_basarisiz` alanına GEREKÇESİYLE yazılmasıdır —
        sessizce yaşamasına izin verilmez.
        """
        hatalar = [
            (g.grup, v.metin, v.uretilen)
            for g in alan_gruplari
            for v in g.varyantlar
            if not v.dogru and not v.beklenen_basarisiz
        ]
        assert not hatalar, f"Gerekçesiz başarısızlık: {hatalar}"

    def test_siniflandirmada_surpriz_yok(self, etiket_gruplari: list[GrupSonucu]) -> None:
        """Aynı kural sınıflandırma ekseni için de geçerli."""
        hatalar = [
            (g.grup, v.metin, v.uretilen)
            for g in etiket_gruplari
            for v in g.varyantlar
            if not v.dogru and not v.beklenen_basarisiz
        ]
        assert not hatalar, f"Gerekçesiz başarısızlık: {hatalar}"


class TestDegismezlikEsigi:
    """Toplam oran gerilemesin."""

    def test_toplam_oran_esigin_altina_dusmez(
        self, alan_gruplari: list[GrupSonucu], etiket_gruplari: list[GrupSonucu]
    ) -> None:
        """Küme büyütülürse eşik de güncellenmeli; düşürmek karar gerektirir."""
        toplam, cozulen, _, _ = _ozet([*alan_gruplari, *etiket_gruplari])
        oran = cozulen / toplam
        assert oran >= ASGARI_DEGISMEZLIK, (
            f"Değişmezlik {oran:.4f} < eşik {ASGARI_DEGISMEZLIK:.4f} ({cozulen}/{toplam})"
        )

    def test_sartname_ornek_biciminin_tamami_cozulur(self, alan_gruplari: list[GrupSonucu]) -> None:
        """⚠️ §5.6 ÖRNEĞİ PAZARLIK KONUSU DEĞİL.

        Şartname "%2,05, % 2.05 ve 2.05 % aynı değer olarak yorumlanmalıdır"
        diyor ve bunu ADIYLA örnekliyor. Bu grupta tek bir kayıp bile
        doğrudan bir şartname maddesinin karşılanmadığı anlamına gelir.
        """
        grup = next(g for g in alan_gruplari if g.grup == "oran-2.05")
        kayip = [v.metin for v in grup.varyantlar if not v.dogru]
        assert not kayip, f"§5.6 örneğinde çözülmeyen yazım: {kayip}"

    def test_para_birimi_esdegerligi_tam(self, alan_gruplari: list[GrupSonucu]) -> None:
        """§5.6: "500 TL, 500₺ ve 500 Türk Lirası aynı değer"."""
        grup = next(g for g in alan_gruplari if g.grup == "odul-500")
        kayip = [v.metin for v in grup.varyantlar if not v.dogru]
        assert not kayip, f"Para birimi eşdeğerliğinde kayıp: {kayip}"
