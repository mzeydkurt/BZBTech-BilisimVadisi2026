"""Ortak dönem çözümünün kuralları ve ÖLÇÜLMÜŞ regresyonları.

Buradaki testlerin çoğu kurgusal değildir: her biri canlı arşivde (1170 dosya,
495 kampanya) ölçülmüş somut bir hatadan doğdu. Ölçüm yapılmadan yazılan katı
bir yakınlık kuralı 467 tarihli kampanyanın 197'sini kaybediyordu; bugünkü
kural o ölçümle şekillendi ve kayıp 9'a indi.

⚠️ Bu dosyadaki kuralları "sadeleştirmek" için değiştirmeyin. Her `_is_label`,
`_value_block_span_before`, `_is_pure_date_line` dalının arkasında gerçek bir
banka sayfası düzeni var.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.processing.dates import (
    PeriodResult,
    PeriodSource,
    donem_gecerli_mi,
    find_period_in_sources,
    parse_structured_period,
)


def _govdeden(text: str):  # type: ignore[no-untyped-def]
    """Metni yalnızca gövde kaynağı olarak çözer."""
    return find_period_in_sources(((PeriodSource.BODY, text),))


class TestEtiketDegerBlogu:
    """Etiket bir satırda, değer başka satırda — gerçek sayfaların düzeni."""

    def test_etiket_ve_deger_ayri_satirda_cozulur(self) -> None:
        """Ziraat: "Kampanya Dönemi" / "11-08-2026" / "-" / "31-08-2026"."""
        donem = _govdeden("Zen Pırlanta'da 3 Taksit\nKampanya Dönemi\n11-08-2026\n-\n31-08-2026")

        assert donem.start == date(2026, 8, 11)
        assert donem.end == date(2026, 8, 31)
        assert donem.precision == "exact"

    def test_tek_satirlik_aralik_etiketten_sonra_cozulur(self) -> None:
        """Kuveyt Türk: "Kampanya Tarihleri" / "21.06.2024 - 31.12.2027"."""
        donem = _govdeden("Sağlam Kart\nKampanya Tarihleri\n21.06.2024 - 31.12.2027")

        assert (donem.start, donem.end) == (date(2024, 6, 21), date(2027, 12, 31))

    def test_etiketle_deger_arasindaki_bos_satir_bagi_koparmaz(self) -> None:
        donem = _govdeden("Kampanya Dönemi\n\n11-08-2026 - 31-08-2026")

        assert donem.start == date(2026, 8, 11)

    def test_etiket_degeri_kosul_paragrafini_yutmaz(self) -> None:
        """Değer bloğu ilk tarih/ayraç olmayan satırda durur."""
        donem = _govdeden(
            "Kampanya Dönemi\n11-08-2026 - 31-08-2026\n"
            "Kampanya Koşulları:\nBankkart ile 5 Eylül 2026 tarihinde yapılan..."
        )

        assert donem.end == date(2026, 8, 31)

    def test_uzun_paragraf_etiket_sayilmaz(self) -> None:
        """⚠️ İşaretçi geçen uzun bir paragraf, sonraki tarihe işaretçi bağışlayamaz."""
        uzun = (
            "Kampanya dönemi boyunca yapılan harcamalarda geçerli olmak üzere "
            "aşağıdaki koşullar uygulanır ve bu koşullar değiştirilebilir."
        )
        donem = _govdeden(f"{uzun}\nÖdüller 9 Eylül 2026 hesaplara yansıtılacaktır.")

        assert donem.precision == "unknown"


class TestIsaretciArkada:
    """İşaretçi değerin ARDINDAN geliyor — Ziraat'in "sona ermiştir" bandı."""

    def test_sona_ermistir_bandi_bitis_verir(self) -> None:
        """ÖLÇÜLDÜ (#195): sayfada 09-02-2026 yazarken DB'de 31-08-2026 vardı."""
        donem = _govdeden(
            "Ayakkabı Dünyası'nda 4 Taksit\nKampanya\n09-02-2026\nTarihinde Sona Ermiştir."
        )

        assert donem.end == date(2026, 2, 9)
        assert donem.start is None
        assert donem.precision == "partial"

    def test_tam_aralik_bandin_onune_gecer(self) -> None:
        """⚠️ Bant yalnızca BİTİŞ taşır; koşul metnindeki tam aralık daha kesindir.

        Bant "tartışmasız" kabul edilirse 10 kampanyanın başlangıcı düşüyordu.
        """
        donem = _govdeden(
            "Kampanya\n30-06-2026\nTarihinde Sona Ermiştir.\n"
            "Kampanya, 8 Haziran 2026 saat 09.00 - 30 Haziran 2026 saat 23.59 "
            "arasında geçerlidir."
        )

        assert donem.start == date(2026, 6, 8)
        assert donem.end == date(2026, 6, 30)
        assert donem.precision == "exact"


