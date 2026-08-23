"""Hesaplayıcı probe → product_rates yazımı (bağlayıcı değil)."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.bank import Bank
from app.db.models.calculator import CalculatorProbe
from app.db.models.product import Product, ProductRate
from app.services.calculator_probe_service import upsert_probe_and_rate


def test_probe_is_binding_false(seeded_session: Session) -> None:
    banka = seeded_session.scalar(select(Bank).where(Bank.code == "albaraka"))
    assert banka is not None
    urun = Product(
        bank_id=banka.id,
        external_key="alb:probe-test",
        name="İhtiyaç Probe",
        product_type="ihtiyac_finansmani",
    )
    seeded_session.add(urun)
    seeded_session.flush()

    upsert_probe_and_rate(
        seeded_session,
        product=urun,
        inventory=None,
        amount=Decimal("10000"),
        term_months=36,
        method="playwright",
        profit_rate_pct=Decimal("4.52"),
        monthly_installment=Decimal("492.63"),
        response_raw="örnek",
    )
    seeded_session.flush()

    probe = seeded_session.scalar(
        select(CalculatorProbe).where(CalculatorProbe.product_id == urun.id)
    )
    assert probe is not None
    assert probe.is_binding is False
    assert probe.profit_rate_pct == Decimal("4.52")

    oran = seeded_session.scalar(
        select(ProductRate).where(
            ProductRate.product_id == urun.id,
            ProductRate.rate_source == "calculator_playwright",
        )
    )
    assert oran is not None
    assert oran.is_binding is False
    assert oran.profit_rate_pct == Decimal("4.52")
    assert urun.is_binding is False
