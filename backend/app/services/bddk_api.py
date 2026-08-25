"""BDDK kanon görünümlerini API şemasına çeviren yardımcılar."""

from __future__ import annotations

from app.db.models.product import ProductLimit
from app.schemas.bddk import BankLimitDeviationOut, BddkBandOut, BddkCanonicalLimitsOut
from app.services.bddk_limits_service import (
    CanonicalLimitsView,
    compare_bank_limit_to_canon,
    get_canonical_limits,
)


def canonical_to_out(view: CanonicalLimitsView) -> BddkCanonicalLimitsOut:
    """Servis görünümünü Pydantic şemasına çevirir."""
    return BddkCanonicalLimitsOut(
        family=view.family,
        kind=view.kind,
        decision_no=view.decision_no,
        decision_date=view.decision_date,
        legal_reference=view.legal_reference,
        source_url=view.source_url,
        bands=[
            BddkBandOut(
                label=b.label,
                amount_min=b.amount_min,
                amount_max=b.amount_max,
                value_min=b.value_min,
                value_max=b.value_max,
                max_term_months=b.max_term_months,
                max_ratio_pct=b.max_ratio_pct,
                rates=b.rates,
            )
            for b in view.bands
        ],
        max_term_months=view.max_term_months,
        second_home_reduction_pct=view.second_home_reduction_pct,
        second_home_note=view.second_home_note,
        as_of=view.as_of,
    )


def bddk_out_for_product_type(product_type: str | None) -> BddkCanonicalLimitsOut | None:
    """Ürün türüne göre BDDK tavan şeması; aile yoksa None."""
    view = get_canonical_limits(product_type=product_type)
    return canonical_to_out(view) if view else None


def all_family_bddk_outs() -> dict[str, BddkCanonicalLimitsOut]:
    """Üç ailenin (ihtiyac/konut/tasit) BDDK tavanları."""
    sonuc: dict[str, BddkCanonicalLimitsOut] = {}
    for aile in ("ihtiyac", "konut", "tasit"):
        view = get_canonical_limits(family=aile)
        if view:
            sonuc[aile] = canonical_to_out(view)
    return sonuc


def bank_limit_deviations_for_product(
    product_type: str | None,
    limits: list[ProductLimit],
) -> list[BankLimitDeviationOut]:
    """Banka LTV satırlarını BDDK kanonuyla karşılaştırır."""
    sapmalar: list[BankLimitDeviationOut] = []
    for limit in limits:
        mesaj = compare_bank_limit_to_canon(
            product_type=product_type,
            financing_ratio_pct=getattr(limit, "financing_ratio_pct", None),
            asset_value_max=getattr(limit, "asset_value_max", None),
            energy_class=getattr(limit, "energy_class", None),
            term_months_max=getattr(limit, "term_months_max", None),
        )
        if mesaj:
            sapmalar.append(BankLimitDeviationOut(limit_id=int(limit.id), message=mesaj))
    return sapmalar
