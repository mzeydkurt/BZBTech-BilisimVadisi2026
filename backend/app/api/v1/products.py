"""Ürün ve Oran Karşılaştırma API Uçları (Sprint 2.5 KAPI F5)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession
from app.core.vocab import RATE_TYPES
from app.db.models.bank import Bank
from app.db.models.product import Product
from app.schemas.compare import ProductRankingRequest, ProductRankingResponse
from app.schemas.product import ProductDetailOut, ProductOut
from app.services.comparison_service import RankingError, rank_products

router = APIRouter(prefix="/products", tags=["products"])


def _urun_cikti(urun: Product, rate_type: str | None = None) -> ProductOut:
    """ORM ürününü listeleme şemasına çevirir, oranları isteğe göre süzer."""
    cikti = ProductOut.model_validate(urun)
    cikti.bank_code = urun.bank.code if urun.bank else None
    cikti.bank_name = urun.bank.name if urun.bank else None
    if rate_type:
        cikti.rates = [o for o in cikti.rates if o.rate_type == rate_type]
    return cikti


@router.get("", response_model=list[ProductOut])
def list_products(
    db: DbSession,
    bank_code: Annotated[str | None, Query(description="Banka kodu süzgeci")] = None,
    product_type: Annotated[str | None, Query(description="Ürün türü süzgeci")] = None,
    rate_type: Annotated[
        str | None,
        Query(description="Oran türü: financing_rate | participation_yield | profit_sharing_ratio"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[ProductOut]:
    """Ürünleri oranları ve limitleriyle listeler.

    `rate_type` verilirse yalnızca o türden oranı OLAN ürünler döner; oranlar
    da o türe süzülür. Süzgeç uygulanmazsa üç tür bir arada gelir — bu liste
    görünümü içindir, karşılaştırma için değil.
    """
    if rate_type and rate_type not in RATE_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Geçersiz rate_type: {rate_type!r}. Geçerli değerler: {', '.join(RATE_TYPES)}",
        )

    stmt = (
        select(Product)
        .options(
            selectinload(Product.rates),
            selectinload(Product.limits),
            selectinload(Product.bank),
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

    if rate_type:
        # Süzgeç SQL tarafında uygulanır; aksi hâlde `limit` oranı olmayan
        # ürünlerle dolar ve sayfa beklenenden az sonuç döndürür.
        from app.db.models.product import ProductRate

        stmt = stmt.where(Product.rates.any(ProductRate.rate_type == rate_type))

    urunler = list(db.scalars(stmt.limit(limit)))
    return [_urun_cikti(u, rate_type) for u in urunler]


@router.post("/compare", response_model=ProductRankingResponse)
def compare_products(req: ProductRankingRequest, db: DbSession) -> ProductRankingResponse:
    """Ürünleri tek bir açık ölçüte göre sıralar.

    ⚠️ Uç adı `/compare`: SPRINT2.5 §8.2 ve §10'da sözleşme olarak
    dondurulmuş, Sprint 4 arayüz promptu da bu adla çağırıyor. Servis
    fonksiyonu §8.3 gereği `rank_products` adını taşır.

    ⚠️ `rate_type` ZORUNLUDUR ve şemada varsayılanı yoktur: finansman
    maliyeti ile katılma getirisi aynı sıralamaya giremez.
    """
    try:
        return rank_products(
            db,
            rate_type=req.rate_type,
            criterion=req.criterion,
            product_type=req.product_type,
            bank_codes=req.bank_codes,
            term_months=req.term_months,
            term_days=req.term_days,
            currency=req.currency,
            amount_try=req.amount_try,
            weights=req.weights,
            limit=req.limit,
        )
    except RankingError as hata:
        raise HTTPException(status_code=422, detail=str(hata)) from hata


@router.get("/{product_id}", response_model=ProductDetailOut)
def get_product(product_id: int, db: DbSession) -> ProductDetailOut:
    """Tek ürünün tüm oranlarını, limitlerini, varyantlarını ve kaynağını verir.

    Kaynak URL yanıtın parçasıdır: arayüzde gösterilen her oranın bankanın
    hangi sayfasından okunduğu izlenebilir olmalıdır (KAPI F5 §8.2).
    """
    urun = db.scalar(
        select(Product)
        .options(
            selectinload(Product.rates),
            selectinload(Product.limits),
            selectinload(Product.bank),
            selectinload(Product.source_document),
            selectinload(Product.variants).selectinload(Product.rates),
            selectinload(Product.variants).selectinload(Product.limits),
            selectinload(Product.variants).selectinload(Product.bank),
        )
        .where(Product.id == product_id)
    )
    if urun is None:
        raise HTTPException(status_code=404, detail=f"Ürün bulunamadı: {product_id}")

    cikti = ProductDetailOut.model_validate(urun)
    cikti.bank_code = urun.bank.code if urun.bank else None
    cikti.bank_name = urun.bank.name if urun.bank else None
    if urun.source_document is not None:
        cikti.source_url = urun.source_document.url
        cikti.source_fetched_at = urun.source_document.fetched_at.isoformat()
    cikti.variants = [_urun_cikti(v) for v in urun.variants]
    return cikti
