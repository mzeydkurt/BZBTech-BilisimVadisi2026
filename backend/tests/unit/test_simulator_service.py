"""Finansman simülatörü ve BDDK denetçisi testleri."""

from decimal import Decimal
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.simulator import BDDKLimitCheckRequest, FinancingSimulationRequest, ParticipationYieldRequest
from app.services.simulator_service import check_bddk_limits

client = TestClient(app)


def test_bddk_limit_check_tasit() -> None:
    req = BDDKLimitCheckRequest(asset_type="tasit", asset_value_try=Decimal("600000"))
    res = check_bddk_limits(req)
    assert res.max_financing_ratio_pct == 50.0
    assert res.max_allowed_term_months == 36
    assert res.max_financing_amount_try == 300000.0


def test_bddk_limit_check_konut() -> None:
    req = BDDKLimitCheckRequest(asset_type="konut", asset_value_try=Decimal("2000000"), energy_class="A")
    res = check_bddk_limits(req)
    assert res.max_financing_ratio_pct == 90.0
    assert res.max_financing_amount_try == 1800000.0


def test_simulator_api_financing() -> None:
    response = client.post(
        "/api/v1/simulator/financing",
        json={"amount_try": 500000, "term_months": 36, "product_type": "tasit_finansmani"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["amount_try"] == 500000.0
    assert len(data["offers"]) > 0
    assert data["best_bank_code"] is not None


def test_simulator_api_yield() -> None:
    response = client.post(
        "/api/v1/simulator/yield",
        json={"deposit_try": 100000, "term_days": 91, "currency": "TRY"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["deposit_try"] == 100000.0
    assert len(data["offers"]) > 0
