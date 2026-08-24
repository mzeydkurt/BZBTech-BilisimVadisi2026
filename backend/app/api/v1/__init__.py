"""API v1 yönlendirici birleştirme."""

from fastapi import APIRouter

from app.api.v1 import (
    admin,
    annotate,
    banks,
    campaigns,
    chat,
    extract,
    financing,
    health,
    katilim_hesabi,
    products,
    simulator,
    stats,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(admin.router)
api_router.include_router(banks.router)
api_router.include_router(campaigns.router)
api_router.include_router(products.router)
# KATİP KAPI 6/7 — Kampanyalar/Ürünler'in yanına eklenen yeni sekmeler.
api_router.include_router(financing.router)
api_router.include_router(katilim_hesabi.router)
api_router.include_router(simulator.router)
api_router.include_router(chat.router)
api_router.include_router(stats.router)
# Canlı çıkarım — şartname madde 6 (metin girdisi).
api_router.include_router(extract.router)
# Gold set etiketleme aracı — yalnızca yerel kullanım (bkz. annotate.py).
api_router.include_router(annotate.router)

__all__ = ["api_router"]
