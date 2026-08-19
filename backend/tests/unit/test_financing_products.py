"""Finansman ürünleri ve varyant ağacı testleri (SPRINT 2.5 KAPI F4)."""

from app.scrapers.banks.dunya_katilim import DunyaKatilimScraper
from app.scrapers.banks.ziraat_katilim import ZiraatKatilimScraper
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