class TestSaltTarihSatiri:
    """Etiketi görselde kalan tarih rozetleri."""

    def test_salt_aralik_satiri_kabul_edilir(self) -> None:
        """T.O.M.: dönem gövdenin başında yalın bir satır."""
        donem = _govdeden("05 Aralık - 15 Ocak 2025\nBilet.com'da %15 İndirim!")

        assert (donem.start, donem.end) == (date(2024, 12, 5), date(2025, 1, 15))

    def test_isaretcili_cumle_salt_satirin_onune_gecer(self) -> None:
        """ÖLÇÜLDÜ (#358): rozette 11 Şubat, cümlede 10 Şubat yazıyor.

        Açık dönem ifadesi taşıyan cümle daha güçlü bir iddiadır.
        """
        donem = _govdeden(
            "11 Şubat - 28 Şubat 2025\n"
            "Kampanya 10 Şubat-28 Şubat 2025 tarihleri arasında geçerlidir."
        )

        assert donem.start == date(2025, 2, 10)


class TestTuzaklar:
    """`dates.py` başlığında sayılan yanlış eşleşmeler hâlâ reddedilmeli."""

    @pytest.mark.parametrize(
        "metin",
        [
            "5 Ağustos 2023 tarihi itibarıyla Bankamız müşterisi olan kişiler katılabilir.",
            "* 15-08-2026 09:29:58 tarihli kur bilgileridir.",
            "1 Haziran Dünya Bankacılar Günü'ne Özel Avantajlar",
            "SAMSUNG boşluk TCKN boşluk Doğum Tarihi yazıp 3855'e gönderin.",
        ],
    )
    def test_donem_olmayan_tarih_alinmaz(self, metin: str) -> None:
        assert _govdeden(metin).precision == "unknown"

    def test_tekil_tarihinde_donem_bildirmez(self) -> None:
        """⚠️ ÇOĞUL "tarihlerinde" kabul edilir, TEKİL "tarihinde" edilmez."""
        assert (
            _govdeden("Ödül 15 Ekim 2026 tarihinde hesaba yatırılacaktır.").precision == "unknown"
        )

    def test_cogul_tarihlerinde_donem_bildirir(self) -> None:
        donem = _govdeden("1-31 Ağustos 2026 tarihlerinde yapılan alışverişlerde geçerlidir.")

        assert donem.end == date(2026, 8, 31)


class TestYapisalAlan:
    """DOM'da etiketli alan — işaretçi aranmaz ama içerik denetlenir."""

    def test_yapisal_alanda_isaretci_aranmaz(self) -> None:
        donem = parse_structured_period("02 Ocak 2026 - 31 Aralık 2026")

        assert donem.start == date(2026, 1, 2)
        assert donem.source is PeriodSource.STRUCTURED

    def test_alan_sonraki_bolumu_yutmussa_bas_blok_alinir(self) -> None:
        """ÖLÇÜLDÜ: Vakıf'ta alan koşul bölümünü de içine alıyordu."""
        donem = parse_structured_period(
            "02 Ocak 2026 - 31 Aralık 2026\n\nKampanya Koşulları\n\n"
            "Kampanyaya yalnızca bireysel müşterilerimiz katılabilir. "
            "Altı kriterin tamamlanması gerekmektedir. "
            "Ödüller kampanya bitiminden sonra 10 iş günü içinde tanımlanır."
        )

        assert (donem.start, donem.end) == (date(2026, 1, 2), date(2026, 12, 31))

    def test_menu_metnini_yakalayan_alan_yapisal_sayilmaz(self) -> None:
        """ÖLÇÜLDÜ (Albaraka #290): "yapısal alan" sanılan şey menüydü.

        Kayıt `2020-01-01` başlangıcını `exact` güveniyle taşıyordu.
        """
        menu = (
            "Albaraka Mobil Mobil Bankacılık Aç Bireysel Kurumsal Yatırım "
            "Albaraka'da Masraflara Son! Hemen Başvur Şubelerimiz İletişim "
            "Albaraka Portal Kampanyalar Ürünler Hakkımızda Kariyer"
        )
        donem = parse_structured_period(f"{menu} 01.01.2020 - 31.12.2026")

        assert donem.precision == "unknown"


