"""Slot çıkarımı, araç tetikleme ve LLM slot doğrulaması."""

from __future__ import annotations

from decimal import Decimal

from app.retrieval.slots import (
    extract_slots,
    missing_for_tool,
    validate_numeric_slots_against_query,
)
from app.services.chat_tools import detect_tool


class TestExtractSlots:
    def test_tutar_ve_vade(self) -> None:
        slots = extract_slots("400.000 TL, 48 ay vadeli bir finansman istiyorum")
        assert slots.amount_try == Decimal("400000")
        assert slots.term_months == 48

    def test_milyon_carpan(self) -> None:
        slots = extract_slots("Evimin kasko değeri 5 milyon, enerji sınıfı A")
        assert slots.amount_try == Decimal("5000000")
        assert slots.asset_value_try == Decimal("5000000")
        assert slots.energy_class == "A"

    def test_urun_turu(self) -> None:
        assert extract_slots("taşıt finansmanı istiyorum").product_type == "tasit_finansmani"
        assert extract_slots("konut için 100 ay").product_type == "konut_finansmani"
        assert extract_slots("ihtiyaç finansmanı").product_type == "ihtiyac_finansmani"

    def test_vade_kelimesi(self) -> None:
        slots = extract_slots("1 milyon TL taşıt 36 vade")
        assert slots.term_months == 36
        assert slots.amount_try == Decimal("1000000")

    def test_vade_tutar_sanilmaz(self) -> None:
        """'120 ay vadeli konut' → tutar yok, vade 120; 120 TL uydurma."""
        slots = extract_slots("Bana 120 ay vadeli bir konut finansmanı önerir misin")
        assert slots.term_months == 120
        assert slots.amount_try is None
        assert slots.product_type == "konut_finansmani"
        assert (
            detect_tool(
                "Bana 120 ay vadeli bir konut finansmanı önerir misin",
                source_domain="finansman",
                slots=slots,
            )
            == "finansman_teklif"
        )
        assert "amount_try" in missing_for_tool("finansman_teklif", slots)

    def test_ikinci_el_araba_500bin(self) -> None:
        """'2.el' tutar değil; 500 bin + 12 ay taşıt olarak okunur (ölçüldü)."""
        q = (
            "ben 2. el araba alacağım ancak 500bin tutaarında bir eksiğim var "
            "bunu hangi bankadan faizsiz bir şekilde eksiğimi giderebilirim "
            "ben aracı 2 hafta sonra alcam 12 ayda da öderim ama 12 ayı geçen "
            "senaryoda 50 bin ödeyebilirim anca"
        )
        slots = extract_slots(q)
        assert slots.amount_try == Decimal("500000")
        assert slots.term_months == 12
        assert slots.product_type == "tasit_finansmani"

    def test_coklu_vade(self) -> None:
        slots = extract_slots(
            "1 milyon liralık araç, en mantıklı finansman hangisi 12 veya 24 vade"
        )
        assert slots.amount_try == Decimal("1000000")
        assert slots.product_type == "tasit_finansmani"
        assert slots.term_months is None
        assert slots.term_months_options == [12, 24]
        assert slots.tool_hint == "finansman_teklif"


