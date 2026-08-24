"""Admin API şemaları — job başlatma / durum."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

AdminJobKind = Literal[
    "campaign",
    "js_campaign",
    "product",
    "bank_pipeline",
    "campaign_all",
    "js_campaign_all",
    "product_all",
    "tkbb",
    "tkbb_seed",
    "llm_health",
]


class AdminJobCreateRequest(BaseModel):
    kind: AdminJobKind = Field(description="İş türü (whitelist)")
    bank_code: str | None = Field(
        default=None,
        description="Kampanya / ürün / JS / pipeline için banka kodu",
    )


class AdminJobOut(BaseModel):
    id: str
    kind: AdminJobKind
    bank_code: str | None
    status: Literal["queued", "running", "succeeded", "failed"]
    command: list[str]
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    log: str = ""
    error: str | None = None
    summary: str | None = None
