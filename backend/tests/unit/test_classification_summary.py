"""KAPI A8 — sınıflandırma boşluk doldurma ve özetleme testleri.

⚠️ Sahte yanıtlar `MockProvider` alt sınıflarıyla verilir, fixture dosyası
ile DEĞİL. Fixture adı istem özetinden türüyor; prompt metni değişince
sessizce bulunamaz hâle gelir ve test "fixture yok" yoluna düşerek
GEÇMEYE DEVAM EDER. Kanıtlamak istediğimiz davranış o zaman hiç
sınanmamış olur.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.classification import (
    LLM_LABEL_CONFIDENCE,
    complete_classification,
    missing_axes,
)
from app.ai.providers.base import LLMResponse
from app.ai.providers.mock import MockProvider
from app.ai.summarization import (
    REASON_EMPTY,
    REASON_FORBIDDEN_TERM,
    REASON_UNSUPPORTED_NUMBER,
    summarize,
    validate_summary,
)
from app.ai.validation.terminology import load_forbidden_terms
from app.db.models import Bank, Campaign, CampaignCategory, SourceDocument

PROMPT_VERSION = "v1"

KAYNAK = (
    "Emeklilere Özel Market Kampanyası\n"
    "Maaşını bankamızdan alan emekli müşterilerimize market alışverişlerinde "
    "%10 indirim ve 250 TL nakit iade.\n"
    "Kampanya 31.12.2026 tarihine kadar geçerlidir.\n"
)


class SabitYanitProvider(MockProvider):
    """Verilen JSON'u aynen döndüren sahte sağlayıcı."""

    def __init__(self, payload: dict[str, Any]) -> None:
        super().__init__(mode="null")
        self._payload = payload

    async def generate(self, prompt: str, **kwargs: Any) -> LLMResponse:
        del prompt, kwargs
        metin = json.dumps(self._payload, ensure_ascii=False)
        return LLMResponse(
            text=metin,
            parsed=self._payload,
            latency_ms=1,
            from_cache=False,
            model_name=self.model_info.name,
        )


def _etiket(eksen: str, deger: str, guven: str, kaynak: str = "keyword") -> CampaignCategory:
    """Test için etiket nesnesi (veritabanına yazılmamış)."""
    return CampaignCategory(
        campaign_id=1, axis=eksen, value=deger, confidence=Decimal(guven), source=kaynak
    )


class TestEksenSecimi:
    """Hangi eksenler modele sorulur?"""

    def test_etiketi_olmayan_eksen_istenir(self) -> None:
        assert "audience" in missing_axes({})

    def test_guven_bir_olan_eksene_dokunulmaz(self) -> None:
        """⚠️ URL ve banka etiketi kaynağın kendi beyanıdır."""
        mevcut = {"product_type": [_etiket("product_type", "kart", "1.000", "url")]}
        assert "product_type" not in missing_axes(mevcut)

    def test_sector_genel_bos_sayilir(self) -> None:
        """⚠️ `genel` bir etiket değil, etiketlenememenin adıdır."""
        mevcut = {"sector": [_etiket("sector", "genel", "0.900")]}
        assert "sector" in missing_axes(mevcut)

    def test_zayif_etiketli_eksen_istenir(self) -> None:
        mevcut = {"sector": [_etiket("sector", "market_gida", "0.300")]}
        assert "sector" in missing_axes(mevcut)

    def test_guclu_etiketli_eksen_istenmez(self) -> None:
        mevcut = {"sector": [_etiket("sector", "market_gida", "0.800")]}
        assert "sector" not in missing_axes(mevcut)

    def test_zayif_ve_guven_bir_birlikteyse_dokunulmaz(self) -> None:
        """Bir eksende hem zayıf hem kesin etiket varsa kesin olan korur."""
        mevcut = {
            "sector": [
                _etiket("sector", "market_gida", "0.300"),
                _etiket("sector", "akaryakit", "1.000", "url"),
            ]
        }
        assert "sector" not in missing_axes(mevcut)


@pytest.fixture
def kampanya(db_session: Session) -> Campaign:
    """Kaynak belgesiyle birlikte test kampanyası."""
    bank = Bank(code="a8_bank", name="A8", website="https://ornek.test")
    db_session.add(bank)
    db_session.flush()
    belge = SourceDocument(
        bank_id=bank.id,
        url="https://ornek.test/a8",
        url_hash="a8",
        doc_type="campaign",
        clean_text=KAYNAK,
    )
    db_session.add(belge)
    db_session.flush()
    kayit = Campaign(
        bank_id=bank.id,
        source_document_id=belge.id,
        external_slug="a8",
        title="Emeklilere Özel Market Kampanyası",
        source_url="https://ornek.test/a8",
        status="unknown",
        date_precision="unknown",
    )
    db_session.add(kayit)
    db_session.flush()
    return kayit


