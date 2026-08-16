"""KAPI A6 — LLM çıkarıcısının birim testleri (MockProvider ile).

Bu dosya A6 geçiş koşullarının HER BİRİNİ bir teste bağlar. Hepsi gerçek
model olmadan çalışır; SPRINT 3B'de `LocalProvider` takılınca bu testler
değişmeyecek — kanıtlamak istedikleri şey modelin kalitesi değil,
pipeline'ın davranışıdır.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.ai.extraction.llm_extractor import (
    LLM_CONFIDENCE,
    _locate,
    _merge,
    extract_llm,
)
from app.ai.fields import EXTRACTABLE_FIELDS
from app.ai.providers.base import LLMResponse, LLMUnavailableError
from app.ai.providers.mock import FABRICATED_EVIDENCE, MockProvider
from app.db.models import Bank, Campaign, LLMCache, SourceDocument

PROMPT_VERSION = "v1"

METIN = (
    "Zen Pırlanta'da 3 Taksit\n"
    "Kampanya Dönemi 11-08-2026 - 31-08-2026\n"
    "Kampanya Koşulları:\n"
    "Ziraat Katılım Bankkart ile peşin fiyatına 3 taksit fırsatından faydalanabilirsiniz.\n"
    "Kampanyadan yalnızca bireysel müşterilerimiz faydalanabilir.\n"
)


class _SahteKampanya:
    """Günlükleme dışında kullanılmayan asgari kampanya nesnesi."""

    id = 1


@pytest.fixture
def kampanya() -> _SahteKampanya:
    return _SahteKampanya()


class TestAlreadyFoundFiltresi:
    """Kuralın çözdüğü alan modele SORULMAZ."""

    async def test_alan_kalmadiysa_hic_cagri_yapilmaz(
        self, db_session: Session, kampanya: _SahteKampanya
    ) -> None:
        cagrilar: list[str] = []

        class SayanProvider(MockProvider):
            async def generate(self, prompt: str, **kwargs: object) -> LLMResponse:  # type: ignore[override]
                cagrilar.append(prompt)
                return await super().generate(prompt, **kwargs)  # type: ignore[arg-type]

        sonuc = await extract_llm(
            SayanProvider(mode="null"),
            db_session,
            METIN,
            kampanya,
            set(EXTRACTABLE_FIELDS),
            prompt_version=PROMPT_VERSION,
        )

        assert cagrilar == []
        assert sonuc.llm_calls == 0
        assert sonuc.fields == []

    async def test_cozulen_alanlar_istemde_gecmez(
        self, db_session: Session, kampanya: _SahteKampanya
    ) -> None:
        yakalanan: list[str] = []

        class YakalayanProvider(MockProvider):
            async def generate(self, prompt: str, **kwargs: object) -> LLMResponse:  # type: ignore[override]
                yakalanan.append(prompt)
                return await super().generate(prompt, **kwargs)  # type: ignore[arg-type]

        await extract_llm(
            YakalayanProvider(mode="null"),
            db_session,
            METIN,
            kampanya,
            {"start_date", "end_date", "installment_count"},
            prompt_version=PROMPT_VERSION,
        )

        istem = yakalanan[0]
        istenen_satiri = istem.split("\n")[1]
        assert "start_date" not in istenen_satiri
        assert "installment_count" not in istenen_satiri
        assert "profit_rate_pct" in istenen_satiri


class TestHataYollari:
    """Model hatası kampanyayı düşürür, çalıştırmayı DEĞİL."""

    async def test_bozuk_json_yeniden_denenir_sonra_atlanir(
        self, db_session: Session, kampanya: _SahteKampanya
    ) -> None:
        deneme = {"sayi": 0}

        class SayanProvider(MockProvider):
            async def generate(self, prompt: str, **kwargs: object) -> LLMResponse:  # type: ignore[override]
                deneme["sayi"] += 1
                return await super().generate(prompt, **kwargs)  # type: ignore[arg-type]

        sonuc = await extract_llm(
            SayanProvider(mode="invalid"),
            db_session,
            METIN,
            kampanya,
            set(),
            prompt_version=PROMPT_VERSION,
        )

        # İlk deneme + bir yeniden deneme = 2 çağrı, sonra graceful skip.
        assert deneme["sayi"] == 2
        assert sonuc.skipped_reason == "invalid_json"
        assert sonuc.fields == []

    async def test_zaman_asiminda_kampanya_atlanir(
        self, db_session: Session, kampanya: _SahteKampanya
    ) -> None:
        sonuc = await extract_llm(
            MockProvider(mode="timeout"),
            db_session,
            METIN,
            kampanya,
            set(),
            prompt_version=PROMPT_VERSION,
        )
        assert sonuc.skipped_reason == "LLMTimeoutError"
        assert sonuc.fields == []

    async def test_servis_yoksa_kampanya_atlanir(
        self, db_session: Session, kampanya: _SahteKampanya
    ) -> None:
        class OlmayanServis(MockProvider):
            async def generate(self, prompt: str, **kwargs: object) -> LLMResponse:  # type: ignore[override]
                raise LLMUnavailableError("servis yok")

        sonuc = await extract_llm(
            OlmayanServis(mode="null"),
            db_session,
            METIN,
            kampanya,
            set(),
            prompt_version=PROMPT_VERSION,
        )
        assert sonuc.skipped_reason == "LLMUnavailableError"


class TestNullDavranisi:
    """Varsayılan sahte yanıt her alanı null döndürür."""

    async def test_null_yanit_alan_uretmez(
        self, db_session: Session, kampanya: _SahteKampanya
    ) -> None:
        sonuc = await extract_llm(
            MockProvider(mode="null"),
            db_session,
            METIN,
            kampanya,
            set(),
            prompt_version=PROMPT_VERSION,
        )
        # ⚠️ "Bilgi yok" DOĞRU yanıttır; boş kayıt üretilmemeli.
        assert sonuc.fields == []
        assert sonuc.llm_calls >= 1


class TestHalusinasyonHazirligi:
    """`halluc` kipi guard'ın (KAPI A7) reddedeceği kaydı üretir."""

    async def test_kaynakta_olmayan_kanit_isaretlenir(
        self, db_session: Session, kampanya: _SahteKampanya
    ) -> None:
        sonuc = await extract_llm(
            MockProvider(mode="halluc"),
            db_session,
            METIN,
            kampanya,
            set(),
            prompt_version=PROMPT_VERSION,
        )

        assert sonuc.fields, "halluc kipi alan üretmeli"
        for alan in sonuc.fields:
            # ⚠️ Kayıt ATILMAZ ama ofsetsiz ve notlu gelir: guard reddedecek,
            # halüsinasyon oranı ancak böyle raporlanabilir.
            assert alan.evidence_char_start is None
            assert alan.validation_note == "kanıt kaynakta bulunamadı"
            assert alan.evidence_text == FABRICATED_EVIDENCE
            assert alan.confidence == LLM_CONFIDENCE


