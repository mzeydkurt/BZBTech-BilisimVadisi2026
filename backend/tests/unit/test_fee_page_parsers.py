"""Ürün/hizmet ücret sayfası ayrıştırıcıları."""

from __future__ import annotations

from decimal import Decimal

from app.processing.fee_page_parsers import (
    parse_albaraka_ucret_page,
    parse_hayat_ucret_page,
    parse_turkiye_finans_ucret_page,
)

ALBARAKA_HTML = """
<table><tbody>
<tr><td>Tahsis Ücreti</td></tr>
<tr><td>Konut Finansmanı</td><td></td><td>-</td><td>% 0.5</td><td>-</td><td>% 0.5</td></tr>
<tr><td>Taşıt Finansmanı</td><td></td><td>-</td><td>% 0.5</td><td>-</td><td>% 0.5</td></tr>
</tbody></table>
"""

HAYAT_HTML = """
<table><tbody>
<tr><td>Finansman Tahsis Ücreti</td><td>TL</td><td>%0,25</td><td>-</td><td>-</td></tr>
</tbody></table>
"""

TF_HTML = """
<h3>Konut Finansmanı</h3>
<table><tr><td>Tahsis Ücreti</td><td>% 0.5</td><td>BSMV dahil</td></tr></table>
<h3>Taşıt Finansmanı</h3>
<table><tr><td>Tahsis Ücreti</td><td>% 0.5</td><td>BSMV dahil</td></tr></table>
"""


def test_albaraka_tahsis_ayristirilir() -> None:
    urunler = parse_albaraka_ucret_page(ALBARAKA_HTML, "https://www.albaraka.com.tr/tr/urun-ve-hizmet-ucretleri")
    assert len(urunler) == 2
    konut = next(u for u in urunler if u.product_type == "konut_finansmani")
    assert konut.rates[0].allocation_fee_pct == Decimal("0.5")


def test_albaraka_genel_finansman_tahsis_satiri() -> None:
    html = """
    <table><tr><td>Finansman Tahsis</td><td></td><td>-</td><td>-</td><td>-</td><td>% 0.2</td></tr></table>
    """
    urunler = parse_albaraka_ucret_page(html, "https://www.albaraka.com.tr/tr/urun-ve-hizmet-ucretleri")
    assert len(urunler) == 3
    assert all(u.rates[0].allocation_fee_pct == Decimal("0.2") for u in urunler)


def test_hayat_tahsis_ayristirilir() -> None:
    urunler = parse_hayat_ucret_page(HAYAT_HTML, "https://hayatfinans.com.tr/urun-ve-hizmet-ucretleri")
    assert len(urunler) == 1
    assert urunler[0].rates[0].allocation_fee_pct == Decimal("0.25")


def test_turkiye_finans_tahsis_ayristirilir() -> None:
    urunler = parse_turkiye_finans_ucret_page(
        TF_HTML,
        "https://www.turkiyefinans.com.tr/tr-tr/bireysel/Sayfalar/urun-hizmet-ucretleri.aspx",
    )
    assert len(urunler) == 2
    tipler = {u.product_type for u in urunler}
    assert tipler == {"konut_finansmani", "tasit_finansmani"}
