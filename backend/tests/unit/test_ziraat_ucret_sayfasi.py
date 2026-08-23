"""Ziraat Katılım'ın ücret/oran sayfası ayrıştırıcısı testleri (KATİP).

Testler ağa çıkmaz: kaydedilmiş bir HTML fixture'ı doğrudan
`_parse_fee_rate_page`'e verilir (§13). Fixture, canlı sayfadan (21 Ağustos
2026) alınmış üç sekmenin (İhtiyaç/Konut/Taşıt Finansmanı) küçültülmüş bir
örneğidir; Tahsis Ücreti ve Yıllık Maliyet Oranı satırları bilinçli olarak
dahil edildi — kâr oranı satırına birleşeceklerini doğrulamak için.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.scrapers.banks.ziraat_katilim import FEE_RATE_URL, _parse_fee_rate_page


@pytest.fixture
def html(read_fixture) -> str:  # type: ignore[no-untyped-def]
    return read_fixture("html/ziraat_katilim/urun_ve_hizmet_ucretleri.html")


def test_her_sekme_dogru_urun_turune_eslenir(html: str) -> None:
    urunler = _parse_fee_rate_page(html, FEE_RATE_URL)
    turler = {u.product_type for u in urunler}
    assert turler == {"ihtiyac_finansmani", "konut_finansmani", "tasit_finansmani"}


def test_tahsis_ucreti_kar_orani_satirina_eklenir(html: str) -> None:
    """Tahsis Ücreti ayrı satır değil; eşleşen kâr oranı satırına yazılır."""
    urunler = _parse_fee_rate_page(html, FEE_RATE_URL)
    arsa = next(u for u in urunler if u.name == "Arsa Finansmanı")
    assert len(arsa.rates) == 1
    assert arsa.rates[0].profit_rate_pct == Decimal("4.99")
    assert arsa.rates[0].allocation_fee_pct == Decimal("0.50")
    assert arsa.rates[0].term_months == 60
    assert arsa.rates[0].term_label == "1-60 ay vade"
    assert arsa.rates[0].rate_source == "html_table"
    assert "Tahsis ücreti %0.50" in (arsa.rates[0].evidence_text or "")


def test_yillik_maliyet_orani_kar_orani_satirina_eklenir(html: str) -> None:
    konut = next(u for u in _parse_fee_rate_page(html, FEE_RATE_URL) if "Konut" in u.name)
    assert konut.rates[0].annual_cost_pct == Decimal("42.15")
    assert "Yıllık maliyet oranı %42.15" in (konut.rates[0].evidence_text or "")


def test_panel_basligindaki_tutar_bandi_ayristirilir(html: str) -> None:
    konut = next(u for u in _parse_fee_rate_page(html, FEE_RATE_URL) if "Konut" in u.name)
    assert konut.amount_min == Decimal("0")
    assert konut.amount_max == Decimal("10000000")


def test_yildizli_ve_bosluksuz_tutar_bandi_ayristirilir(html: str) -> None:
    """ "(0 - 400.000 TL)*" — sondaki yıldız ve boşluk tutarsızlığı sorun çıkarmamalı."""
    tasit = next(u for u in _parse_fee_rate_page(html, FEE_RATE_URL) if "Kaskolu" in u.name)
    assert tasit.amount_min == Decimal("0")
    assert tasit.amount_max == Decimal("400000")
    # Aynı panelde iki farklı vade bandı — ikisi de ayrı oran satırı olmalı.
    assert {r.term_label for r in tasit.rates} == {"1-24 ay vade", "25-36 ay vade"}
    assert {r.profit_rate_pct for r in tasit.rates} == {Decimal("3.49"), Decimal("3.39")}


def test_evidence_text_birebir_aciklamayi_tasir(html: str) -> None:
    konut = next(u for u in _parse_fee_rate_page(html, FEE_RATE_URL) if "Konut" in u.name)
    assert "KKDF ve BSMV'den muaftır." in (konut.rates[0].evidence_text or "")
    # Kaynak hücre zaten yüzde işareti taşımıyorsa (bu panelde "3,19" biçiminde)
    # kanıt metninde TEK bir "%" işareti olmalı, çift değil.
    assert "% %" not in (konut.rates[0].evidence_text or "")


def test_hicbir_kar_orani_yoksa_bos_liste_doner() -> None:
    bos_html = "<html><body><ul class='nav nav-pills'></ul></body></html>"
    assert _parse_fee_rate_page(bos_html, FEE_RATE_URL) == []
