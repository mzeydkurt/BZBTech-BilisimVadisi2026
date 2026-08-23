"""Finansman simülatörü ve BDDK denetçisi API uç noktaları."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import DbSession
from app.schemas.simulator import (
    BDDKLimitCheckRequest,
    BDDKLimitCheckResponse,
    FinancingSimulationRequest,
    FinancingSimulationResponse,
    ParticipationYieldRequest,
    ParticipationYieldResponse,
)
from app.services.simulator_service import (
    calculate_financing_simulation,
    calculate_participation_yield,
    check_bddk_limits,
)

router = APIRouter(prefix="/simulator", tags=["simulator"])


@router.post("/financing", response_model=FinancingSimulationResponse)
def simulate_financing(
    req: FinancingSimulationRequest,
    db: DbSession,
) -> FinancingSimulationResponse:
    """Finansman taksit ve geri ödeme simülasyonu yapar."""
    return calculate_financing_simulation(db, req)


@router.post("/yield", response_model=ParticipationYieldResponse)
def simulate_yield(
    req: ParticipationYieldRequest,
    db: DbSession,
) -> ParticipationYieldResponse:
    """Katılma hesabı kâr paylaşımı brüt/net getirisini hesaplar."""
    return calculate_participation_yield(db, req)


@router.post("/bddk-check", response_model=BDDKLimitCheckResponse)
def check_bddk(req: BDDKLimitCheckRequest) -> BDDKLimitCheckResponse:
    """BDDK Taşıt/Konut/İhtiyaç azami limitlerini denetler."""
    return check_bddk_limits(req)
