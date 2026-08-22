"""Kanıtlı arama — sorgu anlama, hibrit erişim, toplama ve yanıt üretimi.

Katmanların tamamı `app/retrieval/` altındadır; bu modül yalnızca onları
sıraya dizer ve API şemasına çevirir.

⚠️ SORGUDAKİ YASAKLI TERİM SORGUYU REDDETMEZ. Kullanıcı "faiz oranı en düşük
kredi hangisi?" diye sorabilir; bu bir hata değil, alışkanlıktır. Uyarı
gösterilir ve sorgu **çalıştırılır** — reddetmek, aracı kullanılamaz kılar.

⚠️ MODEL ÇAĞRISI YALNIZCA CÜMLE İÇİN. Sıralama, süzgeç ve toplama modele hiç
sorulmaz; model erişilemezse bu üçü çalışmaya devam eder ve yanıt şablona
düşer (`answer.source`).
"""

from __future__ import annotations

import time
from dataclasses import replace

from sqlalchemy.orm import Session

from app.ai.providers import get_provider
from app.ai.providers.base import LLMProvider, LLMProviderError
from app.ai.validation.terminology import check_terminology, load_forbidden_terms
from app.config import get_settings
from app.logging_config import get_logger
from app.retrieval import aggregate
from app.retrieval.answer import GeneratedAnswer, generate_answer
from app.retrieval.corpus import CAMPAIGN_ENTITY, Corpus, build_corpus
from app.retrieval.query import AggregateSpec, QueryPlan, parse_query
from app.retrieval.search import SearchHit, SearchResult, filter_all, search
from app.retrieval.semantic import EmbeddingStore
from app.schemas.chat import (
    AggregateBlock,
    AnswerBlock,
    ChatMetric,
    ChatRequest,
    ChatResponse,
    ChatResultItem,
    FilterRejection,
    RelaxationHintOut,
    RetrievalReport,
    TerminologyWarningOut,
    UnderstoodFilter,
    UnverifiedNumberOut,
)

logger = get_logger(__name__)

# Süzgeç anahtarı → arayüzde gösterilecek Türkçe açıklama.
REJECTION_LABELS: dict[str, str] = {
    "banka": "Banka süzgeci",
    "durum": "Durum süzgeci",
    "eksen:product_type": "Ürün türü süzgeci",
    "eksen:sector": "Sektör süzgeci",
    "eksen:audience": "Hedef kitle süzgeci",
    "eksen:benefit": "Fayda süzgeci",
}


def _rejection_label(key: str) -> str:
    """Eleme anahtarını okunur açıklamaya çevirir."""
    if key in REJECTION_LABELS:
        return REJECTION_LABELS[key]
    alan, _, sebep = key.partition(":")
    etiket, _birim = aggregate.FIELD_LABELS.get(alan, (alan, ""))
    if sebep == "veri_yok":
        # ⚠️ "Eşiği geçmedi" ile "veri yok" AYRI gösterilir; ikisini
        # birleştirmek, çıkarılamamış alanı "koşulu sağlamıyor" gibi okutur.
        return f"{etiket.capitalize()} — kampanyada bu alan çıkarılamamış"
    return f"{etiket.capitalize()} eşiği"


def _understood(plan: QueryPlan) -> list[UnderstoodFilter]:
    """Sorgu sinyallerini arayüz çiplerine çevirir.

    ⚠️ TAKSONOMİ SLUG'I TÜRKÇEYE BURADA ÇEVRİLMEZ. Okunur adlar
    `frontend/src/lib/taxonomy.ts` içinde yaşıyor; backend'e ikinci bir
    sözlük açmak, iki sözlüğün sessizce ıraksaması demek olurdu (Sprint 2'de
    `PRODUCT_TYPES` bu yüzden tek yerde tutuldu). Eksen sinyallerinde `display`
    slug'ın kendisidir; arayüz `taxonomyLabel()` uygular ve o işlev karşılığı
    olmayan değeri olduğu gibi döndürdüğü için banka adı ve durum metni
    dokunulmadan geçer.
    """
    ciplar: list[UnderstoodFilter] = []
    for sinyal in plan.signals:
        if sinyal.kind == "numeric":
            alan, islec, deger = sinyal.value.split(":", 2)
            _etiket, birim = aggregate.FIELD_LABELS.get(alan, (alan, ""))
            yon = "en çok" if islec == "lte" else "en az"
            gosterim = f"{yon} %{deger}" if birim == "%" else f"{yon} {deger}{birim}"
        elif sinyal.kind == "status":
            gosterim = sinyal.label
        else:
            # Banka kodu ve taksonomi slug'ı: arayüz çevirir.
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
    """Kampanyanın sorguyla ilgili sayısal alanlarını seçer.

    ⚠️ TÜM METRİKLER GÖSTERİLMEZ. Kullanıcı kâr payı sorduysa 14 alanın
    tamamını göstermek asıl bilgiyi gürültüde boğar. Sorguda geçen alanlar
    öne alınır; hiçbiri yoksa en sık kullanılan üç alan gösterilir.
    """
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
    """Erişim sonuçlarını API öğelerine çevirir."""
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
    """Erişim şeffaflık şeridini üretir."""
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


