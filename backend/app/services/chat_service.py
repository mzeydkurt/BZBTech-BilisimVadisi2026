"""Kanıtlı arama — sorgu anlama, hibrit erişim, toplama ve yanıt üretimi.

Katmanların tamamı `app/retrieval/` altındadır; bu modül yalnızca onları
sıraya dizer ve API şemasına çevirir.

⚠️ SORGUDAKİ YASAKLI TERİM SORGUYU REDDETMEZ.
⚠️ MODEL ÇAĞRISI YALNIZCA CÜMLE İÇİN. Sıralama/süzgeç/toplama/tanim/kapsam_disi
modele hiç sorulmaz.
⚠️ `/compare` HTTP ile çağrılmaz — `rank_products` doğrudan kullanılır.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.providers import active_embedding_model, get_provider
from app.ai.providers.base import LLMProvider, LLMProviderError
from app.ai.validation.terminology import check_terminology, load_forbidden_terms
from app.config import get_settings
from app.core.normalization.text import ascii_fold_tr, lower_tr, normalize_text
from app.core.rate_direction import yon_notu
from app.core.vocab import KATILIM_HESABI_VADE_ETIKETI
from app.db.models.bank import Bank
from app.logging_config import get_logger
from app.retrieval import aggregate
from app.retrieval.answer import GeneratedAnswer, generate_answer
from app.retrieval.corpus import (
    CAMPAIGN_ENTITY,
    Corpus,
    GlossaryDoc,
    ProductDoc,
    ProductRateDoc,
    build_corpus,
)
from app.retrieval.lexical import tokenize
from app.retrieval.narrate import (
    FactTriple,
    NarrationFacts,
    narrate,
    relaxation_to_natural,
)
from app.retrieval.qdrant_store import QdrantStore, QdrantUnavailableError
from app.retrieval.query import (
    AggregateSpec,
    QueryPlan,
    merge_with_previous,
    parse_katilma_vadeler,
    parse_katilma_varyant,
    parse_query,
)
from app.retrieval.rank import RankCandidate, score_candidates
from app.retrieval.relevance import filter_relevant_hits, strip_citation_markers
from app.retrieval.search import (
    CHANNEL_CANDIDATES,
    SearchHit,
    SearchResult,
    filter_all,
    search,
)
from app.retrieval.semantic import EmbeddingStore, SemanticHit
from app.schemas.chat import (
    AggregateBlock,
    AnswerBlock,
    ChatComparisonBlock,
    ChatGlossaryItem,
    ChatMetric,
    ChatProductItem,
    ChatRequest,
    ChatResponse,
    ChatResultItem,
    ChatTopMatch,
    FilterRejection,
    RelaxationHintOut,
    RetrievalReport,
    TerminologyWarningOut,
    UnderstoodFilter,
    UnverifiedNumberOut,
)
from app.schemas.compare import CRITERIA
from app.schemas.katilim_hesabi import KatilimHesabiRow
from app.services import chat_model_service as chat_models
from app.services import chat_session_service as chat_sessions
from app.services.comparison_service import RankingError, rank_products
from app.services.katilim_hesabi_service import build_katilim_hesabi

logger = get_logger(__name__)

REJECTION_LABELS: dict[str, str] = {
    "banka": "Banka süzgeci",
    "durum": "Durum süzgeci",
    "eksen:product_type": "Ürün türü süzgeci",
    "eksen:sector": "Sektör süzgeci",
    "eksen:audience": "Hedef kitle süzgeci",
    "eksen:benefit": "Fayda süzgeci",
}

_KAPSAM_DISI_METIN = (
    "Bu soru katılım bankacılığı kampanya ve ürün kapsamının dışında. "
    "Kampanya, finansman, katılma hesabı veya kâr payı hakkında soru sorabilirsiniz."
)

_SOHBET_METIN = (
    "Merhaba, ben Katibim — katılım bankacılığı kampanya, finansman ve "
    "katılma hesabı asistanıyım. Bankalar arası oran karşılaştırması, "
    "kampanya arama ve finansman simülasyonu yapabilirim. "
    "Örnek: «En düşük konut finansmanı kâr payı hangi bankada?» veya "
    "«Kuveyt Türk’te aktif kart kampanyaları»."
)

_NETLESTIRME_SORU = (
    "Hangi oran türünü kastediyorsunuz: finansman kâr payı oranı, "
    "katılma hesabı dağıtılan kâr payı, yoksa kâr paylaşım oranı (müşteri payı)?"
)

_KATILMA_GIRIS = (
    "Katılma hesabı, katılım bankasında kâr-zarar ortaklığına dayanan vadeli "
    "birikim ürünüdür. Dağıtılan kâr payı (getiri) ile kâr paylaşım oranı "
    "(müşteri/banka payı, örn. 90/10) ayrı sayılardır."
)

_SIRA_ISARET: tuple[str, ...] = (
    "en ideal",
    "en iyi",
    "en yuksek",
    "en avantajli",
    "hangisi",
    "hangi banka",
    "hangi bankadan",
    "karsilastir",
    "daha iyi",
    "sence",
    "oner",
    "tavsiye",
    "acmaliyim",
    "acacagim",
)

_VADE_ADI: dict[int, str] = {1: "aylık", 3: "3 aylık", 6: "6 aylık", 12: "yıllık"}
_TUM_VADELER: tuple[int, ...] = (1, 3, 6, 12)


def _yuzde_yaz(deger: Decimal) -> str:
    """Decimal yüzdeyi Türkçe gösterir: 31.35 → %31,35 (40.000 yazılmaz)."""
    metin = format(deger, "f")
    if "." in metin:
        metin = metin.rstrip("0").rstrip(".")
    return f"%{metin.replace('.', ',')}"


def sirala_katilma_satirlari(
    satirlar: list[KatilimHesabiRow],
    *,
    hucre: str,
    limit: int = 3,
) -> list[tuple[KatilimHesabiRow, Decimal]]:
    """Pivot satırlarını tek hücreye göre (banka başına bir kez) sıralar."""
    adaylar: list[tuple[KatilimHesabiRow, Decimal]] = []
    for satir in satirlar:
        deger = satir.values.get(hucre)
        if deger is None:
            continue
        adaylar.append((satir, deger))
    adaylar.sort(key=lambda ikili: (-ikili[1], ikili[0].bank_name))
    return adaylar[:limit]


def _katilma_rate_type(plan: QueryPlan) -> str:
    folded = _fold(plan.raw)
    if plan.rate_type == "profit_sharing_ratio" or "paylasim" in folded:
        return "profit_sharing_ratio"
    # "ideal / getiri / aylık standart" → dağıtılan kâr payı (Katılım Hesabı sekmesi).
    return "participation_yield"


def _katilma_sirala_mi(plan: QueryPlan) -> bool:
    folded = _fold(plan.raw)
    return any(isaret in folded for isaret in _SIRA_ISARET) or plan.intent in {
        "compare",
        "aggregate",
    }


def _katilma_vade_secimi(folded: str, plan: QueryPlan) -> tuple[int, ...]:
    """Sorgudaki vadeler; vade yoksa ve sıralama varsa dört vade birden."""
    vadeler = parse_katilma_vadeler(folded)
    if vadeler:
        return vadeler
    if _katilma_sirala_mi(plan):
        return _TUM_VADELER
    return (1,)


def _selamla(folded: str) -> str:
    if folded.startswith("merhaba"):
        return "Merhaba."
    if folded.startswith("selam"):
        return "Selam."
    if folded.startswith("iyi gunler"):
        return "İyi günler."
    return ""


def _banka_sira_cumlesi(sirali: list[tuple[KatilimHesabiRow, Decimal]]) -> str:
    parcalar = [f"{satir.bank_name} {_yuzde_yaz(deger)}" for satir, deger in sirali]
    if not parcalar:
        return ""
    if len(parcalar) == 1:
        return parcalar[0]
    return ", ".join(parcalar[:-1]) + " ve " + parcalar[-1]


def _katilma_cevap_metni(
    *,
    folded: str,
    giris_gerekli: bool,
    sirala: bool,
    currency: str,
    oran_etiketi: str,
    urun_adi: str,
    vade_siralar: list[tuple[int, list[tuple[KatilimHesabiRow, Decimal]]]],
) -> str:
    """Müşteriye konuşan, kaynaklı katılma yanıtı (şablon; model yok)."""
    bloklar: list[str] = []
    selam = _selamla(folded)
    if selam:
        bloklar.append(selam)
    if giris_gerekli:
        bloklar.append(_KATILMA_GIRIS)

    dolu = [(ay, sira) for ay, sira in vade_siralar if sira]
    if not dolu:
        bloklar.append(
            "Bu süzgeçte Katılım Hesabı verisinde oran bulamadım. "
            "Katılım Hesabı sayfasından vade veya para birimini değiştirmeyi deneyin."
        )
        return "\n\n".join(bloklar)

    if sirala:
        if len(dolu) == 1:
            ay, sira = dolu[0]
            vade_adi = _VADE_ADI.get(ay, "aylık")
            bloklar.append(
                "Bu sitedeki katılım bankalarının TKBB’de yayımlanan oranlarına "
                f"baktım. {vade_adi.capitalize()} standart katılma hesabında "
                f"({currency}) {oran_etiketi} şu an en yüksek üç bankada şöyle: "
                f"{_banka_sira_cumlesi(sira)}."
            )
            bloklar.append(
                "Getiri yüksek olan taraf müşteri için daha avantajlı; kararı "
                "size bırakıyorum. Oranlar değişebilir — güncel tablo Katılım "
                "Hesabı sayfasında."
            )
        else:
            bloklar.append(
                "Bu sitedeki katılım bankalarının TKBB’de yayımlanan dağıtılan "
                f"kâr payı (getiri, {currency}) oranlarına baktım. Kararı size "
                "bırakıyorum; ben yalnızca elimizdeki rakamları vade vade "
                "sıralıyorum. Getiri yüksek olan taraf müşteri için daha avantajlı."
            )
            for ay, sira in dolu:
                vade_adi = _VADE_ADI.get(ay, "aylık")
                bloklar.append(
                    f"{vade_adi.capitalize()} vadede öne çıkan üç banka: "
                    f"{_banka_sira_cumlesi(sira)}."
                )
            bloklar.append(
                "Kartlarda bir vadenin ilk üçü de duruyor. Oranlar değişebilir; "
                "güncel tablo Katılım Hesabı sayfasında."
            )
    else:
        ay, sira = dolu[0]
        vade_adi = _VADE_ADI.get(ay, "aylık")
        bloklar.append(
            f"{vade_adi.capitalize()} {urun_adi} için {oran_etiketi} ({currency}) "
            f"şu an şöyle: {_banka_sira_cumlesi(sira)}. Kaynak Katılım Hesabı "
            "(TKBB öncelikli)."
        )

    return "\n\n".join(bloklar)


def _katilma_yanit(
    session: Session,
    plan: QueryPlan,
    _req: ChatRequest,
    *,
    uyari: str | None,
    elapsed_ms: int,
) -> ChatResponse:
    """Katılma sorularını Katılım Hesabı pivot'undan (TKBB öncelikli) yanıtlar.

    ⚠️ Banka sitesinden kazınmış ham `profit_sharing_ratio` satırları (aynı
    ürünün onlarca kopyası, %40 paylaşım) getiri sanılmaz. Sayfa ile aynı
    `build_katilim_hesabi` kaynağı kullanılır.
    """
    folded = _fold(plan.raw)
    rate_type = _katilma_rate_type(plan)
    variant = parse_katilma_varyant(folded)
    vadeler = _katilma_vade_secimi(folded, plan)
    sirala = _katilma_sirala_mi(plan)
    kart_vade = 3 if 3 in vadeler else vadeler[0]

    currency = "TRY"
    if "usd" in folded or "dolar" in folded:
        currency = "USD"
    elif "eur" in folded or "euro" in folded:
        currency = "EUR"
    elif "altin" in folded or "xau" in folded:
        currency = "XAU"

    pivot = build_katilim_hesabi(
        session,
        rate_type=rate_type,
        variant=variant,
        currency=currency,
        term_months=None if len(vadeler) != 1 else vadeler[0],
    )

    urun_adi = (
        "Ara Ödemeli Katılma Hesabı" if variant == "ara_odemeli" else "Standart Katılma Hesabı"
    )
    oran_etiketi = (
        "kâr paylaşım oranı (müşteri payı)"
        if rate_type == "profit_sharing_ratio"
        else "dağıtılan kâr payı (getiri)"
    )

    vade_siralar: list[tuple[int, list[tuple[KatilimHesabiRow, Decimal]]]] = []
    for ay in vadeler:
        vade_etiketi = KATILIM_HESABI_VADE_ETIKETI.get(ay, "aylik")
        hucre = f"{vade_etiketi}|{currency}"
        vade_siralar.append((ay, sirala_katilma_satirlari(pivot.rows, hucre=hucre, limit=3)))

    kart_sirali = next((sira for ay, sira in vade_siralar if ay == kart_vade), [])
    vade_adi = _VADE_ADI.get(kart_vade, "aylık")

    bank_ids = {
        b.code: b.id
        for b in session.scalars(
            select(Bank).where(Bank.code.in_([s.bank_code for s, _ in kart_sirali] or ["__yok__"]))
        )
    }

    products: list[ChatProductItem] = []
    top_adaylar: list[RankCandidate] = []
    for i, (satir, deger) in enumerate(kart_sirali):
        kaynak = "TKBB Veri Peteği" if "tkbb" in (satir.data_source or "") else "banka sitesi"
        reason = f"{vade_adi.capitalize()} {oran_etiketi}: {_yuzde_yaz(deger)} ({kaynak})"
        products.append(
            ChatProductItem(
                product_id=bank_ids.get(satir.bank_code, i + 1),
                product_name=urun_adi,
                bank_code=satir.bank_code,
                bank_name=satir.bank_name,
                product_type="birikim_katilma_hesabi",
                rate_type=rate_type,
                card_text=reason,
                profit_rate_pct=deger if rate_type == "participation_yield" else None,
                investor_share_pct=deger if rate_type == "profit_sharing_ratio" else None,
                term_months=kart_vade,
                source_url=None,
            )
        )
        top_adaylar.append(
            RankCandidate(
                entity_type="product_rate",
                id=bank_ids.get(satir.bank_code, i + 1),
                title=urun_adi,
                bank_name=satir.bank_name,
                source_url=None,
                detail_path="/katilim-hesabi",
                rank_index=i,
                is_active=True,
                intent_boost=0.2,
                reason=reason,
            )
        )

    giris_gerekli = any(k in folded for k in ("nedir", "ne demek", "ne anlama"))
    metin = _katilma_cevap_metni(
        folded=folded,
        giris_gerekli=giris_gerekli,
        sirala=sirala,
        currency=currency,
        oran_etiketi=oran_etiketi,
        urun_adi=urun_adi,
        vade_siralar=vade_siralar,
    )
    kart_hucre = f"{KATILIM_HESABI_VADE_ETIKETI.get(kart_vade, 'aylik')}|{currency}"

    return _finalize(
        ChatResponse(
            query=plan.raw,
            intent=plan.intent,
            understood=_understood(plan),
            answer=AnswerBlock(text=metin, source="computed", is_grounded=True),
            results=[],
            products=products[:3],
            retrieval=RetrievalReport(
                corpus_size=len(pivot.rows),
                returned=len(products[:3]),
                lexical_used=False,
                semantic_used=False,
                semantic_note=(
                    "Katılma yanıtı build_katilim_hesabi pivot'undan "
                    f"(hücre={kart_hucre}, vadeler={vadeler}, rate_type={rate_type}); "
                    "ham ürün satırı dökülmez."
                ),
                elapsed_ms=elapsed_ms,
            ),
            forbidden_terms_warning=uyari,
            direction_note=None,
        ),
        plan,
        top=score_candidates(top_adaylar),
    )


def _rejection_label(key: str) -> str:
    if key in REJECTION_LABELS:
        return REJECTION_LABELS[key]
    alan, _, sebep = key.partition(":")
    etiket, _birim = aggregate.FIELD_LABELS.get(alan, (alan, ""))
    if sebep == "veri_yok":
        return f"{etiket.capitalize()} — kampanyada bu alan çıkarılamamış"
    return f"{etiket.capitalize()} eşiği"


def _understood(plan: QueryPlan) -> list[UnderstoodFilter]:
    """Sorgu sinyallerini arayüz çiplerine çevirir.

    ⚠️ TAKSONOMİ SLUG'I TÜRKÇEYE BURADA ÇEVRİLMEZ. Okunur adlar
    `frontend/src/lib/taxonomy.ts` içinde yaşıyor; backend'e ikinci bir sözlük
    açmak, iki sözlüğün sessizce ıraksaması demek olurdu (Sprint 2'de
    `PRODUCT_TYPES` bu yüzden tek yerde tutuldu). Eksen sinyallerinde `display`
    slug'ın kendisidir; arayüz `taxonomyLabel()` uygular ve o işlev karşılığı
    olmayan değeri olduğu gibi döndürdüğü için banka adı ve durum metni
    dokunulmadan geçer.
    """
    ciplar: list[UnderstoodFilter] = []

    # ⚠️ TOPLAMA NİYETİ DE BİR ÇİPTİR. "En düşük kâr payı oranı hangi bankada?"
    # sorusunda hiçbir süzgeç sinyali çıkmıyor; çip listesi boş kalırsa
    # kullanıcı sistemin soruyu bir HESAP olarak anladığını hiç göremez ve
    # yanıtın 608 kaydın tamamı üzerinden mi geldiğini bilemez.
    if plan.aggregate is not None:
        if plan.aggregate.kind == "count":
            gosterim = "kayıt sayısı"
        else:
            alan_etiketi, _ = aggregate.FIELD_LABELS.get(
                plan.aggregate.field or "", (plan.aggregate.field or "", "")
            )
            yon_metni = "en yüksek" if plan.aggregate.direction == "max" else "en düşük"
            gosterim = f"{yon_metni} {alan_etiketi}"
        ciplar.append(
            UnderstoodFilter(
                kind="aggregate",
                value=plan.aggregate.kind,
                label="Hesap",
                display=gosterim,
                evidence=plan.raw,
            )
        )

    for sinyal in plan.signals:
        if sinyal.kind == "numeric":
            alan, islec, deger = sinyal.value.split(":", 2)
            _etiket, birim = aggregate.FIELD_LABELS.get(alan, (alan, ""))
            yon = "en çok" if islec == "lte" else "en az"
            gosterim = f"{yon} %{deger}" if birim == "%" else f"{yon} {deger}{birim}"
        elif sinyal.kind == "status":
            gosterim = sinyal.label
        else:
            gosterim = sinyal.value
        ciplar.append(
            UnderstoodFilter(
                kind=sinyal.kind,
                value=sinyal.value,
                label=sinyal.label,
                display=gosterim,
                evidence=sinyal.evidence,
            )
        )
    return ciplar


def _metrics(hit: SearchHit, plan: QueryPlan) -> list[ChatMetric]:
    ilgili = [kisit.field for kisit in plan.numeric]
    if plan.aggregate is not None and plan.aggregate.field:
        ilgili.append(plan.aggregate.field)
    if not ilgili:
        ilgili = ["profit_rate_pct", "reward_amount_try", "min_spend_try"]

    sonuc: list[ChatMetric] = []
    for alan in dict.fromkeys(ilgili):
        deger = hit.doc.metrics.get(alan)
        if deger is None:
            continue
        etiket, birim = aggregate.FIELD_LABELS.get(alan, (alan, ""))
        sonuc.append(ChatMetric(field=alan, label=etiket, value=deger, unit=birim))
    return sonuc


def _results(result: SearchResult, plan: QueryPlan) -> list[ChatResultItem]:
    return [
        ChatResultItem(
            campaign_id=vurus.doc.campaign_id,
            bank_code=vurus.doc.bank_code,
            bank_name=vurus.doc.bank_name,
            title=vurus.doc.title,
            status=vurus.doc.status,
            source_url=vurus.doc.source_url,
            summary=vurus.doc.summary,
            card_text=vurus.doc.card_text,
            metrics=_metrics(vurus, plan),
            channels=list(vurus.channels),
            matched_terms=list(vurus.matched_terms),
        )
        for vurus in result.hits
    ]


def _retrieval(result: SearchResult, elapsed_ms: int) -> RetrievalReport:
    return RetrievalReport(
        corpus_size=result.corpus_size,
        returned=len(result.hits),
        lexical_used=result.lexical_used,
        semantic_used=result.semantic_used,
        semantic_note=result.semantic_note,
        rejected=[
            FilterRejection(filter=anahtar, label=_rejection_label(anahtar), count=adet)
            for anahtar, adet in sorted(
                result.filters.rejected.items(), key=lambda ikili: -ikili[1]
            )
        ],
        total_rejected=result.filters.total_rejected,
        elapsed_ms=elapsed_ms,
    )


def _empty_retrieval(corpus_size: int, elapsed_ms: int, note: str | None = None) -> RetrievalReport:
    return RetrievalReport(
        corpus_size=corpus_size,
        returned=0,
        lexical_used=False,
        semantic_used=False,
        semantic_note=note,
        elapsed_ms=elapsed_ms,
    )


def _answer_block(cevap: GeneratedAnswer) -> AnswerBlock:
    return AnswerBlock(
        text=strip_citation_markers(cevap.text),
        source=cevap.source,
        citations=list(cevap.citations),
        unverified_numbers=[
            UnverifiedNumberOut(value=uydurma.value, cited=list(uydurma.cited))
            for uydurma in cevap.unverified_numbers
        ],
        terminology_warnings=[
            TerminologyWarningOut(term=uyari.term, suggestion=uyari.suggestion)
            for uyari in cevap.terminology_warnings
        ],
        is_grounded=cevap.is_grounded,
        model_name=cevap.model_name,
        model_error=cevap.model_error,
        latency_ms=cevap.latency_ms,
    )


def _sorgu_uyarisi(query: str, forbidden: dict[str, str | None]) -> str | None:
    uyarilar = check_terminology(query, forbidden)
    if not uyarilar:
        return None
    ilk = uyarilar[0]
    karsilik = ilk.suggestion or "katılım bankacılığı karşılığı"
    return (
        f"Katılım bankacılığı ilkeleri gereği “{ilk.term}” yerine “{karsilik}” "
        "terimi kullanılır. Sorgunuz yine de çalıştırıldı."
    )


def _provider_or_none(*, plan: QueryPlan, model_id: str | None = None) -> LLMProvider | None:
    """Yanıt üretimi için sağlayıcı döndürür.

    ⚠️ MODEL SEÇİMİ İSTEK BAŞINADIR. Arayüzden gelen seçim `.env` dosyasına
    YAZILMAZ; bir kullanıcının tercihi tüm kurumun yapılandırmasını
    değiştirmemeli. Tanınmayan seçim sessizce yok sayılır ve
    `answer.model_name` hangi modelin gerçekten kullanıldığını bildirir.

    ⚠️ BU NİYETLERDE MODEL HİÇ İSTENMEZ: `aggregate` (SQL ile hesaplanır),
    `tanim` (sözlükten okunur), `kapsam_disi` ve `sohbet` (şablon). Modele
    sormak yalnızca yanlış aktarma riski ekler.
    """
    if plan.intent in {"aggregate", "tanim", "kapsam_disi", "sohbet"}:
        return None

    ayarlar = get_settings()
    secilen = chat_models.resolve_override(model_id)
    if secilen and secilen != ayarlar.llm_provider.strip().lower():
        ayarlar = ayarlar.model_copy(update={"llm_provider": secilen})
        logger.info("istek_basina_saglayici", saglayici=secilen)

    try:
        return get_provider(ayarlar)
    except ValueError as exc:
        logger.warning("saglayici_kurulamadi", hata=str(exc))
        return None


def _sohbet_yanit(plan: QueryPlan, *, uyari: str | None, elapsed_ms: int) -> ChatResponse:
    """Selam / teşekkür / kimsin — asla refusal dönmez."""
    folded = _fold(plan.raw)
    if any(k in folded for k in ("tesekkur", "sagol", "eyvallah")):
        metin = (
            "Rica ederim. Başka bir kampanya, finansman veya katılma hesabı sorusu sorabilirsiniz."
        )
    elif any(k in folded for k in ("gorusuruz", "hosca kal", "bye")):
        metin = "Görüşmek üzere. İhtiyacınız olursa buradayım."
    else:
        metin = _SOHBET_METIN
    return _finalize(
        ChatResponse(
            query=plan.raw,
            intent="sohbet",
            understood=_understood(plan),
            answer=AnswerBlock(text=metin, source="computed", is_grounded=True),
            results=[],
            retrieval=_empty_retrieval(0, elapsed_ms, "Sohbet niyeti; model çağrılmadı."),
            forbidden_terms_warning=uyari,
        ),
        plan,
    )


def _facts_from_response(resp: ChatResponse, plan: QueryPlan) -> NarrationFacts:
    """Computed yanıttan NarrationFacts üretir."""
    facts: list[FactTriple] = []
    if resp.aggregate and resp.aggregate.value is not None:
        facts.append(
            FactTriple(
                etiket=resp.aggregate.field_label or "değer",
                deger=str(resp.aggregate.value),
                birim=resp.aggregate.unit or "",
            )
        )
        facts.append(
            FactTriple(
                etiket="kayıt",
                deger=str(resp.aggregate.with_value),
                birim="adet",
            )
        )
    for p in resp.products[:5]:
        if p.profit_rate_pct is not None:
            facts.append(
                FactTriple(
                    etiket=f"{p.bank_name} getiri",
                    deger=str(p.profit_rate_pct),
                    birim="%",
                    kaynak_url=p.source_url,
                )
            )
        elif p.investor_share_pct is not None:
            facts.append(
                FactTriple(
                    etiket=f"{p.bank_name} katılımcı payı",
                    deger=str(p.investor_share_pct),
                    birim="%",
                    kaynak_url=p.source_url,
                )
            )
        if p.term_months is not None:
            facts.append(
                FactTriple(
                    etiket=f"{p.bank_name} vade",
                    deger=str(p.term_months),
                    birim="ay",
                )
            )
    for r in resp.results[:5]:
        for m in r.metrics:
            facts.append(
                FactTriple(
                    etiket=f"{r.bank_name} {m.label}",
                    deger=str(m.value),
                    birim=m.unit,
                    kaynak_url=r.source_url,
                )
            )
    return NarrationFacts(
        facts=tuple(facts),
        template_text=resp.answer.text,
        question=plan.raw,
        rate_type=plan.rate_type,
    )


async def _anlat_computed(
    resp: ChatResponse,
    plan: QueryPlan,
    *,
    yasakli: dict[str, str | None],
) -> ChatResponse:
    """computed cevapları anlatıcıdan geçirir; reddedilirse şablon kalır."""
    if resp.answer.source != "computed":
        return resp
    if plan.intent in {"sohbet", "tanim", "kapsam_disi"} or resp.clarification_needed:
        return resp
    if resp.answer.text.startswith("Bu soru") or resp.answer.source == "refusal":
        return resp
    try:
        saglayici = get_provider(get_settings())
    except ValueError:
        saglayici = None
    sonuc = await narrate(
        _facts_from_response(resp, plan),
        provider=saglayici,
        forbidden_terms=yasakli,
    )
    resp.answer = AnswerBlock(
        text=sonuc.text,
        source=sonuc.source if sonuc.source == "model" else "computed",
        is_grounded=True,
        model_name=sonuc.model_name,
        model_error=sonuc.model_error,
        latency_ms=sonuc.latency_ms,
    )
    return resp


async def _bos_sonuc_anlat(
    plan: QueryPlan,
    hints: list[RelaxationHintOut],
    *,
    yasakli: dict[str, str | None],
) -> AnswerBlock:
    """Boş sonuçta relaxation_hints → doğal cümle (+ isteğe bağlı anlatıcı)."""
    sablon = relaxation_to_natural([(h.kind, h.value, h.label, h.hit_count) for h in hints])
    try:
        saglayici = get_provider(get_settings())
    except ValueError:
        saglayici = None
    facts = NarrationFacts(
        facts=tuple(
            FactTriple(etiket=h.label, deger=str(h.hit_count), birim="kayıt") for h in hints[:3]
        ),
        template_text=sablon,
        question=plan.raw,
        rate_type=plan.rate_type,
    )
    sonuc = await narrate(facts, provider=saglayici, forbidden_terms=yasakli)
    return AnswerBlock(
        text=sonuc.text,
        source=sonuc.source if sonuc.source == "model" else "computed",
        is_grounded=True,
        model_name=sonuc.model_name,
        model_error=sonuc.model_error,
        latency_ms=sonuc.latency_ms,
    )


def _embedding_store(session: Session) -> EmbeddingStore:
    return EmbeddingStore.load(
        session,
        entity_type=CAMPAIGN_ENTITY,
        # Yazan taraf ile AYNI kaynak; ikisi ıraksarsa kanal sessizce boşalır.
        model_name=active_embedding_model(get_settings()),
    )


async def _qdrant_ara(
    query_vector: list[float] | None,
) -> tuple[list[SemanticHit] | None, str | None, str | None]:
    """Qdrant'tan anlamsal aday getirir.

    ⚠️ QDRANT BİRİNCİL, YEREL TABLO YEDEK. `VECTOR_BACKEND=qdrant` iken önce
    Qdrant denenir; erişilemezse `None` döner ve çağıran taraf yerel
    `embeddings` tablosuna düşer. Kapalı ağ (airgap) gösterimi bu yol
    sayesinde Qdrant olmadan da çalışır.

    ⚠️ SESSİZCE DÜŞÜLMEZ. Hangi arka ucun kullanıldığı ve neden düşüldüğü
    yanıttaki `semantic_note` alanında bildirilir; "anlamsal arama yapıldı"
    izlenimi vermek, yapılmadığında yanlış bilgi olur.

    Returns:
        `(sonuçlar, kaynak, not)` — `sonuçlar` `None` ise yerele düşülmeli.
    """
    ayarlar = get_settings()
    if ayarlar.vector_backend.strip().lower() != "qdrant":
        return None, None, None
    if not ayarlar.qdrant_url:
        return None, None, "VECTOR_BACKEND=qdrant ama QDRANT_URL tanımlı değil; yerele düşüldü."
    if not query_vector:
        return None, None, None

    depo = QdrantStore(
        base_url=ayarlar.qdrant_url,
        api_key=ayarlar.qdrant_api_key,
        collection=ayarlar.qdrant_collection,
        model_name=active_embedding_model(ayarlar),
    )
    try:
        if not await depo.describe():
            return None, None, "Qdrant koleksiyonu bulunamadı; yerel gömme tablosuna düşüldü."
        if depo.dim and len(query_vector) != depo.dim:
            # Boyut uyuşmazlığı yerelde de olacaktır; ama neden Qdrant'ın
            # atlandığı yazılmalı.
            return (
                None,
                None,
                f"Qdrant koleksiyonu {depo.dim} boyutlu, sorgu vektörü "
                f"{len(query_vector)} boyut; yerele düşüldü.",
            )
        vuruslar = await depo.search(
            query_vector, limit=CHANNEL_CANDIDATES, entity_type=CAMPAIGN_ENTITY
        )
    except QdrantUnavailableError as exc:
        logger.warning("qdrant_erisilemedi", hata=str(exc))
        return None, None, f"Qdrant'a ulaşılamadı ({exc}); yerel gömme tablosuna düşüldü."

    return vuruslar, "qdrant", None


# Sorgu vektörü önbelleği — (model, katlanmış sorgu) → vektör.
# ⚠️ NEDEN VAR: sorgu vektörü, sohbet gecikmesinin en büyük tek kalemi
# (EVREN'e ayrı bir ağ turu; ölçüldü ~1-2 sn). Aynı soru tekrar sorulduğunda
# ya da kullanıcı bir süzgeç çipini kaldırıp sorguyu yeniden çalıştırdığında
# aynı vektör yeniden istenmemeli. EVREN duyurusu da aynı bağlam üzerinden
# tekrarlı isteğin hem bizim hem sistemin performansını artırdığını söylüyor.
#
# ⚠️ SÜREÇ İÇİ VE SINIRLI. Kalıcı bir tablo değil: gömme modeli değişince
# anahtar da değişir, süreç yeniden başlayınca önbellek boşalır. Sınır,
# uzun oturumlarda belleğin sessizce büyümesini engeller.
_SORGU_VEKTOR_ONBELLEGI: OrderedDict[tuple[str, str], list[float]] = OrderedDict()
SORGU_VEKTOR_ONBELLEK_SINIRI: Final[int] = 256


def sorgu_vektor_onbellegini_bosalt() -> None:
    """Önbelleği düşürür (testler ve model değişikliği için)."""
    _SORGU_VEKTOR_ONBELLEGI.clear()


async def _query_vector(provider: LLMProvider | None, plan: QueryPlan) -> list[float] | None:
    if provider is None:
        return None

    anahtar = (active_embedding_model(get_settings()), _fold(plan.raw))
    onbellekten = _SORGU_VEKTOR_ONBELLEGI.get(anahtar)
    if onbellekten is not None:
        _SORGU_VEKTOR_ONBELLEGI.move_to_end(anahtar)
        return onbellekten

    try:
        vektorler = await provider.embed([plan.raw])
    except (LLMProviderError, NotImplementedError, ValueError) as exc:
        logger.info("sorgu_vektoru_uretilemedi", hata=str(exc), tip=type(exc).__name__)
        return None

    vektor = vektorler[0] if vektorler else None
    if vektor:
        _SORGU_VEKTOR_ONBELLEGI[anahtar] = vektor
        _SORGU_VEKTOR_ONBELLEGI.move_to_end(anahtar)
        while len(_SORGU_VEKTOR_ONBELLEGI) > SORGU_VEKTOR_ONBELLEK_SINIRI:
            _SORGU_VEKTOR_ONBELLEGI.popitem(last=False)
    return vektor


def _fold(text: str) -> str:
    return ascii_fold_tr(lower_tr(normalize_text(text or "")))


def _glossary_bul(corpus: Corpus, terim: str | None) -> GlossaryDoc | None:
    if not terim or not corpus.glossary_docs:
        return None
    aranan = _fold(terim)
    for doc in corpus.glossary_docs.values():
        if aranan in _fold(doc.term) or _fold(doc.term) in aranan:
            return doc
        for alias in doc.aliases:
            if aranan in _fold(alias) or _fold(alias) in aranan:
                return doc
    return None


def _rate_docs_filtrele(corpus: Corpus, plan: QueryPlan) -> list[ProductRateDoc]:
    if not corpus.rate_docs:
        return []
    sonuc: list[ProductRateDoc] = []
    urun_tipleri = set(plan.axis_filters.get("product_type", ()))
    for doc in corpus.rate_docs.values():
        if plan.bank_codes and doc.bank_code not in plan.bank_codes:
            continue
        if plan.rate_type and doc.rate_type != plan.rate_type:
            continue
        if urun_tipleri and doc.product_type not in urun_tipleri:
            # Taksonomi slug ↔ ürün tipi eşleşmesi gevşek: konut_finansmani ⊂ finansman.
            if not any(
                tip in (doc.product_type or "") or (doc.product_type or "") in tip
                for tip in urun_tipleri
            ):
                continue
        sonuc.append(doc)
    return sonuc


def _product_item(doc: ProductRateDoc) -> ChatProductItem:
    return ChatProductItem(
        product_id=doc.product_id,
        product_name=doc.product_name,
        bank_code=doc.bank_code,
        bank_name=doc.bank_name,
        product_type=doc.product_type,
        rate_type=doc.rate_type,
        rate_id=doc.rate_id,
        card_text=doc.card_text,
        profit_rate_pct=doc.profit_rate_pct,
        investor_share_pct=doc.investor_share_pct,
        term_months=doc.term_months,
        source_url=doc.source_url,
    )


def _product_bm25(
    corpus: Corpus, plan: QueryPlan, *, limit: int = 8
) -> list[tuple[int, ProductDoc]]:
    """Finansman / katılma için kullanılmayan product_index'i devreye alır."""
    if not corpus.product_index or not corpus.product_docs:
        return []
    terimler = tokenize(plan.raw)
    if not terimler and plan.free_terms:
        terimler = list(plan.free_terms)
    if not terimler:
        return []
    vuruslar = corpus.product_index.search(terimler, limit=limit * 3)
    sonuc: list[tuple[int, ProductDoc]] = []
    for sira, vurus in enumerate(vuruslar):
        doc = corpus.product_docs.get(vurus.doc_id)
        if doc is None:
            continue
        if plan.bank_codes and doc.bank_code not in plan.bank_codes:
            continue
        urun_tipleri = set(plan.axis_filters.get("product_type", ()))
        if urun_tipleri and doc.product_type:
            if not any(tip in doc.product_type or doc.product_type in tip for tip in urun_tipleri):
                continue
        # Katılma alanı: birikim / katılma ürünleri.
        if plan.source_domain == "katilma":
            tip = (doc.product_type or "").lower()
            ad = _fold(doc.name)
            if not any(k in tip or k in ad for k in ("katilma", "birikim", "ara_donem", "katilim")):
                continue
        if plan.source_domain == "finansman":
            tip = (doc.product_type or "").lower()
            if "birikim" in tip or "katilma" in tip:
                continue
        sonuc.append((sira, doc))
        if len(sonuc) >= limit:
            break
    return sonuc


