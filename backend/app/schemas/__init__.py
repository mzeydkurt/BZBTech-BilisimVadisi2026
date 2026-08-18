"""API yanıt şemaları (Pydantic v2)."""

from app.schemas.bank import BankBase, BankDetail, BankSummary
from app.schemas.campaign import CampaignDetail, CampaignListItem, SourceDocumentSummary
from app.schemas.chat import ChatRequest, ChatResponse, ChatResultItem
from app.schemas.common import ErrorDetail, ErrorResponse, HealthResponse, Page
from app.schemas.compare import ComparisonItem, ComparisonRequest, ComparisonResponse, ComparisonWeights
from app.schemas.simulator import (
    BDDKLimitCheckRequest,
    BDDKLimitCheckResponse,
    FinancingSimulationRequest,
    FinancingSimulationResponse,
    ParticipationYieldRequest,
    ParticipationYieldResponse,
)
from app.schemas.stats import BankCampaignCount, CategoryCount, RadarScore, SectorCount, StatsResponse

__all__ = [
    "BDDKLimitCheckRequest",
    "BDDKLimitCheckResponse",
    "BankBase",
    "BankCampaignCount",
    "BankDetail",
    "BankSummary",
    "CampaignDetail",
    "CampaignListItem",
    "CategoryCount",
    "ChatRequest",
    "ChatResponse",
    "ChatResultItem",
    "ComparisonItem",
    "ComparisonRequest",
    "ComparisonResponse",
    "ComparisonWeights",
    "ErrorDetail",
    "ErrorResponse",
    "FinancingSimulationRequest",
    "FinancingSimulationResponse",
    "HealthResponse",
    "Page",
    "ParticipationYieldRequest",
    "ParticipationYieldResponse",
    "RadarScore",
    "SectorCount",
    "SourceDocumentSummary",
    "StatsResponse",
]
