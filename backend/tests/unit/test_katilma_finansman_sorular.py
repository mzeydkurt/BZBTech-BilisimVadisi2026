"""Katılma ve finansman — öngörülen soru kalıpları (kavram ayrımı, oran listesi)."""

from __future__ import annotations

from decimal import Decimal

from app.retrieval.query import (
    finansman_oran_listesi_mi,
    katilma_kar_payi_paylasim_karsilastirma_mi,
    katilma_oran_listesi_mi,
    parse_query,
)
from app.retrieval.slots import extract_slots
from app.services.chat_tools import detect_tool


class TestKatilmaKavramAyrimi:
    def test_kar_payi_paylasim_karsilastirma(self) -> None:
        q = "dağıtılan kâr payı ile kâr paylaşım oranı aynı mı katılma hesabında"
        assert katilma_kar_payi_paylasim_karsilastirma_mi(q)
        assert detect_tool(q, source_domain="katilma", slots=extract_slots(q)) is None

    def test_kar_payi_paylasim_farki_nedir(self) -> None:
        q = "kar payi ile kar paylasim orani farki nedir"
        assert katilma_kar_payi_paylasim_karsilastirma_mi(q)

    def test_sadece_paylasim_orani_tek_aday(self) -> None:
        plan = parse_query("ziraat katılım kâr paylaşım oranı nedir")
        assert plan.source_domain == "katilma"
        assert plan.rate_type == "profit_sharing_ratio"

    def test_sadece_getiri_tek_aday(self) -> None:
        plan = parse_query("ziraat katılma hesabı dağıtılan kâr payı oranları")
        assert plan.rate_type == "participation_yield"
        assert "profit_sharing_ratio" not in plan.rate_type_candidates


class TestOranListesiSimulasyonAyrimi:
    def test_katilma_oran_listesi_tutar_temizlenir(self) -> None:
        q = (
            "ziraatin aylık 3 aylık 6 aylık ve yıllık oranları nedir "
            "katılım hesabında 10000"
        )
        assert katilma_oran_listesi_mi(q)
        slots = extract_slots(q, bank_codes=("ziraat_katilim",))
        assert slots.deposit_try is None
        assert detect_tool(q, source_domain="katilma", slots=slots) is None

    def test_katilma_hesaplama_oran_listesi_degil(self) -> None:
        q = "10000 tl yatırsam 3 ay sonra ne kadar kazanırım katılma hesabında"
        assert not katilma_oran_listesi_mi(q)
        slots = extract_slots(q)
        assert slots.deposit_try == Decimal("10000")
        assert detect_tool(q, source_domain="katilma", slots=slots) == "katilma_getiri"

    def test_finansman_oran_listesi(self) -> None:
        q = "konut finansmanı kâr payı oranları hangi bankada düşük"
        assert finansman_oran_listesi_mi(q)
        assert detect_tool(q, source_domain="finansman", slots=extract_slots(q)) is None

    def test_finansman_hesaplama_oran_listesi_degil(self) -> None:
        q = "400.000 TL 48 ay konut finansmanı hesapla"
        assert not finansman_oran_listesi_mi(q)
        slots = extract_slots(q)
        assert detect_tool(q, source_domain="finansman", slots=slots) == "finansman_teklif"

    def test_finansman_kar_payi_katilma_getirisi_karistirilmaz(self) -> None:
        plan = parse_query("en düşük konut finansman kâr payı oranı")
        assert plan.source_domain == "finansman"
        assert plan.rate_type == "financing_rate"
        assert "participation_yield" not in plan.rate_type_candidates
