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

ÜÇ KİP (ablasyon tablosunun kolonları):

    rule_only  tablo → kural                    LLM'e HİÇ çağrı yok
    hybrid     tablo → kural → (already_found) → LLM
    llm_only   LLM                              kural devre dışı

⚠️ `llm_only` KİPİ KURALI DEVRE DIŞI BIRAKIR ve bu bilinçlidir: ablasyon
tablosu "kural olmasaydı ne olurdu?" sorusuna ancak böyle yanıt verebilir.
Üretimde kullanılacak kip `hybrid`tir.

⚠️ İPTAL EDİLEBİLİR. Ctrl+C çalıştırmayı `cancelled` olarak kapatır ve O ANA
KADAR yazılanları KORUR. Yerel modelle 495 kampanya saatler sürebilir;
yarıda kesmenin her şeyi çöpe atması, denemeyi imkânsız kılardı.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Final

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ai.extraction import ExtractedField, extract_rule_based
from app.ai.extraction.llm_extractor import extract_llm
from app.ai.providers.base import LLMProvider
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

# Uygulanmış kipler (ablasyon tablosunun kolonları).
IMPLEMENTED_MODES: Final[tuple[str, ...]] = ("rule_only", "hybrid", "llm_only")

# LLM'e çağrı yapan kipler.
LLM_MODES: Final[tuple[str, ...]] = ("hybrid", "llm_only")

# Kural ve tablo katmanının çalıştığı kipler.
RULE_MODES: Final[tuple[str, ...]] = ("rule_only", "hybrid")

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
    llm_calls: int = 0
    cache_hits: int = 0
    llm_skipped: int = 0
    status: str = "success"


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


async def run_extraction(
    session: Session,
    provider: LLMProvider | None = None,
    *,
    mode: str = "rule_only",
    bank_code: str | None = None,
    limit: int | None = None,
    use_cache: bool = True,
) -> ExtractionSummary:
    """Çıkarımı çalıştırır ve sonuçları kaydeder.

    Args:
        session: Veritabanı oturumu.
        mode: `rule_only` | `hybrid` | `llm_only`.
        provider: LLM sağlayıcısı; `hybrid` ve `llm_only` için ZORUNLU.
        bank_code: Yalnızca bu bankayı işle.
        limit: En fazla bu kadar kampanya işle.
        use_cache: False ise LLM önbelleği okunmaz (`--yeniden`).

    Returns:
        Çalıştırma özeti.

    Raises:
        ValueError: Tanımsız kip ya da LLM kipinde sağlayıcı verilmediyse.
    """
    if mode not in IMPLEMENTED_MODES:
        raise ValueError(f"Tanımsız çıkarım kipi: {mode!r}. Geçerli: {IMPLEMENTED_MODES}")
    if mode in LLM_MODES and provider is None:
        # ⚠️ Sessizce kural kipine DÜŞÜLMEZ: ablasyon tablosunda `hybrid`
        # kolonuna kural sonuçlarını yazmak, LLM'in katkısını olduğundan
        # büyük ya da küçük gösterirdi.
        raise ValueError(f"{mode!r} kipi bir LLM sağlayıcısı gerektirir.")

    ayarlar = get_settings()
    baslangic = time.monotonic()

    run = ExtractionRun(
        mode=mode,
        scope=bank_code,
        status="running",
        prompt_version=ayarlar.prompt_version,
        model_name=provider.model_info.name if provider else None,
    )
    session.add(run)
    session.flush()

    kampanyalar = _campaigns(session, bank_code=bank_code, limit=limit)
    logger.info(
        "cikarim_basladi",
        kip=mode,
        kampanya=len(kampanyalar),
        kapsam=bank_code,
        model=run.model_name,
    )

    sayac = _Sayaclar()
    durum = "success"

    try:
        for sira, (kampanya, metin) in enumerate(kampanyalar, start=1):
            try:
                await _process_campaign(
                    session,
                    provider,
                    kampanya,
                    metin,
                    mode=mode,
                    prompt_version=ayarlar.prompt_version,
                    sayac=sayac,
                    use_cache=use_cache,
                )
                session.flush()
            except Exception as exc:
                sayac.hata += 1
                logger.warning(
                    "kampanya_islenemedi",
                    kampanya_id=kampanya.id,
                    hata=f"{type(exc).__name__}: {exc}",
                )

            if sira % PROGRESS_EVERY == 0:
                logger.info("cikarim_ilerleme", islenen=sira, toplam=len(kampanyalar))
    except KeyboardInterrupt:
        # ⚠️ O ANA KADAR YAZILANLAR KORUNUR. Uzun çalıştırmayı yarıda kesmek
        # her şeyi çöpe atmamalı.
        durum = "cancelled"
        logger.warning("cikarim_iptal_edildi", islenen=sayac.kampanya)

    sure = int(time.monotonic() - baslangic)
    run.finished_at = utc_now()
    run.status = durum if durum == "cancelled" else ("partial" if sayac.hata else "success")
    run.campaigns_processed = sayac.kampanya
    run.fields_extracted = sayac.alan
    run.errors_count = sayac.hata
    run.llm_calls = sayac.llm_cagri
    run.cache_hits = sayac.onbellek
    run.duration_seconds = sure
    session.commit()

    logger.info(
        "cikarim_bitti",
        kip=mode,
        durum=run.status,
        kampanya=sayac.kampanya,
        alan=sayac.alan,
        hata=sayac.hata,
        llm_cagri=sayac.llm_cagri,
        onbellek=sayac.onbellek,
        llm_atlanan=sayac.llm_atlanan,
        saniye=sure,
    )

    return ExtractionSummary(
        run_id=run.id,
        mode=mode,
        campaigns_processed=sayac.kampanya,
        fields_extracted=sayac.alan,
        errors_count=sayac.hata,
        duration_seconds=sure,
        by_field=dict(sorted(sayac.alan_sayaci.items(), key=lambda p: -p[1])),
        llm_calls=sayac.llm_cagri,
        cache_hits=sayac.onbellek,
        llm_skipped=sayac.llm_atlanan,
        status=run.status,
    )


