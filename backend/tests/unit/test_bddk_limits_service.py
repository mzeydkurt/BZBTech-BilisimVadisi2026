"""BDDK kanon servisi birim testleri."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.schemas.simulator import BDDKLimitCheckRequest
from app.services.bddk_limits_service import (
    check_bddk_limits,
    compare_bank_limit_to_canon,
    family_for_product_type,
    get_canonical_limits,
    max_term_for_ihtiyac_amount,
)


def test_ihtiyac_vade_bantlari() -> None:
    assert max_term_for_ihtiyac_amount(Decimal("125000"))[0] == 36
    assert max_term_for_ihtiyac_amount(Decimal("125000.01"))[0] == 24
    assert max_term_for_ihtiyac_amount(Decimal("250000"))[0] == 24
    assert max_term_for_ihtiyac_amount(Decimal("1000000"))[0] == 12


def test_ihtiyac_check_endpoint() -> None:
    sonuc = check_bddk_limits(
        BDDKLimitCheckRequest(asset_type="ihtiyac", asset_value_try=Decimal("1000000"))
    )
    assert sonuc.max_allowed_term_months == 12
    assert sonuc.is_financing_allowed is True
    assert "11152" in sonuc.legal_reference


def test_ikinci_konut_yuzde_yetmis_bes_indirim() -> None:
    """A-B ≤5M ilk-ev %90 → ikinci konut %22,5 (Kuveyt Türk tablosu)."""
    ilk = check_bddk_limits(
        BDDKLimitCheckRequest(
            asset_type="konut",
            asset_value_try=Decimal("2000000"),
            energy_class="A",
            first_home=True,
        )
    )
    ikinci = check_bddk_limits(
        BDDKLimitCheckRequest(
            asset_type="konut",
            asset_value_try=Decimal("2000000"),
            energy_class="A",
            first_home=False,
        )
    )
    assert ilk.max_financing_ratio_pct == Decimal("90")
    assert ikinci.max_financing_ratio_pct == Decimal("22.50")
    assert ikinci.first_home is False


def test_konut_kanon_dayanak_11364() -> None:
    sonuc = check_bddk_limits(
        BDDKLimitCheckRequest(
            asset_type="konut", asset_value_try=Decimal("25000000"), energy_class="A"
        )
    )
    assert "11364" in sonuc.legal_reference
    assert sonuc.max_financing_amount_try == Decimal("10000000.00")


def test_tasit_bandi_kanondan() -> None:
    sonuc = check_bddk_limits(
        BDDKLimitCheckRequest(asset_type="tasit", asset_value_try=Decimal("600000"))
    )
    assert sonuc.max_financing_ratio_pct == Decimal("50")
    assert sonuc.max_allowed_term_months == 36


def test_product_type_aile_eslesmesi() -> None:
    assert family_for_product_type("ihtiyac_finansmani") == "ihtiyac"
    assert family_for_product_type("konut_finansmani") == "konut"
    assert family_for_product_type("tasit_finansmani") == "tasit"
    assert family_for_product_type("karz_i_hasen") is None


def test_canonical_limits_view() -> None:
    view = get_canonical_limits(product_type="ihtiyac_finansmani")
    assert view is not None
    assert view.family == "ihtiyac"
    assert len(view.bands) == 3
    assert view.bands[0].max_term_months == 36


def test_banka_ikinci_konut_tablosu_uyari() -> None:
    """Kuveyt tarzı %22,5 satırı ikinci-konut olarak etiketlenir, hata sayılmaz."""
    uyari = compare_bank_limit_to_canon(
        product_type="konut_finansmani",
        financing_ratio_pct=Decimal("22.5"),
        asset_value_max=Decimal("5000000"),
        energy_class="A-B",
        term_months_max=None,
    )
    assert uyari is not None
    assert "ikinci-konut" in uyari


def test_banka_tavan_asimi() -> None:
    uyari = compare_bank_limit_to_canon(
        product_type="tasit_finansmani",
        financing_ratio_pct=Decimal("90"),
        asset_value_max=Decimal("600000"),
        energy_class=None,
        term_months_max=None,
    )
    assert uyari is not None
    assert "üzerinde" in uyari
