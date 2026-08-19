"""Doğal dil sohbet ve terminoloji uyarısı Pydantic şemaları."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Sohbet ve arama isteği."""

    query: str = Field(
        min_length=2,
        description="Doğal dil sorusu (Örn: 'En düşük konut finansmanı oranı hangi bankada?')",
    )
    bank_code: str | None = Field(default=None, description="Banka süzgeci")


class ChatResultItem(BaseModel):
    """Sohbet arama sonucu öğesi."""

    campaign_id: int
    bank_code: str
    bank_name: str
    title: str
    summary: str | None = None
    evidence_text: str | None = None
    source_url: str | None = None
    profit_rate_pct: float | None = None


class ChatResponse(BaseModel):
    """Sohbet ve arama yanıtı."""

    query: str
    answer_text: str
    forbidden_terms_warning: str | None = Field(
        default=None,
        description=(
            "Yasaklı konvansiyonel terim uyarısı (örn. 'faiz' yerine 'kâr payı' kullanılır)"
        ),
    )
    results: list[ChatResultItem] = Field(default_factory=list)
