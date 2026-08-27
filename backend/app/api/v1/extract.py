"""Canlı çıkarım ucu — `POST /api/v1/extract` (KAPI A9).

Şartname madde 6'daki *"metin girdisi verilmesi"* gereksiniminin birebir
karşılığı: kullanıcı ham bir kampanya metni yapıştırır, sistem alanları
kanıtlarıyla birlikte döndürür.

⚠️ VERİTABANINA HİÇBİR ŞEY YAZILMAZ. Bu uç bir demo/deneme aracıdır;
girilen metin bir kampanya kaydı değildir. Yazsaydı, denemeler gerçek
veri setini kirletir ve F1 ölçümü anlamını yitirirdi.

⚠️ AYNI KATMANLAR, AYNI GUARD. Uç, kendi çıkarım mantığını YAZMAZ —
`extract_rule_based`, `extract_llm` ve `guard_fields` doğrudan çağrılır.
Ayrı bir kod yolu, arayüzde gösterilen sonucun toplu çalıştırmadan farklı
olması demek olurdu.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, status

from app.ai.classification import AXIS_VOCAB
from app.ai.extraction import extract_rule_based
from app.ai.extraction.llm_extractor import extract_llm
from app.ai.pipeline import IMPLEMENTED_MODES, LLM_MODES, RULE_MODES
from app.ai.providers import get_provider
from app.ai.summarization import summarize
from app.ai.validation import guard_fields, merge_extractions
from app.ai.validation.terminology import load_forbidden_terms
from app.api.deps import DbSession
from app.config import get_settings
from app.processing.categorizer import categorize
from app.schemas.extract import (
    ExtractedFieldOut,
    ExtractRequest,
    ExtractResponse,
    ModelInfoOut,
    RejectedFieldOut,
)

router = APIRouter(prefix="/extract", tags=["extract"])


class _GeciciKampanya:
    """`extract_llm` ve `summarize` için asgari kampanya nesnesi.

    ⚠️ Veritabanı kaydı DEĞİLDİR; yalnızca günlükleme ve imza uyumu için
    vardır. `id=None` olması bu kaydın kalıcı olmadığını açıkça gösterir.
    """

    id = None
    source_url = None
    summary_ai: str | None = None


@router.post(
    "",
    response_model=ExtractResponse,
    summary="Verilen metinden bilgi çıkarır",
)
async def extract_from_text(session: DbSession, payload: ExtractRequest) -> ExtractResponse:
    """Ham metinden alanları, etiketleri ve özeti çıkarır.

    Args:
        session: Veritabanı oturumu (yalnızca önbellek ve sözlük için).
        payload: Metin ve çalıştırma kipi.

    Returns:
        Alanlar, kanıtlar, reddedilenler ve model kimliği.

    Raises:
        HTTPException: Tanımsız kip verildiyse.
    """
    if payload.mode not in IMPLEMENTED_MODES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Tanımsız kip: {payload.mode!r}. Geçerli: {IMPLEMENTED_MODES}",
        )

    baslangic = time.monotonic()
    ayarlar = get_settings()
    metin = payload.text
    kampanya = _GeciciKampanya()

    bulgular = []
    if payload.mode in RULE_MODES:
        bulgular.extend(extract_rule_based(metin))

    saglayici = get_provider(ayarlar)
    ozet_metni: str | None = None

    if payload.mode in LLM_MODES:
        cozulen = {alan.field_name for alan in bulgular}
        llm_sonuc = await extract_llm(
            saglayici,
            session,
            metin,
            kampanya,
            cozulen,
            prompt_version=ayarlar.prompt_version,
        )
        bulgular.extend(llm_sonuc.fields)

        ozet = await summarize(
            saglayici,
            session,
            kampanya,  # type: ignore[arg-type]
            metin,
            load_forbidden_terms(session),
            prompt_version=ayarlar.prompt_version,
        )
        # ⚠️ Doğrulamayı geçemeyen özet DÖNDÜRÜLMEZ.
        ozet_metni = ozet.summary if ozet.accepted else None

    # ── Guard + merger ────────────────────────────────────
    guard = guard_fields(bulgular, metin)
    birlesim = merge_extractions(guard.accepted)

    alanlar = {
        alan.field_name: ExtractedFieldOut(
            value=alan.value_normalized,
            unit=alan.unit,
            confidence=float(alan.confidence),
            method=alan.method,
            evidence=alan.evidence_text or None,
            evidence_span=(
                (alan.evidence_char_start, alan.evidence_char_end)
                if alan.evidence_char_start is not None and alan.evidence_char_end is not None
                else None
            ),
            validation_note=alan.validation_note or guard.logic_violations.get(alan.field_name),
        )
        for alan in birlesim.fields
    }

    reddedilenler = [
        RejectedFieldOut(
            field_name=alan.field_name,
            value=alan.value_normalized,
            method=alan.method,
            reason=gerekce,
            evidence=alan.evidence_text or None,
        )
        for alan, gerekce in guard.rejected
    ]

    # Sınıflandırma DÖRT eksende metinden yapılır; `categorize` veritabanı
    # gerektirmez, tek metinlik istekte de çalışır.
    #
    # ⚠️ Yalnızca çıkarılan enum alanlarına bakmak, `audience` ve `benefit`
    # eksenlerini tamamen dışarıda bırakıyordu: "Emeklilere" ve "Yeni
    # müşterilerimize" geçen bir metinde `labels` BOŞ dönüyordu. Şartname
    # "hedef müşteri" alanını adıyla sayıyor.
    etiketler: dict[str, list[str]] = {}
    for etiket in categorize(title=metin.split("\n", 1)[0], body_text=metin):
        etiketler.setdefault(etiket.axis, []).append(etiket.value)

    # Çıkarım katmanı bir eksende değer bulduysa o da eklenir (tekrar etmeden).
    for alan_adi, eksen in (("product_type", "product_type"), ("sector", "sector")):
        bulgu = alanlar.get(alan_adi)
        if (
            bulgu
            and bulgu.value in AXIS_VOCAB[eksen]
            and bulgu.value not in etiketler.get(eksen, [])
        ):
            etiketler.setdefault(eksen, []).append(bulgu.value)

    model_bilgisi = saglayici.model_info
    return ExtractResponse(
        fields=alanlar,
        labels=etiketler,
        summary=ozet_metni,
        rejected=reddedilenler,
        logic_violations=guard.logic_violations,
        model=ModelInfoOut(
            name=model_bilgisi.name,
            license=model_bilgisi.license,
            local=model_bilgisi.is_local,
        ),
        latency_ms=int((time.monotonic() - baslangic) * 1000),
        mode=payload.mode,
    )
