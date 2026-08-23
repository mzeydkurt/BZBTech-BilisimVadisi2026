"""BDDK kanonik finansman tavanları API şemaları."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


class BddkBandOut(BaseModel):
    """Tek BDDK tavan bandı."""

    label: str
    amount_min: Decimal | None = None
    amount_max: Decimal | None = None
    value_min: Decimal | None = None
    value_max: Decimal | None = None
    max_term_months: int | None = None
    max_ratio_pct: Decimal | None = None
    rates: dict[str, Decimal] | None = None


class BddkCanonicalLimitsOut(BaseModel):
    """Ürün ailesine göre BDDK yasal tavan özeti."""

    family: str = Field(description="ihtiyac | konut | tasit")
    kind: str
    decision_no: str
    decision_date: str
    legal_reference: str
    source_url: str
    bands: list[BddkBandOut] = Field(default_factory=list)
    max_term_months: int | None = None
    second_home_reduction_pct: Decimal | None = None
    second_home_note: str | None = None
    as_of: str | None = None


class BankLimitDeviationOut(BaseModel):
    """Banka LTV satırının BDDK tavandan sapması / ikinci-konut eşleşmesi."""

    limit_id: int
    message: str
