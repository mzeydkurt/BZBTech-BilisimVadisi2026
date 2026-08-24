"""Katibim — top-3 puanlama."""

from __future__ import annotations

from app.retrieval.rank import RankCandidate, TOP_N, score_candidates


def test_top3_sirasi() -> None:
    adaylar = [
        RankCandidate(
            entity_type="campaign",
            id=1,
            title="A",
            bank_name="B1",
            source_url=None,
            detail_path="/campaigns?id=1",
            rank_index=2,
            is_active=False,
        ),
        RankCandidate(
            entity_type="campaign",
            id=2,
            title="B",
            bank_name="B2",
            source_url=None,
            detail_path="/campaigns?id=2",
            rank_index=0,
            is_active=True,
            intent_boost=0.2,
        ),
        RankCandidate(
            entity_type="campaign",
            id=3,
            title="C",
            bank_name="B3",
            source_url=None,
            detail_path="/campaigns?id=3",
            rank_index=1,
            is_active=True,
        ),
        RankCandidate(
            entity_type="campaign",
            id=4,
            title="D",
            bank_name="B4",
            source_url=None,
            detail_path="/campaigns?id=4",
            rank_index=3,
        ),
    ]
    sonuc = score_candidates(adaylar)
    assert len(sonuc) == TOP_N
    assert sonuc[0].id == 2  # en iyi sıra + boost + aktif
    assert all(m.score is not None for m in sonuc)


def test_bos_aday() -> None:
    assert score_candidates([]) == []
