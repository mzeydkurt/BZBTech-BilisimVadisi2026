"""Gold set etiketleme uçları ve arayüzü.

Bu uçlar yalnızca YEREL etiketleme aracını besler; genel API'nin parçası
değildir. Ayrı bir sunucu (`http.server`) yerine mevcut FastAPI üzerinde
durmalarının nedeni CORS'tur: iki ayrı köken arasında istek atmak, tek
kullanıcılı yerel bir araç için gereksiz karmaşıklık üretir ve yeni bağımlılık
eklemeden çözülemez.
"""

from __future__ import annotations

import re
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
from app.core.vocab import ANNOTATION_METHODS, OTO_KANIT_NOTU
from app.db.models import Bank, Campaign, GoldAnnotation, SourceDocument
from app.schemas.annotate import (
    AnnotatedField,
    AnnotationIn,
    AnnotationOut,
    CampaignForAnnotation,
    ProgressOut,
)
from app.services.gold_service import (
    BLIND_COUNT,
    campaign_key,
    gold_progress,
    load_sample,
)

router = APIRouter(prefix="/annotate", tags=["gold set"])

# backend/app/api/v1/annotate.py -> backend/ -> depo kökü
REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[4]
SAMPLE_PATH: Final[Path] = REPO_ROOT / "data" / "gold" / "gold_sample.jsonl"
UI_PATH: Final[Path] = Path(__file__).resolve().parents[2] / "static" / "annotate.html"


def _key_to_id(session: DbSession) -> dict[str, int]:
    """Kararlı anahtar → güncel `campaign_id` haritası."""
    satirlar = session.execute(
        select(Campaign.id, Bank.code, Campaign.external_slug).join(
            Bank, Bank.id == Campaign.bank_id
        )
    ).all()
    return {campaign_key(kod, slug): cid for cid, kod, slug in satirlar}


def _version_suffix_match(hedef_slug: str, aday_slug: str) -> bool:
    """Yeniden kazımada eklenen `-3` / `_1` sürüm ekini tolere eder.

    ⚠️ Miktar farkı olan slug'ları EŞLEŞTİRMEZ:
    `...idealfitte-1000-...` ≠ `...idealfitte-3000-...`
    Yalnızca bir slug diğerinin üzerine `[-_]\\d+` eklenmişse kabul edilir.
    """
    if hedef_slug == aday_slug:
        return True
    if re.fullmatch(re.escape(hedef_slug) + r"[-_]\d+", aday_slug):
        return True
    return bool(re.fullmatch(re.escape(aday_slug) + r"[-_]\d+", hedef_slug))


def _resolve_id(session: DbSession, kayit: dict[str, Any]) -> int | None:
    """Örneklem kaydını GÜNCEL kampanya kimliğine çözer.

    ⚠️ Önce `campaign_key`, sonra güvenli sürüm-eki eşleşmesi, en son
    (yalnızca anahtarsız eski örneklemde) `campaign_id`.

    ⚠️ Anahtar var ama kampanya yoksa id'ye DÜŞÜLMEZ — başka kampanyayı
    göstermek yanlış gold üretir. Yeniden kazımada slug'a eklenen `-N`
    eki için tek güvenli bulanık eşleşme yapılır.

    Args:
        session: Veritabanı oturumu.
        kayit: `gold_sample.jsonl` satırı.

    Returns:
        Güncel kampanya kimliği; kampanya artık yoksa None.
    """
    anahtar = kayit.get("campaign_key")
    if anahtar:
        harita = _key_to_id(session)
        cid = harita.get(str(anahtar))
        if cid is not None:
            return cid

        # bank_code:slug → sürüm ekiyle yeniden kazınmış olabilir.
        parca = str(anahtar).split(":", 1)
        if len(parca) != 2:
            return None
        banka_kodu, hedef_slug = parca
        adaylar = [
            (cid, slug)
            for key, cid in harita.items()
            if key.startswith(f"{banka_kodu}:")
            for slug in (key.split(":", 1)[1],)
        ]
        eslesen = [cid for cid, slug in adaylar if _version_suffix_match(hedef_slug, slug)]
        if len(eslesen) == 1:
            return eslesen[0]
        return None

    # Eski biçimli örneklem (anahtarsız): id ile devam edilir.
    kimlik = kayit.get("campaign_id")
    return int(kimlik) if kimlik is not None else None


def _sample_index(session: DbSession) -> dict[int, dict[str, Any]]:
    """Örneklemi GÜNCEL kampanya kimliğine göre indeksler."""
    indeks: dict[int, dict[str, Any]] = {}
    for kayit in load_sample(SAMPLE_PATH):
        cid = _resolve_id(session, kayit)
        if cid is not None:
            indeks[cid] = kayit
    return indeks


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
    orneklem = load_sample(SAMPLE_PATH)
    erisilebilir = sum(1 for kayit in orneklem if _resolve_id(session, kayit) is not None)
    return ProgressOut(
        sample_size=len(orneklem),
        reachable_campaigns=erisilebilir,
        orphan_campaigns=len(orneklem) - erisilebilir,
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
    annotator: str | None = Query(
        default=None,
        description="Bu etiketleyicinin henüz etiketlemediği ilk kayıt. Öz-tutarlılık turu için.",
    ),
) -> CampaignForAnnotation:
    """Örneklemde henüz etiketlenmemiş ilk kampanyayı döndürür.

    ⚠️ SIRA KORUNUR: örneklemin ilk `BLIND_COUNT` kaydı kördür. Sıra
    atlanırsa kör alt küme eksik kalır ve yanlılık ölçümü yapılamaz.

    """
    # Hem güncel campaign_id hem campaign_key ile bak: silme sonrası
    # campaign_id NULL kalan satırlar "etiketlenmemiş" sanılmasın.
    id_sorgu = select(GoldAnnotation.campaign_id).where(GoldAnnotation.campaign_id.isnot(None))
    key_sorgu = select(GoldAnnotation.campaign_key)
    if annotator:
        id_sorgu = id_sorgu.where(GoldAnnotation.annotator == annotator)
        key_sorgu = key_sorgu.where(GoldAnnotation.annotator == annotator)
    etiketli_id = set(session.scalars(id_sorgu.distinct()))
    etiketli_key = set(session.scalars(key_sorgu.distinct()))

    for kayit in load_sample(SAMPLE_PATH):
        if method and kayit.get("method") != method:
            continue
        cid = _resolve_id(session, kayit)
        if cid is None or cid in etiketli_id:
            continue
        anahtar = kayit.get("campaign_key")
        if anahtar and str(anahtar) in etiketli_key:
            continue
        return _build(session, cid, annotator=annotator)

    raise HTTPException(status.HTTP_404_NOT_FOUND, "Etiketlenecek kampanya kalmadı")


