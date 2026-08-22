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

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Bank, Campaign, CampaignCategory, CampaignMetric, EntityCard
from app.logging_config import get_logger
from app.retrieval.lexical import Bm25Index

logger = get_logger(__name__)

CAMPAIGN_ENTITY: Final[str] = "campaign"


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
class Corpus:
    """Aranabilir gövde ve kurulu BM25 dizini."""

    docs: dict[int, CampaignDoc]
    index: Bm25Index

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


def invalidate_corpus() -> None:
    """Önbelleği düşürür.

    `siniflandir`, `cikarim`, `kart-uret` gibi veriyi değiştiren komutlardan
    sonra çağrılır. Düşürülmezse arama, süreç yeniden başlatılana kadar eski
    kart metinlerini kullanmaya devam eder.
    """
    global _cache
    _cache = None


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
    global _cache
    if _cache is not None:
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
    _cache = Corpus(docs=docs, index=Bm25Index(gövde))
    logger.info("arama_govdesi_kuruldu", kampanya=len(docs), kartsiz=kartsiz)
    return _cache