@dataclass
class _Sayaclar:
    """Çalıştırma boyunca biriken sayaçlar."""

    kampanya: int = 0
    alan: int = 0
    hata: int = 0
    llm_cagri: int = 0
    onbellek: int = 0
    llm_atlanan: int = 0
    alan_sayaci: dict[str, int] = dataclass_field(default_factory=dict)

    def say(self, alan_adi: str) -> None:
        """Bir alanı sayaçlara işler."""
        self.alan_sayaci[alan_adi] = self.alan_sayaci.get(alan_adi, 0) + 1
        self.alan += 1


async def _process_campaign(
    session: Session,
    provider: LLMProvider | None,
    kampanya: Campaign,
    metin: str,
    *,
    mode: str,
    prompt_version: str,
    sayac: _Sayaclar,
    use_cache: bool = True,
) -> None:
    """Tek kampanyayı işler ve çıkarımlarını yazar.

    ⚠️ ESKİ KAYITLAR ÖNCE SİLİNİR. Yeniden çalıştırma kayıtları katlamamalı;
    aksi hâlde "kaç alan çıkarıldı" sorusunun yanıtı her koşuda büyür.
    Yalnızca BU KİPİN ürettiği yöntemler silinir: `rule_only` çalıştırmak
    `hybrid`in LLM kayıtlarını düşürmemeli.
    """
    silinecek: list[str] = []
    if mode in RULE_MODES:
        silinecek += ["rule", "table"]
    if mode in LLM_MODES:
        silinecek.append("llm")
    session.execute(
        delete(CampaignExtraction).where(
            CampaignExtraction.campaign_id == kampanya.id,
            CampaignExtraction.extraction_method.in_(silinecek),
        )
    )

    bulunan_alanlar: set[str] = set()

    if mode in RULE_MODES:
        for kayit in _taxonomy_fields(session, kampanya):
            session.add(kayit)
            sayac.say(kayit.field_name)
            bulunan_alanlar.add(kayit.field_name)

        for alan in extract_rule_based(metin):
            session.add(_to_row(kampanya, alan, prompt_version))
            sayac.say(alan.field_name)
            bulunan_alanlar.add(alan.field_name)

    if mode in LLM_MODES and provider is not None:
        # ⚠️ `llm_only` kipinde `bulunan_alanlar` BOŞTUR: kural devre dışı
        # olduğu için modele tüm alanlar sorulur. Ablasyonun anlamı budur.
        sonuc = await extract_llm(
            provider,
            session,
            metin,
            kampanya,
            bulunan_alanlar,
            prompt_version=prompt_version,
            use_cache=use_cache,
        )
        sayac.llm_cagri += sonuc.llm_calls
        sayac.onbellek += sonuc.cache_hits
        if sonuc.skipped_reason:
            sayac.llm_atlanan += 1

        for alan in sonuc.fields:
            session.add(_to_row(kampanya, alan, prompt_version))
            sayac.say(alan.field_name)

    sayac.kampanya += 1
