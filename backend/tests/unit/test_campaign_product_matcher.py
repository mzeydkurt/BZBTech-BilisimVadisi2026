"""Kampanya ↔ ürün eşleştirme testleri.

⚠️ Bu eşleştiricinin en büyük riski FAZLA CÖMERT olmasıdır. Her kampanyayı
bankanın her ürününe bağlarsa "bu kampanya hangi ürüne ait" sorusu anlamını
yitirir ve ürünün oran tablosu ilgisiz kampanyalara sızar. Testler bu yüzden
hem "doğru bağı kuruyor" hem "yanlış bağı REDDEDİYOR" tarafını ölçer.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.processing.campaign_product_matcher import UrunAdayi, esles

TASIT = UrunAdayi(
    product_id=1, name="Taşıt Finansmanı (Taşıt Kredisi)*", url_slug="tasit-finansmani"
)
KONUT = UrunAdayi(product_id=2, name="Konut Finansmanı", url_slug="konut-finansmani")
KART = UrunAdayi(product_id=3, name="Kart", url_slug="kart")


def _esles(baslik: str = "", metin: str = "", slug: str = "", url: str = "", adaylar=None):  # type: ignore[no-untyped-def]
    return esles(
        title=baslik,
        campaign_slug=slug,
        source_url=url,
        clean_text=metin,
        adaylar=adaylar if adaylar is not None else [TASIT, KONUT],
    )


class TestSinyalGucu:
    """En güçlü sinyal kaydedilir: title > slug > body."""

    def test_baslikta_gecen_urun_en_yuksek_guven(self) -> None:
        (bag,) = _esles(baslik="3 Ay Ertelemeli Taşıt Finansmanı", adaylar=[TASIT])

        assert bag.match_method == "title"
        assert bag.confidence == Decimal("0.900")

    def test_adreste_gecen_urun_orta_guven(self) -> None:
        (bag,) = _esles(
            baslik="Yeni Kampanya",
            url="https://ornek.com.tr/kampanya/tasit-finansmani-firsati",
            adaylar=[TASIT],
        )

        assert bag.match_method == "slug"
        assert bag.confidence == Decimal("0.850")

    def test_yalnizca_govdede_gecen_urun_dusuk_guven(self) -> None:
        """⚠️ Gövdede geçmek "kampanya bu ürüne ait" demek DEĞİLDİR.

        Ürün adı çoğu zaman geçerken anılır; bu yüzden güven düşük tutulur ve
        tüketen taraf eşiğe göre süzer.
        """
        (bag,) = _esles(
            baslik="Yeni Yıl Fırsatı",
            metin="Kampanya kapsamında Taşıt Finansmanı ürünümüz de geçerlidir.",
            adaylar=[TASIT],
        )

        assert bag.match_method == "body"
        assert bag.confidence == Decimal("0.600")

    def test_baslik_govdeye_tercih_edilir(self) -> None:
        """Aynı ürün hem başlıkta hem gövdede geçiyorsa bağ TEK olur."""
        baglar = _esles(
            baslik="Taşıt Finansmanı Kampanyası",
            metin="Taşıt Finansmanı ile ilgili detaylar aşağıdadır.",
            adaylar=[TASIT],
        )

        assert len(baglar) == 1
        assert baglar[0].match_method == "title"


class TestYanlisBagReddedilir:
    def test_kisa_urun_adi_eslesmez(self) -> None:
        """⚠️ "Kart" her metinde geçer; eşiksiz çalışırsa her kampanya bağlanır."""
        assert _esles(baslik="Kart ile alışverişe taksit", adaylar=[KART]) == []

    def test_adi_gecmeyen_urun_baglanmaz(self) -> None:
        """⚠️ Ürün TÜRÜNDEN bağ kurulmaz.

        Metinde "finansman" geçse bile ürünün ADI geçmiyorsa bağ yoktur;
        aksi hâlde ürünün oran tablosu ilgisiz kampanyaya sızar.
        """
        baglar = _esles(
            baslik="Avantajlı finansman fırsatı",
            metin="Bankamızın finansman ürünlerinden yararlanın.",
        )

        assert baglar == []

    def test_metnin_sonundaki_menu_baglanmaz(self) -> None:
        """⚠️ Kampanya metninin sonu banka geneli menü ve yasal uyarıdır.

        Orada geçen ürün adı o kampanyaya ait değildir; pencere sınırı bunu
        keser.
        """
        dolgu = "kampanya koşulları " * 300
        baglar = _esles(baslik="Market Kampanyası", metin=dolgu + "Taşıt Finansmanı")

        assert baglar == []

    def test_baska_bankanin_urunu_verilmez(self) -> None:
        """Aday listesi çağıran tarafından banka bazında süzülür."""
        assert _esles(baslik="Taşıt Finansmanı Kampanyası", adaylar=[]) == []


class TestUrunAdiCekirdegi:
    """Bankalar ürün adına parantezli açıklama ve yıldız ekliyor."""

    def test_parantezli_ek_yok_sayilir(self) -> None:
        """`"Taşıt Finansmanı (Taşıt Kredisi)*"` kampanya metninde böyle geçmez."""
        (bag,) = _esles(baslik="Ocak ayına özel Taşıt Finansmanı", adaylar=[TASIT])

        assert bag.product_id == TASIT.product_id


class TestCokluBag:
    def test_bir_kampanya_birden_cok_urune_baglanabilir(self) -> None:
        """Bir kampanya metni birden çok ürünü konu alabilir."""
        baglar = _esles(
            baslik="Konut Finansmanı ve Taşıt Finansmanı kampanyası",
            adaylar=[TASIT, KONUT],
        )

        assert {b.product_id for b in baglar} == {1, 2}

    def test_ayni_urun_iki_kez_baglanmaz(self) -> None:
        baglar = _esles(
            baslik="Taşıt Finansmanı",
            slug="tasit-finansmani",
            url="https://ornek.com.tr/tasit-finansmani",
            metin="Taşıt Finansmanı detayları",
            adaylar=[TASIT],
        )

        assert len(baglar) == 1


def test_kanit_ham_metinden_alinir() -> None:
    """⚠️ Kanıt KATLANMIŞ metinden alınırsa Türkçe harfler bozulur."""
    (bag,) = _esles(
        baslik="Yeni Fırsat",
        metin="Bu ay Taşıt Finansmanı ürününde avantaj var.",
        adaylar=[TASIT],
    )

    assert "Taşıt" in bag.evidence


@pytest.mark.parametrize("bos", ["", None])
def test_bos_metin_bag_uretmez(bos: str | None) -> None:
    assert esles(title="", campaign_slug="", source_url="", clean_text=bos, adaylar=[TASIT]) == []


def test_varyant_ana_urunle_ayni_cekirdege_iner() -> None:
    """⚠️ Varyant ile ana ürün AYNI ÇEKİRDEĞE iner; ikisi de aday olursa bağ çoğalır.

    Bankalar ürün adını parantezli açıklamayla yazıyor:

        İhtiyaç Finansmanı (İhtiyaç Kredisi)*              ← ana ürün
        İhtiyaç Finansmanı (İhtiyaç Kredisi)* — Sigortalı  ← varyant

    `_ad_cekirdegi` parantezden sonrasını attığı için ikisinin de çekirdeği
    `"ihtiyac finansmani"` oluyor ve tek anıştan iki bağ çıkıyor. Ölçüldü:
    canlı veride bir kampanya aynı ürüne ÜÇ kez bağlanmıştı.

    Çözüm aday listesinde: yalnızca ana ürünler girer
    (`scripts/match_campaign_products.py::_banka_urunleri`).
    """
    ana = UrunAdayi(
        product_id=1, name="İhtiyaç Finansmanı (İhtiyaç Kredisi)*", url_slug="ihtiyac-finansmani"
    )
    varyant = UrunAdayi(
        product_id=2,
        name="İhtiyaç Finansmanı (İhtiyaç Kredisi)* — Sigortalı",
        url_slug="ihtiyac-finansmani",
    )
    metin = "Size özel İhtiyaç Finansmanı fırsatı."

    ikisi = esles(
        title="", campaign_slug="", source_url="", clean_text=metin, adaylar=[ana, varyant]
    )
    yalniz_ana = esles(title="", campaign_slug="", source_url="", clean_text=metin, adaylar=[ana])

    assert len(ikisi) == 2, "iki aday verilirse bağ çoğalır — bu yüzden süzgeç gerekli"
    assert len(yalniz_ana) == 1
