"""Dünya Katılım limit kazıma, azami limit koruması ve sıfır kâr payı filtre testleri."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

from app.scrapers.banks.dunya_katilim import DunyaKatilimScraper
from app.scrapers.calculator_probes.api_adapters import dunya as dunya_adapter
from app.scrapers.models import DiscoveredUrl, RawProduct
from app.services.calculator_probe_service import (
    finansman_orani_gosterilebilir_mi,
    is_zero_rate_promotional,
    probe_orani_guvenilir_mi,
)


class TestZeroRatePromotional:
    """Meşru sıfır kâr payı / faizsiz finansman ayrımı testleri."""

    def test_karz_i_hasen_veya_faizsiz_turler_gecerli(self) -> None:
        assert is_zero_rate_promotional(product_type="karz_i_hasen")
        assert is_zero_rate_promotional(rate_type="interest_free_benevolent_loan")

    def test_promosyon_metinleri_gecerli(self) -> None:
        assert is_zero_rate_promotional(product_name="Togg Finansmanı")
        assert is_zero_rate_promotional(product_name="0 Faizli İhtiyaç Kredisi")
        assert is_zero_rate_promotional(
            product_name="Vade Farksız Alışveriş Finansmanı"
        )
        assert is_zero_rate_promotional(evidence_text="Yıllık %0 kâr payı ile masrafsız finansman")

    def test_aciklamadaki_vade_farksiz_yetmez(self) -> None:
        """Tanıtım cümlesindeki 'vade farksız' / 'sıfır kâr' tek başına yetmez."""
        assert not is_zero_rate_promotional(
            product_name="Gönlüne Göre Konut Finansmanı",
            description="Aboneliklerde vade farksız finansman imkanı, sıfır kâr oranı ile...",
        )

    def test_alisveris_finansmani_sifir_korunur(self) -> None:
        """LC Waikiki vb. alışveriş kampanyası %0 uydurma değildir."""
        assert is_zero_rate_promotional(product_name="LC Waikiki Alışveriş Finansmanı")
        assert finansman_orani_gosterilebilir_mi(
            profit_rate_pct=Decimal("0"),
            product_name="LC Waikiki Alışveriş Finansmanı",
            product_type="ihtiyac_finansmani",
            evidence_text="sıfır kâr / vade farksız ifadesi",
        )

    def test_standart_finansmanlar_sifir_oran_alamaz(self) -> None:
        assert not is_zero_rate_promotional(product_name="Araç Finansmanı")
        assert not is_zero_rate_promotional(product_name="İhtiyaç Finansmanı")
        assert not is_zero_rate_promotional(product_name="Konut Finansmanı")
        assert not is_zero_rate_promotional(product_name="Çevre Dostu Taşıt")


class TestProbeOraniGuvenilirlik:
    """probe_orani_guvenilir_mi sıfır kâr payı kapısı testleri."""

    def test_standart_urunde_sifir_oran_reddedilir(self) -> None:
        guvenilir, neden = probe_orani_guvenilir_mi(
            profit_rate_pct=Decimal("0.0000"),
            term_months=36,
            monthly_installment=Decimal("22000.00"),
            total_repayment=Decimal("792000.00"),
            product_name="Araç Finansmanı",
            product_type="tasit_finansmani",
        )
        assert not guvenilir
        assert neden is not None
        assert "sıfır/geçersiz kâr payı" in neden

    def test_ucret_bandi_dusuk_oran_reddedilir(self) -> None:
        guvenilir, neden = probe_orani_guvenilir_mi(
            profit_rate_pct=Decimal("0.5000"),
            term_months=120,
            monthly_installment=None,
            total_repayment=None,
            product_name="Kentsel Dönüşüm Finansmanı",
            product_type="konut_finansmani",
        )
        assert not guvenilir
        assert neden is not None
        assert "şüpheli düşük" in neden

    def test_mevcut_oranli_standart_urun_kabul_edilir(self) -> None:
        guvenilir, neden = probe_orani_guvenilir_mi(
            profit_rate_pct=Decimal("3.39"),
            term_months=48,
            monthly_installment=Decimal("10086.71"),
            total_repayment=Decimal("484161.55"),
            product_name="Araç Finansmanı",
            product_type="tasit_finansmani",
        )
        assert guvenilir
        assert neden is None

    def test_togg_veya_karz_i_hasende_sifir_kabul_edilir(self) -> None:
        guvenilir, neden = probe_orani_guvenilir_mi(
            profit_rate_pct=Decimal("0.0000"),
            term_months=12,
            monthly_installment=Decimal("10000.00"),
            total_repayment=Decimal("120000.00"),
            product_name="Togg Finansmanı",
            product_type="tasit_finansmani",
        )
        assert guvenilir
        assert neden is None


class TestDunyaApiAdapterLimits:
    """Dünya Katılım API adaptörünün azami limit koruması testleri."""

    def test_calculate_limitten_buyuk_tutari_azamiye_ceker(self) -> None:
        mock_option = {
            "code": "ARACBINEK2ELTUKETICI",
            "label": "Araç Binek 2.El",
            "values": {
                "result": "SUCCESS",
                "maxAmount": 400000.0,
                "minAmount": 0.0,
                "defaultAmount": 200000.0,
                "maxInstallment": 48,
                "defaultInstallment": 12,
                "category": "Vehicle",
            },
        }

        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "result": "SUCCESS",
            "rate": 3.39,
            "monthlyInterest": 43633.42,
            "totalPayment": 523601.04,
        }
        mock_client.post.return_value = mock_resp

        # 800.000 TL isteniyor (limit 400.000 TL)
        calc = dunya_adapter.calculate(
            mock_option,
            "dummy_token",
            amount=Decimal("800000"),
            term_months=12,
            client=mock_client,
        )

        assert calc is not None
        # Tutar 400.000 TL'ye (maxAmount) çekilmeli
        assert calc.amount == Decimal("400000")
        assert calc.profit_rate_pct == Decimal("3.39")

        # API'ye giden post isteğinde amount 400.000 olarak biçimlendirilmeli
        post_kwargs = mock_client.post.call_args
        posted_data = post_kwargs[1].get("data") or post_kwargs.kwargs.get("data")
        assert posted_data["amount"] == "400.000"

    def test_calculate_sifir_veya_hata_donusunu_yoksayar(self) -> None:
        mock_option = {
            "code": "ARACBINEK2ELTUKETICI",
            "label": "Araç Binek 2.El",
            "values": {
                "result": "SUCCESS",
                "maxAmount": 400000.0,
                "defaultAmount": 200000.0,
                "maxInstallment": 48,
                "category": "Vehicle",
            },
        }

        mock_client = MagicMock()
        # RATEERROR dönen simülasyon
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "result": "RATEERROR",
            "rate": None,
        }
        mock_client.post.return_value = mock_resp

        calc = dunya_adapter.calculate(
            mock_option,
            "dummy_token",
            amount=Decimal("200000"),
            client=mock_client,
        )
        assert calc is None


class TestDunyaScraperLimits:
    """DunyaKatilimScraper parse_products limit atama testleri."""

    def test_finansman_limitleri_dogru_atanir(self) -> None:
        scraper = DunyaKatilimScraper.__new__(DunyaKatilimScraper)
        hint = DiscoveredUrl(
            url="https://dunyakatilim.com.tr/kendim-icin/finansmanlar/arac-finansmanlari/arac-finansmani",
            doc_type="product",
            category_hint="tasit_finansmani",
        )

        with patch("app.scrapers.base.BaseScraper.parse_products") as mock_super:
            mock_super.return_value = [
                RawProduct(
                    external_key="arac-finansmani#base",
                    name="Araç Finansmanı",
                    source_url=hint.url,
                    product_type="tasit_finansmani",
                )
            ]
            urunler = scraper.parse_products("<html></html>", hint.url, hint)

        assert len(urunler) == 1
        urun = urunler[0]
        assert urun.amount_max == Decimal("400000")
        assert urun.term_months_max == 48
        assert urun.limits_source == "calculator"
        assert len(urun.limits) >= 1
        assert urun.limits[0].amount_max == Decimal("400000")
        assert urun.limits[0].term_months_max == 48


class TestProductsApiFiltering:
    """products / financing API uçlarında geçersiz 0 oranların süzülmesi testleri."""

    def test_guncel_oranlar_hatali_sifir_orani_suzer(self) -> None:
        from app.api.v1.products import _guncel_oranlar
        from app.db.models import Bank, Product, ProductRate

        bank = Bank(id=1, code="dunya_katilim", name="Dünya Katılım")
        product = Product(
            id=3,
            bank_id=1,
            bank=bank,
            name="Araç Finansmanı",
            product_type="tasit_finansmani",
            description="Standart taşıt kredisi",
        )
        # Hatalı 0.00 oranı
        bad_rate = ProductRate(
            id=101,
            product_id=3,
            product=product,
            rate_type="financing_rate",
            profit_rate_pct=Decimal("0.0000"),
            rate_source="calculator_playwright",
            data_source="product_page",
            currency="TRY",
            is_binding=False,
            amount_min=Decimal("800000"),
            amount_max=Decimal("800000"),
        )
        # Geçerli 3.39 oranı
        good_rate = ProductRate(
            id=102,
            product_id=3,
            product=product,
            rate_type="financing_rate",
            profit_rate_pct=Decimal("3.3900"),
            rate_source="calculator_api",
            data_source="product_page",
            currency="TRY",
            is_binding=False,
            amount_min=Decimal("200000"),
            amount_max=Decimal("200000"),
        )
        product.rates = [bad_rate, good_rate]

        oranlar = _guncel_oranlar(product, rate_type="financing_rate")
        # Yalnızca geçerli 3.39 oranı dönmeli; 0.00 oranı filtrelenmeli
        oran_degerleri = [o.profit_rate_pct for o in oranlar]
        assert Decimal("3.3900") in oran_degerleri
        assert Decimal("0.0000") not in oran_degerleri
