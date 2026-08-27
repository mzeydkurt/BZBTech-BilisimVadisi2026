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
        '<form><input name="__RequestVerificationToken" type="hidden" value="abcTOKEN123" /></form>'
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


def _kuveyt_urun(title: str, params: list[dict]) -> dict:
    return {"Title": title, "Parameters": params}


def test_kuveyt_tasit_bddk_400bin_48ay() -> None:
    """Eski örnek 500.000 TL idi; BDDK 400.000/48 bandı hiç sorulmuyordu."""
    from app.scrapers.calculator_probes.api_adapters.kuveyt import probe_noktalari

    urun = _kuveyt_urun(
        "Yeni Binek Araç Finansmanı",
        [
            {"Key": "ProductCode", "Value": "ARACBINEKYENI"},
            {"Key": "MaturityTermMin", "Value": "1"},
            {"Key": "MaturityTermMax", "Value": "48"},
            {"Key": "DefaultAmountMin", "Value": "1000"},
            {"Key": "DefaultAmountMax", "Value": "5000000"},
        ],
    )
    noktalar = probe_noktalari(urun["Title"], urun)
    assert (Decimal("400000"), 48) in noktalar
    assert (Decimal("800000"), 36) in noktalar
    assert (Decimal("1200000"), 24) in noktalar
    assert not any(tutar == Decimal("500000") for tutar, _vade in noktalar)


def test_kuveyt_ihtiyac_bddk_ve_katalog_adimlari() -> None:
    from app.scrapers.calculator_probes.api_adapters.kuveyt import probe_noktalari

    urun = _kuveyt_urun(
        "İhtiyaç Finansmanı",
        [
            {"Key": "ProductCode", "Value": "SAGLIKFINANSMANI"},
            {"Key": "MaturityTermMin", "Value": "1", "Description": "1000"},
            {"Key": "MaturityTermMax", "Value": "36", "Description": "1000"},
            {"Key": "DefaultAmountMin", "Value": "1000"},
            {"Key": "DefaultAmountMax", "Value": "5000000"},
            {"Key": "MaturityTermMin2", "Value": "1", "Description": "125000"},
            {"Key": "MaturityTermMax2", "Value": "24", "Description": "125000"},
            {"Key": "MaturityTermMin3", "Value": "1", "Description": "250000"},
            {"Key": "MaturityTermMax3", "Value": "12", "Description": "250000"},
        ],
    )
    noktalar = probe_noktalari(urun["Title"], urun)
    assert (Decimal("10000"), 36) in noktalar
    assert (Decimal("200000"), 24) in noktalar
    assert (Decimal("1000000"), 12) in noktalar


def test_urun_tipi_ipucu_buyuk_i() -> None:
    from app.scrapers.calculator_probes.common import urun_tipi_ipucu

    assert urun_tipi_ipucu("İhtiyaç Finansmanı") == "ihtiyac_finansmani"
    assert urun_tipi_ipucu("Yeni Binek Araç Finansmanı") == "tasit_finansmani"


def test_kuveyt_konut_ve_arsa_katalog_vade() -> None:
    from app.scrapers.calculator_probes.api_adapters.kuveyt import probe_noktalari

    konut = _kuveyt_urun(
        "Konut Finansmanı",
        [
            {"Key": "ProductCode", "Value": "GMENKULKONUTYENI"},
            {"Key": "MaturityTermMin", "Value": "1"},
            {"Key": "MaturityTermMax", "Value": "120"},
            {"Key": "DefaultAmountMin", "Value": "1000"},
            {"Key": "DefaultAmountMax", "Value": "3000000"},
        ],
    )
    assert (Decimal("1000000"), 120) in probe_noktalari(konut["Title"], konut)

    arsa = _kuveyt_urun(
        "Arsa Finansmanı",
        [
            {"Key": "ProductCode", "Value": "GMENKULARSA"},
            {"Key": "MaturityTermMin", "Value": "1"},
            {"Key": "MaturityTermMax", "Value": "60"},
            {"Key": "DefaultAmountMin", "Value": "1000"},
            {"Key": "DefaultAmountMax", "Value": "5000000"},
        ],
    )
    assert (Decimal("1000000"), 60) in probe_noktalari(arsa["Title"], arsa)


def test_kuveyt_seyahat_katalog_basamaklari() -> None:
    """Ürün tipi ipucu yoksa katalog 125k/250k vade basamakları doldurur."""
    from app.scrapers.calculator_probes.api_adapters.kuveyt import probe_noktalari

    urun = _kuveyt_urun(
        "Seyahat Finansmanı",
        [
            {"Key": "ProductCode", "Value": "SEYAHATFINANSMANI"},
            {"Key": "MaturityTermMin", "Value": "1", "Description": "1000"},
            {"Key": "MaturityTermMax", "Value": "36", "Description": "1000"},
            {"Key": "DefaultAmountMin", "Value": "1000"},
            {"Key": "MaturityTermMin2", "Value": "1", "Description": "125000"},
            {"Key": "MaturityTermMax2", "Value": "24", "Description": "125000"},
            {"Key": "MaturityTermMin3", "Value": "1", "Description": "250000"},
            {"Key": "MaturityTermMax3", "Value": "12", "Description": "250000"},
        ],
    )
    noktalar = probe_noktalari(urun["Title"], urun)
    vadeler = {vade for _tutar, vade in noktalar}
    assert 36 in vadeler
    assert 24 in vadeler
    assert 12 in vadeler


def test_tf_band_value_is_monthly_rate() -> None:
    band = {"Value": 4.2, "Cost": 96.05, "Min": 1, "Max": 3}
    assert parse_tr_rate(band["Value"]) == Decimal("4.2")
    assert parse_tr_rate(band["Cost"]) == Decimal("96.05")
