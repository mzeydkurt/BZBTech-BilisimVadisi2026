"""Yabancı kampanya bloğu ayıklamasının birim testleri (Şartname 5.8).

Buradaki senaryoların TAMAMI canlı veriden alınmıştır; hiçbiri kurgusal
değildir. Her biri, kural gevşetilirse geri dönecek ve HATA FIRLATMADAN
yanlış veri üretecek bir durumu kilitler:

  - Koşul cümlesinin bölüm başlığı sanılması (83 Ziraat kaydı)
  - Üst menüdeki "Diğer Kampanyalar"dan kesip kampanyayı yok etmek
  - Başlıksız kampanya kartlarının hiç fark edilmemesi (209 Ziraat kaydı)
  - Kampanyanın başlıktan ÖNCE yazılmış tarihini silmek (3 T.O.M. kaydı)
  - Soru işaretiyle biten menü bağlantısında gezinme bloğunu erken kesmek
    (Kuveyt Türk'te 21 satır sonra duruyordu, menünün 158 satırı kalıyordu)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.processing.boilerplate import (
    MIN_KEEP_CHARS,
    strip_boilerplate_sections,
    strip_chrome_lines,
    strip_leading_navigation,
    strip_related_sections,
)
from app.processing.cleaner import clean_html

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "html"


# Ziraat Katılım #79 (`zen-pirlantada-3-taksit`) — kısaltılmış ama yapısı birebir.
# Üstte sol filtre menüsü, ortada kampanya, altta BAŞLIKSIZ kart ızgarası.
ZIRAAT_METIN = """Zen Pırlanta'da 3 Taksit
Tüm Kampanyalar
7
Kuyum, Optik ve Saat
16
Diğer Kampanyalar
17
Giyim ve Aksesuar
Zen Pırlanta'da 3 Taksit
Kampanya Dönemi
11-08-2026
-
31-08-2026
Kampanya Koşulları:
Ziraat Katılım Bankkart ile peşin fiyatına 3 taksit fırsatından faydalanabilirsiniz.
Ücretsiz ve ticari kredi kartlarımız kampanyaya dahil değildir.
Kampanya başka kampanyalarla birleştirilemez.
Bankamız kampanya koşullarını değiştirme ve kampanyayı durdurma hakkına sahiptir.
Kuyum, Optik ve Saat
Atasun Optik'te 6 Taksit
Son Gün 31.08.2026
Detaylar
Kuyum, Optik ve Saat
Optik Alışverişinize 500 TL Bankkart Lira!
Son Gün 07.09.2026
Detaylar"""

ZIRAAT_BASLIK = "Zen Pırlanta'da 3 Taksit"


class TestZiraatKartIzgarasi:
    """Başlıksız ilgili kampanya bloğu (canlı veri: 209 kayıt)."""

    @pytest.fixture
    def temiz(self) -> str:
        return strip_boilerplate_sections(
            ZIRAAT_METIN, bank_code="ziraat_katilim", title=ZIRAAT_BASLIK
        )

    def test_kampanyanin_kendi_tarihi_korunur(self, temiz: str) -> None:
        assert "11-08-2026" in temiz
        assert "31-08-2026" in temiz

    def test_komsu_kampanyanin_tarihi_atilir(self, temiz: str) -> None:
        # 07.09.2026 yalnızca alttaki kartta geçiyor; metne karışmamalı.
        assert "07.09.2026" not in temiz

    def test_komsu_kampanyanin_basligi_atilir(self, temiz: str) -> None:
        assert "Atasun" not in temiz
        assert "Bankkart Lira" not in temiz

    def test_kampanya_kosullari_tam_korunur(self, temiz: str) -> None:
        assert "peşin fiyatına 3 taksit fırsatından faydalanabilirsiniz" in temiz
        assert "Ücretsiz ve ticari kredi kartlarımız kampanyaya dahil değildir." in temiz
        assert "Bankamız kampanya koşullarını değiştirme" in temiz

    def test_sol_filtre_menusu_atilir(self, temiz: str) -> None:
        # Menüdeki kategori sayaçları ve kategori adları metinde kalmamalı.
        assert "Giyim ve Aksesuar" not in temiz
        assert not temiz.startswith("Tüm Kampanyalar")

    def test_baslik_korunur(self, temiz: str) -> None:
        assert temiz.startswith(ZIRAAT_BASLIK)


class TestKosulCumlesiBaslikSanilmaz:
    """TUZAK 1 — alt dize araması koşul metnini siliyordu (83 kayıt)."""

    @pytest.mark.parametrize(
        "cumle",
        [
            "Kampanya başka kampanyalarla birleştirilemez.",
            "Kampanya, başka kampanyalar ile birleşebilir, kuponlar ile birleşemez.",
            "Bu kampanya Hayat Finans'ın diğer kampanyaları ile birleştirilemez.",
            "Diğer kampanyalarla birleştirilemez.",
            "Türkiye Finans tüm kampanyalarda değişiklik yapma hakkını saklı tutar.",
        ],
    )
    def test_birlestirilemez_cumlesi_korunur(self, cumle: str) -> None:
        metin = (
            "Kampanya Koşulları:\n"
            "Kampanya 1 Ağustos - 31 Ağustos 2026 tarihleri arasında geçerlidir.\n"
            "Alışverişlerinizde 250 TL nakit iade kazanırsınız ve bu tutar hesabınıza yansıtılır.\n"
            f"{cumle}\n"
            "Bankamız kampanya koşullarını değiştirme hakkına sahiptir."
        )
        assert cumle in strip_related_sections(metin, "ziraat_katilim")


class TestBelirsizBaslikKonumaBagli:
    """TUZAK 2 — aynı ifade kimi bankada üst menü, kimisinde alt bölüm."""

    GOVDE = (
        "Kampanya Koşulları:\n"
        "Kampanya 1 Ağustos - 31 Ağustos 2026 tarihleri arasında geçerlidir.\n"
        "Alışverişlerinizde 250 TL nakit iade kazanırsınız ve bu tutar hesabınıza yansıtılır.\n"
        "Bankamız kampanya koşullarını değiştirme ve kampanyayı durdurma hakkına sahiptir."
    )

    def test_ustteki_menu_ogesi_kesim_yapmaz(self) -> None:
        metin = f"Diğer Kampanyalar\nKuyum ve Saat\n{self.GOVDE}"
        assert "250 TL nakit iade" in strip_related_sections(metin, "ziraat_katilim")

    def test_alttaki_bolum_basligi_keser(self) -> None:
        metin = f"{self.GOVDE}\nDiğer Kampanyalar\nBaşka Bir Kampanya\nSon Gün 07.09.2026"
        temiz = strip_related_sections(metin, "dunya_katilim")
        assert "Başka Bir Kampanya" not in temiz
        assert "250 TL nakit iade" in temiz

    def test_kesin_baslik_konumdan_bagimsiz_keser(self) -> None:
        metin = f"{self.GOVDE}\nİlginizi Çekebilir\nBaşka Bir Kampanya"
        assert "Başka Bir Kampanya" not in strip_related_sections(metin, "tom_bank")


class TestGezinmeBloguKesimi:
    """Başlık çıpasıyla baştaki menünün atılması."""

    def test_menu_bagintisi_soru_isaretiyle_bitebilir(self) -> None:
        """Kuveyt Türk: '?' ile biten menü ögesi bloğu erken kesmemeli."""
        metin = (
            "Ana Sayfa\n"
            "Harcama İtirazı (Chargeback) Nasıl Yapılır?\n"
            "Faizsiz Sigortacılık Nedir?\n"
            "Ayın Kampüslüsü'ne Özel Fırsatlar!\n"
            "Kartlar\n"
            "Sağlam Kart Kampanyası!\n"
            "Kuveyt Türk Mobil üzerinden hesap açan müşterilerimiz kampanyadan faydalanabilir.\n"
            "Kampanya 1 Ağustos - 31 Ağustos 2026 tarihleri arasında geçerlidir.\n"
            "Müşteriler bu kampanyadan yalnızca bir kez faydalanabilir.\n"
            "Kuveyt Türk, haber vermeden kampanya koşullarında değişiklik yapabilir."
        )
        temiz = strip_leading_navigation(metin, "Sağlam Kart Kampanyası!")
        assert temiz.startswith("Sağlam Kart Kampanyası!")
        assert "Chargeback" not in temiz
        assert "Ayın Kampüslüsü" not in temiz

    def test_baslik_oncesi_tarih_korunur(self) -> None:
        """T.O.M. Bank kampanyanın kendi tarihini başlıktan ÖNCE yazıyor."""
        metin = (
            "Hemen İndir\n"
            "Kampanya Tarihleri\n"
            "01 Mart - 16 Mart 2025\n"
            "A101 Ekstra'da Peşin Fiyatına 3 Taksit!\n"
            "Kampanya Detayları\n"
            "Kampanya kapsamında aynı marka telefondan sadece 2 tane alınabilir.\n"
            "Kampanya sadece A101 uygulamasından alınacak cep telefonlarında geçerlidir.\n"
            "T.O.M. Bank kampanyayı durdurma ve koşullarını değiştirme hakkını saklı tutar."
        )
        temiz = strip_leading_navigation(metin, "A101 Ekstra'da Peşin Fiyatına 3 Taksit!")
        assert "01 Mart - 16 Mart 2025" in temiz
        assert "Hemen İndir" not in temiz

    def test_icerik_ortasindaki_baslik_tekrari_cipa_olmaz(self) -> None:
        """Ziraat #183: başlık alttaki kartta da geçiyordu; oran kuralı
        yanlış çıpayı seçip kampanyanın tüm koşullarını siliyordu."""
        baslik = "E-Ticaret Alışverişlerinize 500 TL!"
        metin = (
            f"{baslik}\n"
            "Tüm Kampanyalar\n"
            "E-Ticaret\n"
            f"{baslik}\n"
            "Kampanya Koşulları:\n"
            "Kampanya 8 Nisan 2026 - 8 Mayıs 2026 tarihleri arasında geçerlidir.\n"
            "Bankkart Lira kazanabilmek için alışveriş yapmadan önce katılım sağlanmalıdır.\n"
            "E-Ticaret\n"
            f"{baslik}\n"
            "Son Gün 07.09.2026"
        )
        temiz = strip_leading_navigation(metin, baslik)
        assert "8 Nisan 2026 - 8 Mayıs 2026" in temiz
        assert "Bankkart Lira kazanabilmek için" in temiz

    def test_baslik_yoksa_metin_degismez(self) -> None:
        assert strip_leading_navigation(ZIRAAT_METIN, None) == ZIRAAT_METIN


class TestGuvenlikAgi:
    """Kesim gerçek içeriği silecekse UYGULANMAZ."""

    def test_kisa_metinde_kesim_reddedilir(self) -> None:
        metin = "Kısa Kampanya\nİlginizi Çekebilir\nBaşka Kampanya\nSon Gün 31.08.2026"
        # Kesim sonrası 'Kısa Kampanya' MIN_KEEP_CHARS'ın altında kalır.
        assert len("Kısa Kampanya") < MIN_KEEP_CHARS
        assert strip_related_sections(metin, "tom_bank") == metin

    def test_bos_metin_bos_doner(self) -> None:
        assert strip_boilerplate_sections("", bank_code="ziraat_katilim", title="X") == ""

    def test_tum_satirlar_gezinme_ise_cokmez(self) -> None:
        """404 gövdesinde her satır kısa olabiliyor; dizin taşması olmamalı."""
        metin = "Sayfa Bulunamadı\nAna Sayfa\nKampanyalar"
        assert strip_leading_navigation(metin, "Ana Sayfa") == metin
        assert strip_boilerplate_sections(metin, bank_code="hayat_finans", title="Sayfa Bulunamadı")

    def test_tek_satirlik_metin_cokmez(self) -> None:
        assert strip_leading_navigation("Tek Satır", "Tek Satır") == "Tek Satır"


class TestArayuzSatirlari:
    """Bilgi taşımayan düğme etiketleri atılır, veri satırları KALIR."""

    def test_dugme_etiketleri_atilir(self) -> None:
        metin = "Başlık\nPaylaş\nDetaylar\nHemen İndir\nKampanya 250 TL iade sunar."
        temiz = strip_chrome_lines(metin)
        assert "Paylaş" not in temiz
        assert "Detaylar" not in temiz
        assert "Kampanya 250 TL iade sunar." in temiz

    def test_veri_tasiyan_satir_korunur(self) -> None:
        metin = "Bitiş Tarihi: 31 Ağustos 2026\nPaylaş"
        assert "Bitiş Tarihi: 31 Ağustos 2026" in strip_chrome_lines(metin)


class TestBankaFixtureleri:
    """Kayıtlı HTML fixture'ları üzerinde uçtan uca davranış (ağa çıkmaz)."""

    def test_dunya_katilim_orani_spec_hedefini_karsilar(self) -> None:
        """Şartname §6.1: Dünya Katılım'da temiz/ham oranı < 0.60."""
        html = (FIXTURE_DIR / "dunya_katilim" / "kampanya_detay.html").read_bytes()
        metin = html.decode("utf-8", "replace")
        temiz = clean_html(metin, bank_code="dunya_katilim")
        assert temiz, "temiz metin boş olmamalı"
        assert len(temiz) / len(metin) < 0.60

    def test_ziraat_fixture_kart_bloklari_atilir(self) -> None:
        html = (FIXTURE_DIR / "ziraat_katilim" / "kampanya_donem.html").read_bytes()
        temiz = clean_html(html.decode("utf-8", "replace"), bank_code="ziraat_katilim")
        assert "Son Gün" not in temiz

    def test_banka_kodu_verilmezse_bolum_ayiklamasi_calismaz(self) -> None:
        """soft-404 denetimi bu davranışa bağlı; değiştirilmemeli."""
        html = (FIXTURE_DIR / "dunya_katilim" / "kampanya_detay.html").read_bytes()
        metin = html.decode("utf-8", "replace")
        assert len(clean_html(metin)) >= len(clean_html(metin, bank_code="dunya_katilim"))
