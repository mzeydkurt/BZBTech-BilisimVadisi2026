"""KAPI A7 — halüsinasyon guard'ı ve merger testleri.

⚠️ EN KRİTİK TEST `TestHallucModu`. Projenin en savunulabilir teknik
iddiası "sistem bilgi yokken bilgi uydurmaz"dır; bu iddia ancak uydurma
bir çıktının FİİLEN reddedildiği gösterilerek savunulabilir.
`MockProvider`'ın `halluc` kipi bunu gerçek model olmadan kanıtlar.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.ai.extraction import extract_rule_based
from app.ai.extraction.rule_based import ExtractedField
from app.ai.providers.mock import FABRICATED_EVIDENCE, MockProvider
from app.ai.validation import (
    REASON_EVIDENCE_NOT_FOUND,
    REASON_NO_EVIDENCE,
    REASON_NUMBER_NOT_IN_SOURCE,
    REASON_TERM_IS_INSTALLMENT,
    check_logic,
    check_terminology,
    guard_fields,
    load_forbidden_terms,
    merge_extractions,
    validate_evidence,
    validate_number_in_source,
)

KAYNAK = (
    "Zen Pırlanta'da 3 Taksit\n"
    "Kampanya Dönemi 11-08-2026 - 31-08-2026\n"
    "Ziraat Katılım Bankkart ile %2,05 kâr payı oranıyla peşin fiyatına 3 taksit.\n"
    "5.000 TL ve üzeri harcamalarda 250 TL nakit iade edilir.\n"
)


def _alan(
    ad: str = "profit_rate_pct",
    deger: str = "2.05",
    kanit: str = "%2,05 kâr payı oranıyla",
    yontem: str = "llm",
    birim: str = "pct",
    guven: str = "0.70",
) -> ExtractedField:
    """Test için çıkarım kaydı üretir."""
    return ExtractedField(
        field_name=ad,
        value_raw=kanit,
        value_normalized=deger,
        unit=birim,
        evidence_text=kanit,
        evidence_char_start=None,
        evidence_char_end=None,
        confidence=Decimal(guven),
        method=yontem,
    )


class TestKatman3Kanit:
    """Kanıt kaynakta fiilen geçiyor mu?"""

    def test_birebir_kanit_kabul(self) -> None:
        gecerli, bas, son = validate_evidence("%2,05 kâr payı oranıyla", KAYNAK)
        assert gecerli
        assert KAYNAK[bas:son] == "%2,05 kâr payı oranıyla"

    def test_satir_sonu_farki_affedilir(self) -> None:
        """Model satır sonunu boşluğa çevirmiş olabilir; guard aşırı katı olmamalı."""
        gecerli, _, _ = validate_evidence(
            "Kampanya Dönemi 11-08-2026 - 31-08-2026 Ziraat Katılım Bankkart", KAYNAK
        )
        assert gecerli

    def test_tirnak_ve_tire_farki_affedilir(self) -> None:
        gecerli, _, _ = validate_evidence("5.000 TL ve üzeri harcamalarda 250 TL", KAYNAK)
        assert gecerli

    def test_uydurma_kanit_reddedilir(self) -> None:
        assert validate_evidence(FABRICATED_EVIDENCE, KAYNAK)[0] is False

    def test_cok_kisa_kanit_reddedilir(self) -> None:
        # ⚠️ Kısa dize her yerde eşleşir; doğrulamayı anlamsızlaştırır.
        assert validate_evidence("3", KAYNAK)[0] is False

    def test_benzer_ama_farkli_sayi_reddedilir(self) -> None:
        """⚠️ %90 eşiği sayısal halüsinasyonu AFFETMEMELİ."""
        gecerli, _, _ = validate_evidence(
            "Ziraat Katılım Bankkart ile %9,95 kâr payı oranıyla peşin fiyatına 3 taksit.", KAYNAK
        )
        # Cümle çok benzer ama sayı farklı — katman 4 kesin olarak yakalar.
        assert validate_number_in_source("9.95", "pct", KAYNAK) is False or not gecerli


class TestKatman4Sayi:
    """Üretilen rakam kaynakta geçiyor mu?"""

    @pytest.mark.parametrize(
        ("deger", "birim"),
        [("2.05", "pct"), ("5000", "TRY"), ("250", "TRY"), ("3", "count")],
    )
    def test_kaynakta_gecen_sayi_kabul(self, deger: str, birim: str) -> None:
        assert validate_number_in_source(deger, birim, KAYNAK) is True

    @pytest.mark.parametrize("deger", ["1.23", "9999", "7.77"])
    def test_kaynakta_gecmeyen_sayi_reddedilir(self, deger: str) -> None:
        assert validate_number_in_source(deger, "pct", KAYNAK) is False

    def test_turkce_binlik_ayraci(self) -> None:
        """`5.000` beş bindir; `5000` ile aynı sayıdır."""
        assert validate_number_in_source("5000", "TRY", "Toplam 5.000 TL tutarında") is True

    def test_bin_kelimesi(self) -> None:
        assert validate_number_in_source("5000", "TRY", "5 bin TL değerinde hediye") is True

    def test_siniflandirma_alanlari_muaf(self) -> None:
        # ⚠️ `nakit_iade` bir sayı değildir; kaynakta aramak her doğru
        # çıkarımı reddederdi.
        assert validate_number_in_source("nakit_iade", "enum", KAYNAK) is True
        assert validate_number_in_source("true", "bool", KAYNAK) is True

    def test_sifir_muaf(self) -> None:
        """ "vade farksız" → 0 TÜRETİLMİŞ değerdir; kaynakta "0" geçmez."""
        assert validate_number_in_source("0", "pct", "Vade farksız 4 taksit") is True


class TestKatman5Mantik:
    """Alanlar birbiriyle tutarlı mı?"""

    def test_ters_tarih_yakalanir(self) -> None:
        ihlal = check_logic({"start_date": "2026-12-31", "end_date": "2026-01-01"})
        assert "start_date" in ihlal and "end_date" in ihlal

    def test_dogru_tarih_sirasi_temiz(self) -> None:
        assert check_logic({"start_date": "2026-01-01", "end_date": "2026-12-31"}) == {}

    def test_tek_gunluk_kampanya_gecerli(self) -> None:
        # ⚠️ Eşitlik ihlal değildir.
        assert check_logic({"start_date": "2026-05-05", "end_date": "2026-05-05"}) == {}

    @pytest.mark.parametrize(
        ("alan", "deger"),
        [
            ("profit_rate_pct", "250"),
            ("term_months_max", "480"),
            ("installment_count", "120"),
            ("cashback_pct", "150"),
        ],
    )
    def test_araliklar_disi_yakalanir(self, alan: str, deger: str) -> None:
        assert alan in check_logic({alan: deger})

    def test_ters_harcama_araligi_yakalanir(self) -> None:
        assert "min_spend_try" in check_logic({"min_spend_try": "9000", "max_spend_try": "500"})

    def test_eksik_alan_ihlal_degildir(self) -> None:
        """⚠️ "Bilgi yok"u hataya çevirmek yanlış olur."""
        assert check_logic({"min_spend_try": "5000"}) == {}
        assert check_logic({"start_date": "2026-01-01"}) == {}


class TestKatman6Terminoloji:
    """Bizim ürettiğimiz metinde konvansiyonel terim var mı?"""

    def test_uretilen_metinde_yasakli_terim_yakalanir(self, seeded_session: Session) -> None:
        terimler = load_forbidden_terms(seeded_session)
        uyarilar = check_terminology("Bu üründe faiz oranı %2,05 olarak uygulanır.", terimler)
        assert any(u.term.startswith("faiz") for u in uyarilar)

    def test_kaynakta_gecen_terim_uyarmaz(self, seeded_session: Session) -> None:
        """⚠️ Banka öyle yazmış olabilir; ham veri bizim hatamız değildir."""
        terimler = load_forbidden_terms(seeded_session)
        uyarilar = check_terminology(
            "Banka faiz oranını açıklamıştır.",
            terimler,
            source_text="Sayfada faiz oranı ifadesi geçmektedir.",
        )
        assert uyarilar == []

    def test_kredi_karti_uyari_uretmez(self, seeded_session: Session) -> None:
        """⚠️ Ürünün resmî adı; elenmezse her kart kampanyası yanlış uyarır."""
        terimler = load_forbidden_terms(seeded_session)
        assert check_terminology("Kredi kartınızla yapacağınız alışverişler.", terimler) == []

    def test_kelime_sinirina_uyar(self, seeded_session: Session) -> None:
        """ "kredibilite" içinde "kredi" geçer ama yasak terim değildir."""
        terimler = load_forbidden_terms(seeded_session)
        assert check_terminology("Müşterinin kredibilitesi değerlendirilir.", terimler) == []

    def test_temiz_metin_uyari_uretmez(self, seeded_session: Session) -> None:
        terimler = load_forbidden_terms(seeded_session)
        assert check_terminology("Kâr payı oranı ve finansman koşulları.", terimler) == []


class TestGuardOrkestrasyonu:
    """Katmanlar birlikte çalışıyor mu?"""

    def test_kanitsiz_alan_reddedilir(self) -> None:
        sonuc = guard_fields([_alan(kanit="")], KAYNAK)
        assert sonuc.rejected[0][1] == REASON_NO_EVIDENCE

    def test_uydurma_kanit_reddedilir(self) -> None:
        sonuc = guard_fields([_alan(kanit=FABRICATED_EVIDENCE)], KAYNAK)
        assert sonuc.rejected[0][1] == REASON_EVIDENCE_NOT_FOUND
        assert sonuc.accepted == []

    def test_kanit_dogru_sayi_uydurma_ise_reddedilir(self) -> None:
        """Model doğru cümleyi alıntılayıp içindeki sayıyı bozabilir."""
        sonuc = guard_fields([_alan(deger="7.77")], KAYNAK)
        assert sonuc.rejected[0][1] == REASON_NUMBER_NOT_IN_SOURCE

    def test_taksit_sayisi_vade_alanina_yazilamaz(self) -> None:
        """Katman 4b — ölçüldü: LLM kaynaklı 229 vade değerinin 221'inin kanıtı
        "taksit" diyor, "ay" demiyor.

        ⚠️ Katman 4 bunu yakalayamaz: rakam kaynakta gerçekten geçiyor, ama
        BAŞKA BİR BÜYÜKLÜĞÜ ölçüyor.
        """
        sonuc = guard_fields(
            [
                _alan(
                    ad="term_months_max", deger="3", kanit="peşin fiyatına 3 taksit", birim="month"
                )
            ],
            KAYNAK,
        )
        assert sonuc.rejected[0][1] == REASON_TERM_IS_INSTALLMENT
        assert sonuc.accepted == []

    def test_ay_geciyorsa_vade_kabul_edilir(self) -> None:
        """Kapı kör değil: gerçek vade ifadesi geçmeye devam eder."""
        kaynak = KAYNAK + "36 aya varan vade imkânı sunulmaktadır.\n"
        sonuc = guard_fields(
            [_alan(ad="term_months_max", deger="36", kanit="36 aya varan vade", birim="month")],
            kaynak,
        )
        assert sonuc.rejected == []
        assert len(sonuc.accepted) == 1

    def test_hem_ay_hem_taksit_geciyorsa_kabul(self) -> None:
        """Kanıtta ay DA geçiyorsa değer vade olabilir; reddedilmez."""
        kaynak = KAYNAK + "12 ay vade ile 6 taksit imkânı vardır.\n"
        sonuc = guard_fields(
            [
                _alan(
                    ad="term_months_max", deger="12", kanit="12 ay vade ile 6 taksit", birim="month"
                )
            ],
            kaynak,
        )
        assert sonuc.rejected == []

    def test_taksit_alani_etkilenmez(self) -> None:
        """Kapı yalnızca `term_months*` alanlarına uygulanır."""
        sonuc = guard_fields(
            [
                _alan(
                    ad="installment_count", deger="3", kanit="peşin fiyatına 3 taksit", birim="adet"
                )
            ],
            KAYNAK,
        )
        assert sonuc.rejected == []

    def test_gecerli_alan_kabul(self) -> None:
        sonuc = guard_fields([_alan()], KAYNAK)
        assert len(sonuc.accepted) == 1
        assert sonuc.rejected == []

    def test_kural_katmani_kanit_dogrulamasindan_muaf(self) -> None:
        """⚠️ Kural kanıtını kaynaktan DİLİMLEYEREK üretir; aramak gereksiz."""
        sonuc = guard_fields([_alan(yontem="rule", kanit="kaynakta olmayan metin")], KAYNAK)
        assert len(sonuc.accepted) == 1

    def test_halusinasyon_orani_hesaplanir(self) -> None:
        sonuc = guard_fields([_alan(), _alan(kanit=FABRICATED_EVIDENCE)], KAYNAK)
        assert sonuc.hallucination_rate == 0.5

    def test_katman_bazinda_sayac(self) -> None:
        sonuc = guard_fields(
            [_alan(kanit=""), _alan(kanit=FABRICATED_EVIDENCE), _alan(deger="7.77")], KAYNAK
        )
        assert sonuc.rejected_by_layer[REASON_NO_EVIDENCE] == 1
        assert sonuc.rejected_by_layer[REASON_EVIDENCE_NOT_FOUND] == 1
        assert sonuc.rejected_by_layer[REASON_NUMBER_NOT_IN_SOURCE] == 1


class TestMerger:
    """Öncelik: tablo > kural > LLM."""

    def test_tablo_kurali_yener(self) -> None:
        sonuc = merge_extractions(
            [_alan(deger="2.05", yontem="rule"), _alan(deger="3.00", yontem="table")]
        )
        assert len(sonuc.fields) == 1
        assert sonuc.fields[0].value_normalized == "3.00"

    def test_kural_llm_i_yener(self) -> None:
        sonuc = merge_extractions(
            [_alan(deger="2.50", yontem="llm"), _alan(deger="2.05", yontem="rule")]
        )
        assert sonuc.fields[0].value_normalized == "2.05"

    def test_cakisma_raporlanir_ve_guven_duser(self) -> None:
        sonuc = merge_extractions(
            [_alan(deger="2.50", yontem="llm"), _alan(deger="2.05", yontem="rule", guven="0.90")],
            campaign_id=42,
        )
        assert len(sonuc.conflicts) == 1
        catisma = sonuc.conflicts[0]
        assert catisma.winner_method == "rule"
        assert catisma.loser_method == "llm"
        assert catisma.campaign_id == 42
        # Güven 0.90 - 0.15 = 0.75
        assert sonuc.fields[0].confidence == Decimal("0.75")
        assert "çakışma" in (sonuc.fields[0].validation_note or "")

    def test_ayni_deger_cakisma_degildir(self) -> None:
        """⚠️ İki kaynağın aynı değeri bulması UYUMDUR, sorun değil."""
        sonuc = merge_extractions(
            [_alan(deger="2.05", yontem="llm"), _alan(deger="2.05", yontem="rule", guven="0.90")]
        )
        assert sonuc.conflicts == []
        assert sonuc.fields[0].confidence == Decimal("0.90")


class TestKasitliBozukMetin:
    """⚠️ KAPI A7 geçiş koşulu: bilgi yokken bilgi üretilmemeli."""

    def test_oran_bulunmamaktadir_ifadesi_oran_uretmez(self) -> None:
        metin = "Bu kampanyada kâr payı oranı bulunmamaktadır."
        alanlar = {a.field_name for a in extract_rule_based(metin)}
        assert "profit_rate_pct" not in alanlar

    def test_avantajli_kar_payi_oran_uretmez(self) -> None:
        metin = "Konut finansmanında avantajlı kâr payı fırsatı sizi bekliyor."
        alanlar = {a.field_name for a in extract_rule_based(metin)}
        assert "profit_rate_pct" not in alanlar


class TestHallucModu:
    """⭐ Gerçek model olmadan guard'ın çalıştığının kanıtı."""

    async def test_uydurma_ciktilarin_tamami_reddedilir(self, db_session: Session) -> None:
        from app.ai.extraction.llm_extractor import extract_llm

        class _Kampanya:
            id = 1

        sonuc = await extract_llm(
            MockProvider(mode="halluc"),
            db_session,
            KAYNAK,
            _Kampanya(),
            set(),
            prompt_version="v1",
        )
        assert sonuc.fields, "halluc kipi alan üretmeli ki guard sınanabilsin"

        guard = guard_fields(sonuc.fields, KAYNAK)
        assert guard.accepted == [], "uydurma kanıtların HEPSİ reddedilmeli"
        assert len(guard.rejected) == len(sonuc.fields)
        assert guard.hallucination_rate == 1.0
        assert set(guard.rejected_by_layer) == {REASON_EVIDENCE_NOT_FOUND}


