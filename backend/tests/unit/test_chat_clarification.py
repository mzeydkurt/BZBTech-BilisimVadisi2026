"""Netleştirme akışı — clarification_needed geriye dönük uyumlu."""

from __future__ import annotations

import httpx
from sqlalchemy.orm import Session

from app.retrieval.corpus import invalidate_corpus


def setup_function() -> None:
    invalidate_corpus()


def test_clarification_alanlari_var(
    api_client: httpx.Client, seeded_session: Session
) -> None:
    """Mevcut istemciler kırılmaz: alanlar her zaman yanıtta."""
    veri = api_client.post(
        "/api/v1/chat", json={"query": "Kuveyt Türk market kampanyası"}
    ).json()
    assert "clarification_needed" in veri
    assert veri["clarification_needed"] is False
    assert veri.get("clarification_question") is None
    assert "products" in veri
    assert "glossary" in veri
    assert "direction_note" in veri