@router.get("/{campaign_id}", response_model=CampaignForAnnotation, summary="Kampanya detayı")
def read_campaign(
    session: DbSession,
    campaign_id: int,
    annotator: str | None = Query(
        default=None,
        description="Yalnızca bu etiketleyicinin kayıtları geri yüklenir (öz-tutarlılık turu).",
    ),
) -> CampaignForAnnotation:
    """Tek bir kampanyayı etiketleme bağlamıyla döndürür."""
    return _build(session, campaign_id, annotator=annotator)


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
    kampanya = session.get(Campaign, campaign_id)
    if kampanya is None:
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

    # Kampanya silinip yeniden kazınınca id değişir; UNIQUE (campaign_key,
    # field_name, annotator) eski satırlarda kalır (campaign_id SET NULL).
    # Yalnızca campaign_id ile bakmak INSERT → 500 IntegrityError üretir.
    banka = session.get(Bank, kampanya.bank_id)
    if banka is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Banka bulunamadı: {kampanya.bank_id}")
    anahtar = campaign_key(banka.code, kampanya.external_slug)

    mevcut = {
        kayit.field_name: kayit
        for kayit in session.scalars(
            select(GoldAnnotation).where(
                GoldAnnotation.campaign_key == anahtar,
                GoldAnnotation.annotator == payload.annotator,
            )
        )
    }

    kaydedilen: list[GoldAnnotation] = []
    for alan_adi, alan in payload.fields.items():
        kayit = mevcut.get(alan_adi)
        if kayit is None:
            kayit = GoldAnnotation(
                campaign_key=anahtar,
                campaign_id=campaign_id,
                field_name=alan_adi,
                annotator=payload.annotator,
            )
            session.add(kayit)
        else:
            # Öksüz satırı yeni kampanya id'sine yeniden bağla.
            kayit.campaign_id = campaign_id
            kayit.reanchor_method = kayit.reanchor_method or "slug"

        birim = alan.unit or unit_of(alan_adi)
        # ⚠️ `oto-kanit` işareti, kanıtın betikle bağlandığını (insan
        # doğrulaması OLMADIĞINI) söyler. Kanıt DEĞİŞMEDİYSE işaret korunur;
        # yoksa kampanyayı yeniden kaydetmek işareti sessizce siler ve
        # `gold-durum` raporu otomatik bağlamayı insan seçimi sayar.
        kanit_degisti = (kayit.evidence_text or "") != (alan.evidence or "")
        oto_isaretli = (kayit.note or "") == OTO_KANIT_NOTU

        kayit.gold_value = _normalize_gold(alan.value, birim)
        kayit.unit = birim
        kayit.evidence_text = alan.evidence
        kayit.method = payload.method
        kayit.is_difficult = payload.is_difficult
        kayit.note = OTO_KANIT_NOTU if (oto_isaretli and not kanit_degisti) else payload.note
        kaydedilen.append(kayit)

    session.commit()
    return [AnnotationOut.model_validate(kayit) for kayit in kaydedilen]


def _build(
    session: DbSession, campaign_id: int, *, annotator: str | None = None
) -> CampaignForAnnotation:
    """Kampanyayı etiketleme bağlamıyla birleştirir.

    ⚠️ `existing` YALNIZCA verilen etiketleyicinin kayıtlarını taşır.
    """
    satir = session.execute(
        select(Campaign, Bank, SourceDocument.clean_text)
        .join(Bank, Bank.id == Campaign.bank_id)
        .outerjoin(SourceDocument, Campaign.source_document_id == SourceDocument.id)
        .where(Campaign.id == campaign_id)
    ).first()

    if satir is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Kampanya bulunamadı: {campaign_id}")

    campaign, bank, clean_text = satir
    ornek = _sample_index(session).get(campaign_id, {})
    anahtar = campaign_key(bank.code, campaign.external_slug)

    # Yeniden kazıma sonrası eski satırlar campaign_id=NULL kalabilir; UI'nin
    # önceden kaydedilmiş etiketleri görmesi için anahtarla da bakılır.
    mevcut_sorgu = select(GoldAnnotation).where(GoldAnnotation.campaign_key == anahtar)
    if annotator:
        mevcut_sorgu = mevcut_sorgu.where(GoldAnnotation.annotator == annotator)
    mevcut = list(session.scalars(mevcut_sorgu.order_by(GoldAnnotation.field_name)))

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
