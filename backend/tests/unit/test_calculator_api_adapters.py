"""Albaraka / Vakıf API parse birim testleri (ağa çıkmaz)."""

from __future__ import annotations

from decimal import Decimal

from app.scrapers.calculator_probes.api_adapters import parse_tr_money, parse_tr_rate
from app.scrapers.calculator_probes.api_adapters.vakif import _csrf_token


def test_parse_tr_money_and_rate() -> None:
    assert parse_tr_money("11.349,76 TL") == Decimal("11349.76")
    assert parse_tr_rate("%3,75") == Decimal("3.75")
    assert parse_tr_rate("4,0") == Decimal("4.0")
    assert parse_tr_rate(4.01) == Decimal("4.01")


def test_vakif_csrf_from_html() -> None:
    html = (
        '<form><input name="__RequestVerificationToken" type="hidden" '
        'value="abcTOKEN123" /></form>'
    )
    assert _csrf_token(html) == "abcTOKEN123"


def test_albaraka_fixture_fields_parse() -> None:
    data = {
        "ProfitRate": "4,0",
        "AnnualCostRate": "% 85,1",
        "MonthlyInstallmentAmount": "11.349,76 TL",
        "TotalAmountTobeRefunded": "261.044,84 TL",
        "TotalFees": "862,50",
    }
    assert parse_tr_rate(data["ProfitRate"]) == Decimal("4.0")
    assert parse_tr_money(data["MonthlyInstallmentAmount"]) == Decimal("11349.76")
    assert parse_tr_money(data["TotalAmountTobeRefunded"]) == Decimal("261044.84")
    assert parse_tr_money(data["TotalFees"]) == Decimal("862.50")


def test_kuveyt_meta_parse() -> None:
    meta = {
        "ProfitRate": 4.01,
        "InstallmentPayment": 7397.98,
        "TotalAmount": 177551.50,
        "AllocationAmount": 575.00,
        "YearlyCost": 84.97,
    }
    assert parse_tr_rate(meta["ProfitRate"]) == Decimal("4.01")
    assert parse_tr_money(meta["InstallmentPayment"]) == Decimal("7397.98")


def test_tf_band_value_is_monthly_rate() -> None:
    band = {"Value": 4.2, "Cost": 96.05, "Min": 1, "Max": 3}
    assert parse_tr_rate(band["Value"]) == Decimal("4.2")
    assert parse_tr_rate(band["Cost"]) == Decimal("96.05")
