"""Kural tabanlı sınıflandırma testleri.

Sınıflandırma DETERMİNİSTİKTİR: aynı girdi daima aynı etiketleri üretir.
Yapay zekâ çıkarımı bu sprintte kullanılmaz.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.taxonomy import AXIS_VALUES, BANK_CATEGORY_SECTOR, MERCHANT_SECTOR, is_valid
from app.processing.categorizer import CategoryLabel, categorize, infer_segment


def _etiket(etiketler: list[CategoryLabel], axis: str) -> set[str]:
    return {e.value for e in etiketler if e.axis == axis}


def _ilk(etiketler: list[CategoryLabel], axis: str, value: str) -> CategoryLabel:
    return next(e for e in etiketler if e.axis == axis and e.value == value)


class TestSozlukTutarliligi:
    """Sözlükler şemadaki kontrollü listelerle uyumlu mu?"""

    def test_banka_kategorileri_gecerli_sektore_esleniyor(self) -> None:
        for etiket, sektor in BANK_CATEGORY_SECTOR.items():
            assert is_valid("sector", sektor), f"{etiket} -> {sektor}"

    def test_marka_sozlugu_gecerli_sektore_esleniyor(self) -> None:
        for marka, sektor in MERCHANT_SECTOR.items():
            assert is_valid("sector", sektor), f"{marka} -> {sektor}"

    def test_dort_eksen_tanimli(self) -> None:
        assert set(AXIS_VALUES) == {"product_type", "sector", "audience", "benefit"}

    def test_eksen_degerleri_tekil(self) -> None:
        for eksen, degerler in AXIS_VALUES.items():
            assert len(degerler) == len(set(degerler)), eksen


class TestKanitOnceligi:
    """Güçlü kanıt zayıfını bastırır."""

    def test_banka_kategorisi_tam_guven_alir(self) -> None:
        etiketler = categorize(
            title="Zen Pırlanta'da 3 Taksit",
            bank_category="Kuyum, Optik ve Saat",
            source_url="https://ornek.com.tr/k/zen",
        )
        etiket = _ilk(etiketler, "sector", "kuyum_optik_saat")
        assert etiket.source == "bank_category"
        assert etiket.confidence == Decimal("1.000")

    def test_adres_yolundan_urun_turu_okunur(self) -> None:
        """✅ Kuveyt Türk'te kategori adres yolunda duruyor."""
        etiketler = categorize(
            title="Barçın Spor'da 4 Taksit",
            source_url=(
                "https://www.kuveytturk.com.tr/kampanyalar/kendim-icin/"
                "kart-kampanyalari/barcin-sporda-4-taksit"
            ),
        )
        etiket = _ilk(etiketler, "product_type", "kart")
        assert etiket.source == "url"
        assert etiket.confidence == Decimal("1.000")

    def test_marka_eslesmesi_anahtar_kelimeden_guclu(self) -> None:
        etiketler = categorize(title="Trendyol'da 500 TL İndirim")
        etiket = _ilk(etiketler, "sector", "eticaret_pazaryeri")
        assert etiket.source == "merchant"
        assert etiket.confidence == Decimal("0.900")

    def test_ayni_etiket_icin_en_guclu_kanit_tutulur(self) -> None:
        """Banka kategorisi ile anahtar kelime aynı sektöre işaret edebilir."""
        etiketler = categorize(
            title="Market ve Gıda Alışverişinde İndirim",
            bank_category="Market ve Gıda",
        )
        market = [e for e in etiketler if e.axis == "sector" and e.value == "market_gida"]
        assert len(market) == 1
        assert market[0].source == "bank_category"

    def test_belirsiz_marka_guveni_dusuk(self) -> None:
        """⚠️ "apple" gibi kısa adlar sıradan metinde de geçebilir."""
        etiketler = categorize(title="Apple Ürünlerinde 6 Taksit")
        etiket = _ilk(etiketler, "sector", "elektronik_telekom")
        assert etiket.confidence < Decimal("0.900")


class TestKelimeSiniri:
    """⚠️ Ham `in` araması yanlış eşleşme üretiyor."""

    def test_marka_adi_kelime_ortasinda_eslesmez(self) -> None:
        etiketler = categorize(title="Kazangain Bonus Kampanyası")
        assert "eglence_dijital" not in _etiket(etiketler, "sector")

    def test_turkce_ek_eslesmeyi_bozmaz(self) -> None:
        """ "Trendyol'da" ifadesi de eşleşmeli."""
        etiketler = categorize(title="Trendyol'da Kaçırılmayacak Fırsat")
        assert "eticaret_pazaryeri" in _etiket(etiketler, "sector")