def _top_from_campaigns(
    hits: list[SearchHit] | tuple[SearchHit, ...], domain: str
) -> list[ChatTopMatch]:
    adaylar = [
        RankCandidate(
            entity_type="campaign",
            id=v.doc.campaign_id,
            title=v.doc.title,
            bank_name=v.doc.bank_name,
            source_url=v.doc.source_url,
            detail_path=f"/campaigns/{v.doc.campaign_id}",
            rank_index=i,
            is_active=v.doc.status == "active",
            intent_boost=0.1 if domain == "kampanya" else 0.0,
            reason=v.doc.summary,
        )
        for i, v in enumerate(hits)
    ]
    return score_candidates(adaylar)


def _top_from_products(
    products: list[ChatProductItem],
    *,
    domain: str,
) -> list[ChatTopMatch]:
    adaylar: list[RankCandidate] = []
    for i, p in enumerate(products):
        path = (
            "/katilim-hesabi"
            if p.rate_type in {"participation_yield", "profit_sharing_ratio"} or domain == "katilma"
            else f"/products/{p.product_id}"
        )
        reason = None
        if p.profit_rate_pct is not None:
            reason = f"Getiri {_yuzde_yaz(p.profit_rate_pct)}"
        elif p.investor_share_pct is not None and domain != "katilma":
            reason = f"Katılımcı payı {_yuzde_yaz(p.investor_share_pct)}"
        adaylar.append(
            RankCandidate(
                entity_type="product_rate" if p.rate_id else "product",
                id=p.product_id,
                title=p.product_name,
                bank_name=p.bank_name,
                source_url=p.source_url,
                detail_path=path,
                rank_index=i,
                is_active=True,
                intent_boost=0.1 if domain in {"finansman", "katilma"} else 0.0,
                reason=reason,
            )
        )
    # Aynı banka/ürün tekrarını ele.
    gorulen: set[tuple[str, int]] = set()
    tekil: list[RankCandidate] = []
    for aday in adaylar:
        anahtar = (aday.bank_name or "", aday.id)
        if anahtar in gorulen:
            continue
        gorulen.add(anahtar)
        tekil.append(aday)
    return score_candidates(tekil)