class TestSiniflandirma:
    """Boşluk doldurma davranışı."""

    async def test_sozluk_ici_etiket_eklenir(self, db_session: Session, kampanya: Campaign) -> None:
        saglayici = SabitYanitProvider(
            {"audience": [{"value": "emekli", "evidence": "emekli müşterilerimize"}]}
        )
        sonuc = await complete_classification(
            saglayici, db_session, kampanya, KAYNAK, prompt_version=PROMPT_VERSION
        )

        assert len(sonuc.added) >= 1
        eklenen = {(k.axis, k.value) for k in sonuc.added}
        assert ("audience", "emekli") in eklenen
        assert all(k.source == "llm" for k in sonuc.added)
        assert all(k.confidence == LLM_LABEL_CONFIDENCE for k in sonuc.added)

    async def test_sozluk_disi_etiket_reddedilir(
        self, db_session: Session, kampanya: Campaign
    ) -> None:
        """⚠️ Sözlük dışı değer veritabanı CHECK kısıtını ihlal ederdi."""
        saglayici = SabitYanitProvider(
            {"audience": [{"value": "emekliler_ve_yaslilar", "evidence": "emekli"}]}
        )
        sonuc = await complete_classification(
            saglayici, db_session, kampanya, KAYNAK, prompt_version=PROMPT_VERSION
        )

        assert ("audience", "emekliler_ve_yaslilar") in sonuc.rejected_labels
        assert all(k.value != "emekliler_ve_yaslilar" for k in sonuc.added)

    async def test_guven_bir_etiketin_uzerine_yazilmaz(
        self, db_session: Session, kampanya: Campaign
    ) -> None:
        """⚠️ KAPI A8 geçiş koşulu."""
        db_session.add(
            CampaignCategory(
                campaign_id=kampanya.id,
                axis="product_type",
                value="kart",
                confidence=Decimal("1.000"),
                source="url",
            )
        )
        db_session.flush()

        saglayici = SabitYanitProvider(
            {"product_type": [{"value": "finansman", "evidence": "uydurma"}]}
        )
        sonuc = await complete_classification(
            saglayici, db_session, kampanya, KAYNAK, prompt_version=PROMPT_VERSION
        )

        assert "product_type" not in sonuc.requested_axes
        kayitlar = db_session.scalars(
            select(CampaignCategory).where(
                CampaignCategory.campaign_id == kampanya.id,
                CampaignCategory.axis == "product_type",
            )
        ).all()
        assert {k.value for k in kayitlar} == {"kart"}

    async def test_mevcut_etiket_tekrar_eklenmez(
        self, db_session: Session, kampanya: Campaign
    ) -> None:
        db_session.add(
            CampaignCategory(
                campaign_id=kampanya.id,
                axis="audience",
                value="emekli",
                confidence=Decimal("0.300"),
                source="keyword",
            )
        )
        db_session.flush()

        saglayici = SabitYanitProvider({"audience": [{"value": "emekli", "evidence": "emekli"}]})
        sonuc = await complete_classification(
            saglayici, db_session, kampanya, KAYNAK, prompt_version=PROMPT_VERSION
        )
        assert all(k.value != "emekli" for k in sonuc.added)

    async def test_doldurulacak_eksen_yoksa_cagri_yapilmaz(
        self, db_session: Session, kampanya: Campaign
    ) -> None:
        for eksen, deger in (
            ("product_type", "kart"),
            ("sector", "market_gida"),
            ("audience", "emekli"),
            ("benefit", "indirim"),
        ):
            db_session.add(
                CampaignCategory(
                    campaign_id=kampanya.id,
                    axis=eksen,
                    value=deger,
                    confidence=Decimal("1.000"),
                    source="url",
                )
            )
        db_session.flush()

        cagrildi = {"evet": False}

        class SayanProvider(SabitYanitProvider):
            async def generate(self, prompt: str, **kwargs: Any) -> LLMResponse:
                cagrildi["evet"] = True
                return await super().generate(prompt, **kwargs)

        sonuc = await complete_classification(
            SayanProvider({}), db_session, kampanya, KAYNAK, prompt_version=PROMPT_VERSION
        )
        assert cagrildi["evet"] is False
        assert sonuc.llm_calls == 0

    async def test_saglayici_hatasi_calistirmayi_dusurmez(
        self, db_session: Session, kampanya: Campaign
    ) -> None:
        sonuc = await complete_classification(
            MockProvider(mode="timeout"),
            db_session,
            kampanya,
            KAYNAK,
            prompt_version=PROMPT_VERSION,
        )
        assert sonuc.skipped_reason == "LLMTimeoutError"
        assert sonuc.added == []


