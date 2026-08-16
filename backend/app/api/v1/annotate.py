"""Gold set etiketleme uçları ve arayüzü.

Bu uçlar yalnızca YEREL etiketleme aracını besler; genel API'nin parçası
değildir. Ayrı bir sunucu (`http.server`) yerine mevcut FastAPI üzerinde
durmalarının nedeni CORS'tur: iki ayrı köken arasında istek atmak, tek
kullanıcılı yerel bir araç için gereksiz karmaşıklık üretir ve yeni bağımlılık
eklemeden çözülemez.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Final

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app.ai.extraction import extract_rule_based
from app.ai.fields import EXTRACTABLE_FIELDS, options_for, unit_of
from app.api.deps import DbSession
from app.core.normalization.date_tr import parse_date_tr
from app.core.vocab import ANNOTATION_METHODS
from app.db.models import Bank, Campaign, GoldAnnotation, SourceDocument
from app.schemas.annotate import (
    AnnotatedField,
    AnnotationIn,
    AnnotationOut,
    CampaignForAnnotation,
    ProgressOut,
)
from app.services.gold_service import BLIND_COUNT, gold_progress, load_sample

router = APIRouter(prefix="/annotate", tags=["gold set"])

# backend/app/api/v1/annotate.py -> backend/ -> depo kökü
REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[4]
SAMPLE_PATH: Final[Path] = REPO_ROOT / "data" / "gold" / "gold_sample.jsonl"
UI_PATH: Final[Path] = Path(__file__).resolve().parents[2] / "static" / "annotate.html"


def _sample_index() -> dict[int, dict[str, Any]]:
    """Örneklemi kampanya kimliğine göre indeksler."""
    return {int(kayit["campaign_id"]): kayit for kayit in load_sample(SAMPLE_PATH)}


@router.get("/ui", response_class=HTMLResponse, include_in_schema=False)
def annotation_ui() -> HTMLResponse:
    """Etiketleme arayüzünü döndürür."""
    if not UI_PATH.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Etiketleme arayüzü bulunamadı")
    return HTMLResponse(UI_PATH.read_text(encoding="utf-8"))


@router.get("/fields", summary="Etiketlenecek alanlar")
def read_fields() -> dict[str, dict[str, Any]]:
    """Alan adı → birim ve (varsa) kontrollü değer listesi.

    Arayüz form alanlarını bu listeden üretir; alan listesi tek yerde
    (`app/ai/fields.py`) tanımlıdır ki etiketleme ile çıkarım ayrışmasın.

    ⚠️ Enum alanlarda `options` dolu gelir ve arayüz bunları otomatik
    tamamlama olarak sunar: elle yazılan bir değer (`e-ticaret` yerine
    `eticaret_pazaryeri`) değerlendirmede sessizce "yanlış" sayılırdı.
    """
    return {
        ad: {"unit": birim, "options": list(options_for(ad))}
        for ad, birim in EXTRACTABLE_FIELDS.items()
    }


@router.get("/progress", response_model=ProgressOut, summary="Etiketleme ilerlemesi")
def read_progress(session: DbSession) -> ProgressOut:
    """Kaç kampanyanın etiketlendiğini ve kör/ön-doldurmalı dağılımını verir."""
    ilerleme = gold_progress(session)
    return ProgressOut(
        sample_size=len(load_sample(SAMPLE_PATH)),
        annotated_campaigns=ilerleme.annotated_campaigns,
        total_annotations=ilerleme.total_annotations,
        blind_campaigns=ilerleme.blind_campaigns,
        blind_target=BLIND_COUNT,
        assisted_campaigns=ilerleme.assisted_campaigns,
        difficult_campaigns=ilerleme.difficult_campaigns,
        explicit_null_fields=ilerleme.explicit_null_fields,
    )


@router.get("/next", response_model=CampaignForAnnotation, summary="Sıradaki kampanya")
def read_next(
    session: DbSession,
    method: str | None = Query(default=None, description=f"Filtre: {ANNOTATION_METHODS}"),
) -> CampaignForAnnotation:
    """Örneklemde henüz etiketlenmemiş ilk kampanyayı döndürür.

    ⚠️ SIRA KORUNUR: örneklemin ilk `BLIND_COUNT` kaydı kördür. Sıra
    atlanırsa kör alt küme eksik kalır ve yanlılık ölçümü yapılamaz.
    """
    etiketli = set(session.scalars(select(GoldAnnotation.campaign_id).distinct()))

    for kayit in load_sample(SAMPLE_PATH):
        if method and kayit.get("method") != method:
            continue
        if int(kayit["campaign_id"]) in etiketli:
            continue
        return _build(session, int(kayit["campaign_id"]))

    raise HTTPException(status.HTTP_404_NOT_FOUND, "Etiketlenecek kampanya kalmadı")


@router.get("/{campaign_id}", response_model=CampaignForAnnotation, summary="Kampanya detayı")
def read_campaign(session: DbSession, campaign_id: int) -> CampaignForAnnotation:
    """Tek bir kampanyayı etiketleme bağlamıyla döndürür."""
    return _build(session, campaign_id)


def _normalize_gold(deger: str | None, birim: str) -> str | None:
    """Etiket değerini kılavuzun biçimine getirir.

    ⚠️ Şu an yalnızca TARİH normalize edilir. Kılavuz (§4.5) `2026-08-31`
    diyor ama arayüzden `31.08.2026` de yazılabiliyor; 67 tarih etiketinin
    14'ü böyle kaydedilmişti. Değerlendirici artık iki biçimi de anlıyor
    ama gold set'in KENDİSİ tutarlı olmalı: dosyaya dışa aktarıldığında
    (`gold_set.jsonl`) biçim karışıklığı sonraki her tüketiciye taşınır.

    ⚠️ Ayrıştırılamayan değer DEĞİŞTİRİLMEDEN saklanır. Etiketleyicinin
    yazdığını sessizce atmak, düzeltilemeyecek bir veri kaybıdır.

    Args:
        deger: Etiketleyicinin yazdığı ham değer.
        birim: Alanın birimi.

    Returns:
        Normalize edilmiş değer.
    """
    if deger is None or birim != "date":
        return deger

    ham = deger.strip()
    if not ham:
        return deger
    try:
        return date.fromisoformat(ham).isoformat()
    except ValueError:
        ayristirilan = parse_date_tr(ham)
        return ayristirilan.isoformat() if ayristirilan else deger


@router.post(
    "/{campaign_id}",
    response_model=list[AnnotationOut],
    status_code=status.HTTP_201_CREATED,
    summary="Etiketleri kaydet",
)
def save_annotations(
    session: DbSession, campaign_id: int, payload: AnnotationIn
) -> list[AnnotationOut]:
    """Bir kampanyanın etiketlerini kaydeder veya günceller.

    ⚠️ YALNIZCA GÖNDERİLEN ALANLAR yazılır. Gövdede bulunmayan bir alan için
    kayıt oluşturulmaz; "etiketlenmedi" durumu böyle temsil edilir.
    Gövdede bulunan ama `value=null` olan alan ise ∅'dir: "metinde YOK".

    Raises:
        HTTPException: Kampanya yoksa (404), yöntem ya da alan adı
            geçersizse (422).
    """
    if session.get(Campaign, campaign_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Kampanya bulunamadı: {campaign_id}")

    if payload.method not in ANNOTATION_METHODS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Geçersiz yöntem: {payload.method!r}. Geçerli: {ANNOTATION_METHODS}",
        )

    bilinmeyen = [ad for ad in payload.fields if ad not in EXTRACTABLE_FIELDS]
    if bilinmeyen:
        # Sessizce yok sayılırsa, yazım hatası olan bir alan etiketlenmiş
        # sanılır ve değerlendirmede "sistem kaçırdı" olarak görünür.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Tanımsız alan: {bilinmeyen}")

    mevcut = {
        kayit.field_name: kayit
        for kayit in session.scalars(
            select(GoldAnnotation).where(
                GoldAnnotation.campaign_id == campaign_id,
                GoldAnnotation.annotator == payload.annotator,
            )
        )
    }

    kaydedilen: list[GoldAnnotation] = []
    for alan_adi, alan in payload.fields.items():
        kayit = mevcut.get(alan_adi)
        if kayit is None:
            kayit = GoldAnnotation(
                campaign_id=campaign_id, field_name=alan_adi, annotator=payload.annotator
            )
            session.add(kayit)

        birim = alan.unit or unit_of(alan_adi)
        kayit.gold_value = _normalize_gold(alan.value, birim)
        kayit.unit = birim
        kayit.evidence_text = alan.evidence
        kayit.method = payload.method
        kayit.is_difficult = payload.is_difficult
        kayit.note = payload.note
        kaydedilen.append(kayit)

    session.commit()
    return [AnnotationOut.model_validate(kayit) for kayit in kaydedilen]


def _build(session: DbSession, campaign_id: int) -> CampaignForAnnotation:
    """Kampanyayı etiketleme bağlamıyla birleştirir."""
    satir = session.execute(
        select(Campaign, Bank, SourceDocument.clean_text)
        .join(Bank, Bank.id == Campaign.bank_id)
        .outerjoin(SourceDocument, Campaign.source_document_id == SourceDocument.id)
        .where(Campaign.id == campaign_id)
    ).first()

    if satir is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Kampanya bulunamadı: {campaign_id}")

    campaign, bank, clean_text = satir
    ornek = _sample_index().get(campaign_id, {})

    mevcut = list(
        session.scalars(
            select(GoldAnnotation)
            .where(GoldAnnotation.campaign_id == campaign_id)
            .order_by(GoldAnnotation.field_name)
        )
    )

    return CampaignForAnnotation(
        campaign_id=campaign_id,
        order=ornek.get("order"),
        bank_code=bank.code,
        bank_name=bank.name,
        title=campaign.title,
        source_url=campaign.source_url,
        clean_text=clean_text or "",
        method=str(ornek.get("method", "blind")),
        is_difficult=bool(ornek.get("is_difficult", False)),
        difficulty_reasons=list(ornek.get("difficulty_reasons", [])),
        existing=[AnnotationOut.model_validate(k) for k in mevcut],
        # ⚠️ Kör kipte arayüz bu değerleri GÖSTERMEZ; yalnızca `assisted`
        # kipte ön-doldurma olarak kullanılır.
        prefill=_prefill(clean_text),
    )


def _prefill(clean_text: str | None) -> dict[str, AnnotatedField]:
    """Kural tabanlı çıkarımdan ön-doldurma değerleri üretir.

    ⚠️ YALNIZCA `assisted` KİPTE KULLANILIR. Kör etiketlemede (ilk 30 kayıt)
    arayüz bu değerleri hiç göstermez: sistemin cevabını gören etiketleyici
    ona meyleder ve F1 sahte şişer. Yanlılık ölçümü tam olarak bu iki kipin
    farkına dayanıyor.

    ⚠️ Aynı alan için birden çok eşleşme varsa İLKİ korunur. Ön-doldurma bir
    ÖNERİDİR; karar etiketleyicinindir.

    Args:
        clean_text: Kampanyanın temizlenmiş metni.

    Returns:
        Alan adı → önerilen değer ve kanıt.
    """
    if not clean_text:
        return {}

    oneriler: dict[str, AnnotatedField] = {}
    for bulgu in extract_rule_based(clean_text):
        if bulgu.field_name in oneriler:
            continue
        oneriler[bulgu.field_name] = AnnotatedField(
            value=bulgu.value_normalized,
            evidence=bulgu.evidence_text,
            unit=bulgu.unit,
        )
    return oneriler