def _top_from_glossary(items: list[ChatGlossaryItem]) -> list[ChatTopMatch]:
    adaylar = [
        RankCandidate(
            entity_type="glossary",
            id=g.term_id,
            title=g.term,
            bank_name=None,
            source_url=None,
            detail_path="/chat",
            rank_index=i,
            intent_boost=0.2,
            reason=g.definition[:120] if g.definition else None,
        )
        for i, g in enumerate(items)
    ]
    return score_candidates(adaylar)


def _finalize(
    resp: ChatResponse,
    plan: QueryPlan,
    *,
    top: list[ChatTopMatch] | None = None,
) -> ChatResponse:
    """source_domain + top_matches ekler (sözleşme: yalnızca ekleme)."""
    resp.source_domain = plan.source_domain
    if top is not None:
        resp.top_matches = top
    elif not resp.top_matches:
        if resp.results:
            adaylar = [
                RankCandidate(
                    entity_type="campaign",
                    id=r.campaign_id,
                    title=r.title,
                    bank_name=r.bank_name,
                    source_url=r.source_url,
                    detail_path=f"/campaigns/{r.campaign_id}",
                    rank_index=i,
                    is_active=r.status == "active",
                    reason=r.summary,
                )
                for i, r in enumerate(resp.results)
            ]
            resp.top_matches = score_candidates(adaylar)
        elif resp.products:
            resp.top_matches = _top_from_products(resp.products, domain=plan.source_domain)
        elif resp.glossary:
            resp.top_matches = _top_from_glossary(resp.glossary)
    return resp


