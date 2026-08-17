"""Banka ürün sayfası whitelist'lerinin sözlük uyumu.

⚠️ BU TEST GERÇEK BİR HATADAN DOĞDU. Dünya Katılım'ın whitelist'i teminat
türünü serbest metinle yazıyordu (`teminatsiz`, `arac_ipotegi`, `ipotek`);
üçü de `COLLATERAL_TYPES` sözlüğünde yok. Hata ancak veritabanına yazarken
CHECK ihlali olarak ortaya çıkıyor, `ProductRunner` onu tek adresin hatası
sayıp yutuyor ve çalıştırma "partial" kapanıyordu — `products` tablosu boş
kalırken çalıştırma başarılı görünüyordu.

Whitelist bir SÖZLEŞMEDİR ve beyan anında doğrulanır; veritabanına kadar
gitmesi beklenmez.
"""

from __future__ import annotations

import pytest

from app.core.taxonomy import PRODUCT_TYPES
from app.core.vocab import COLLATERAL_TYPES
from app.scrapers.registry import BANK_REGISTRY, available_banks


@pytest.mark.parametrize("bank_code", available_banks())
def test_urun_sayfasi_whitelisti_sozluge_uyuyor(bank_code: str) -> None:
    """Her whitelist girdisi kontrollü sözlükten değer taşımalı."""
    scraper_class = BANK_REGISTRY[bank_code]

    for yol, urun_turu, teminat in scraper_class.product_pages:
        assert yol.startswith("/"), f"{bank_code}: yol '/' ile başlamalı — {yol}"
        assert urun_turu in PRODUCT_TYPES, (
            f"{bank_code}: '{urun_turu}' PRODUCT_TYPES'ta yok ({yol})"
        )
        # ⚠️ None geçerli: teminat yapısı bilinmiyorsa UYDURULMAZ.
        assert teminat is None or teminat in COLLATERAL_TYPES, (
            f"{bank_code}: '{teminat}' COLLATERAL_TYPES'ta yok ({yol})"
        )


@pytest.mark.parametrize("bank_code", available_banks())
def test_whitelist_varsa_taban_adres_de_var(bank_code: str) -> None:
    """`product_pages` dolu olan bankanın `product_base_url`'ü olmalı.

    Aksi hâlde `urljoin` göreli adres üretir ve çekim sessizce başarısız olur.
    """
    scraper_class = BANK_REGISTRY[bank_code]

    if scraper_class.product_pages:
        assert scraper_class.product_base_url.startswith("http"), (
            f"{bank_code}: product_pages dolu ama product_base_url boş"
        )


@pytest.mark.parametrize("bank_code", available_banks())
def test_whitelist_yollari_tekil(bank_code: str) -> None:
    """Aynı yol iki kez listelenirse aynı sayfa iki kez çekilir."""
    yollar = [yol for yol, _, _ in BANK_REGISTRY[bank_code].product_pages]

    assert len(yollar) == len(set(yollar)), f"{bank_code}: whitelist'te tekrar eden yol var"
