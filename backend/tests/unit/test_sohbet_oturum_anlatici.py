"""Sohbet niyeti, merge, anlatıcı guardları ve oturum uçları."""

from __future__ import annotations

import pytest

from app.retrieval.narrate import (
    FactTriple,
    NarrationFacts,
    narrate,
    relaxation_to_natural,
)
from app.retrieval.query import merge_with_previous, parse_query


def test_sohbet_merhaba() -> None:
    plan = parse_query("Merhaba")
    assert plan.intent == "sohbet"
    assert plan.source_domain == "sohbet"


def test_sohbet_finansal_sinyalde_devreye_girmez() -> None:
    plan = parse_query("merhaba, katılma hesabı açacağım")
    assert plan.intent != "sohbet"
    assert plan.source_domain == "katilma"


def test_merge_with_previous_banka_devralir() -> None:
    onceki = parse_query("Kuveyt Türk konut finansmanı")
    yeni = parse_query("Peki 6 aylıkta?")
    birlesik = merge_with_previous(yeni, onceki)
    assert "kuveyt_turk" in birlesik.bank_codes
    assert any(s.evidence == "önceki soru" for s in birlesik.signals)


@pytest.mark.asyncio
async def test_anlatici_sayi_reddi() -> None:
    class Sahte:
        async def generate(self, *_a, **_k):
            from app.ai.providers.base import LLMResponse

            return LLMResponse(text="Oran %99.9 ve 42 banka var.", latency_ms=1, model_name="mock")

    facts = NarrationFacts(
        facts=(FactTriple(etiket="oran", deger="3.5", birim="%"),),
        template_text="Oran %3.5.",
        question="oran nedir",
    )
    sonuc = await narrate(facts, provider=Sahte())  # type: ignore[arg-type]
    assert sonuc.source == "computed"
    assert sonuc.text == "Oran %3.5."


@pytest.mark.asyncio
async def test_anlatici_olguya_uygun() -> None:
    class Sahte:
        async def generate(self, *_a, **_k):
            from app.ai.providers.base import LLMResponse

            return LLMResponse(text="Kuveyt Türk oranı %3.5.", latency_ms=1, model_name="mock")

    facts = NarrationFacts(
        facts=(FactTriple(etiket="oran", deger="3.5", birim="%"),),
        template_text="Kuveyt Türk oranı %3.5.",
        question="oran",
    )
    sonuc = await narrate(facts, provider=Sahte())  # type: ignore[arg-type]
    assert sonuc.source == "model"
    assert "3.5" in sonuc.text


def test_relaxation_natural() -> None:
    metin = relaxation_to_natural([("bank", "kuveyt_turk", "Banka", 12)])
    assert "12" in metin
    assert "kayıt" in metin.lower() or "kayit" in metin.lower()


def test_chat_sohbet_asla_refusal(api_client) -> None:
    """Merhaba → sohbet; refusal değil."""
    r = api_client.post("/api/v1/chat", json={"query": "Merhaba"})
    assert r.status_code == 200
    body = r.json()
    assert body["intent"] == "sohbet"
    assert body["answer"]["source"] != "refusal"
    assert body["session_id"]
    assert body["turn_index"] is not None


def test_chat_session_crud(api_client) -> None:
    created = api_client.post("/api/v1/chat/sessions", json={})
    assert created.status_code == 200
    sid = created.json()["session_id"]

    chat = api_client.post("/api/v1/chat", json={"query": "Teşekkürler", "session_id": sid})
    assert chat.status_code == 200
    assert chat.json()["intent"] == "sohbet"

    hist = api_client.get(f"/api/v1/chat/sessions/{sid}")
    assert hist.status_code == 200
    assert len(hist.json()["messages"]) >= 2

    ended = api_client.delete(f"/api/v1/chat/sessions/{sid}")
    assert ended.status_code == 204

    again = api_client.get(f"/api/v1/chat/sessions/{sid}")
    assert again.status_code == 200
    assert again.json()["ended_at"] is not None
