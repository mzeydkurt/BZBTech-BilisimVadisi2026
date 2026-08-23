"""Arama gövdesi — kart metni ve süzgeç için gereken yapısal alanlar.

ARAMA GÖVDESİ `entity_cards` TABLOSUDUR. Kart üretimi (`app/ai/cards.py`)
yapısal değerleri Türkçe cümleye çeviriyor: `profit_rate_pct=0` satırı
aranamaz ama "kâr payı oranı %0" aranabilir. Kartlara YALNIZCA doğrulanmış ve
güveni ≥0,60 olan değerler giriyor; guard'ın elediği bir değer arama gövdesine
de girmez.

KART METNİ TEK BAŞINA YETMEZ. Sert süzgeçler (banka, durum, taksonomi,
sayısal kısıt) kart METNİNDEN okunamaz — okunmaya çalışılırsa "kâr payı %2'nin
altında" sorgusu, metinde "2" geçen her kartı geçirir. Süzgeçler yapısal
kolonlardan uygulanır; kart metni yalnızca SIRALAMA içindir.

GÖVDE HER İSTEKTE YENİDEN KURULMAZ. 1.253 kartı her sorguda yeniden
simgelemek gereksiz; gövde süreç ömrü boyunca önbelleklenir ve veri
değiştiğinde `invalidate_corpus()` ile düşürülür.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Bank, Campaign, CampaignCategory, CampaignMetric, EntityCard, Product
from app.logging_config import get_logger
from app.retrieval.lexical import Bm25Index

logger = get_logger(__name__)

CAMPAIGN_ENTITY: Final[str] = "campaign"
PRODUCT_ENTITY: Final[str] = "product"


@dataclass(frozen=True)
class CampaignDoc:
    """Bir kampanyanın arama ve süzgeç için gereken tüm alanları."""

    campaign_id: int
    bank_code: str
    bank_name: str
    title: str
    card_text: str
    status: str
    source_url: str
    date_precision: str
    # Eksen → o kampanyanın etiketleri.
    axis_values: dict[str, frozenset[str]]
    # `campaign_metrics` alanları; yalnızca DOLU olanlar bulunur.
    metrics: dict[str, Decimal]
    summary: str | None


@dataclass(frozen=True)
class ProductDoc:
    """Finansman ürünü arama belgesi."""

    product_id: int
    bank_code: str
    bank_name: str
    name: str
    product_type: str | None
    card_text: str
    source_url: str | None


@dataclass(frozen=True)
class Corpus:
    """Aranabilir gövde ve kurulu BM25 dizini."""

    docs: dict[int, CampaignDoc]
    index: Bm25Index
    product_docs: dict[int, ProductDoc] | None = None
    product_index: Bm25Index | None = None

    @property
    def size(self) -> int:
        """Gövdedeki kampanya sayısı."""
        return len(self.docs)


# ⚠️ `Decimal` KORUNUR. Sayısal kısıt karşılaştırması `float`a çevrilirse
# "%2'nin altında" sorgusu %2,00 oranlı kampanyayı yuvarlama hatasıyla
# içeri alabilir ya da dışarıda bırakabilir (CLAUDE.md: float YASAK).
_METRIC_FIELDS: Final[tuple[str, ...]] = (
    "profit_rate_pct",
    "profit_share_rate_pct",
    "term_months_min",
    "term_months_max",
    "installment_count",
    "financing_amount_min",
    "financing_amount_max",
    "min_spend_try",
    "max_spend_try",
    "reward_amount_try",
    "cashback_pct",
    "discount_pct",
    "loyalty_points",
    "max_total_benefit_try",
)

_cache: Corpus | None = None
_cache_fingerprint: tuple[int, ...] | None = None


def invalidate_corpus() -> None:
    """Önbelleği elle düşürür.

    Normalde gerekmez — parmak izi denetimi (`_parmak_izi`) veri değişikliğini
    kendiliğinden yakalar. Testlerde ve veri yolunu doğrudan değiştiren
    betiklerde açık düşürme kullanılabilir.
    """
    global _cache, _cache_fingerprint
    _cache = None
    _cache_fingerprint = None


def _parmak_izi(session: Session) -> tuple[int, int, int, int]:
    """Gövdenin değişip değişmediğini anlatan ucuz imza.

    ⚠️ ÖNBELLEK KOŞULSUZ TUTULAMAZ. Süreç ömrü boyunca saklanan bir gövde,
    `kart-uret` ya da `siniflandir` çalıştıktan sonra ESKİ metinlerle arama
    yapmaya devam eder ve bunu hiçbir yerde bildirmez. Aynı sorun testlerde de
    çıkıyor: bir testin kurduğu gövde, farklı bir veritabanı kullanan sonraki
    teste sızıyor.

    Dört sayaç: kampanya kartı, en büyük kart id, kampanya sayısı, ürün kartı.
    """
    kart_adedi = (
        session.scalar(
            select(func.count())
            .select_from(EntityCard)
            .where(EntityCard.entity_type == CAMPAIGN_ENTITY)
        )
        or 0
    )
    en_buyuk_kart = (
        session.scalar(
            select(func.max(EntityCard.id)).where(EntityCard.entity_type == CAMPAIGN_ENTITY)
        )
        or 0
    )
    kampanya_adedi = session.scalar(select(func.count()).select_from(Campaign)) or 0
    urun_kart = (
        session.scalar(
            select(func.count())
            .select_from(EntityCard)
            .where(EntityCard.entity_type == PRODUCT_ENTITY)
        )
        or 0
    )
    return int(kart_adedi), int(en_buyuk_kart), int(kampanya_adedi), int(urun_kart)


def _metrikler(metric: CampaignMetric | None) -> dict[str, Decimal]:
    """Dolu metrik alanlarını sözlüğe alır.

    ⚠️ `None` ALANLAR SÖZLÜĞE GİRMEZ, SIFIR OLARAK YAZILMAZ. Kâr payı oranı
    çıkarılamamış bir kampanyayı `0` saymak, onu "en düşük oranlı kampanya"
    yapar ve `unknown` bilgisini sessizce sıfıra çevirir.
    """
    if metric is None:
        return {}
    sonuc: dict[str, Decimal] = {}
    for alan in _METRIC_FIELDS:
        deger = getattr(metric, alan, None)
        if deger is None:
            continue
        sonuc[alan] = deger if isinstance(deger, Decimal) else Decimal(str(deger))
    return sonuc


def build_corpus(session: Session) -> Corpus:
    """Arama gövdesini kurar ve önbelleğe alır.

    Kartı OLMAYAN kampanya gövdeye girmez: kart yoksa aranabilir metin de
    yoktur. Bu durum loglanır — sessizce eksik gövdeyle arama yapmak,
    "kampanya bulunamadı" yanıtını yanlış nedenle üretir.

    Args:
        session: Veritabanı oturumu.

    Returns:
        Kampanya belgeleri ve kurulu BM25 dizini.
    """
    global _cache, _cache_fingerprint
    imza = _parmak_izi(session)
    if _cache is not None and _cache_fingerprint == imza:
        return _cache

    kartlar = {
        kart.entity_id: kart.card_text
        for kart in session.scalars(
            select(EntityCard).where(EntityCard.entity_type == CAMPAIGN_ENTITY)
        )
    }

    etiketler: dict[int, dict[str, set[str]]] = {}
    for etiket in session.scalars(select(CampaignCategory)):
        eksen_sozlugu = etiketler.setdefault(etiket.campaign_id, {})
        eksen_sozlugu.setdefault(etiket.axis, set()).add(etiket.value)

    docs: dict[int, CampaignDoc] = {}
    kartsiz = 0
    satirlar = session.execute(
        select(Campaign, Bank, CampaignMetric)
        .join(Bank, Bank.id == Campaign.bank_id)
        .outerjoin(CampaignMetric, CampaignMetric.campaign_id == Campaign.id)
    ).all()

    for kampanya, banka, metrik in satirlar:
        kart_metni = kartlar.get(kampanya.id)
        if not kart_metni:
            kartsiz += 1
            continue
        docs[kampanya.id] = CampaignDoc(
            campaign_id=kampanya.id,
            bank_code=banka.code,
            bank_name=banka.name,
            title=kampanya.title,
            card_text=kart_metni,
            status=kampanya.status,
            source_url=kampanya.source_url,
            date_precision=kampanya.date_precision,
            axis_values={
                eksen: frozenset(degerler)
                for eksen, degerler in etiketler.get(kampanya.id, {}).items()
            },
            metrics=_metrikler(metrik),
            summary=kampanya.summary_ai,
        )

    if kartsiz:
        logger.warning(
            "arama_govdesinde_kartsiz_kampanya",
            adet=kartsiz,
            not_="`python dev.py kart-uret` çalıştırılmalı; bu kampanyalar aranamıyor",
        )

    # ⚠️ Başlık kart metnine EKLENİR. Kart üretimi başlığı zaten ilk satıra
    # koyuyor ama bir kampanyanın kartı yeniden üretilmemişse başlık düşebilir;
    # başlık aramanın en güçlü sinyali olduğu için burada güvence altına alınır.
    gövde = {
        doc.campaign_id: f"{doc.title}\n{doc.bank_name}\n{doc.card_text}" for doc in docs.values()
    }

    # Finansman ürün kartları — kampanya gövdesinden AYRI indekslenir
    # (kimlik çakışması olmasın diye). Chat finansman sorularında buraya bakar.
    urun_kartlari = {
        kart.entity_id: kart.card_text
        for kart in session.scalars(
            select(EntityCard).where(EntityCard.entity_type == PRODUCT_ENTITY)
        )
    }
    product_docs: dict[int, ProductDoc] = {}
    for urun, banka in session.execute(
        select(Product, Bank).join(Bank, Bank.id == Product.bank_id)
    ).all():
        kart_metni = urun_kartlari.get(urun.id)
        if not kart_metni:
            continue
        product_docs[urun.id] = ProductDoc(
            product_id=urun.id,
            bank_code=banka.code,
            bank_name=banka.name,
            name=urun.name,
            product_type=urun.product_type,
            card_text=kart_metni,
            source_url=None,
        )
    urun_govde = {
        d.product_id: f"{d.name}\n{d.bank_name}\n{d.card_text}" for d in product_docs.values()
    }

    _cache = Corpus(
        docs=docs,
        index=Bm25Index(gövde),
        product_docs=product_docs or None,
        product_index=Bm25Index(urun_govde) if urun_govde else None,
    )
    _cache_fingerprint = imza
    logger.info(
        "arama_govdesi_kuruldu",
        kampanya=len(docs),
        urun=len(product_docs),
        kartsiz=kartsiz,
    )
    return _cache