class TestCokEtiketlilik:
    """Aynı eksende birden fazla etiket serbesttir."""

    def test_fayda_ekseninde_birden_fazla_etiket(self) -> None:
        etiketler = categorize(
            title="Peşin Fiyatına 6 Taksit",
            description="Ayrıca 500 TL nakit iade kazanın.",
        )
        faydalar = _etiket(etiketler, "benefit")
        assert {"taksit", "vade_farksiz_taksit", "nakit_iade"} <= faydalar

    def test_hedef_kitle_kosul_metninden_de_okunur(self) -> None:
        etiketler = categorize(
            title="Finansman Kampanyası",
            conditions_text="Kampanya yalnızca emekli müşterilerimiz için geçerlidir.",
        )
        assert "emekli" in _etiket(etiketler, "audience")


class TestUydurmaEtiketYok:
    """Kaynak yoksa etiket yazılmaz."""

    def test_sinyal_yoksa_yalnizca_genel_sektor(self) -> None:
        etiketler = categorize(title="Tanımsız Duyuru", description="Kısa metin.")
        assert _etiket(etiketler, "sector") == {"genel"}
        assert _ilk(etiketler, "sector", "genel").confidence == Decimal("0.300")

    def test_genel_etiketi_dusuk_guvenle_isaretlenir(self) -> None:
        """Düşük güven, sonraki sprintte hangi kayıtların ele alınacağını gösterir."""
        etiketler = categorize(title="Bilinmeyen")
        assert _ilk(etiketler, "sector", "genel").confidence < Decimal("0.500")

    def test_her_kampanyada_en_az_bir_sektor(self) -> None:
        for baslik in ("Bir", "Konut Finansmanı", "Trendyol İndirimi", ""):
            etiketler = categorize(title=baslik)
            assert any(e.axis == "sector" for e in etiketler), baslik

    def test_uretilen_tum_etiketler_kontrollu_sozlukten(self) -> None:
        etiketler = categorize(
            title="Trendyol'da Konut Finansmanına Özel Nakit İade",
            description="Yeni müşterilerimize peşin fiyatına taksit.",
            conditions_text="Emekli ve esnaf müşterilerimiz için geçerlidir.",
            source_url="https://www.kuveytturk.com.tr/kampanyalar/kendim-icin/kart-kampanyalari/x",
        )
        assert etiketler
        for e in etiketler:
            assert is_valid(e.axis, e.value), f"{e.axis}={e.value}"


class TestDeterminizm:
    """Aynı girdi daima aynı çıktıyı verir."""

    @pytest.mark.parametrize("tekrar", range(3))
    def test_ayni_girdi_ayni_sonuc(self, tekrar: int) -> None:
        girdi = {
            "title": "A101'de Süt Ürünlerinde %50 Hediye Bakiye",
            "description": "Bankkart lira kazanın.",
            "source_url": "https://ornek.com.tr/k/a101",
        }
        assert categorize(**girdi) == categorize(**girdi)

    def test_etiketler_kararli_siralanir(self) -> None:
        etiketler = categorize(title="Trendyol'da Taksit", description="Nakit iade.")
        eksenler = [e.axis for e in etiketler]
        assert eksenler == sorted(eksenler)


class TestKanitMetni:
    """Her etikette gerekçe bulunur."""

    def test_kanit_alani_doldurulur(self) -> None:
        etiketler = categorize(title="Trendyol'da 500 TL İndirim")
        etiket = _ilk(etiketler, "sector", "eticaret_pazaryeri")
        assert etiket.evidence
        assert "Trendyol" in etiket.evidence

    def test_kanit_metni_kirpilir(self) -> None:
        uzun = "Trendyol " + ("çok uzun bir açıklama metni " * 40)
        etiketler = categorize(title="Kampanya", description=uzun)
        for e in etiketler:
            assert e.evidence is None or len(e.evidence) <= 160


class TestHayatFinansSinyalleri:
    """Hayat Finans kampanyalarındaki marka/ürün sinyalleri."""

    def test_xiaomi_elektronik_sektor(self) -> None:
        etiketler = categorize(title="Xiaomi Ürünlerinde Finansman Avantajı")
        assert "elektronik_telekom" in _etiket(etiketler, "sector")

    def test_gastroclub_restoran_sektor(self) -> None:
        etiketler = categorize(title="Hayat Finans ile GastroClub Ayrıcalıkları")
        assert "restoran_kafe" in _etiket(etiketler, "sector")

    def test_fx_yatirim_sektor(self) -> None:
        etiketler = categorize(
            title="Avantajlı Hesap Müşterilerine Özel FX Dar Makas Avantajı!"
        )
        assert "yatirim_birikim" in _etiket(etiketler, "sector")
        assert "birikim_katilma_hesabi" in _etiket(etiketler, "product_type")

    def test_bana_bunu_al_finansman(self) -> None:
        etiketler = categorize(
            title="Bana Bunu Al İş Ortağım ile Troy Mağazalarında Finansman Fırsatı!"
        )
        assert "alisveris_finansmani" in _etiket(etiketler, "product_type") or "finansman" in _etiket(
            etiketler, "product_type"
        )