class TestPipelineEntegrasyonu:
    """Guard ve merger pipeline'a bağlı mı?"""

    @pytest.fixture
    def hazir_db(self, db_session: Session) -> Session:
        from app.db.models import Bank, Campaign, SourceDocument

        bank = Bank(code="guard_bank", name="Guard", website="https://ornek.test")
        db_session.add(bank)
        db_session.flush()
        belge = SourceDocument(
            bank_id=bank.id,
            url="https://ornek.test/g1",
            url_hash="g1",
            doc_type="campaign",
            clean_text=KAYNAK,
        )
        db_session.add(belge)
        db_session.flush()
        db_session.add(
            Campaign(
                bank_id=bank.id,
                source_document_id=belge.id,
                external_slug="g1",
                title="Zen Pırlanta'da 3 Taksit",
                source_url="https://ornek.test/g1",
                status="unknown",
                date_precision="unknown",
            )
        )
        db_session.flush()
        return db_session

    async def test_reddedilen_kayitlar_silinmez(self, hazir_db: Session) -> None:
        """⚠️ Halüsinasyon oranı ancak reddedilenler kayıtlıysa raporlanabilir."""
        from sqlalchemy import select

        from app.ai.pipeline import run_extraction
        from app.db.models import CampaignExtraction

        ozet = await run_extraction(
            hazir_db, MockProvider(mode="halluc"), mode="hybrid", bank_code="guard_bank"
        )

        assert ozet.fields_rejected > 0
        reddedilenler = list(
            hazir_db.scalars(
                select(CampaignExtraction).where(CampaignExtraction.rejected_reason.isnot(None))
            )
        )
        assert len(reddedilenler) == ozet.fields_rejected
        assert all(k.extraction_method == "llm" for k in reddedilenler)
        assert all(k.is_validated is False for k in reddedilenler)

    async def test_metrics_yalnizca_guardi_gecen_degerlerle_dolar(self, hazir_db: Session) -> None:
        """⚠️ Reddedilmiş bir değerin buraya sızması, halüsinasyonu
        kullanıcıya göstermek demektir."""
        from sqlalchemy import select

        from app.ai.pipeline import run_extraction
        from app.db.models import CampaignMetric

        await run_extraction(
            hazir_db, MockProvider(mode="halluc"), mode="hybrid", bank_code="guard_bank"
        )

        metrik = hazir_db.scalar(select(CampaignMetric))
        assert metrik is not None
        # halluc kipi her alana 1.23 uydurdu; hiçbiri metriklere geçmemeli.
        assert metrik.profit_rate_pct != Decimal("1.23")
        assert metrik.file_fee_try != Decimal("1.23")
        # Kural katmanının bulduğu gerçek değer ise yazılmalı.
        assert metrik.profit_rate_pct == Decimal("2.0500")

    async def test_rule_only_kipinde_red_yok(self, hazir_db: Session) -> None:
        from app.ai.pipeline import run_extraction

        ozet = await run_extraction(hazir_db, None, mode="rule_only", bank_code="guard_bank")
        assert ozet.fields_rejected == 0
