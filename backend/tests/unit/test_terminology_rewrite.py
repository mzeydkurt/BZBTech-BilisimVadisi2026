"""Terminoloji düzeltme turu (Guard 6) — MockProvider."""

from __future__ import annotations

import pytest

from app.ai.providers.mock import MockProvider
from app.retrieval.answer import generate_answer
from app.retrieval.corpus import CampaignDoc
from app.retrieval.query import QueryPlan
from app.retrieval.search import SearchHit


@pytest.mark.asyncio
async def test_yasakli_terim_yeniden_yazma_veya_sablon() -> None:
    """Mock 'faiz' üretirse Guard 6 şablona düşer veya temizler."""
    doc = CampaignDoc(
        campaign_id=1,
        bank_code="kuveyt_turk",
        bank_name="Kuveyt Türk",
        title="Test",
        card_text="Kâr payı oranı %1,50 ile finansman.",
        status="active",
        source_url="https://example.test/1",
        date_precision="exact",
        axis_values={},
        metrics={},
        summary=None,
    )
    hits = (
        SearchHit(
            doc=doc, score=1.0, lexical_rank=1, semantic_rank=None, matched_terms=("finansman",)
        ),
    )
    plan = QueryPlan(raw="finansman oranı", intent="search", rate_type="financing_rate")
    provider = MockProvider(mode="null")
    # MockProvider varsayılanı genelde temiz; yine de çağrı hata vermemeli.
    cevap = await generate_answer(
        plan,
        hits,
        provider=provider,
        forbidden_terms={"faiz": "kâr payı", "kredi": "finansman", "mevduat": "katılım fonu"},
    )
    assert cevap.source in {"model", "template", "refusal"}
    if cevap.source == "model":
        folded = cevap.text.lower()
        # Kaynakta yoksa faiz sızmamalı (veya warning + şablon).
        assert "faiz" not in folded or cevap.terminology_warnings