class TestDetectTool:
    def test_finansman_teklif(self) -> None:
        q = "400.000 TL 48 ay vadeli finansman istiyorum bana uygunları bul"
        slots = extract_slots(q)
        assert detect_tool(q, source_domain="finansman", slots=slots) == "finansman_teklif"

    def test_arac_mantikli_finansman(self) -> None:
        q = "1 milyon liralık araç almak istiyorum. benim için en mantıklı finansman hangisi"
        slots = extract_slots(q)
        assert slots.product_type == "tasit_finansmani"
        assert detect_tool(q, source_domain="finansman", slots=slots) == "finansman_teklif"
        assert "term_months" in missing_for_tool("finansman_teklif", slots)

    def test_bddk(self) -> None:
        q = "BDDK limiti nedir, kasko değeri 5 milyon enerji sınıfı A"
        slots = extract_slots(q)
        assert detect_tool(q, source_domain="finansman", slots=slots) == "bddk_limit"

    def test_tasit_limitleri_genel(self) -> None:
        q = "taşıt finansmanında limitler nedir"
        slots = extract_slots(q)
        assert slots.tool_hint == "bddk_limit"
        assert slots.product_type == "tasit_finansmani"
        assert detect_tool(q, source_domain="finansman", slots=slots) == "bddk_limit"
        assert missing_for_tool("bddk_limit", slots) == []

    def test_kampanya_sorusu_finansman_araci_degil(self) -> None:
        q = "Ziraat katılımın taksit avantajlı kampanyalarını getirir misin"
        slots = extract_slots(q)
        assert slots.tool_hint != "finansman_teklif"
        assert detect_tool(q, source_domain="kampanya", slots=slots) is None

    def test_katilma_yatirim_getiri_hesabi(self) -> None:
        q = (
            "ben ziraat katılımdan 3 aylık standart katılım hesabına "
            "10000 tl yatırsam dönem sonu bu param ne kadar olma ihtimali var"
        )
        slots = extract_slots(q, bank_codes=("ziraat_katilim",))
        assert slots.deposit_try == Decimal("10000")
        assert slots.term_months == 3
        assert detect_tool(q, source_domain="katilma", slots=slots) == "katilma_getiri"
        assert missing_for_tool("katilma_getiri", slots) == []

    def test_katilma_oran_listesi_hesaplayici_degil(self) -> None:
        from app.retrieval.query import katilma_oran_listesi_mi

        q = "ziraatin aylık 3 aylık 6 aylık ve yıllık oranları nedir katılım hesabında"
        assert katilma_oran_listesi_mi(q)
        slots = extract_slots(q, bank_codes=("ziraat_katilim",))
        assert slots.deposit_try is None
        assert detect_tool(q, source_domain="katilma", slots=slots) is None

        q2 = q + " 10000"
        assert katilma_oran_listesi_mi(q2)
        slots2 = extract_slots(q2, bank_codes=("ziraat_katilim",))
        assert slots2.deposit_try is None
        assert detect_tool(q2, source_domain="katilma", slots=slots2) is None

    def test_limitlerini_merak(self) -> None:
        q = "Taşıt finansmanı limitlerini merak ediyorum"
        slots = extract_slots(q)
        assert detect_tool(q, source_domain="finansman", slots=slots) == "bddk_limit"

    def test_eksik_urun_turu(self) -> None:
        slots = extract_slots("400.000 TL 48 ay finansman")
        assert "product_type" in missing_for_tool("finansman_teklif", slots)


class TestValidateNumericSlots:
    def test_sorguda_olmayan_sayi_reddedilir(self) -> None:
        temiz, reddedilen = validate_numeric_slots_against_query(
            "bana uygun finansman bul",
            {"amount_try": "999999", "term_months": 36},
        )
        assert "amount_try" in reddedilen
        assert "term_months" in reddedilen
        assert "amount_try" not in temiz

    def test_sorgudaki_sayi_kabul(self) -> None:
        temiz, reddedilen = validate_numeric_slots_against_query(
            "400000 TL 48 ay taşıt",
            {"amount_try": "400000", "term_months": 48, "product_type": "tasit_finansmani"},
        )
        assert "amount_try" not in reddedilen
        assert temiz.get("amount_try") == "400000"
        assert temiz.get("product_type") == "tasit_finansmani"

    def test_coklu_vade_adayi_kabul(self) -> None:
        temiz, reddedilen = validate_numeric_slots_against_query(
            "1 milyon araç 12 veya 24 vade",
            {"term_months": 12},
        )
        assert "term_months" not in reddedilen
        assert temiz.get("term_months") == "12"
