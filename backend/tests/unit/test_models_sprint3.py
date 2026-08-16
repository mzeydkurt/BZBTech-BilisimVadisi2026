"""SPRINT 3A — çıkarım motoru şeması.

Buradaki kısıtların ortak amacı, ÖLÇÜMÜ BOZAN veriyi hata vererek reddetmektir.
Kontrolsüz bir `mode` değeri ablasyon tablosunu, kontrolsüz bir `method` değeri
kör/ön-doldurmalı yanlılık karşılaştırmasını sessizce anlamsızlaştırır — ve o
noktada F1 sayısı hâlâ "geçerli" görünür.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    Bank,
    Campaign,
    CampaignExtraction,
    Embedding,
    EntityCard,
    ExtractionRun,
    GoldAnnotation,
    LLMCache,
)


@pytest.fixture
def kampanya(db_session: Session) -> Campaign:
    """Etiketlenecek tek bir kampanya."""
    bank = Bank(code="ornek_katilim", name="Örnek Katılım", website="https://ornek.com.tr")
    db_session.add(bank)
    db_session.flush()

    campaign = Campaign(
        bank_id=bank.id,
        external_slug="ornek-kampanya",
        title="Örnek Kampanya",
        source_url="https://ornek.com.tr/kampanyalar/ornek-kampanya",
        date_precision="unknown",
        status="unknown",
    )
    db_session.add(campaign)
    db_session.flush()
    return campaign


# ── extraction_runs ───────────────────────────────────────


def test_calistirma_kipi_kontrollu_sozlukten(db_session: Session) -> None:
    """Tanımsız bir kip reddedilir.

    `hybrid` yerine `hibrit` yazılırsa ablasyon tablosu iki ayrı kipi tek
    kolonda toplar ve kural/LLM katkısı ayrıştırılamaz.
    """
    db_session.add(ExtractionRun(mode="hibrit", status="running"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_reddedilen_alan_sayaci_ayri_tutulur(db_session: Session) -> None:
    """`fields_rejected`, `fields_extracted`ten bağımsız sayılır.

    Guard'ın reddettiği alan sayısı halüsinasyon oranının payıdır; çıkarılan
    alanlarla toplanırsa "bilgi yokken bilgi üretmeme" yeteneği raporlanamaz.
    """
    run = ExtractionRun(mode="hybrid", status="success", fields_extracted=40, fields_rejected=7)
    db_session.add(run)
    db_session.flush()

    assert run.fields_extracted == 40
    assert run.fields_rejected == 7
    # Varsayılanlar sıfırdan başlar: sayaç okunmadan önce None olmamalı.
    assert run.llm_calls == 0
    assert run.cache_hits == 0


# ── gold_annotations ──────────────────────────────────────


def test_etiketleme_yontemi_kontrollu_sozlukten(db_session: Session, kampanya: Campaign) -> None:
    """`blind` / `assisted` dışında bir yöntem reddedilir.

    Yanlılık kontrolü bu iki alt kümenin F1 farkına dayanıyor; üçüncü bir
    değer sızarsa hangi kayıtların kör olduğu bilinemez.
    """
    db_session.add(
        GoldAnnotation(
            campaign_id=kampanya.id,
            field_name="profit_rate_pct",
            annotator="zeyd",
            method="yarim_kor",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_gold_deger_null_olabilir(db_session: Session, kampanya: Campaign) -> None:
    """`gold_value = None` geçerlidir: "bu alan metinde YOK" demektir.

    ⚠️ Bu satır kayıt olarak VAR olmalı. Yokluğu "etiketlenmedi" ile
    karıştırılırsa, sistemin boş alana değer üretmesi (halüsinasyon) yanlış
    pozitif olarak sayılamaz.
    """
    etiket = GoldAnnotation(
        campaign_id=kampanya.id,
        field_name="profit_rate_pct",
        gold_value=None,
        annotator="zeyd",
        method="blind",
    )
    db_session.add(etiket)
    db_session.flush()

    assert etiket.gold_value is None
    assert etiket.is_difficult is False


def test_ayni_alan_ayni_etiketleyiciyle_tekrarlanamaz(
    db_session: Session, kampanya: Campaign
) -> None:
    """Aynı (kampanya, alan, etiketleyici) üçlüsü tekildir."""
    for _ in range(2):
        db_session.add(
            GoldAnnotation(
                campaign_id=kampanya.id,
                field_name="end_date",
                annotator="zeyd",
                method="blind",
            )
        )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_kampanya_silinince_etiketi_de_silinir(db_session: Session, kampanya: Campaign) -> None:
    """Foreign key ve CASCADE çalışıyor."""
    db_session.add(
        GoldAnnotation(
            campaign_id=kampanya.id,
            field_name="end_date",
            annotator="zeyd",
            method="blind",
        )
    )
    db_session.flush()

    db_session.delete(kampanya)
    db_session.flush()

    assert db_session.query(GoldAnnotation).count() == 0


# ── entity_cards / embeddings ─────────────────────────────


def test_varlik_turu_kontrollu_sozlukten(db_session: Session) -> None:
    """Tanımsız varlık türü reddedilir."""
    db_session.add(EntityCard(entity_type="reklam", entity_id=1, card_text="...", card_hash="abc"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_bir_varligin_tek_karti_olur(db_session: Session) -> None:
    """Aynı varlık için ikinci kart eklenemez; yeniden üretim günceller."""
    for _ in range(2):
        db_session.add(
            EntityCard(entity_type="campaign", entity_id=1, card_text="...", card_hash="abc")
        )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_gomme_boyutu_pozitif_olmali(db_session: Session) -> None:
    """`dim <= 0` reddedilir: boş vektör benzerlik hesabını sessizce bozar."""
    db_session.add(
        Embedding(
            entity_type="campaign",
            entity_id=1,
            chunk_text="...",
            embedding=b"",
            dim=0,
            model_name="bge-m3",
            source_hash="abc",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


# ── llm_cache ─────────────────────────────────────────────


def test_onbellek_anahtari_tekil(db_session: Session) -> None:
    """Aynı anahtar iki kez yazılamaz."""
    for _ in range(2):
        db_session.add(
            LLMCache(
                cache_key="ayni-anahtar",
                task="extract",
                response_json="{}",
                model_name="mock",
                prompt_version="v1",
            )
        )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_onbellek_gorevi_kontrollu_sozlukten(db_session: Session) -> None:
    """Tanımsız görev reddedilir: aynı metin farklı görevde farklı yanıt verir."""
    db_session.add(
        LLMCache(
            cache_key="k1",
            task="ozetle",
            response_json="{}",
            model_name="mock",
            prompt_version="v1",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


# ── campaign_extractions.rejected_reason ──────────────────


def test_reddedilen_cikarim_saklanir(db_session: Session, kampanya: Campaign) -> None:
    """Reddedilen çıkarım SİLİNMEZ, gerekçesiyle saklanır.

    Halüsinasyon oranı ancak reddedilen kayıtlar durursa raporlanabilir.
    """
    cikarim = CampaignExtraction(
        campaign_id=kampanya.id,
        field_name="profit_rate_pct",
        value_normalized="2.05",
        extraction_method="llm",
        rejected_reason="evidence kaynak metinde bulunamadı",
        extracted_at=datetime.now(UTC),
    )
    db_session.add(cikarim)
    db_session.flush()

    assert cikarim.rejected_reason == "evidence kaynak metinde bulunamadı"
    assert cikarim.value_normalized == "2.05"
