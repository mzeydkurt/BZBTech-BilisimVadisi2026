"""Güven puanlı alan yönlendirmesi — açık uçlu soru katılmaya kilitlenmez."""

from __future__ import annotations

from app.retrieval.query import parse_query
from app.retrieval.routing import AMBIGUITY_GAP, score_domains
from app.retrieval.slots import extract_slots
from app.services.chat_tools import detect_tool


class TestScoreDomains:
    def test_katilma_hesabi_yuksek_guven(self) -> None:
        plan = parse_query("Katılma hesabı getirisi ne kadar?")
        assert plan.source_domain == "katilma"
        assert plan.domain_confidence >= 0.55
        assert plan.domain_ambiguous is False

    def test_konut_finansmani_yuksek_guven(self) -> None:
        plan = parse_query("Konut finansmanı oranı hangi bankada düşük?")
        assert plan.source_domain == "finansman"
        assert plan.domain_confidence >= 0.55

    def test_kampanya_sinyali(self) -> None:
        plan = parse_query("En yüksek nakit iade veren kampanyalar")
        assert plan.source_domain == "kampanya"

    def test_acik_uclu_kar_payi_kilitlemez(self) -> None:
        """'kâr payı olarak ne kadar öderim' tek başına katılmaya kilitlenmemeli."""
        plan = parse_query(
            "Bana en uygun seçenekleri önerir misin, kâr payı olarak ne kadar öderim?"
        )
        # Tek sözcüklük 'kar payi' paylaşımlı düşük sinyal → belirsiz veya finansman.
        assert plan.source_domain != "katilma" or plan.domain_ambiguous
        if plan.source_domain == "katilma":
            assert plan.domain_ambiguous is True

    def test_getiri_tek_basina_dusuk_guven(self) -> None:
        karar = score_domains(
            "getiri ne kadar",
            intent="search",
            rate_type=None,
            axis_filters={},
        )
        assert karar.domain == "katilma"
        assert karar.confidence <= 0.55 or karar.is_ambiguous or karar.confidence == 0.25

    def test_belirsizlik_esigi(self) -> None:
        karar = score_domains(
            "kar payi oran",
            intent="search",
            rate_type=None,
            axis_filters={},
        )
        # Paylaşımlı sinyaller birden fazla alana puan verir.
        assert karar.is_ambiguous or abs(
            max(karar.scores.values()) - sorted(karar.scores.values())[-2]
        ) < AMBIGUITY_GAP + 0.01

    def test_tanim_ve_kapsam(self) -> None:
        assert parse_query("Murabaha nedir?").source_domain == "tanim"
        assert parse_query("Yarın hava nasıl?").source_domain == "kapsam_disi"

    def test_milyon_puan_mil_uretmez(self) -> None:
        """'mil' kökü 'milyon' içinde puan/mil faydası üretmemeli."""
        plan = parse_query(
            "1 milyon liralık araç almak istiyorum. benim için en mantıklı finansman hangisi"
        )
        assert "puan_mil" not in plan.axis_filters.get("benefit", ())
        assert plan.source_domain == "finansman"
        assert all(s.value != "puan_mil" for s in plan.signals if s.kind == "benefit")

    def test_limitler_tanim_degil(self) -> None:
        plan = parse_query("taşıt finansmanında limitler nedir")
        assert plan.intent != "tanim"
        assert plan.source_domain == "finansman"
        assert plan.axis_filters.get("product_type") == ("tasit_finansmani",)

    def test_kampanya_taksit_finansmana_dusmez(self) -> None:
        """'kampanyaları getirir misin' → katılma/finansman simülasyonu değil."""
        plan = parse_query(
            "Bana ziraat katılımın taksit avantajı olduğu kampanyaları getirir misin"
        )
        assert plan.source_domain == "kampanya"
        assert plan.rate_type is None
        assert "taksit" in plan.axis_filters.get("benefit", ())
        slots = extract_slots(plan.raw, bank_codes=plan.bank_codes)
        assert detect_tool(plan.raw, source_domain=plan.source_domain, slots=slots) is None
        assert slots.tool_hint != "finansman_teklif"

    def test_getirir_participation_yield_uretmez(self) -> None:
        plan = parse_query("kampanyaları getirir misin")
        assert "participation_yield" not in plan.rate_type_candidates

    def test_iki_banka_avantajli_compare(self) -> None:
        from app.retrieval.query import karsilastirma_konusu_belirsiz

        plan = parse_query("Kuveyt Türk mü daha avantajlı, Albaraka mı?")
        assert plan.intent == "compare"
        assert plan.bank_codes == ("kuveyt_turk", "albaraka")
        assert karsilastirma_konusu_belirsiz(plan)

    def test_iki_banka_konu_belli_netlestirme_yok(self) -> None:
        from app.retrieval.query import karsilastirma_konusu_belirsiz

        plan = parse_query(
            "Kuveyt Türk ile Albaraka katılma hesabı getirisinde hangisi daha iyi"
        )
        assert not karsilastirma_konusu_belirsiz(plan)

