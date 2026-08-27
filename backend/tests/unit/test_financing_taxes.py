"""Finansman vergileri (BSMV ve KKDF) birim testleri."""

from decimal import Decimal

from app.core.financing_taxes import financing_tax_rates


def test_konut_finansmani_vergiden_muaf() -> None:
    tax = financing_tax_rates("konut_finansmani")
    assert tax.bsmv_rate == Decimal("0.00")
    assert tax.kkdf_rate == Decimal("0.00")
    assert tax.total_tax_multiplier == Decimal("1.00")
    assert tax.is_tax_exempt


def test_tasit_finansmani_vergili() -> None:
    tax = financing_tax_rates("tasit_finansmani")
    assert tax.bsmv_rate == Decimal("0.15")
    assert tax.kkdf_rate == Decimal("0.15")
    assert tax.bsmv_pct == Decimal("15.00")
    assert tax.kkdf_pct == Decimal("15.00")
    assert tax.total_tax_multiplier == Decimal("1.30")
    assert not tax.is_tax_exempt


def test_ihtiyac_finansmani_vergili() -> None:
    tax = financing_tax_rates("ihtiyac_finansmani")
    assert tax.bsmv_rate == Decimal("0.15")
    assert tax.kkdf_rate == Decimal("0.15")
    assert tax.total_tax_multiplier == Decimal("1.30")
    assert not tax.is_tax_exempt


def test_ticari_segment_yalnizca_bsmv_alır() -> None:
    tax = financing_tax_rates("tasit_finansmani", segment="ticari")
    assert tax.bsmv_rate == Decimal("0.05")
    assert tax.kkdf_rate == Decimal("0.00")
    assert tax.total_tax_multiplier == Decimal("1.05")