class TestKurumsalKobiSektor:
    """sector=kurumsal_kobi yalnızca gerçek B2B / üye işyeri sinyaliyle."""

    def test_paraf_pos_bireysel_taksit_degil(self) -> None:
        """Mağazada 'Paraf POS' = kart terminali; KOBİ sektörü değil."""
        etiketler = categorize(
            title="Paraf ile Koçtaş'ta 5 Taksit Fırsatı!",
            description=(
                "Dünya Katılım Paraf ile Koçtaş'ta Paraf POS'undan "
                "yapacağınız alışverişlerinize 5 taksit fırsatı sunulur."
            ),
        )
        assert "kurumsal_kobi" not in _etiket(etiketler, "sector")

    def test_poset_cay_yanlis_onek_degil(self) -> None:
        """'pos' → 'poşet' önek eşleşmesi olmamalı."""
        etiketler = categorize(
            title="2026'da Hadi Black Kredi Kartı ile evinin çayı bedava!",
            description="Lipton Yellow Label 48'li Demlik Poşet Çayı bizden!",
        )
        assert "kurumsal_kobi" not in _etiket(etiketler, "sector")

    def test_sanal_pos_kampanyasi_kurumsal(self) -> None:
        etiketler = categorize(
            title="Kuveyt Türk'ten Sanal POS Kampanyası",
            description="İşletmenizin finansal ihtiyaçlarına uygun esnek çözüm.",
        )
        assert "kurumsal_kobi" in _etiket(etiketler, "sector")

    def test_uye_sanal_pos_bireysel_taksit_degil(self) -> None:
        """'Paraf üyesi X sanal Pos'u' = mağaza terminali, KOBİ değil."""
        etiketler = categorize(
            title="Vaillant'ta 9 Aya Varan Taksit Fırsatı!",
            description=(
                "Paraf ile Paraf üyesi Vaillant sanal Pos'u üzerinden "
                "gerçekleşen işlemlere vade farksız 9 aya varan taksit."
            ),
        )
        assert "kurumsal_kobi" not in _etiket(etiketler, "sector")

    def test_kobilere_ozel_kurumsal(self) -> None:
        etiketler = categorize(
            title="Mobil'den Müşteri Olan KOBİ'lerimize Avantaj Paketi",
            description="Hesabınızı şubeye gitmeden Mobil'de açın.",
        )
        assert "kurumsal_kobi" in _etiket(etiketler, "sector")
        assert "kobi" in _etiket(etiketler, "audience")

    def test_nav_kobi_metni_audience_degil(self) -> None:
        """Gezinti menüsündeki çıplak 'KOBİ' hedef kitle sayılmamalı."""
        etiketler = categorize(
            title="Yoyo'da %40 GastroClub İndirim!",
            description="Restoranlarda indirim.",
            body_text="Trend Bankacılık\nEflatun Bankacılık\nKOBİ\nFinansmanlar\nKobi Nakdi Finansman",
        )
        assert "kobi" not in _etiket(etiketler, "audience")


class TestSegmentCikarimi:
    """Campaign.segment — audience ekseni değil."""

    def test_url_kendim_icin_bireysel(self) -> None:
        sonuc = infer_segment(
            title="Kart Kampanyası",
            source_url="https://www.kuveytturk.com.tr/kampanyalar/kendim-icin/kart-kampanyalari/x",
        )
        assert sonuc is not None
        assert sonuc.value == "bireysel"
        assert sonuc.source == "url"

    def test_url_isim_icin_kurumsal(self) -> None:
        sonuc = infer_segment(
            title="POS Kampanyası",
            source_url="https://www.vakifkatilim.com.tr/tr/isim-icin/kampanyalar/detay/x",
        )
        assert sonuc is not None
        assert sonuc.value == "kurumsal"

    def test_metinden_kobi(self) -> None:
        sonuc = infer_segment(title="KOBİ'lere Özel Finansman", description="Kobiler için fırsat.")
        assert sonuc is not None
        assert sonuc.value == "kobi"

    def test_sinyal_yoksa_none(self) -> None:
        assert infer_segment(title="Genel Duyuru", description="Kısa metin.") is None


