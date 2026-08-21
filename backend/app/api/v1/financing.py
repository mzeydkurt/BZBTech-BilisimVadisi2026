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

router = APIRouter(prefix="/financing", tags=["finansmanlar"])


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
    `product_limits` (LTV/tutar-vade matrisi) yine döner, `no_data_products`
    listesinde de ayrıca işaretlenir.
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
        .where(Product.product_type.in_(FINANSMAN_TIPLERI))
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
    for urun in urunler:
        cikti = ProductOut.model_validate(urun)
        cikti.bank_code = urun.bank.code if urun.bank else None
        cikti.bank_name = urun.bank.name if urun.bank else None
        financing.append(cikti)
        if not urun.rates and not urun.limits:
            banka_adi = urun.bank.name if urun.bank else "Bilinmeyen banka"
            no_data_products.append(f"{banka_adi} — {urun.name}")

    return FinancingResponse(
        financing=financing,
        no_data_products=no_data_products,
        coverage_note=(
            "Katılım bankalarının çoğu finansman kâr payı oranını kamuya açık "
            "yayınlamamaktadır. Sistem, veri olmayan yerde uydurmak yerine mevcut "
            "olanı gösterir ve eksik olanı açıkça işaretler. Karz-ı Hasen ve Eğitim "
            'Finansmanı gibi vade farksız ürünlerde oran sütunu "Kâr Payı Alınmaz" '
            "olarak gösterilir, %0 ile karıştırılmaz."
        ),
    )
