"""Finansmanlar sekmesi API ucu (KATİP KAPI 6).

Kapsam belirleme `app/core/vocab.py::FINANSMAN_TIPLERI`'de merkezîleştirilir:
katılma hesabı ürünleri (KAPI 7'nin işi) buraya SIZMAZ.

⚠️ `/api/v1/products/compare` sözleşmesine dokunmaz; `list_products`
(`app/api/v1/products.py`) ile aynı sorgu desenini yeniden kullanır.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession
from app.core.vocab import FINANSMAN_TIPLERI
from app.db.models.bank import Bank
from app.db.models.product import Product
from app.schemas.financing import FinancingResponse
from app.schemas.product import ProductOut
from app.services.bddk_api import all_family_bddk_outs, bddk_out_for_product_type

router = APIRouter(prefix="/financing", tags=["finansmanlar"])


def _urun_etiketi(urun: Product) -> str:
    banka_adi = urun.bank.name if urun.bank else "Bilinmeyen banka"
    return f"{banka_adi} — {urun.name}"


def _limiti_var_mi(urun: Product) -> bool:
    if urun.limits:
        return True
    return any(
        (
            urun.amount_min is not None,
            urun.amount_max is not None,
            urun.term_months_min is not None,
            urun.term_months_max is not None,
            bool(urun.allowed_terms),
            urun.ltv_max_pct is not None,
        )
    )


@router.get("", response_model=FinancingResponse, summary="Finansman ürünleri listesi")
def list_financing(
    db: DbSession,
    bank_code: Annotated[str | None, Query(description="Banka kodu süzgeci")] = None,
    product_type: Annotated[
        str | None,
        Query(description=f"Finansman türü süzgeci: {', '.join(sorted(FINANSMAN_TIPLERI))}"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> FinancingResponse:
    """Finansman ürünlerini oranları ve limitleriyle listeler.

    Kampanyalar/Katılım Hesabı'ndan AYRI bir sekmedir; kapsam `product_type`
    değeri `FINANSMAN_TIPLERI` kümesinde olan ürünlerle sınırlıdır. Oran
    yayınlamayan bankalar için satır BOŞ BIRAKILMAZ — ürün ve varsa
    limit bilgisi yine döner; `products_with_limits_only` / `no_data_products`
    ayrımı yapılır.
    """
    if product_type is not None and product_type not in FINANSMAN_TIPLERI:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Geçersiz product_type: {product_type!r}. "
                f"Geçerli değerler: {', '.join(sorted(FINANSMAN_TIPLERI))}"
            ),
        )

    stmt = (
        select(Product)
        .options(
            selectinload(Product.rates),
            selectinload(Product.limits),
            selectinload(Product.bank),
        )
        .where(
            Product.product_type.in_(FINANSMAN_TIPLERI),
            Product.is_active.is_(True),
        )
        .order_by(Product.name)
    )

    if bank_code:
        banka = db.scalar(select(Bank).where(Bank.code == bank_code))
        if banka is None:
            raise HTTPException(status_code=404, detail=f"Banka bulunamadı: {bank_code}")
        stmt = stmt.where(Product.bank_id == banka.id)

    if product_type:
        stmt = stmt.where(Product.product_type == product_type)

    urunler = list(db.scalars(stmt.limit(limit)))

    financing: list[ProductOut] = []
    no_data_products: list[str] = []
    products_with_limits_only: list[str] = []
    for urun in urunler:
        cikti = ProductOut.model_validate(urun)
        cikti.bank_code = urun.bank.code if urun.bank else None
        cikti.bank_name = urun.bank.name if urun.bank else None
        financing.append(cikti)
        if urun.rates:
            continue
        etiket = _urun_etiketi(urun)
        if _limiti_var_mi(urun):
            products_with_limits_only.append(etiket)
        else:
            no_data_products.append(etiket)

    tablo_sayisi = sum(1 for u in urunler if any(r.rate_source == "html_table" for r in u.rates))
    probe_sayisi = sum(
        1
        for u in urunler
        if any(
            r.rate_source in ("calculator_api", "calculator_playwright", "payment_plan_derived")
            for r in u.rates
        )
    )
    oranli = sum(1 for u in urunler if u.rates)
    limit_only = len(products_with_limits_only)
    bos = len(no_data_products)

    note_parts = [f"{oranli} üründe oran (tablo {tablo_sayisi} · hesaplayıcı {probe_sayisi})"]
    if limit_only:
        note_parts.append(f"{limit_only} üründe yalnızca limit")
    if bos:
        note_parts.append(f"{bos} üründe veri yok")
    coverage_note = " · ".join(note_parts) + ". Eksik oran uydurulmaz."

    return FinancingResponse(
        financing=financing,
        no_data_products=no_data_products,
        products_with_limits_only=products_with_limits_only,
        coverage_note=coverage_note,
        bddk_limits=bddk_out_for_product_type(product_type) if product_type else None,
        bddk_limits_by_family=all_family_bddk_outs(),
    )