class TestKaynakSirasi:
    """Kaynak sırası bir güven sıralamasıdır ve tek başına bir penceredir."""

    def test_kosullarda_bulunursa_govdeye_inilmez(self) -> None:
        donem = find_period_in_sources(
            (
                (PeriodSource.CONDITIONS, "Kampanya 1-31 Ağustos 2026 tarihlerinde geçerlidir."),
                (PeriodSource.BODY, "Kampanya Dönemi\n01-01-2020 - 31-12-2020"),
            )
        )

        assert donem.end == date(2026, 8, 31)
        assert donem.source is PeriodSource.CONDITIONS

    def test_hicbiri_tutmazsa_tarih_uydurulmaz(self) -> None:
        donem = find_period_in_sources(
            ((PeriodSource.CONDITIONS, "Detaylı bilgi için şubelerimize başvurun."),)
        )

        assert (donem.start, donem.end, donem.precision) == (None, None, "unknown")


class TestKanitsizExactYasagi:
    """`exact` iddiası kanıt metni olmadan geçersizdir."""

    def test_bulgu_daima_kanit_tasir(self) -> None:
        donem = _govdeden(
            "Kampanya 1 Ağustos 2026 - 31 Ağustos 2026 tarihleri arasında geçerlidir."
        )

        assert donem.precision == "exact"
        assert donem.evidence_text
        assert "31" in donem.evidence_text

    def test_kanit_kaynaktan_birebir_dilimlenebilir(self) -> None:
        """KAPI A4 ofset doğrulaması: `metin[bas:son] == evidence_text`."""
        metin = "Başlık\nKampanya Dönemi\n11-08-2026 - 31-08-2026\nKoşullar:"
        donem = _govdeden(metin)

        assert metin[donem.evidence_start : donem.evidence_end] == donem.evidence_text


class TestDonemDenetimi:
    """`min_campaign_year` eşiği ve mantık denetimleri."""

    BUGUN = date(2026, 8, 17)

    def test_esikten_once_bitmis_kampanya_reddedilir(self) -> None:
        """Bankanın kaldırmayı unuttuğu bayat kayıt."""
        donem = _govdeden("Kampanya 01.06.2024 - 31.12.2024 tarihleri arasında geçerlidir.")
        kabul, neden = donem_gecerli_mi(donem, min_yil=2025, bugun=self.BUGUN)

        assert (kabul, neden) == (False, "bitis_esigi_alti")

    def test_erken_baslayip_devam_eden_kampanya_korunur(self) -> None:
        """⚠️ Kuveyt Türk #299: 2024-06-21 → 2027-12-31, bugün CANLI.

        Eşik başlangıca uygulansaydı bu kayıt silinirdi. "Eski tarihte
        başlamış" olmak bayatlık göstergesi değildir.
        """
        donem = _govdeden("Kampanya 21.06.2024 - 31.12.2027 tarihleri arasında geçerlidir.")

        assert donem_gecerli_mi(donem, min_yil=2025, bugun=self.BUGUN) == (True, None)

    def test_bitissiz_ve_eski_baslangic_reddedilir(self) -> None:
        """Bitişi hiç bilinmiyorsa ölçüt başlangıç olur."""
        donem = PeriodResult(
            date(2023, 3, 1), None, "partial", evidence_text="01.03.2023", source=PeriodSource.BODY
        )
        kabul, neden = donem_gecerli_mi(donem, min_yil=2025, bugun=self.BUGUN)

        assert (kabul, neden) == (False, "yil_esigi_alti")

    def test_gecerli_donem_kabul_edilir(self) -> None:
        donem = _govdeden("Kampanya 01.08.2026 - 31.12.2026 tarihleri arasında geçerlidir.")

        assert donem_gecerli_mi(donem, min_yil=2025, bugun=self.BUGUN) == (True, None)

    def test_asiri_gelecek_tarih_reddedilir(self) -> None:
        donem = _govdeden("Kampanya 01.08.2026 - 31.12.2099 tarihleri arasında geçerlidir.")
        kabul, neden = donem_gecerli_mi(donem, min_yil=2025, bugun=self.BUGUN)

        assert (kabul, neden) == (False, "gelecek_asiri")

    def test_tarihsiz_kampanya_reddedilmez(self) -> None:
        """⚠️ "Tarih yok" bir kusur değildir; kampanya veri setinde KALIR."""
        donem = _govdeden("Detaylı bilgi için şubelerimize başvurabilirsiniz.")

        assert donem_gecerli_mi(donem, min_yil=2025, bugun=self.BUGUN) == (True, None)