def _compare_criterion(plan: QueryPlan) -> str:
    """Karşılaştırma ölçütünü rate_type / sorgu yönünden seçer."""
    if plan.rate_type == "participation_yield":
        return "en_yuksek_getiri"
    if plan.rate_type == "profit_sharing_ratio":
        return "en_yuksek_paylasim_orani"
    if plan.rate_type == "financing_rate":
        return "en_dusuk_kar_payi"
    folded = _fold(plan.raw)
    if "getiri" in folded or "katilma" in folded:
        return "en_yuksek_getiri"
    if "paylasim" in folded:
        return "en_yuksek_paylasim_orani"
    return "en_dusuk_kar_payi"


def _netlestirme_gerekli(plan: QueryPlan) -> bool:
    """compare / tekil_sorgu'da rate_type belirsiz ve birden fazla aday."""
    if plan.intent not in {"compare", "tekil_sorgu"}:
        return False
    if plan.rate_type:
        return False
    return len(plan.rate_type_candidates) > 1 or (
        plan.intent == "compare" and not plan.rate_type and not plan.rate_type_candidates
    )


async def _aggregate_response(
    plan: QueryPlan,
    spec: AggregateSpec,
    corpus: Corpus,
    req: ChatRequest,
    uyari: str | None,
    baslangic: float,
) -> ChatResponse:
    docs, rapor = filter_all(corpus, plan)
    hesap = aggregate.compute(docs, spec)
    metin = aggregate.describe(hesap)

    etiket = birim = None
    if hesap.field:
        etiket, birim = aggregate.FIELD_LABELS.get(hesap.field, (hesap.field, ""))

    gosterilecek = [hesap.winner, *hesap.ties] if hesap.winner else []
    kanitlar = [
        ChatResultItem(
            campaign_id=doc.campaign_id,
            bank_code=doc.bank_code,
            bank_name=doc.bank_name,
            title=doc.title,
            status=doc.status,
            source_url=doc.source_url,
            summary=doc.summary,
            card_text=doc.card_text,
            metrics=[
                ChatMetric(
                    field=hesap.field,
                    label=etiket or hesap.field,
                    value=doc.metrics[hesap.field],
                    unit=birim or "",
                )
            ]
            if hesap.field and hesap.field in doc.metrics
            else [],
            channels=[],
            matched_terms=[],
        )
        for doc in gosterilecek[: req.limit]
        if doc is not None
    ]

    gecen = int((time.perf_counter() - baslangic) * 1000)
    return ChatResponse(
        query=plan.raw,
        intent=plan.intent,
        understood=_understood(plan),
        answer=AnswerBlock(
            text=metin,
            source="computed",
            citations=[doc.campaign_id for doc in gosterilecek[: req.limit] if doc],
            is_grounded=True,
        ),
        aggregate=AggregateBlock(
            kind=hesap.kind,
            field=hesap.field,
            field_label=etiket,
            value=hesap.value,
            unit=birim,
            winner_campaign_id=hesap.winner.campaign_id if hesap.winner else None,
            with_value=hesap.with_value,
            without_value=hesap.without_value,
            total=hesap.total,
            tie_count=len(hesap.ties),
            by_bank=hesap.by_bank,
        ),
        results=kanitlar,
        retrieval=RetrievalReport(
            corpus_size=corpus.size,
            returned=len(kanitlar),
            lexical_used=False,
            semantic_used=False,
            semantic_note="Toplama sorusu erişime girmez; hesap tüm kayıtlar üzerinde yapıldı.",
            rejected=[
                FilterRejection(filter=anahtar, label=_rejection_label(anahtar), count=adet)
                for anahtar, adet in sorted(rapor.rejected.items(), key=lambda ikili: -ikili[1])
            ],
            total_rejected=rapor.total_rejected,
            elapsed_ms=gecen,
        ),
        forbidden_terms_warning=uyari,
    )


