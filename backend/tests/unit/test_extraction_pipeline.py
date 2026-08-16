"""Çıkarım orkestrasyonu.

⚠️ EN KRİTİK TEST `test_yeniden_calistirma_kayitlari_katlamaz`. Katlanan
kayıtlar "kaç alan çıkarıldı" sorusunun yanıtını bozar ve ablasyon tablosunda
kural katmanını olduğundan güçlü gösterir.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.pipeline import run_extraction
from app.db.models import Bank, Campaign, CampaignExtraction, ExtractionRun, SourceDocument

METIN = (
    "Kampanya kapsamında %2,05 kâr payı oranı uygulanır. "
    "3.000 TL ve üzeri harcamalarda 150 TL nakit iade. "
    "01.01.2026 - 31.12.2026 tarihleri arasında geçerlidir."
)


def _kampanya(session: Session, bank: Bank, slug: str, metin: str) -> Campaign:
    """Kaynak belgesiyle birlikte kampanya oluşturur."""
    belge = SourceDocument(
        bank_id=bank.id,
        url=f"https://ornek.com.tr/{slug}",
        url_hash=slug,
        doc_type="campaign",
        clean_text=metin,
    )
    session.add(belge)
    session.flush()

    kampanya = Campaign(
        bank_id=bank.id,
        source_document_id=belge.id,
        external_slug=slug,
        title=f"Kampanya {slug}",
        source_url=belge.url,
        date_precision="unknown",
        status="unknown",
    )
    session.add(kampanya)
    session.flush()
    return kampanya


@pytest.fixture
def banka(db_session: Session) -> Bank:
    """Test bankası."""
    bank = Bank(code="ornek_katilim", name="Örnek Katılım", website="https://ornek.com.tr")
    db_session.add(bank)
    db_session.flush()
    return bank


def test_cikarim_kaydediliyor(db_session: Session, banka: Bank) -> None:
    """Bulunan alanlar `campaign_extractions` tablosuna yazılır."""
    _kampanya(db_session, banka, "test", METIN)

    ozet = run_extraction(db_session, mode="rule_only")

    assert ozet.campaigns_processed == 1
    assert ozet.fields_extracted > 0
    assert ozet.errors_count == 0

    alanlar = {k.field_name: k for k in db_session.scalars(select(CampaignExtraction))}
    assert alanlar["profit_rate_pct"].value_normalized == "2.05"
    assert alanlar["min_spend_try"].value_normalized == "3000"


def test_prompt_surumu_her_kayda_yazilir(db_session: Session, banka: Bank) -> None:
    """⚠️ KAPI A2 geçiş koşulu burada kapanır.

    Sürümü bilinmeyen bir sonuç yeniden üretilemez ve ablasyon
    karşılaştırmasına giremez.
    """
    _kampanya(db_session, banka, "surum", METIN)

    run_extraction(db_session, mode="rule_only")

    bossuz = db_session.scalar(
        select(func.count())
        .select_from(CampaignExtraction)
        .where(CampaignExtraction.prompt_version.is_(None))
    )
    assert bossuz == 0


def test_ofset_veritabaninda_da_korunur(db_session: Session, banka: Bank) -> None:
    """Kanıt aralığı kaydedilirken kaymamalı."""
    _kampanya(db_session, banka, "ofset", METIN)

    run_extraction(db_session, mode="rule_only")

    for kayit in db_session.scalars(select(CampaignExtraction)):
        assert kayit.evidence_char_start is not None
        assert METIN[kayit.evidence_char_start : kayit.evidence_char_end] == kayit.evidence_text


def test_yeniden_calistirma_kayitlari_katlamaz(db_session: Session, banka: Bank) -> None:
    """⚠️ Aynı kampanya iki kez işlenince kayıtlar ÇOĞALMAMALI.

    Çoğalırsa "kaç alan çıkarıldı" sayısı şişer ve kural katmanı ablasyon
    tablosunda olduğundan güçlü görünür.
    """
    _kampanya(db_session, banka, "tekrar", METIN)

    ilk = run_extraction(db_session, mode="rule_only")
    ikinci = run_extraction(db_session, mode="rule_only")

    toplam = db_session.scalar(select(func.count()).select_from(CampaignExtraction))
    assert ilk.fields_extracted == ikinci.fields_extracted
    assert toplam == ilk.fields_extracted


def test_calistirma_kaydi_sayaclariyla_kapanir(db_session: Session, banka: Bank) -> None:
    """`extraction_runs` doğru sayılarla kapatılır."""
    _kampanya(db_session, banka, "kayit", METIN)

    ozet = run_extraction(db_session, mode="rule_only")

    run = db_session.get(ExtractionRun, ozet.run_id)
    assert run is not None
    assert run.status == "success"
    assert run.finished_at is not None
    assert run.campaigns_processed == 1
    assert run.fields_extracted == ozet.fields_extracted
    # LLM katmanı çalışmadı: sayaçlar sıfır kalmalı.
    assert run.llm_calls == 0


def test_metni_bos_kampanya_atlanir(db_session: Session, banka: Bank) -> None:
    """⚠️ Okunacak metin yokken çıkarım denenmez.

    Denenirse boş sonuç "sistem bulamadı" olarak kaydedilir ve
    değerlendirmede kaçırma sayılır.
    """
    _kampanya(db_session, banka, "bos", "   ")

    ozet = run_extraction(db_session, mode="rule_only")

    assert ozet.campaigns_processed == 0


def test_banka_filtresi_calisir(db_session: Session, banka: Bank) -> None:
    """Tek banka işlenebilir."""
    _kampanya(db_session, banka, "a", METIN)

    ozet = run_extraction(db_session, mode="rule_only", bank_code="baska_banka")

    assert ozet.campaigns_processed == 0


def test_uygulanmamis_kip_acik_hata_verir(db_session: Session) -> None:
    """⚠️ `hybrid` sessizce kural kipine DÜŞMEZ.

    Düşseydi ablasyon tablosu iki farklı kipi aynı kolonda toplar ve LLM'in
    katkısı ölçülemezdi.
    """
    with pytest.raises(ValueError, match="hybrid"):
        run_extraction(db_session, mode="hybrid")
