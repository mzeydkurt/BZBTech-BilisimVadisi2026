"""Finansman simülatörü ve BDDK denetçisi API uç noktaları."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import DbSession
from app.schemas.bddk import BddkCanonicalLimitsOut
from app.schemas.simulator import (
    BDDKLimitCheckRequest,
    BDDKLimitCheckResponse,
    FinancingSimulationRequest,
    FinancingSimulationResponse,
    ParticipationYieldRequest,
    ParticipationYieldResponse,
)
from app.services.bddk_api import all_family_bddk_outs
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


@router.get("/bddk-bands", response_model=dict[str, BddkCanonicalLimitsOut])
def bddk_bands() -> dict[str, BddkCanonicalLimitsOut]:
    """Üç ailenin (taşıt / konut / ihtiyaç) BDDK değer bantlarını döndürür.

    Arayüz bu bantları seçim listesi olarak sunar: kullanıcı varlık değerini
    serbest yazmak yerine mevzuatın tanımladığı bandı seçer.

    ⚠️ Bantlar kanondan okunur, arayüzde SABİT YAZILMAZ. BDDK kararı
    değiştiğinde tek kaynak `data/seed/bddk_finansman_limitleri.json`; iki
    yerde tutulan bir tablo, güncellenmeyen tarafta sessizce yanlış limit
    gösterir.
    """
    return all_family_bddk_outs()