async def process_chat_query(session: Session, req: ChatRequest) -> ChatResponse:
    """Doğal dil sorusunu uçtan uca işler (oturum + çok tur + anlatıcı)."""
    baslangic = time.perf_counter()
    oturum = chat_sessions.resolve_or_create(session, req.session_id, title_hint=req.query)
    turn = chat_sessions.next_turn_index(oturum)
    onceki_plan = chat_sessions.previous_plan(oturum)

    plan = parse_query(req.query)
    plan = merge_with_previous(plan, onceki_plan)

    if req.bank_code:
        plan = replace(plan, bank_codes=(req.bank_code,))

    yasakli = load_forbidden_terms(session)
    uyari = _sorgu_uyarisi(req.query, yasakli)
    corpus = build_corpus(session)
    gecen = lambda: int((time.perf_counter() - baslangic) * 1000)  # noqa: E731

    resp = await _process_chat_core(
        session,
        req,
        plan=plan,
        corpus=corpus,
        uyari=uyari,
        yasakli=yasakli,
        baslangic=baslangic,
        gecen=gecen,
        previous_query=onceki_plan.raw if onceki_plan else None,
    )
    resp = await _anlat_computed(resp, plan, yasakli=yasakli)
    resp.session_id = oturum.session_key
    resp.turn_index = turn
    chat_sessions.record_turn(
        session,
        oturum,
        turn_index=turn,
        user_text=req.query,
        plan=plan,
        response=resp,
    )
    session.commit()
    return resp