class TestOnbellek:
    """İkinci çağrı modele gitmez."""

    async def test_ikinci_calistirma_onbellekten_gelir(
        self, db_session: Session, kampanya: _SahteKampanya
    ) -> None:
        saglayici = MockProvider(mode="null")

        ilk = await extract_llm(
            saglayici, db_session, METIN, kampanya, set(), prompt_version=PROMPT_VERSION
        )
        ikinci = await extract_llm(
            saglayici, db_session, METIN, kampanya, set(), prompt_version=PROMPT_VERSION
        )

        assert ilk.cache_hits == 0
        assert ikinci.cache_hits == ikinci.llm_calls > 0
        assert db_session.query(LLMCache).count() >= 1

    async def test_model_degisince_onbellek_gecersizlesir(
        self, db_session: Session, kampanya: _SahteKampanya
    ) -> None:
        """⚠️ Model adı anahtara dahildir; SPRINT 3B'de gerçek model
        takılınca önbellek KENDİLİĞİNDEN geçersizleşmeli. Aksi hâlde
        mock yanıtları gerçek modelin sonucu sanılırdı."""
        await extract_llm(
            MockProvider(mode="null"),
            db_session,
            METIN,
            kampanya,
            set(),
            prompt_version=PROMPT_VERSION,
        )
        # `halluc` farklı bir model adı üretir (mock:halluc): önbellek ıskalar.
        ikinci = await extract_llm(
            MockProvider(mode="halluc"),
            db_session,
            METIN,
            kampanya,
            set(),
            prompt_version=PROMPT_VERSION,
        )
        assert ikinci.cache_hits == 0


class TestKanitKonumu:
    """Kanıtın kaynak metindeki aralığı doğru bulunur."""

    def test_birebir_eslesme(self) -> None:
        aralik = _locate("peşin fiyatına 3 taksit", METIN)
        assert aralik is not None
        assert METIN[aralik[0] : aralik[1]] == "peşin fiyatına 3 taksit"

    def test_satir_sonu_farkina_dayanikli(self) -> None:
        # Model satır sonunu boşluğa çevirmiş olabilir.
        aralik = _locate("Kampanya Koşulları: Ziraat Katılım Bankkart", METIN)
        assert aralik is not None
        assert "Ziraat Katılım Bankkart" in METIN[aralik[0] : aralik[1]]

    def test_kaynakta_olmayan_kanit_bulunamaz(self) -> None:
        assert _locate(FABRICATED_EVIDENCE, METIN) is None

    def test_cok_kisa_kanit_aranmaz(self) -> None:
        # ⚠️ Kısa dize her yerde eşleşir; kanıt doğrulamasını anlamsızlaştırır.
        assert _locate("3", METIN) is None