def _answer_block(cevap: GeneratedAnswer) -> AnswerBlock:
    """Üretilen yanıtı API bloğuna çevirir."""
    return AnswerBlock(
        text=cevap.text,
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
    """Kullanıcının sorusunda konvansiyonel terim var mı?

    ⚠️ Bu uyarı SORGUYU DURDURMAZ. "Faiz oranı en düşük kredi hangisi?" geçerli
    bir sorudur; kullanıcıya doğru terimi göstermek yeterlidir.
    """
    uyarilar = check_terminology(query, forbidden)
    if not uyarilar:
        return None
    ilk = uyarilar[0]
    karsilik = ilk.suggestion or "katılım bankacılığı karşılığı"
    return (
        f"Katılım bankacılığı ilkeleri gereği “{ilk.term}” yerine “{karsilik}” "
        "terimi kullanılır. Sorgunuz yine de çalıştırıldı."
    )


def _provider_or_none(*, plan: QueryPlan) -> LLMProvider | None:
    """Yanıt üretimi için sağlayıcı döndürür.

    ⚠️ Toplama sorularında sağlayıcı HİÇ istenmez: yanıt zaten hesaplanmış
    durumda ve modele yazdırmak yalnızca yanlış aktarma riski ekler.
    """
    if plan.intent == "aggregate":
        return None
    try:
        return get_provider(get_settings())
    except ValueError as exc:
        # Tanımsız sağlayıcı adı yapılandırma hatasıdır; arama yine çalışsın.
        logger.warning("saglayici_kurulamadi", hata=str(exc))
        return None


def _embedding_store(session: Session) -> EmbeddingStore:
    """Gömme deposunu yükler.

    Boşsa arama sözcüksel kanala düşer ve bu durum yanıtta bildirilir.
    """
    return EmbeddingStore.load(
        session,
        entity_type=CAMPAIGN_ENTITY,
        model_name=get_settings().embedding_model,
    )


async def _query_vector(provider: LLMProvider | None, plan: QueryPlan) -> list[float] | None:
    """Sorgunun gömme vektörünü üretir.

    ⚠️ GÖMME BAŞARISIZ OLURSA ARAMA DURMAZ. Anlamsal kanal atlanır, sözcüksel
    kanal çalışmaya devam eder ve durum `semantic_note` ile bildirilir.
    """
    if provider is None:
        return None
    try:
        vektorler = await provider.embed([plan.raw])
    except (LLMProviderError, NotImplementedError, ValueError) as exc:
        logger.info("sorgu_vektoru_uretilemedi", hata=str(exc), tip=type(exc).__name__)
        return None
    return vektorler[0] if vektorler else None


async def _aggregate_response(
    plan: QueryPlan,
    spec: AggregateSpec,
    corpus: Corpus,
    req: ChatRequest,
    uyari: str | None,
    baslangic: float,
) -> ChatResponse:
    """Toplama sorusunu yanıtlar — model çağrılmaz."""
    docs, rapor = filter_all(corpus, plan)
    hesap = aggregate.compute(docs, spec)
    metin = aggregate.describe(hesap)

    etiket = birim = None
    if hesap.field:
        etiket, birim = aggregate.FIELD_LABELS.get(hesap.field, (hesap.field, ""))

    # Kazanan ve beraberler kanıt listesine konur; kullanıcı hesabın hangi
    # kayda dayandığını görmeden sayıya güvenemez.
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
    """Doğal dil sorusunu uçtan uca işler.

    Args:
        session: Veritabanı oturumu.
        req: Kullanıcı isteği.

    Returns:
        Yanıt, kanıtlar, süzgeç dökümü ve denetim sonuçları.
    """
    baslangic = time.perf_counter()
    plan = parse_query(req.query)

    # ⚠️ Arayüzden gelen banka süzgeci sorgu metnini EZER. İkisini birleştirmek
    # ("Kuveyt Türk" yazıp açılır listeden Albaraka seçmek) daima boş sonuç
    # verirdi; kullanıcının son eylemi açılır listedir.
    if req.bank_code:
        plan = replace(plan, bank_codes=(req.bank_code,))

    yasakli = load_forbidden_terms(session)
    uyari = _sorgu_uyarisi(req.query, yasakli)
    corpus = build_corpus(session)

    if plan.intent == "aggregate" and plan.aggregate is not None:
        return await _aggregate_response(plan, plan.aggregate, corpus, req, uyari, baslangic)

    saglayici = _provider_or_none(plan=plan)
    depo = _embedding_store(session)
    vektor = await _query_vector(saglayici, plan) if not depo.is_empty else None

    sonuc = search(plan, corpus, query_vector=vektor, store=depo, limit=req.limit)
    cevap = await generate_answer(plan, sonuc.hits, provider=saglayici, forbidden_terms=yasakli)

    gecen = int((time.perf_counter() - baslangic) * 1000)
    return ChatResponse(
        query=plan.raw,
        intent=plan.intent,
        understood=_understood(plan),
        answer=_answer_block(cevap),
        results=_results(sonuc, plan),
        retrieval=_retrieval(sonuc, gecen),
        relaxation_hints=[
            RelaxationHintOut(
                kind=oneri.kind,
                value=oneri.value,
                label=oneri.label,
                hit_count=oneri.hit_count,
            )
            for oneri in sonuc.relaxation_hints
        ],
        forbidden_terms_warning=uyari,
    )
