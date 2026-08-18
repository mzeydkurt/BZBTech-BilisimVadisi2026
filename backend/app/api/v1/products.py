"""Ürün ve Oran Karşılaştırma API Uçları (Sprint 2.5 KAPI F5)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models.bank import Bank
from app.db.models.product import Product, ProductLimit, ProductRate
from app.db.session import get_db

router = APIRouter(prefix="/products", tags=["products"])


@router.get("")
def list_products(
    bank_code: Annotated[str | None, Query(description="Banka kodu süzgeci")] = None,
    product_type: Annotated[str | None, Query(description="Ürün türü süzgeci")] = None,
    rate_type: Annotated[str | None, Query(description="Oran türü: financing_rate, profit_sharing_ratio, participation_yield")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Ürünleri oranları ve limitleriyle listeler."""
    stmt = (
        select(Product)
        .options(selectinload(Product.rates), selectinload(Product.limits))
        .order_by(Product.name)
    )

    if bank_code:
        banka = db.scalar(select(Bank).where(Bank.code == bank_code))
        if banka:
            stmt = stmt.where(Product.bank_id == banka.id)

    if product_type:
        stmt = stmt.where(Product.product_type == product_type)

    urunler = list(db.scalars(stmt.limit(limit)))

    sonuclar = []
    for u in urunler:
        oranlar = []
        for r in u.rates:
            if rate_type and r.rate_type != rate_type:
                continue
            oranlar.append({
                "id": r.id,
                "rate_type": r.rate_type,
                "profit_rate_pct": float(r.profit_rate_pct) if r.profit_rate_pct is not None else None,
                "investor_share_pct": float(r.investor_share_pct) if r.investor_share_pct is not None else None,
                "bank_share_pct": float(r.bank_share_pct) if r.bank_share_pct is not None else None,
                "term_months": r.term_months,
                "term_label": r.term_label,
                "currency": r.currency,
                "evidence_text": r.evidence_text,
            })

        if rate_type and not oranlar:
            continue

        limitler = []
        for l in u.limits:
            limitler.append({
                "id": l.id,
                "asset_value_min": float(l.asset_value_min) if l.asset_value_min is not None else None,
                "asset_value_max": float(l.asset_value_max) if l.asset_value_max is not None else None,
                "financing_ratio_pct": float(l.financing_ratio_pct) if l.financing_ratio_pct is not None else None,
                "term_months_max": l.term_months_max,
                "energy_class": l.energy_class,
                "evidence_text": l.evidence_text,
            })

        sonuclar.append({
            "id": u.id,
            "external_key": u.external_key,
            "name": u.name,
            "product_type": u.product_type,
            "rates": oranlar,
            "limits": limitler,
        })

    return sonuclar