class TestAltinyildizVeYanlisPozitifler:
    """Scraped kampanya başlıklarından ölçülen yanlış sınıflandırma yamaları."""

    def test_altinyildiz_giyim_degil_yatirim(self) -> None:
        """Markadaki 'Altın…' öneki çıplak altın anahtarına yapışmamalı."""
        etiketler = categorize(
            title="Altınyıldız Classics'te Vade Farksız 2 Taksit Fırsatı"
        )
        assert "giyim_aksesuar" in _etiket(etiketler, "sector")
        assert "yatirim_birikim" not in _etiket(etiketler, "sector")

    def test_altin_kazandiran_yatirim_kalir(self) -> None:
        etiketler = categorize(title="Altın Kazandıran Alışveriş Dünya Katılım'da !")
        assert "yatirim_birikim" in _etiket(etiketler, "sector")

    def test_ihtiyac_finansmani_fatura_metni_vergi_sektor_degil(self) -> None:
        etiketler = categorize(
            title="50.000 TL İhtiyaç Finansmanı Kampanyası",
            description="Fatura ödemelerinde kullanabilirsiniz.",
        )
        assert "ihtiyac_finansmani" in _etiket(etiketler, "product_type")
        assert "vergi_fatura_kamu" not in _etiket(etiketler, "sector")

    def test_paraf_pos_magaza_taksit_urun_pos_degil(self) -> None:
        """'Paraf POS üzerinden' bireysel taksit; üye-işyeri ürünü değil."""
        etiketler = categorize(
            title="A101 de Vade Farksız 6 Aya Varan Taksit Fırsatı!",
            description="Paraf POS üzerinden yapacağınız alışverişlere taksit.",
        )
        assert "market_gida" in _etiket(etiketler, "sector")
        assert "pos_uye_isyeri" not in _etiket(etiketler, "product_type")

    def test_poset_cay_urun_pos_degil(self) -> None:
        etiketler = categorize(
            title="2026'da Hadi Black Kredi Kartı ile evinin çayı bedava!",
            description="Lipton Yellow Label 48'li Demlik Poşet Çayı bizden!",
        )
        assert "kart" in _etiket(etiketler, "product_type")
        assert "pos_uye_isyeri" not in _etiket(etiketler, "product_type")

    def test_motosiklet_otomotiv_sektor(self) -> None:
        etiketler = categorize(title="3 Ay Ertelemeli Motosiklet Kampanyası")
        assert "otomotiv" in _etiket(etiketler, "sector")
        assert "tasit_finansmani" in _etiket(etiketler, "product_type")

    def test_giyim_markalari_merchant(self) -> None:
        for baslik in (
            "İpekyol'da 4 Taksit Fırsatı!",
            "Network'te 4 Taksit Fırsatı!",
            "VAKKO'da 4 Taksit Fırsatı!",
            "Mavi'de 4 Taksit",
            "DKart Debit'le Jack & Jones'da Harcadıkça Kazanın!",
            "DKart Debit'le Koton'da Harcadıkça Kazanın!",
        ):
            etiketler = categorize(title=baslik)
            assert "giyim_aksesuar" in _etiket(etiketler, "sector"), baslik

    def test_hadi_birikim_segmenti_restoran_yatirim_degil(self) -> None:
        etiketler = categorize(
            title="Restoran harcamalarında her ay 10.000 TL'ye varan iade!",
            description=(
                "Özel Bankacılık Hadi birikim segmentine göre restoranlarda "
                "%22.5'e varan iade."
            ),
        )
        assert "restoran_kafe" in _etiket(etiketler, "sector")
        assert "yatirim_birikim" not in _etiket(etiketler, "sector")

    def test_harcamaniza_indirim_kart_urunu(self) -> None:
        etiketler = categorize(
            title="Albaraka Otopark ve Vale Harcamanıza %50 İndirim Kazandırıyor!"
        )
        assert "kart" in _etiket(etiketler, "product_type")
        assert "ulasim_arac_kiralama" in _etiket(etiketler, "sector")

    def test_eyt_finansmani_urun(self) -> None:
        etiketler = categorize(title="EYT Finansmanı")
        assert "finansman" in _etiket(etiketler, "product_type")

    def test_marka_indirim_kart_urunu(self) -> None:
        etiketler = categorize(title="Macrocenter.com.tr'de %10 İndirim!")
        assert "market_gida" in _etiket(etiketler, "sector")
        assert "kart" in _etiket(etiketler, "product_type")

    def test_masraflara_son_dijital(self) -> None:
        etiketler = categorize(title="Albaraka'da Masraflara Son!")
        assert "dijital_bankacilik" in _etiket(etiketler, "product_type")
