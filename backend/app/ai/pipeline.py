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

import json
import time
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from decimal import Decimal, InvalidOperation
from typing import Final

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ai.classification import complete_classification
from app.ai.extraction import ExtractedField, extract_rule_based
from app.ai.extraction.llm_extractor import extract_llm
from app.ai.providers.base import LLMProvider
from app.ai.summarization import summarize
from app.ai.validation import Conflict, guard_fields, merge_extractions
from app.ai.validation.terminology import load_forbidden_terms
from app.config import get_settings
from app.db.base import utc_now
from app.db.models import (
    Bank,
    Campaign,
    CampaignCategory,
    CampaignExtraction,
    CampaignMetric,
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

# Çıkarımda yer tutucu / varsayılandan özgül etiket seçilir. Aksi hâlde
# `mevcut_musteri@0.30` ile `yeni_musteri@0.70` aynı eksende ilk gelen kazanır.
_AUDIENCE_SPECIFICITY: Final[dict[str, int]] = {
    "herkes": 0,
    "mevcut_musteri": 1,
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
    fields_rejected: int = 0
    logic_violations: int = 0
    rejected_by_layer: dict[str, int] | None = None
    conflicts: list[Conflict] | None = None
    labels_added: int = 0
    labels_rejected: int = 0
    axes_requested: int = 0
    summaries_written: int = 0
    summaries_rejected: int = 0
    summary_rejections: dict[str, int] | None = None
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


def _taxonomy_pick(adaylar: list[CampaignCategory]) -> CampaignCategory | None:
    """Bir eksende gösterilecek tek etiketi seçer.

    `herkes` elenir. Özgül kitle (`yeni_musteri`, `kobi`, …) varsayılan
    `mevcut_musteri`'den önce gelir; eşitlikte güven ve kaynak (url > diğer)
    karar verir.
    """
    adaylar = [a for a in adaylar if not (a.axis == "audience" and a.value == "herkes")]
    if not adaylar:
        return None

    def _anahtar(kayit: CampaignCategory) -> tuple[int, float, int]:
        ozgul = 2
        if kayit.axis == "audience":
            ozgul = _AUDIENCE_SPECIFICITY.get(kayit.value, 2)
        kaynak = 2 if kayit.source in {"url", "bank_category"} else 1
        return (ozgul, float(kayit.confidence or 0), kaynak)

    return max(adaylar, key=_anahtar)


def _taxonomy_fields(session: Session, campaign: Campaign) -> list[ExtractedField]:
    """Taksonomi etiketlerini çıkarım kaydına çevirir (Katman 1).

    ⚠️ Bu veri ÜRETİLMEZ, TAŞINIR. `campaign_categories` SPRINT 2'de kaynağa
    dayanarak dolduruldu; güveni oradaki değerden alınır ve
    `extraction_method='table'` ile işaretlenir.

    ⚠️ Bir eksende birden çok etiket varsa özgül + yüksek güvenli olan
    seçilir: çıkarım şeması alan başına tek değer bekliyor.
    """
    gruplar: dict[str, list[CampaignCategory]] = {}
    for kayit in session.scalars(
        select(CampaignCategory).where(CampaignCategory.campaign_id == campaign.id)
    ):
        gruplar.setdefault(kayit.axis, []).append(kayit)

    secilen: dict[str, CampaignCategory] = {}
    for eksen, adaylar in gruplar.items():
        kazanan = _taxonomy_pick(adaylar)
        if kazanan is not None:
            secilen[eksen] = kazanan

    kayitlar: list[ExtractedField] = []
    for alan_adi, eksen in TAXONOMY_FIELDS.items():
        kaynak = secilen.get(eksen)
        if kaynak is None:
            continue
        kayitlar.append(
            ExtractedField(
                field_name=alan_adi,
                value_raw=kaynak.evidence or "",
                value_normalized=kaynak.value,
                unit="enum",
                evidence_text=kaynak.evidence or "",
                # ⚠️ Taksonomi etiketi metinden DİLİMLENMEZ; URL yolundan ya
                # da bankanın kendi etiketinden gelir. Ofset uydurmak,
                # arayüzde metnin rastgele bir yerini kanıt diye göstermek
                # olurdu.
                evidence_char_start=None,
                evidence_char_end=None,
                confidence=kaynak.confidence or Decimal("1.000"),
                method="table",
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
    run.fields_rejected = sayac.reddedilen
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
        reddedilen=sayac.reddedilen,
        mantik_ihlali=sayac.mantik_ihlali,
        etiket=sayac.etiket_eklendi,
        ozet=sayac.ozet_uretildi,
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
        fields_rejected=sayac.reddedilen,
        logic_violations=sayac.mantik_ihlali,
        rejected_by_layer=dict(sayac.katman_sayaci),
        conflicts=sayac.catismalar,
        labels_added=sayac.etiket_eklendi,
        labels_rejected=sayac.etiket_reddedildi,
        axes_requested=sayac.eksen_soruldu,
        summaries_written=sayac.ozet_uretildi,
        summaries_rejected=sayac.ozet_reddedildi,
        summary_rejections=dict(sayac.ozet_red_sayaci),
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
    reddedilen: int = 0
    mantik_ihlali: int = 0
    etiket_eklendi: int = 0
    etiket_reddedildi: int = 0
    eksen_soruldu: int = 0
    ozet_uretildi: int = 0
    ozet_reddedildi: int = 0
    # Sözlük çalıştırma başına bir kez okunur.
    yasakli_terimler: dict[str, str | None] | None = None
    alan_sayaci: dict[str, int] = dataclass_field(default_factory=dict)
    katman_sayaci: dict[str, int] = dataclass_field(default_factory=dict)
    catismalar: list[Conflict] = dataclass_field(default_factory=list)
    ozet_red_sayaci: dict[str, int] = dataclass_field(default_factory=dict)

    def say(self, alan_adi: str) -> None:
        """Bir alanı sayaçlara işler."""
        self.alan_sayaci[alan_adi] = self.alan_sayaci.get(alan_adi, 0) + 1
        self.alan += 1


def _coerce(value: str | None, unit: str | None) -> object | None:
    """Metin değeri `campaign_metrics` kolonunun tipine çevirir.

    ⚠️ Para ve oran `Decimal`dir; `float` YASAKTIR (CLAUDE.md). İkili kayan
    nokta gösterimi finansal değerlerde yuvarlama hatası üretir.

    Args:
        value: Normalize edilmiş metin değer.
        unit: Alanın birimi.

    Returns:
        Kolona yazılabilir değer; çevrilemezse None.
    """
    if value is None:
        return None
    try:
        if unit in {"pct", "TRY"}:
            return Decimal(value)
        if unit in {"month", "count"}:
            return int(Decimal(value))
        if unit == "bool":
            return value.strip().casefold() in {"true", "1", "evet"}
        if unit == "json":
            # ⚠️ KOLON `JSON` TİPİNDE; dize olarak yazılırsa SQLAlchemy onu
            # bir kez daha kodlar ve okurken dize dönerdi ("[{...}]" yerine
            # "\"[{...}]\""). Ayrıştırılamayan gövde YAZILMAZ.
            cozulen: object = json.loads(value)
            return cozulen
    except (InvalidOperation, ValueError, json.JSONDecodeError):
        return None
    return value


def _write_metrics(session: Session, campaign: Campaign, fields: list[ExtractedField]) -> None:
    """Merger çıktısını `campaign_metrics` tablosuna yazar.

    ⚠️ YALNIZCA GUARD'I GEÇEN DEĞERLER (§8.6). Bu tablo arayüzün ve
    karşılaştırma motorunun okuduğu yerdir; reddedilmiş bir çıkarımın
    buraya sızması, halüsinasyonun kullanıcıya gösterilmesi demektir.

    ⚠️ Tabloda kolonu OLMAYAN alanlar atlanır: `start_date`, `sector` gibi
    alanlar `campaigns` ve `campaign_categories` tablolarına aittir.
    """
    kayit = session.scalar(select(CampaignMetric).where(CampaignMetric.campaign_id == campaign.id))
    if kayit is None:
        kayit = CampaignMetric(campaign_id=campaign.id)
        session.add(kayit)

    for alan in fields:
        if not hasattr(kayit, alan.field_name):
            continue
        deger = _coerce(alan.value_normalized, alan.unit)
        if deger is not None:
            setattr(kayit, alan.field_name, deger)


async def _classify_and_summarize(
    session: Session,
    provider: LLMProvider,
    kampanya: Campaign,
    metin: str,
    *,
    prompt_version: str,
    sayac: _Sayaclar,
    use_cache: bool,
) -> None:
    """Sınıflandırma boşluklarını doldurur ve özet üretir (KAPI A8).

    ⚠️ İKİSİ DE ÇIKARIMDAN AYRIDIR ve hatası çıkarımı düşürmez. Özet
    üretilemeyen bir kampanyanın alanları yine de çıkarılmış olmalıdır;
    tersi, ikincil bir özelliğin birincil veriyi götürmesi olurdu.

    ⚠️ ÖZET YALNIZCA DOĞRULAMAYI GEÇERSE yazılır. Geçemezse `summary_ai`
    None kalır — yanlış özet göstermektense özet göstermemek doğrudur.
    """
    siniflandirma = await complete_classification(
        provider,
        session,
        kampanya,
        metin,
        prompt_version=prompt_version,
        use_cache=use_cache,
    )
    sayac.llm_cagri += siniflandirma.llm_calls
    sayac.onbellek += siniflandirma.cache_hits
    sayac.etiket_eklendi += len(siniflandirma.added)
    sayac.etiket_reddedildi += len(siniflandirma.rejected_labels)
    sayac.eksen_soruldu += len(siniflandirma.requested_axes)

    if sayac.yasakli_terimler is None:
        # Sözlük çalıştırma başına BİR KEZ okunur; 495 kampanyada
        # 495 sorgu anlamsız olurdu.
        sayac.yasakli_terimler = load_forbidden_terms(session)

    ozet = await summarize(
        provider,
        session,
        kampanya,
        metin,
        sayac.yasakli_terimler,
        prompt_version=prompt_version,
        use_cache=use_cache,
    )
    sayac.llm_cagri += ozet.llm_calls
    sayac.onbellek += ozet.cache_hits

    if ozet.accepted:
        kampanya.summary_ai = ozet.summary
        sayac.ozet_uretildi += 1
    elif ozet.rejected_reason:
        sayac.ozet_reddedildi += 1
        sayac.ozet_red_sayaci[ozet.rejected_reason] = (
            sayac.ozet_red_sayaci.get(ozet.rejected_reason, 0) + 1
        )


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

    bulgular: list[ExtractedField] = []
    bulunan_alanlar: set[str] = set()

    if mode in RULE_MODES:
        for alan in extract_rule_based(metin):
            bulgular.append(alan)
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
        bulgular.extend(sonuc.fields)

        # ── KAPI A8 — sınıflandırma + özetleme ────────────
        await _classify_and_summarize(
            session,
            provider,
            kampanya,
            metin,
            prompt_version=prompt_version,
            sayac=sayac,
            use_cache=use_cache,
        )
        session.flush()

    # ⚠️ Taksonomi SINIFLANDIRMADAN SONRA taşınır. Aksi hâlde LLM etiketleri
    # `campaign_categories`'e yazılır ama çıkarım / F1 eski kural satırını görür.
    if mode in RULE_MODES:
        for alan in _taxonomy_fields(session, kampanya):
            bulgular.append(alan)
            bulunan_alanlar.add(alan.field_name)

    # ── KAPI A7 — halüsinasyon guard'ı ────────────────────
    guard = guard_fields(bulgular, metin)

    for alan, gerekce in guard.rejected:
        # ⚠️ REDDEDİLEN KAYIT SİLİNMEZ. Halüsinasyon oranı ancak
        # reddedilenler kayıtlıysa raporlanabilir.
        satir = _to_row(kampanya, alan, prompt_version)
        satir.rejected_reason = gerekce
        satir.is_validated = False
        session.add(satir)
        sayac.reddedilen += 1
        sayac.katman_sayaci[gerekce] = sayac.katman_sayaci.get(gerekce, 0) + 1

    for alan in guard.accepted:
        satir = _to_row(kampanya, alan, prompt_version)
        ihlal = guard.logic_violations.get(alan.field_name)
        # Mantık ihlali kaydı REDDETMEZ, doğrulanmamış işaretler.
        satir.is_validated = ihlal is None
        if ihlal:
            satir.validation_note = ihlal
            sayac.mantik_ihlali += 1
        session.add(satir)
        sayac.say(alan.field_name)

    # ── Merger + campaign_metrics ─────────────────────────
    birlesim = merge_extractions(guard.accepted, campaign_id=kampanya.id)
    sayac.catismalar.extend(birlesim.conflicts)
    # ⚠️ `campaign_metrics` YALNIZCA guard'ı geçmiş ve mantık ihlali
    # olmayan değerlerle doldurulur (§8.6).
    _write_metrics(
        session,
        kampanya,
        [alan for alan in birlesim.fields if alan.field_name not in guard.logic_violations],
    )

    sayac.kampanya += 1
