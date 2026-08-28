"""Dürüst susma — dört senaryo (plan §E.1 / KAPI 4.3).

1. Veri yok → net "veri yok", uydurma yok
2. rate_type belirsiz → netleştirici soru, tahmin yok
3. Model uydurma sayı → katman 3/4 reddeder (MockProvider halluc)
4. Kapsam dışı → sabit ret, modele hiç gitmez
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.providers.mock import FABRICATED_EVIDENCE, MockProvider
from app.db.models import Bank, Campaign, CampaignMetric, EntityCard
from app.retrieval.answer import generate_answer
from app.retrieval.corpus import CampaignDoc, invalidate_corpus
from app.retrieval.query import QueryPlan
from app.retrieval.search import SearchHit


@pytest.fixture(autouse=True)
def _temiz() -> None:
    invalidate_corpus()


def _kampanya(
    session: Session,
    *,
    bank_code: str,
    campaign_id: int,
    title: str,
    card_text: str,
    profit_rate: str | None = None,
) -> None:
    banka = session.scalar(select(Bank).where(Bank.code == bank_code))
    assert banka is not None
    session.add(
        Campaign(
            id=campaign_id,
            bank_id=banka.id,
            external_slug=f"slug-{campaign_id}",
            title=title,
            source_url=f"https://example.test/{campaign_id}",
            status="active",
            date_precision="exact",
            date_evidence_text="01.01.2026 - 31.12.2026",
            date_evidence_source="structured",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
        )
    )
    session.flush()
    session.add(
        EntityCard(
            entity_type="campaign",
            entity_id=campaign_id,
            card_text=card_text,
            card_hash=f"h-{campaign_id}",
        )
    )
    if profit_rate:
        session.add(CampaignMetric(campaign_id=campaign_id, profit_rate_pct=Decimal(profit_rate)))
    session.commit()


class TestHonestSilence:
    def test_kapsam_disi_modele_gitmez(
        self, api_client: httpx.Client, seeded_session: Session
    ) -> None:
        veri = api_client.post("/api/v1/chat", json={"query": "Yarın hava nasıl?"}).json()
        assert veri["intent"] == "kapsam_disi"
        assert veri["answer"]["source"] == "refusal"
        assert veri["results"] == []
        assert "model çağrılmadı" in (veri["retrieval"].get("semantic_note") or "").lower()

    def test_bitcoin_bulunamadi(self, api_client: httpx.Client, seeded_session: Session) -> None:
        _kampanya(
            seeded_session,
            bank_code="kuveyt_turk",
            campaign_id=501,
            title="Market Kampanyası",
            card_text="Market alışverişinde hediye.",
        )
        veri = api_client.post("/api/v1/chat", json={"query": "Bitcoin kampanyası var mı?"}).json()
        assert veri["intent"] == "search"
        assert veri["answer"]["unverified_numbers"] == []
        if not veri["results"]:
            # Boş sonuç anlatıcısı `computed` dönebilir; sayı uydurmaz.
            assert veri["answer"]["source"] in {
                "refusal",
                "template",
                "model",
                "computed",
            }

    def test_rate_type_belirsiz_netlestirir(
        self, api_client: httpx.Client, seeded_session: Session
    ) -> None:
        veri = api_client.post(
            "/api/v1/chat",
            json={"query": "Kuveyt Türk mü daha avantajlı, Albaraka mı?"},
        ).json()
        assert veri.get("clarification_needed") is True
        assert veri["answer"]["source"] == "computed"
        assert "hangi konuda" in veri["answer"]["text"].lower()
        assert "veriyle yanıt verilemiyor" not in veri["answer"]["text"].lower()
        assert veri["intent"] == "compare"
        assert len(veri.get("actions") or []) >= 2

    def test_rate_type_belirsiz_netlestirir_genel(
        self, api_client: httpx.Client, seeded_session: Session
    ) -> None:
        veri = api_client.post(
            "/api/v1/chat",
            json={"query": "Kuveyt Türk mü daha avantajlı, Albaraka mı? oran karşılaştırması"},
        ).json()
        if veri.get("clarification_needed"):
            assert veri["clarification_question"]
            assert veri["results"] == []
            assert veri["answer"]["source"] == "computed"
        else:
            assert veri["intent"] in {"compare", "search", "tekil_sorgu"}
            assert veri["answer"]["unverified_numbers"] == []

    def test_tanim_computed(self, api_client: httpx.Client, seeded_session: Session) -> None:
        veri = api_client.post("/api/v1/chat", json={"query": "Kâr payı oranı ne demek?"}).json()
        assert veri["intent"] == "tanim"
        assert veri["answer"]["source"] == "computed"
        assert veri["glossary"]
        # Tek kaynak: tanım glossary'de; answer kısa yönlendirme; top_matches boş.
        tanim = veri["glossary"][0]["definition"]
        assert tanim
        assert tanim not in veri["answer"]["text"]
        assert veri.get("top_matches") == []
        metin = veri["answer"]["text"].lower()
        assert "kâr" in metin or "kar" in metin or "tanımı" in metin

    def test_tekil_sorgu_veri_yok_uydurmaz(
        self, api_client: httpx.Client, seeded_session: Session
    ) -> None:
        veri = api_client.post(
            "/api/v1/chat",
            json={"query": "Adil Katılım'ın konut finansmanı oranı ne?"},
        ).json()
        assert veri["intent"] == "tekil_sorgu"
        assert veri["answer"]["unverified_numbers"] == []
        if not veri["products"] and not veri["results"]:
            assert veri["answer"]["source"] == "refusal"

    @pytest.mark.asyncio
    async def test_halluc_sayi_dogrulanamaz(self) -> None:
        """MockProvider halluc → kaynakta olmayan sayı unverified_numbers'a düşer."""
        doc = CampaignDoc(
            campaign_id=1,
            bank_code="kuveyt_turk",
            bank_name="Kuveyt Türk",
            title="Test",
            card_text="Market kampanyası — hediye çeki.",
            status="active",
            source_url="https://example.test/1",
            date_precision="exact",
            axis_values={},
            metrics={},
            summary=None,
        )
        hits = (
            SearchHit(
                doc=doc,
                score=1.0,
                lexical_rank=1,
                semantic_rank=None,
                matched_terms=("market",),
            ),
        )
        plan = QueryPlan(raw="market kampanyası oranı ne?", intent="search")
        provider = MockProvider(mode="halluc")
        cevap = await generate_answer(plan, hits, provider=provider, forbidden_terms={})
        assert FABRICATED_EVIDENCE
        if cevap.source == "model":
            assert cevap.unverified_numbers
        else:
            assert cevap.source in {"template", "refusal"}
