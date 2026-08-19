"""Finansman ürünleri ve varyant ağacı testleri (SPRINT 2.5 KAPI F4)."""

from app.scrapers.banks.dunya_katilim import DunyaKatilimScraper
from app.scrapers.banks.ziraat_katilim import ZiraatKatilimScraper
from app.scrapers.models import RawProduct, RawProductRate
from app.scrapers.products import split_rate_variants
from app.scrapers.soft404 import is_soft_404


class TestFinancingProducts:
    def test_ziraat_katilim_product_discovery(self) -> None:
        scraper = ZiraatKatilimScraper()
        urls = scraper.discover_products()
        assert len(urls) >= 15
        konut_urls = [u for u in urls if u.category_hint == "konut_finansmani"]
        assert len(konut_urls) >= 1

    def test_vakif_katilim_soft404_guard(self) -> None:
        html_soft404 = """
        <html>
        <head><title>404 | Vakıf Katılım</title></head>
        <body><p>Aradığınız sayfa yok yada bulunamadı.</p></body>
        </html>
        """
        assert is_soft_404(html_soft404, "https://www.vakifkatilim.com.tr/invalid-page") is True

    def test_dunya_katilim_product_pages(self) -> None:
        scraper = DunyaKatilimScraper()
        urls = scraper.discover_products()
        assert len(urls) >= 5


# ── Oran tablosu varyantlarının ürüne bölünmesi ────────────


def _oranli_urun(varyantlar: list[str | None]) -> RawProduct:
    """Verilen varyantlarla oranlı bir ana ürün kurar."""
    from decimal import Decimal

    return RawProduct(
        external_key="tasit-finansmani#base",
        name="Taşıt Finansmanı",
        source_url="https://ornek.com.tr/tasit",
        product_type="tasit_finansmani",
        rates=[
            RawProductRate(
                rate_type="financing_rate",
                profit_rate_pct=Decimal("3.05"),
                term_months=36,
                variant=v,
                evidence_text=f"{v} | 36 | %3,05",
                rate_source="html_table",
            )
            for v in varyantlar
        ],
    )


def test_iki_varyant_ayri_urun_olur() -> None:
    """⚠️ Sigortalı ve sigortasız oran AYNI ürünün altında duramaz.

    Ölçüldü: Türkiye Finans taşıt sayfasında dört tablonun (sigorta × araç
    durumu) 28 oranı tek "Taşıt Finansmanı" ürününe yığılıyordu; katalogda
    hangi oranın hangi koşula ait olduğu kayboluyordu.
    """
    urunler = split_rate_variants(_oranli_urun(["sigortali", "sigortasiz"]))

    assert [u.variant_key for u in urunler] == [None, "sigortali", "sigortasiz"]
    assert all(u.parent_external_key == "tasit-finansmani#base" for u in urunler[1:])


def test_her_varyant_kendi_oranini_tasir() -> None:
    urunler = split_rate_variants(_oranli_urun(["sigortali", "sigortali", "sigortasiz"]))

    oran_sayisi = {u.variant_key: len(u.rates) for u in urunler}
    assert oran_sayisi == {None: 0, "sigortali": 2, "sigortasiz": 1}


def test_tek_varyant_bolunmez() -> None:
    """Tek varyantta alt ürün üretmek katalogda anlamsız kırılım yaratır."""
    urunler = split_rate_variants(_oranli_urun(["sigortali"]))

    assert len(urunler) == 1
    assert len(urunler[0].rates) == 1


def test_varyantsiz_oran_ana_urunde_kalir() -> None:
    """⚠️ Ödeme planından türetilmiş oranın varyantı YOKTUR.

    Alt ürüne taşınırsa hangi koşula ait olduğu hakkında sahip olmadığımız
    bir bilgi iddia edilmiş olur.
    """
    urunler = split_rate_variants(_oranli_urun(["sigortali", "sigortasiz", None]))

    ana = urunler[0]
    assert ana.variant_key is None
    assert len(ana.rates) == 1
    assert ana.rates[0].variant is None


def test_bilesik_varyantta_boyut_yazilmaz() -> None:
    """⚠️ `sifir_arac+sigortali` İKİ boyuta yayılır; tek boyut yanlış olur."""
    urunler = split_rate_variants(
        _oranli_urun(["sifir_arac+sigortali", "ikinci_el_arac+sigortali"])
    )

    assert all(u.variant_dimension is None for u in urunler[1:])


def test_tek_boyutlu_varyantta_boyut_yazilir() -> None:
    urunler = split_rate_variants(_oranli_urun(["sifir_arac", "ikinci_el_arac"]))

    assert {u.variant_dimension for u in urunler[1:]} == {"arac_durumu"}


def test_oran_tablosu_varyanti_dropdown_sayilmaz() -> None:
    """⚠️ Site geneli seçici elemesi oran tablosu varyantını VURMAMALI.

    Eleme, her sayfada tekrarlanan hesaplayıcı dropdown'ını ayıklamak için
    var. "Sigortalı"/"Sigortasız" ise o sayfanın KENDİ oran tablosundan
    gelir ve birden çok sayfada görünmesi onu sahte yapmaz.

    Ölçüldü: ayrım yapılmadığında Türkiye Finans'ın konut, arsa ve iş yeri
    finansmanı oranlarının tamamı siliniyordu — ana ürün bölünmede
    boşaltılmış, alt ürünler "site geneli" diye atılmıştı.
    """
    from app.scrapers.products import _dropdown_varyanti

    oran_varyanti = RawProduct(
        external_key="konut#sigortali",
        name="Konut — Sigortalı",
        source_url="https://ornek.com.tr/konut",
        parent_external_key="konut#base",
        variant_source="separate_page",
    )
    dropdown_varyanti = RawProduct(
        external_key="konut#klasik",
        name="Konut — Klasik",
        source_url="https://ornek.com.tr/konut",
        parent_external_key="konut#base",
        variant_source="dropdown_option",
    )

    assert _dropdown_varyanti(oran_varyanti) is False
    assert _dropdown_varyanti(dropdown_varyanti) is True
