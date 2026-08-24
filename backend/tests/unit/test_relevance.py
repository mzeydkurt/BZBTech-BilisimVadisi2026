"""Alaka süzgeci — eğitim sorgusunda İdefix gibi dolgu kampanyalar elenir."""

from __future__ import annotations

from types import SimpleNamespace

from app.retrieval.query import QueryPlan
from app.retrieval.relevance import (
    filter_relevant_hits,
    is_follow_up_query,
    strip_citation_markers,
)
from app.retrieval.search import SearchHit


def _hit(campaign_id: int, title: str, summary: str = "", score: float = 1.0) -> SearchHit:
    doc = SimpleNamespace(
        campaign_id=campaign_id,
        title=title,
        summary=summary,
        bank_name="Ziraat Katılım",
        card_text=summary or title,
    )
    return SearchHit(
        doc=doc,  # type: ignore[arg-type]
        score=score,
        lexical_rank=1,
        semantic_rank=None,
        matched_terms=(),
    )


def test_egitim_sorgusu_idefix_dolguyu_eler() -> None:
    plan = QueryPlan(
        raw="Ziraat Katılım eğitim kampanyası özellikleri",
        intent="search",
        bank_codes=("ziraat_katilim",),
        axis_filters={"sector": ("egitim_kitap",)},
        free_terms=("egitim", "kampanya", "ozellik"),
    )
    hits = (
        _hit(1, "Okul Ödemelerinizde 12 Aya Varan Taksit Fırsatı", "okul ödemelerinde taksit"),
        _hit(2, "Seçili Okullarda Peşin Ödemelerinize 5'e Varan Taksit", "seçili okullarda"),
        _hit(3, "TROY Kartla İdefix'te 3.000 TL'ye Varan İndirim!", "idefix alışveriş indirimi"),
    )
    sonuc = filter_relevant_hits(hits, plan, max_n=3)
    assert len(sonuc) == 2
    assert all("idefix" not in h.doc.title.lower() for h in sonuc)
    assert all("okul" in h.doc.title.lower() for h in sonuc)


def test_tek_alakali_ise_bir_doner() -> None:
    plan = QueryPlan(
        raw="eğitim kampanyası",
        intent="search",
        axis_filters={"sector": ("egitim_kitap",)},
        free_terms=("egitim",),
    )
    hits = (
        _hit(1, "Okul ödemelerinde taksit", score=2.0),
        _hit(2, "Market alışverişinde puan", score=9.0),
    )
    sonuc = filter_relevant_hits(hits, plan, max_n=3)
    assert len(sonuc) == 1
    assert "Okul" in sonuc[0].doc.title


def test_alakasiz_dolgu_bos_doner() -> None:
    plan = QueryPlan(
        raw="eğitim kampanyası",
        intent="search",
        axis_filters={"sector": ("egitim_kitap",)},
        free_terms=("egitim", "okul"),
    )
    hits = (_hit(1, "TROY Kartla İdefix'te İndirim", "pazaryeri indirimi"),)
    assert filter_relevant_hits(hits, plan, max_n=3) == ()


def test_strip_citation_markers() -> None:
    assert strip_citation_markers("Metin [1] devam [N] son.") == "Metin devam son."
    assert "[" not in strip_citation_markers("Oran %2,50 [3]")


def test_is_follow_up_ozellik() -> None:
    assert is_follow_up_query("peki özellikleri?")
    assert is_follow_up_query("devam et")
    assert not is_follow_up_query(
        "Bana Ziraat Katılım'ın eğitim kampanyasından bahseder misin ne gibi özellikleri var"
    )
