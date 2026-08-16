"""Çıkarım orkestrasyonu.

Kampanyaları gezer, katmanları sırayla çalıştırır ve sonuçları
`campaign_extractions` tablosuna yazar. Her çalıştırma `extraction_runs`
tablosunda sayaçlarıyla birlikte kayıt altına alınır — ablasyon tablosu
(KAPI A9) bu kayıtlardan üretilecek.

⚠️ TEK KAMPANYANIN HATASI ÇALIŞTIRMAYI DURDURMAZ. 495 kampanyanın 400'ünü
işledikten sonra çöken bir çalıştırma, o 400 sonucu da beraberinde götürür;
hata sayılır, loglanır ve devam edilir.

⚠️ ÇALIŞTIRMA YİNELENEBİLİRDİR. Aynı kampanya için aynı yöntemle üretilmiş
eski çıkarımlar SİLİNİP yenileri yazılır. Aksi hâlde her çalıştırmada kayıtlar
katlanır ve "kaç alan çıkarıldı" sorusunun yanıtı anlamsızlaşır.

⚠️ SPRINT 3A'DA YALNIZCA `rule_only` KİPİ ÇALIŞIR. `hybrid` ve `llm_only`
KAPI A6'da LLM katmanı eklendiğinde açılacak; şimdiden çağrılırsa açık hata
verir — sessizce kural kipine düşmek, ablasyon tablosunda iki kipi aynı
kolonda toplardı.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Final

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ai.extraction import ExtractedField, extract_rule_based
from app.config import get_settings
from app.db.base import utc_now
from app.db.models import (
    Bank,
    Campaign,
    CampaignCategory,
    CampaignExtraction,
    ExtractionRun,
    SourceDocument,
)
from app.logging_config import get_logger

logger = get_logger(__name__)

# İlerleme kaç kampanyada bir loglanır.
PROGRESS_EVERY: Final[int] = 50

# SPRINT 3A'da uygulanmış kipler.
IMPLEMENTED_MODES: Final[tuple[str, ...]] = ("rule_only",)

# ⚠️ KATMAN 1 — YAPISAL VERİ. Bu üç alan metinden çıkarılmaz; SPRINT 2'de
# `campaign_categories` tablosuna zaten yazıldı (URL yolu, bankanın kendi
# etiketi, marka sözlüğü). Yeniden regex ile çıkarmaya çalışmak, güveni
# 1.00 olan kaynak veriyi 0.90'lık bir tahminle değiştirmek olurdu.
TAXONOMY_FIELDS: Final[dict[str, str]] = {
    "product_type": "product_type",
    "sector": "sector",
    "target_customer": "audience",
}


@dataclass
class ExtractionSummary:
    """Çalıştırma sonucu (CLI çıktısı için)."""

    run_id: int | None = None
    mode: str = "rule_only"
    campaigns_processed: int = 0
    fields_extracted: int = 0
    errors_count: int = 0
    duration_seconds: int = 0
    by_field: dict[str, int] | None = None


def _to_row(campaign: Campaign, alan: ExtractedField, prompt_version: str) -> CampaignExtraction:
    """`ExtractedField`i veritabanı satırına çevirir.

    ⚠️ `prompt_version` HER KAYDA yazılır — kural tabanlı çıkarımda bile.
    Sürüm bilinmeyen bir sonuç yeniden üretilemez ve ablasyon
    karşılaştırmasına giremez.
    """
    return CampaignExtraction(
        campaign_id=campaign.id,
        field_name=alan.field_name,
        value_raw=alan.value_raw,
        value_normalized=alan.value_normalized,
        unit=alan.unit,
        evidence_text=alan.evidence_text,
        evidence_char_start=alan.evidence_char_start,
        evidence_char_end=alan.evidence_char_end,
        evidence_source_url=campaign.source_url,
        confidence=alan.confidence,
        extraction_method=alan.method,
        prompt_version=prompt_version,
        validation_note=alan.validation_note,
        extracted_at=utc_now(),
    )


def _campaigns(
    session: Session, *, bank_code: str | None, limit: int | None
) -> list[tuple[Campaign, str]]:
    """İşlenecek kampanyaları metinleriyle birlikte getirir.

    ⚠️ Metni boş olan kampanya ATLANIR: okunacak metin yokken çıkarım
    denemek, boş sonucu "sistem bulamadı" olarak kaydetmek olurdu.
    """
    sorgu = (
        select(Campaign, SourceDocument.clean_text)
        .join(SourceDocument, Campaign.source_document_id == SourceDocument.id)
        .where(SourceDocument.clean_text.isnot(None))
        .order_by(Campaign.id)
    )
    if bank_code:
        sorgu = sorgu.join(Bank, Bank.id == Campaign.bank_id).where(Bank.code == bank_code)
    if limit:
        sorgu = sorgu.limit(limit)

    return [(kampanya, metin) for kampanya, metin in session.execute(sorgu) if metin.strip()]


def _taxonomy_fields(session: Session, campaign: Campaign) -> list[CampaignExtraction]:
    """Taksonomi etiketlerini çıkarım kaydına çevirir (Katman 1).

    ⚠️ Bu veri ÜRETİLMEZ, TAŞINIR. `campaign_categories` SPRINT 2'de kaynağa
    dayanarak dolduruldu; güveni oradaki değerden alınır ve
    `extraction_method='table'` ile işaretlenir.

    ⚠️ Bir eksende birden çok etiket varsa EN YÜKSEK GÜVENLİ olan seçilir:
    çıkarım şeması alan başına tek değer bekliyor.
    """
    satirlar = session.execute(
        select(CampaignCategory)
        .where(CampaignCategory.campaign_id == campaign.id)
        .order_by(CampaignCategory.confidence.desc())
    ).scalars()

    secilen: dict[str, CampaignCategory] = {}
    for kayit in satirlar:
        secilen.setdefault(kayit.axis, kayit)

    kayitlar: list[CampaignExtraction] = []
    for alan_adi, eksen in TAXONOMY_FIELDS.items():
        kaynak = secilen.get(eksen)
        if kaynak is None:
            continue
        kayitlar.append(
            CampaignExtraction(
                campaign_id=campaign.id,
                field_name=alan_adi,
                value_raw=kaynak.evidence,
                value_normalized=kaynak.value,
                unit="enum",
                evidence_text=kaynak.evidence,
                evidence_source_url=campaign.source_url,
                confidence=kaynak.confidence,
                extraction_method="table",
                prompt_version=get_settings().prompt_version,
                extracted_at=utc_now(),
            )
        )
    return kayitlar


def run_extraction(
    session: Session,
    *,
    mode: str = "rule_only",
    bank_code: str | None = None,
    limit: int | None = None,
) -> ExtractionSummary:
    """Çıkarımı çalıştırır ve sonuçları kaydeder.

    Args:
        session: Veritabanı oturumu.
        mode: `rule_only` (SPRINT 3A'da tek uygulanan kip).
        bank_code: Yalnızca bu bankayı işle.
        limit: En fazla bu kadar kampanya işle.

    Returns:
        Çalıştırma özeti.

    Raises:
        ValueError: Henüz uygulanmamış bir kip istendiyse.
    """
    if mode not in IMPLEMENTED_MODES:
        raise ValueError(
            f"{mode!r} kipi SPRINT 3A'da uygulanmadı (KAPI A6'da gelecek). "
            f"Geçerli: {IMPLEMENTED_MODES}"
        )

    ayarlar = get_settings()
    baslangic = time.monotonic()

    run = ExtractionRun(
        mode=mode,
        scope=bank_code,
        status="running",
        prompt_version=ayarlar.prompt_version,
    )
    session.add(run)
    session.flush()

    kampanyalar = _campaigns(session, bank_code=bank_code, limit=limit)
    logger.info("cikarim_basladi", kip=mode, kampanya=len(kampanyalar), kapsam=bank_code)

    alan_sayaci: dict[str, int] = {}
    toplam_alan = 0
    hata = 0

    for sira, (kampanya, metin) in enumerate(kampanyalar, start=1):
        try:
            bulgular = extract_rule_based(metin)

            # ⚠️ Aynı yöntemle üretilmiş eski kayıtlar silinir: yeniden
            # çalıştırma kayıtları KATLAMAMALI.
            session.execute(
                delete(CampaignExtraction).where(
                    CampaignExtraction.campaign_id == kampanya.id,
                    CampaignExtraction.extraction_method.in_(("rule", "table")),
                )
            )

            for kayit in _taxonomy_fields(session, kampanya):
                session.add(kayit)
                alan_sayaci[kayit.field_name] = alan_sayaci.get(kayit.field_name, 0) + 1
                toplam_alan += 1

            for alan in bulgular:
                session.add(_to_row(kampanya, alan, ayarlar.prompt_version))
                alan_sayaci[alan.field_name] = alan_sayaci.get(alan.field_name, 0) + 1
                toplam_alan += 1

            session.flush()
        except Exception as exc:
            hata += 1
            logger.warning(
                "kampanya_islenemedi", kampanya_id=kampanya.id, hata=f"{type(exc).__name__}: {exc}"
            )

        if sira % PROGRESS_EVERY == 0:
            logger.info("cikarim_ilerleme", islenen=sira, toplam=len(kampanyalar))

    sure = int(time.monotonic() - baslangic)
    run.finished_at = utc_now()
    run.status = "partial" if hata else "success"
    run.campaigns_processed = len(kampanyalar)
    run.fields_extracted = toplam_alan
    run.errors_count = hata
    run.duration_seconds = sure
    session.commit()

    logger.info(
        "cikarim_bitti",
        kip=mode,
        durum=run.status,
        kampanya=len(kampanyalar),
        alan=toplam_alan,
        hata=hata,
        saniye=sure,
    )

    return ExtractionSummary(
        run_id=run.id,
        mode=mode,
        campaigns_processed=len(kampanyalar),
        fields_extracted=toplam_alan,
        errors_count=hata,
        duration_seconds=sure,
        by_field=dict(sorted(alan_sayaci.items(), key=lambda p: -p[1])),
    )
