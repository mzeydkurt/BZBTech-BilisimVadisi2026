"""Katibim — kaynak alanı (source_domain) yönlendirmesi."""

from __future__ import annotations

from app.retrieval.query import parse_query, resolve_source_domain


class TestSourceDomain:
    def test_kampanya_sinyali(self) -> None:
        plan = parse_query("En yüksek nakit iade veren kampanyalar")
        assert plan.source_domain == "kampanya"

    def test_finansman_sinyali(self) -> None:
        plan = parse_query("Konut finansmanı oranı hangi bankada düşük?")
        assert plan.source_domain == "finansman"

    def test_katilma_sinyali(self) -> None:
        plan = parse_query("Katılma hesabı getirisi ne kadar?")
        assert plan.source_domain == "katilma"

    def test_tanim(self) -> None:
        plan = parse_query("Murabaha nedir?")
        assert plan.source_domain == "tanim"
        assert plan.intent == "tanim"

    def test_kapsam_disi(self) -> None:
        plan = parse_query("Yarın hava nasıl?")
        assert plan.source_domain == "kapsam_disi"

    def test_resolve_dogrudan(self) -> None:
        assert (
            resolve_source_domain(
                "kart mil puan",
                intent="search",
                rate_type=None,
                axis_filters={},
            )
            == "kampanya"
        )