async def _process_chat_core(
    session: Session,
    req: ChatRequest,
    *,
    plan: QueryPlan,
    corpus: Corpus,
    uyari: str | None,
    yasakli: dict[str, str | None],
    baslangic: float,
    gecen: Callable[[], int],
    previous_query: str | None = None,
) -> ChatResponse:
    """Niyet dalları — oturum kaydı dış katmanda."""
    # ── sohbet — asla refusal ─────────────────────────────
    if plan.intent == "sohbet":
        return _sohbet_yanit(plan, uyari=uyari, elapsed_ms=gecen())

    # ── kapsam_disi — modele HİÇ gitme ────────────────────
    if plan.intent == "kapsam_disi":
        return _finalize(
            ChatResponse(
                query=plan.raw,
                intent=plan.intent,
                understood=_understood(plan),
                answer=AnswerBlock(text=_KAPSAM_DISI_METIN, source="refusal", is_grounded=True),
                results=[],
                retrieval=_empty_retrieval(corpus.size, gecen(), "Kapsam dışı; model çağrılmadı."),
                forbidden_terms_warning=uyari,
            ),
            plan,
        )

    # ── tanim — glossary, modele gitmez ───────────────────
    if plan.intent == "tanim":
        doc = _glossary_bul(corpus, plan.glossary_term)
        if doc is None:
            return _finalize(
                ChatResponse(
                    query=plan.raw,
                    intent=plan.intent,
                    understood=_understood(plan),
                    answer=AnswerBlock(
                        text=(
                            f"“{plan.glossary_term or plan.raw}” için sözlükte tanım bulunamadı."
                        ),
                        source="refusal",
                        is_grounded=True,
                    ),
                    results=[],
                    retrieval=_empty_retrieval(corpus.size, gecen()),
                    forbidden_terms_warning=uyari,
                ),
                plan,
            )
        glossary = [
            ChatGlossaryItem(
                term_id=doc.term_id,
                term=doc.term,
                definition=doc.definition,
                conventional_equivalent=doc.conventional_equivalent,
            )
        ]
        return _finalize(
            ChatResponse(
                query=plan.raw,
                intent=plan.intent,
                understood=_understood(plan),
                answer=AnswerBlock(
                    text=f"{doc.term}: {doc.definition}",
                    source="computed",
                    is_grounded=True,
                ),
                results=[],
                glossary=glossary,
                retrieval=RetrievalReport(
                    corpus_size=len(corpus.glossary_docs or {}),
                    returned=1,
                    lexical_used=False,
                    semantic_used=False,
                    semantic_note="Tanım sorusu glossary tablosundan yanıtlandı; model çağrılmadı.",
                    elapsed_ms=gecen(),
                ),
                forbidden_terms_warning=uyari,
            ),
            plan,
            top=_top_from_glossary(glossary),
        )

    # ── katılma → Katılım Hesabı pivot (TKBB öncelikli) ───
    if plan.source_domain == "katilma":
        return _katilma_yanit(session, plan, req, uyari=uyari, elapsed_ms=gecen())

    # ── netleştirme ───────────────────────────────────────
    if _netlestirme_gerekli(plan):
        return _finalize(
            ChatResponse(
                query=plan.raw,
                intent=plan.intent,
                understood=_understood(plan),
                answer=AnswerBlock(
                    text=_NETLESTIRME_SORU,
                    source="computed",
                    is_grounded=True,
                ),
                results=[],
                retrieval=_empty_retrieval(corpus.size, gecen(), "rate_type belirsiz; tahmin yok."),
                forbidden_terms_warning=uyari,
                clarification_needed=True,
                clarification_question=_NETLESTIRME_SORU,
            ),
            plan,
        )

    # ── aggregate ─────────────────────────────────────────
    if plan.intent == "aggregate" and plan.aggregate is not None:
        return _finalize(
            await _aggregate_response(plan, plan.aggregate, corpus, req, uyari, baslangic),
            plan,
        )

    # ── compare → ürün ise rank_products ──────────────────
    if plan.intent == "compare":
        urun_mu = (
            bool(plan.axis_filters.get("product_type"))
            or bool(plan.rate_type)
            or any(
                k in _fold(plan.raw)
                for k in ("finansman", "katilma", "konut", "tasit", "ihtiyac", "getiri", "oran")
            )
        )
        if urun_mu:
            rate_type = plan.rate_type or "financing_rate"
            criterion = _compare_criterion(plan)
            if criterion not in CRITERIA:
                criterion = "en_dusuk_kar_payi"
            product_type = None
            if plan.axis_filters.get("product_type"):
                product_type = plan.axis_filters["product_type"][0]
            try:
                ranking = rank_products(
                    session,
                    rate_type=rate_type,
                    criterion=criterion,
                    product_type=product_type,
                    bank_codes=list(plan.bank_codes) or None,
                    limit=req.limit,
                )
            except RankingError as exc:
                return _finalize(
                    ChatResponse(
                        query=plan.raw,
                        intent=plan.intent,
                        understood=_understood(plan),
                        answer=AnswerBlock(text=str(exc), source="refusal", is_grounded=True),
                        results=[],
                        retrieval=_empty_retrieval(corpus.size, gecen()),
                        forbidden_terms_warning=uyari,
                        direction_note=yon_notu(rate_type),
                    ),
                    plan,
                )

            products = [
                ChatProductItem(
                    product_id=s.product_id,
                    product_name=s.product_name,
                    bank_code=s.bank_code,
                    bank_name=s.bank_name,
                    product_type=s.product_type,
                    rate_type=s.rate_type,
                    card_text=s.evidence_text or s.product_name,
                    profit_rate_pct=s.profit_rate_pct,
                    investor_share_pct=s.investor_share_pct,
                    term_months=s.term_months,
                    source_url=s.source_url,
                )
                for s in ranking.ranked
            ]
            without = [
                ChatProductItem(
                    product_id=s.product_id,
                    product_name=s.product_name,
                    bank_code=s.bank_code,
                    bank_name=s.bank_name,
                    product_type=s.product_type,
                    rate_type=s.rate_type,
                    card_text=s.missing_reason or "veri yok",
                    source_url=s.source_url,
                )
                for s in ranking.without_data
            ]
            metin = ranking.winner_reason or ranking.note
            if ranking.winner is None and without:
                metin = (
                    "Karşılaştırma için yeterli oran verisi yok. "
                    f"Veri olmayan bankalar: {', '.join(s.bank_name for s in without[:5])}."
                )
            return _finalize(
                ChatResponse(
                    query=plan.raw,
                    intent=plan.intent,
                    understood=_understood(plan),
                    answer=AnswerBlock(text=metin, source="computed", is_grounded=True),
                    results=[],
                    products=products,
                    comparison=ChatComparisonBlock(
                        rate_type=ranking.rate_type,
                        criterion=ranking.criterion,
                        winner_product_id=ranking.winner.product_id if ranking.winner else None,
                        winner_bank_code=ranking.winner.bank_code if ranking.winner else None,
                        winner_reason=ranking.winner_reason,
                        ranked=products,
                        without_data=without,
                        note=ranking.note,
                    ),
                    retrieval=RetrievalReport(
                        corpus_size=len(ranking.ranked) + len(ranking.without_data),
                        returned=len(products),
                        lexical_used=False,
                        semantic_used=False,
                        semantic_note="Ürün karşılaştırması rank_products ile yapısal hesaplandı.",
                        elapsed_ms=gecen(),
                    ),
                    forbidden_terms_warning=uyari,
                    direction_note=yon_notu(rate_type),
                ),
                plan,
                top=_top_from_products(products, domain=plan.source_domain),
            )

    # ── tekil_sorgu → ürün/oran kartları ──────────────────
    if plan.intent == "tekil_sorgu":
        oranlar = _rate_docs_filtrele(corpus, plan)[: req.limit]
        if not oranlar and corpus.product_docs:
            # Oran yoksa ürün BM25 / kartlarına düş.
            bm25 = _product_bm25(corpus, plan, limit=req.limit)
            if bm25:
                products = [
                    ChatProductItem(
                        product_id=d.product_id,
                        product_name=d.name,
                        bank_code=d.bank_code,
                        bank_name=d.bank_name,
                        product_type=d.product_type,
                        card_text=d.card_text,
                        source_url=d.source_url,
                    )
                    for _sira, d in bm25
                ]
            else:
                urunler = [
                    d
                    for d in corpus.product_docs.values()
                    if (not plan.bank_codes or d.bank_code in plan.bank_codes)
                ][: req.limit]
                products = [
                    ChatProductItem(
                        product_id=d.product_id,
                        product_name=d.name,
                        bank_code=d.bank_code,
                        bank_name=d.bank_name,
                        product_type=d.product_type,
                        card_text=d.card_text,
                        source_url=d.source_url,
                    )
                    for d in urunler
                ]
        else:
            products = [_product_item(d) for d in oranlar]

        if not products:
            return _finalize(
                ChatResponse(
                    query=plan.raw,
                    intent=plan.intent,
                    understood=_understood(plan),
                    answer=AnswerBlock(
                        text=(
                            "Bu banka/ürün için elimizdeki veriyle oran bulunamadı "
                            "(veri yok ≠ kötü değer)."
                        ),
                        source="refusal",
                        is_grounded=True,
                    ),
                    results=[],
                    retrieval=_empty_retrieval(corpus.size, gecen()),
                    forbidden_terms_warning=uyari,
                    direction_note=yon_notu(plan.rate_type) if plan.rate_type else None,
                ),
                plan,
            )

        # Aynı ürünün birden çok rate_type'ı ayrı ayrı listelenir.
        satirlar = []
        for p in products:
            parca = f"{p.bank_name} — {p.product_name}"
            if p.rate_type:
                parca += f" ({p.rate_type})"
            if p.profit_rate_pct is not None:
                parca += f": %{p.profit_rate_pct}"
            elif p.investor_share_pct is not None:
                parca += f": katılımcı payı %{p.investor_share_pct}"
            satirlar.append(parca)
        metin = " | ".join(satirlar[:5])

        return _finalize(
            ChatResponse(
                query=plan.raw,
                intent=plan.intent,
                understood=_understood(plan),
                answer=AnswerBlock(text=metin, source="computed", is_grounded=True),
                results=[],
                products=products,
                retrieval=RetrievalReport(
                    corpus_size=len(corpus.rate_docs or {}) + len(corpus.product_docs or {}),
                    returned=len(products),
                    lexical_used=bool(corpus.product_index),
                    semantic_used=False,
                    semantic_note="Tekil sorgu ürün/oran tablosundan yapısal yanıtlandı.",
                    elapsed_ms=gecen(),
                ),
                forbidden_terms_warning=uyari,
                direction_note=yon_notu(plan.rate_type) if plan.rate_type else None,
            ),
            plan,
            top=_top_from_products(products, domain=plan.source_domain),
        )

    # ── kaynak alanına göre yönlendirme (finansman / katılma önce) ──
    if plan.source_domain in {"finansman", "katilma"} and plan.intent == "search":
        bm25 = _product_bm25(corpus, plan, limit=req.limit)
        oranlar = _rate_docs_filtrele(corpus, plan)
        # Katılma: participation_yield / profit_sharing_ratio öncelikli.
        if plan.source_domain == "katilma":
            oranlar = [
                d for d in oranlar if d.rate_type in {"participation_yield", "profit_sharing_ratio"}
            ] or oranlar
        elif plan.source_domain == "finansman":
            oranlar = [d for d in oranlar if d.rate_type == "financing_rate"] or oranlar

        products = []
        if oranlar:
            products = [_product_item(d) for d in oranlar[: req.limit]]
        elif bm25:
            products = [
                ChatProductItem(
                    product_id=d.product_id,
                    product_name=d.name,
                    bank_code=d.bank_code,
                    bank_name=d.bank_name,
                    product_type=d.product_type,
                    card_text=d.card_text,
                    source_url=d.source_url,
                )
                for _sira, d in bm25
            ]

        if products:
            satirlar = []
            for p in products[:5]:
                parca = f"{p.bank_name} — {p.product_name}"
                if p.profit_rate_pct is not None:
                    parca += f": %{p.profit_rate_pct}"
                elif p.investor_share_pct is not None:
                    parca += f": katılımcı payı %{p.investor_share_pct}"
                satirlar.append(parca)
            # Kaynak URL cevap altına.
            url_satir = ""
            ilk_url = next((p.source_url for p in products if p.source_url), None)
            if ilk_url:
                url_satir = f"\nKaynak: {ilk_url}"
            return _finalize(
                ChatResponse(
                    query=plan.raw,
                    intent=plan.intent,
                    understood=_understood(plan),
                    answer=AnswerBlock(
                        text=" | ".join(satirlar) + url_satir,
                        source="computed",
                        is_grounded=True,
                    ),
                    results=[],
                    products=products,
                    retrieval=RetrievalReport(
                        corpus_size=len(corpus.rate_docs or {}) + len(corpus.product_docs or {}),
                        returned=len(products),
                        lexical_used=bool(bm25),
                        semantic_used=False,
                        semantic_note=(
                            f"Birincil kaynak: {plan.source_domain}; ürün/oran araması."
                        ),
                        elapsed_ms=gecen(),
                    ),
                    forbidden_terms_warning=uyari,
                    direction_note=yon_notu(plan.rate_type) if plan.rate_type else None,
                ),
                plan,
                top=_top_from_products(products, domain=plan.source_domain),
            )
        # Boşsa sessizce kampanya RAG'a düş (uydurma yok).

    # ── search / kampanya compare — hibrit RAG ────────────
    saglayici = _provider_or_none(plan=plan, model_id=req.model_id)
    depo = _embedding_store(session)
    ayarlar = get_settings()
    # ⚠️ Sorgu vektörü Qdrant için de gerekli; yerel depo boş olsa bile
    # üretilmeli. Eski koşul (`if not depo.is_empty`) Qdrant kullanılırken
    # vektörü hiç üretmiyordu ve anlamsal kanal sessizce kapanıyordu.
    qdrant_secili = ayarlar.vector_backend.strip().lower() == "qdrant"
    vektor = await _query_vector(saglayici, plan) if (qdrant_secili or not depo.is_empty) else None
    uzak_vuruslar, uzak_kaynak, uzak_not = await _qdrant_ara(vektor)

    # Geniş havuzdan çek, sonra alaka süzgeciyle kırp (dolgu kampanya yok).
    ham = search(
        plan,
        corpus,
        query_vector=vektor,
        store=depo,
        semantic_hits=uzak_vuruslar,
        semantic_source=uzak_kaynak,
        limit=max(req.limit, 12),
    )
    if uzak_not:
        ham = replace(ham, semantic_note=uzak_not)
    alakali = filter_relevant_hits(ham.hits, plan, max_n=min(req.limit, 3))
    sonuc = SearchResult(
        hits=alakali,
        filters=ham.filters,
        lexical_used=ham.lexical_used,
        semantic_used=ham.semantic_used,
        corpus_size=ham.corpus_size,
        semantic_note=ham.semantic_note,
        relaxation_hints=ham.relaxation_hints if not alakali else (),
    )
    results = _results(sonuc, plan)
    top = _top_from_campaigns(sonuc.hits, plan.source_domain)
    hints = [
        RelaxationHintOut(
            kind=oneri.kind,
            value=oneri.value,
            label=oneri.label,
            hit_count=oneri.hit_count,
        )
        for oneri in sonuc.relaxation_hints
    ]

    # Kampanya birincil boşsa ve finansman/katılma henüz denenmediyse ürün yedek.
    if not results and plan.source_domain == "kampanya":
        bm25 = _product_bm25(corpus, replace(plan, source_domain="finansman"), limit=req.limit)
        if bm25:
            products = [
                ChatProductItem(
                    product_id=d.product_id,
                    product_name=d.name,
                    bank_code=d.bank_code,
                    bank_name=d.bank_name,
                    product_type=d.product_type,
                    card_text=d.card_text,
                    source_url=d.source_url,
                )
                for _sira, d in bm25
            ]
            return _finalize(
                ChatResponse(
                    query=plan.raw,
                    intent=plan.intent,
                    understood=_understood(plan),
                    answer=AnswerBlock(
                        text=" | ".join(f"{p.bank_name} — {p.product_name}" for p in products[:5]),
                        source="computed",
                        is_grounded=True,
                    ),
                    results=[],
                    products=products,
                    retrieval=_retrieval(sonuc, gecen()),
                    forbidden_terms_warning=uyari,
                ),
                plan,
                top=_top_from_products(products, domain="finansman"),
            )

    if not sonuc.hits:
        bos = await _bos_sonuc_anlat(plan, hints, yasakli=yasakli)
        return _finalize(
            ChatResponse(
                query=plan.raw,
                intent=plan.intent,
                understood=_understood(plan),
                answer=bos,
                results=[],
                retrieval=_retrieval(sonuc, gecen()),
                relaxation_hints=hints,
                forbidden_terms_warning=uyari,
            ),
            plan,
            top=top,
        )

    cevap = await generate_answer(
        plan,
        sonuc.hits,
        provider=saglayici,
        forbidden_terms=yasakli,
        previous_query=previous_query,
    )

    return _finalize(
        ChatResponse(
            query=plan.raw,
            intent=plan.intent,
            understood=_understood(plan),
            answer=_answer_block(cevap),
            results=results,
            retrieval=_retrieval(sonuc, gecen()),
            relaxation_hints=hints,
            forbidden_terms_warning=uyari,
            direction_note=cevap.direction_note,
        ),
        plan,
        top=top,
    )