class TestOzetDogrulamasi:
    """Üretilen özet iki katmandan geçmeden kaydedilmez."""

    def test_kaynaktaki_sayilarla_ozet_kabul(self, seeded_session: Session) -> None:
        terimler = load_forbidden_terms(seeded_session)
        ozet = (
            "Emekli müşterilere market alışverişlerinde %10 indirim ve 250 TL "
            "nakit iade sağlanır. Kampanya 31.12.2026 tarihine kadar geçerlidir."
        )
        sonuc = validate_summary(ozet, KAYNAK, terimler)
        assert sonuc.accepted
        assert sonuc.summary == ozet

    def test_uydurma_sayili_ozet_reddedilir(self, seeded_session: Session) -> None:
        """⚠️ KAPI A8 geçiş koşulu."""
        terimler = load_forbidden_terms(seeded_session)
        ozet = (
            "Emekli müşterilere market alışverişlerinde %35 indirim ve 9999 TL nakit iade sağlanır."
        )
        sonuc = validate_summary(ozet, KAYNAK, terimler)

        assert not sonuc.accepted
        assert sonuc.summary is None
        assert sonuc.rejected_reason == REASON_UNSUPPORTED_NUMBER
        assert Decimal("9999") in sonuc.unsupported_numbers

    def test_yasakli_terimli_ozet_reddedilir(self, seeded_session: Session) -> None:
        """⚠️ Terminoloji guard'ı kasıtlı testte tetiklenir."""
        terimler = load_forbidden_terms(seeded_session)
        ozet = (
            "Emekli müşterilere market alışverişlerinde %10 indirim sağlanır ve "
            "faiz oranı uygulanmaz."
        )
        sonuc = validate_summary(ozet, KAYNAK, terimler)

        assert not sonuc.accepted
        assert sonuc.rejected_reason == REASON_FORBIDDEN_TERM
        assert sonuc.terminology_warnings

    def test_bos_ozet_reddedilir(self, seeded_session: Session) -> None:
        terimler = load_forbidden_terms(seeded_session)
        assert validate_summary("", KAYNAK, terimler).rejected_reason == REASON_EMPTY
        assert validate_summary(None, KAYNAK, terimler).rejected_reason == REASON_EMPTY

    def test_tarih_sayi_sanilmaz(self, seeded_session: Session) -> None:
        """⚠️ `31.12.2026` binlik ayraçlı sayı olarak okunursa kaynakla
        BİREBİR AYNI özet bile reddedilirdi."""
        terimler = load_forbidden_terms(seeded_session)
        sonuc = validate_summary(KAYNAK, KAYNAK, terimler)
        assert sonuc.accepted


class TestOzetlemeUctanUca:
    """`summarize()` doğrulamayı uygular mı?"""

    async def test_uydurma_sayili_ozet_kaydedilmez(
        self, db_session: Session, kampanya: Campaign
    ) -> None:
        saglayici = SabitYanitProvider(
            {"summary": "Kampanyada %77 indirim ve 8888 TL iade uygulanır.", "key_points": []}
        )
        sonuc = await summarize(
            saglayici, db_session, kampanya, KAYNAK, {}, prompt_version=PROMPT_VERSION
        )
        assert not sonuc.accepted
        assert sonuc.rejected_reason == REASON_UNSUPPORTED_NUMBER
        assert kampanya.summary_ai is None

    async def test_gecerli_ozet_kabul_edilir(self, db_session: Session, kampanya: Campaign) -> None:
        metin = "Emekli müşterilere market alışverişlerinde %10 indirim ve 250 TL iade verilir."
        saglayici = SabitYanitProvider({"summary": metin, "key_points": ["%10 indirim"]})
        sonuc = await summarize(
            saglayici, db_session, kampanya, KAYNAK, {}, prompt_version=PROMPT_VERSION
        )
        assert sonuc.accepted
        assert sonuc.summary == metin
        assert sonuc.key_points == ["%10 indirim"]

    async def test_saglayici_hatasi_ozeti_atlar(
        self, db_session: Session, kampanya: Campaign
    ) -> None:
        sonuc = await summarize(
            MockProvider(mode="timeout"),
            db_session,
            kampanya,
            KAYNAK,
            {},
            prompt_version=PROMPT_VERSION,
        )
        assert sonuc.skipped_reason == "LLMTimeoutError"
        assert sonuc.summary is None


class TestPipelineEntegrasyonu:
    """A8 pipeline'a bağlı mı?"""

    async def test_hybrid_kipinde_ozet_reddi_sayilir(
        self, db_session: Session, kampanya: Campaign
    ) -> None:
        from app.ai.pipeline import run_extraction

        ozet = await run_extraction(
            db_session, MockProvider(mode="null"), mode="hybrid", bank_code="a8_bank"
        )
        # `null` kipinde model boş özet döner → reddedilir, summary_ai None kalır.
        assert ozet.summaries_rejected == 1
        assert ozet.summaries_written == 0
        assert kampanya.summary_ai is None

    async def test_rule_only_kipinde_a8_calismaz(
        self, db_session: Session, kampanya: Campaign
    ) -> None:
        from app.ai.pipeline import run_extraction

        ozet = await run_extraction(db_session, None, mode="rule_only", bank_code="a8_bank")
        assert ozet.labels_added == 0
        assert ozet.summaries_written == 0
        assert ozet.summaries_rejected == 0