class TestParcaBirlestirme:
    """Bölünmüş metnin sonuçları birleşir."""

    def test_alan_basina_ilk_dolu_deger(self) -> None:
        from decimal import Decimal

        from app.ai.extraction.rule_based import ExtractedField

        def alan(deger: str) -> ExtractedField:
            return ExtractedField(
                field_name="profit_rate_pct",
                value_raw=deger,
                value_normalized=deger,
                unit="pct",
                evidence_text=deger,
                evidence_char_start=0,
                evidence_char_end=1,
                confidence=Decimal("0.70"),
                method="llm",
            )

        birlesik = _merge([[alan("2.05")], [alan("9.99")]])
        assert len(birlesik) == 1
        assert birlesik[0].value_normalized == "2.05"


class TestUzunMetinBolunur:
    """6000 karakteri aşan metin birden çok çağrıya bölünür."""

    async def test_uzun_metin_birden_cok_cagri_uretir(
        self, db_session: Session, kampanya: _SahteKampanya
    ) -> None:
        uzun = "\n\n".join(f"Kampanya koşulu {i} numaralı madde. " * 40 for i in range(12))
        assert len(uzun) > 6000

        sonuc = await extract_llm(
            MockProvider(mode="null"),
            db_session,
            uzun,
            kampanya,
            set(),
            prompt_version=PROMPT_VERSION,
        )
        assert sonuc.llm_calls > 1


class TestPipelineUctanUca:
    """`run_extraction` üç kipte de çalışır ve sayaçları doğru kapatır."""

    @pytest.fixture
    def kampanyali_db(self, db_session: Session) -> Session:
        bank = Bank(code="test_bank", name="Test", website="https://ornek.test")
        db_session.add(bank)
        db_session.flush()
        belge = SourceDocument(
            bank_id=bank.id,
            url="https://ornek.test/k1",
            url_hash="h1",
            doc_type="campaign",
            clean_text=METIN,
        )
        db_session.add(belge)
        db_session.flush()
        db_session.add(
            Campaign(
                bank_id=bank.id,
                source_document_id=belge.id,
                external_slug="k1",
                title="Zen Pırlanta'da 3 Taksit",
                source_url="https://ornek.test/k1",
                status="unknown",
                date_precision="unknown",
            )
        )
        db_session.flush()
        return db_session

    async def test_hybrid_kipi_ucdan_uca_calisir(self, kampanyali_db: Session) -> None:
        from app.ai.pipeline import run_extraction

        ozet = await run_extraction(
            kampanyali_db, MockProvider(mode="null"), mode="hybrid", bank_code="test_bank"
        )
        assert ozet.campaigns_processed == 1
        assert ozet.errors_count == 0
        assert ozet.status == "success"
        # Kural katmanı tarih ve taksiti çözdüğü için LLM'e daha az alan sorulur.
        assert ozet.fields_extracted > 0

    async def test_rule_only_kipinde_llm_cagrilmaz(self, kampanyali_db: Session) -> None:
        from app.ai.pipeline import run_extraction

        ozet = await run_extraction(kampanyali_db, None, mode="rule_only", bank_code="test_bank")
        assert ozet.llm_calls == 0

    async def test_llm_kipinde_saglayici_zorunlu(self, kampanyali_db: Session) -> None:
        from app.ai.pipeline import run_extraction

        with pytest.raises(ValueError, match="sağlayıcı"):
            await run_extraction(kampanyali_db, None, mode="hybrid")

    async def test_timeout_kipinde_calistirma_devam_eder(self, kampanyali_db: Session) -> None:
        from app.ai.pipeline import run_extraction

        ozet = await run_extraction(
            kampanyali_db, MockProvider(mode="timeout"), mode="hybrid", bank_code="test_bank"
        )
        # ⚠️ Kampanya atlandı ama ÇALIŞTIRMA ÇÖKMEDİ ve kural sonuçları kaldı.
        assert ozet.campaigns_processed == 1
        assert ozet.llm_skipped == 1
        assert ozet.errors_count == 0
        assert ozet.fields_extracted > 0

    async def test_invalid_kipinde_calistirma_devam_eder(self, kampanyali_db: Session) -> None:
        from app.ai.pipeline import run_extraction

        ozet = await run_extraction(
            kampanyali_db, MockProvider(mode="invalid"), mode="hybrid", bank_code="test_bank"
        )
        assert ozet.llm_skipped == 1
        assert ozet.errors_count == 0

    async def test_tanimsiz_kip_reddedilir(self, kampanyali_db: Session) -> None:
        from app.ai.pipeline import run_extraction

        with pytest.raises(ValueError, match="Tanımsız çıkarım kipi"):
            await run_extraction(kampanyali_db, None, mode="sihirli_kip")
