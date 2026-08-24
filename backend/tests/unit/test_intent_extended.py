"""Sprint 5 — genişletilmiş niyetler (tanim / tekil_sorgu / kapsam_disi)."""

from __future__ import annotations

from app.retrieval.query import parse_query


class TestTanimNiyeti:
    def test_kar_payi_ne_demek(self) -> None:
        plan = parse_query("Kâr payı oranı ne demek?")
        assert plan.intent == "tanim"
        assert plan.glossary_term
        assert "kar payi" in plan.glossary_term or "oran" in plan.glossary_term

    def test_finansman_nedir(self) -> None:
        assert parse_query("Finansman nedir?").intent == "tanim"


class TestKapsamDisi:
    def test_hava_nasil(self) -> None:
        plan = parse_query("Yarın hava nasıl?")
        assert plan.intent == "kapsam_disi"

    def test_bitcoin_kampanya_search_kalir(self) -> None:
        """'kampanya' finansal sinyaldir → search; boş sonuç ayrı testte."""
        assert parse_query("Bitcoin kampanyası var mı?").intent == "search"


class TestTekilSorgu:
    def test_tek_banka_konut(self) -> None:
        plan = parse_query("Ziraat Katılım'ın konut finansmanı oranı ne?")
        assert plan.intent == "tekil_sorgu"
        assert "ziraat_katilim" in plan.bank_codes
        assert plan.rate_type in (None, "financing_rate") or "konut_finansmani" in plan.axis_filters.get(
            "product_type", ()
        )


class TestRateType:
    def test_vadeli_mevduat_katilmaya_map(self) -> None:
        plan = parse_query("Vadeli mevduat getirisi en yüksek hangi bankada?")
        # konvansiyonel map + getiri → participation_yield veya aggregate
        assert plan.intent in {"aggregate", "search", "tekil_sorgu"}
        assert "participation_yield" in plan.rate_type_candidates or plan.rate_type == "participation_yield"

    def test_faiz_sorgusu_reddedilmez(self) -> None:
        plan = parse_query("En düşük faiz oranı hangi kampanyada?")
        assert plan.intent != "kapsam_disi"
