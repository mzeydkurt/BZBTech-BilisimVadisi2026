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
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.providers import active_embedding_model, get_provider
from app.ai.providers.base import LLMProvider, LLMProviderError
from app.ai.router import route_with_llm
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
    STOPWORDS,
    AggregateSpec,
    QueryPlan,
    QuerySignal,
    has_definition_marker,
    merge_with_previous,
    parse_katilma_vadeler,
    parse_katilma_varyant,
    parse_query,
)
from app.retrieval.rank import RankCandidate, score_candidates
from app.retrieval.relevance import (
    filter_relevant_hits,
    is_anaphoric_query,
    opens_scope,
    refers_to_focus_entity,
    strip_citation_markers,
)
from app.retrieval.routing import LOW_CONFIDENCE, DomainDecision
from app.retrieval.search import (
    CHANNEL_CANDIDATES,
    FilterReport,
    SearchHit,
    SearchResult,
    filter_all,
    search,
)
from app.retrieval.semantic import EmbeddingStore, SemanticHit
from app.retrieval.slots import extract_slots
from app.schemas.chat import (
    AggregateBlock,
    AnswerBlock,
    ChatAction,
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
    RoutingReport,
    TerminologyWarningOut,
    UnderstoodFilter,
    UnverifiedNumberOut,
)
from app.schemas.compare import CRITERIA
from app.schemas.katilim_hesabi import KatilimHesabiRow
from app.services import chat_model_service as chat_models
from app.services import chat_session_service as chat_sessions
from app.services.chat_tools import detect_tool, run_tool
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

_BANKA_KARSILASTIRMA_SORU = (
    "Hangi konuda karşılaştırayım? Kampanya, finansman kâr payı oranı veya "
    "katılma hesabı getirisi için ayrı ayrı bakabilirim — konu belirtilmeden "
    "tek bir «daha avantajlı» yanıtı veremem.\n\n"
    "Örnek: «{ornek} konut finansmanında hangisi daha avantajlı?» veya "
    "«{ornek} katılma hesabı getirisinde hangisi daha iyi?»"
)

_KATILMA_GIRIS = (
    "Katılma hesabı, katılım bankasında kâr-zarar ortaklığına dayanan vadeli "
    "birikim ürünüdür. Dağıtılan kâr payı (getiri) ile kâr paylaşım oranı "
    "(müşteri/banka payı, örn. 90/10) ayrı sayılardır."
)

_KAR_PAYI_PAYLASIM_ACIKLAMA = (
    "Dağıtılan kâr payı (getiri) ile kâr paylaşım oranı aynı şey değildir:\n\n"
    "• Dağıtılan kâr payı (getiri): Katılma hesabında dönem sonunda yatırımcıya "
    "aktarılan yıllık getiri oranıdır (ör. %28,65). Katılım Hesabı tablosunda "
    "vade vade yayımlanır; getiri hesabında bu oran kullanılır.\n"
    "• Kâr paylaşım oranı: Bankanın dağıttığı kârdan müşteriye düşen pay "
    "(ör. %90 müşteri / %10 banka). Bu bir getiri yüzdesi değildir; tabloda "
    "ayrı bir sütundur.\n\n"
    "Finansman kâr payı oranı da bunlardan farklıdır — konut/taşıt/ihtiyaç "
    "finansmanında maliyet oranıdır, katılma getirisi değildir.\n"
    "Geçmiş getiri gelecek getiriyi taahhüt etmez."
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
    oncelik_bankalar: tuple[str, ...] = (),
) -> list[tuple[KatilimHesabiRow, Decimal]]:
    """Pivot satırlarını tek hücreye göre (banka başına bir kez) sıralar.

      `oncelik_bankalar` verilirse önce bu bankalar (sorguda adı geçen),
      kalan slotlar diğer bankalardan doldurulur. Böylece global top-3 içinde
    olmayan banka (ör. Ziraat) boş dönmez.
    """
    adaylar: list[tuple[KatilimHesabiRow, Decimal]] = []
    for satir in satirlar:
        deger = satir.values.get(hucre)
        if deger is None:
            continue
        adaylar.append((satir, deger))
    adaylar.sort(key=lambda ikili: (-ikili[1], ikili[0].bank_name))

    if not oncelik_bankalar:
        return adaylar[:limit]

    oncelik = set(oncelik_bankalar)
    birincil = [ikili for ikili in adaylar if ikili[0].bank_code in oncelik]
    diger = [ikili for ikili in adaylar if ikili[0].bank_code not in oncelik]
    return (birincil + diger)[:limit]


def _katilma_rate_type(plan: QueryPlan) -> str:
    folded = _fold(plan.raw)
    if plan.rate_type in {"profit_sharing_ratio", "participation_yield"}:
        return plan.rate_type
    if any(
        k in folded
        for k in (
            "paylasim orani",
            "paylasim oran",
            "musteri payi",
            "katilimci payi",
            "90/10",
            "98/2",
        )
    ):
        return "profit_sharing_ratio"
    if "paylasim" in folded and "kar payi" not in folded:
        return "profit_sharing_ratio"
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
    oncelik_bankalar: tuple[str, ...] = (),
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

    # Tek banka + çoklu vade: tüm vadeleri o banka için listele.
    tek_banka = len(oncelik_bankalar) == 1 and len(dolu) > 1
    if tek_banka:
        banka_adi = dolu[0][1][0][0].bank_name
        satirlar = []
        for ay, sira in dolu:
            vade_adi = _VADE_ADI.get(ay, "aylık")
            satirlar.append(f"• {vade_adi.capitalize()}: {_yuzde_yaz(sira[0][1])}")
        bloklar.append(
            f"{banka_adi} {urun_adi} için {oran_etiketi} ({currency}):\n"
            + "\n".join(satirlar)
            + "\nKaynak: Katılım Hesabı (TKBB öncelikli). Geçmiş getiri gelecek "
            "getiriyi taahhüt etmez."
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
    oncelik = tuple(plan.bank_codes)
    for ay in vadeler:
        vade_etiketi = KATILIM_HESABI_VADE_ETIKETI.get(ay, "aylik")
        hucre = f"{vade_etiketi}|{currency}"
        sira = sirala_katilma_satirlari(pivot.rows, hucre=hucre, limit=3, oncelik_bankalar=oncelik)
        vade_siralar.append((ay, sira))

    tek_banka_cok_vade = len(oncelik) == 1 and len(vadeler) > 1
    kart_vade = 3 if 3 in vadeler else vadeler[0]
    kart_sirali = next((sira for ay, sira in vade_siralar if ay == kart_vade), [])

    bank_ids = {
        b.code: b.id
        for b in session.scalars(
            select(Bank).where(
                Bank.code.in_(
                    [s.bank_code for s, _ in kart_sirali]
                    + (list(oncelik) if tek_banka_cok_vade else [])
                    or ["__yok__"]
                )
            )
        )
    }

    products: list[ChatProductItem] = []
    top_adaylar: list[RankCandidate] = []
    if tek_banka_cok_vade:
        # Tüm vadeler için tek bankanın kartları.
        for ay, sira in vade_siralar:
            if not sira:
                continue
            satir, deger = sira[0]
            vade_adi = _VADE_ADI.get(ay, "aylık")
            kaynak = "TKBB Veri Peteği" if "tkbb" in (satir.data_source or "") else "banka sitesi"
            reason = f"{vade_adi.capitalize()} {oran_etiketi}: {_yuzde_yaz(deger)} ({kaynak})"
            products.append(
                ChatProductItem(
                    product_id=bank_ids.get(satir.bank_code, ay),
                    product_name=urun_adi,
                    bank_code=satir.bank_code,
                    bank_name=satir.bank_name,
                    product_type="birikim_katilma_hesabi",
                    rate_type=rate_type,
                    card_text=reason,
                    profit_rate_pct=deger if rate_type == "participation_yield" else None,
                    investor_share_pct=deger if rate_type == "profit_sharing_ratio" else None,
                    term_months=ay,
                    source_url=None,
                )
            )
            top_adaylar.append(
                RankCandidate(
                    entity_type="product_rate",
                    id=bank_ids.get(satir.bank_code, ay),
                    title=urun_adi,
                    bank_name=satir.bank_name,
                    source_url=None,
                    detail_path="/katilim-hesabi",
                    rank_index=len(top_adaylar),
                    is_active=True,
                    intent_boost=0.2,
                    reason=reason,
                )
            )
    else:
        vade_adi = _VADE_ADI.get(kart_vade, "aylık")
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
        oncelik_bankalar=oncelik,
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


def _katilma_kavram_yanit(
    session: Session,
    plan: QueryPlan,
    *,
    uyari: str | None,
    elapsed_ms: int,
) -> ChatResponse:
    """Kâr payı vs paylaşım oranı gibi kavram soruları — pivot yerine net açıklama."""
    folded = _fold(plan.raw)
    metin = _KAR_PAYI_PAYLASIM_ACIKLAMA
    oncelik = tuple(plan.bank_codes)
    ornek_satirlar: list[str] = []

    if oncelik:
        variant = parse_katilma_varyant(folded)
        vadeler = _katilma_vade_secimi(folded, plan)
        ay = 3 if 3 in vadeler else vadeler[0]
        for rate_type, etiket in (
            ("participation_yield", "dağıtılan kâr payı (getiri)"),
            ("profit_sharing_ratio", "kâr paylaşım oranı (müşteri payı)"),
        ):
            pivot = build_katilim_hesabi(
                session,
                rate_type=rate_type,
                variant=variant,
                currency="TRY",
                term_months=ay,
            )
            hucre = f"{KATILIM_HESABI_VADE_ETIKETI.get(ay, 'aylik')}|TRY"
            sira = sirala_katilma_satirlari(
                pivot.rows, hucre=hucre, limit=1, oncelik_bankalar=oncelik
            )
            if sira:
                satir, deger = sira[0]
                ornek_satirlar.append(
                    f"• {satir.bank_name} — {_VADE_ADI.get(ay, 'aylık').capitalize()} "
                    f"{etiket}: {_yuzde_yaz(deger)}"
                )

    if ornek_satirlar:
        metin += "\n\nSorduğunuz banka için örnek (TKBB öncelikli):\n" + "\n".join(ornek_satirlar)

    glossary = []
    for terim in ("Dağıtılan Kâr Payı (Getiri)", "Kâr Paylaşım Oranı"):
        doc = _glossary_bul_from_db(session, terim)
        if doc:
            glossary.append(doc)

    return _finalize(
        ChatResponse(
            query=plan.raw,
            intent=plan.intent,
            understood=_understood(plan),
            answer=AnswerBlock(text=metin, source="computed", is_grounded=True),
            results=[],
            glossary=glossary,
            retrieval=RetrievalReport(
                corpus_size=0,
                returned=len(ornek_satirlar),
                lexical_used=False,
                semantic_used=False,
                semantic_note=(
                    "Katılma kavram açıklaması; getiri ile paylaşım oranı karıştırılmadı."
                ),
                elapsed_ms=elapsed_ms,
            ),
            forbidden_terms_warning=uyari,
        ),
        plan,
        top=[],
    )


def _glossary_bul_from_db(session: Session, terim: str) -> ChatGlossaryItem | None:
    """Oturumdan tek glossary kartı (kavram yanıtları için)."""
    from app.db.models import GlossaryTerm

    aranan = _fold(terim)
    sorgu = select(GlossaryTerm).where(GlossaryTerm.is_forbidden_conventional.is_(False))
    for kayit in session.scalars(sorgu):
        # ⚠️ Tanımı boş terim tanım olarak DÖNDÜRÜLMEZ: kullanıcı "bulundu" sanır
        # ama ekranda boş bir kutu görür. Sözlük ıskası aramaya düşsün.
        if not kayit.definition:
            continue
        if aranan in _fold(kayit.term) or _fold(kayit.term) in aranan:
            return ChatGlossaryItem(
                term_id=kayit.id,
                term=kayit.term,
                definition=kayit.definition,
                conventional_equivalent=kayit.conventional_equivalent,
            )
        for alias in kayit.aliases or []:
            if aranan in _fold(alias) or _fold(alias) in aranan:
                return ChatGlossaryItem(
                    term_id=kayit.id,
                    term=kayit.term,
                    definition=kayit.definition,
                    conventional_equivalent=kayit.conventional_equivalent,
                )
    return None


def _banka_karsilastirma_netlestirme(
    plan: QueryPlan,
    corpus: Corpus,
    *,
    uyari: str | None,
    elapsed_ms: int,
) -> ChatResponse:
    """İki banka karşılaştırması — konu belirtilmemişse yönlendirici netleştirme."""
    kod_ad = dict(corpus.banks)
    isimler = [kod_ad.get(k, k) for k in plan.bank_codes[:2]]
    if len(isimler) == 2:
        ornek = f"{isimler[0]} ile {isimler[1]}"
    elif isimler:
        ornek = isimler[0]
    else:
        ornek = "Kuveyt Türk ile Albaraka"

    soru = _BANKA_KARSILASTIRMA_SORU.format(ornek=ornek)

    aksiyonlar = [
        ChatAction(
            kind="refine",
            label="Kampanyalar",
            params={"append": "kampanyalarında hangisi daha avantajlı"},
            reason="Aktif kampanya ve fayda karşılaştırması",
        ),
        ChatAction(
            kind="refine",
            label="Konut finansmanı",
            params={"product_type": "konut_finansmani"},
            reason="Konut finansman kâr payı oranı",
        ),
        ChatAction(
            kind="refine",
            label="Katılma getirisi",
            params={"append": "katılma hesabı getirisinde hangisi daha avantajlı"},
            reason="Dağıtılan kâr payı (getiri) karşılaştırması",
        ),
    ]

    return ChatResponse(
        query=plan.raw,
        intent=plan.intent if plan.intent == "compare" else "compare",
        understood=_understood(plan),
        answer=AnswerBlock(text=soru, source="computed", is_grounded=True),
        results=[],
        retrieval=RetrievalReport(
            corpus_size=corpus.size,
            returned=0,
            lexical_used=False,
            semantic_used=False,
            semantic_note="İki banka karşılaştırması; konu belirtilmedi — netleştirme.",
            elapsed_ms=elapsed_ms,
        ),
        forbidden_terms_warning=uyari,
        clarification_needed=True,
        clarification_question=soru,
        actions=aksiyonlar,
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
        elif plan.aggregate.kind == "count_banks":
            gosterim = "banka sayısı"
        elif plan.aggregate.kind == "absence":
            gosterim = "kaydı olmayan bankalar"
        elif plan.aggregate.kind == "bank_roster":
            gosterim = "kapsanan bankalar"
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
        elif sinyal.kind == "campaign":
            # ⚠️ Çipte veritabanı kimliği GÖSTERİLMEZ. Kullanıcı "Kampanya: 585"
            # ifadesinden ne süzüldüğünü anlamaz; teknik kimlikler yanıt
            # metninden de temizleniyor (`strip_citation_markers`).
            gosterim = "önceki yanıttaki kampanya"
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
    #  Sağlayıcı VE model birlikte değişir; yalnızca sağlayıcıyı geçirmek
    # `evren:llm-large` seçimini sessizce `llm-fast`'e düşürüyordu.
    guncelleme = chat_models.resolve_override(model_id)
    if guncelleme:
        ayarlar = ayarlar.model_copy(update=guncelleme)
        logger.info("istek_basina_model", **guncelleme)

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
    # Araç çıktısı (BDDK / simülasyon / teklif) zaten kanonik; model yeniden yazmasın.
    if resp.tool_runs or resp.bddk or resp.offers:
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
    """Sözlükte en özgül (uzun) eşleşen terimi döndürür."""
    eslesmeler = _glossary_eslesmeler(corpus, terim)
    return eslesmeler[0] if eslesmeler else None


def _glossary_eslesmeler(corpus: Corpus, terim: str | None) -> list[GlossaryDoc]:
    """Sorguya uyan glossary kayıtlarını özgüllük sırasıyla döndürür."""
    if not terim or not corpus.glossary_docs:
        return []
    aranan = _fold(terim)
    bulunan: list[tuple[int, GlossaryDoc]] = []
    for doc in corpus.glossary_docs.values():
        en_uzun = 0
        for aday in (_fold(doc.term), *(_fold(a) for a in doc.aliases)):
            if not aday:
                continue
            if aranan == aday or aday in aranan or aranan in aday:
                en_uzun = max(en_uzun, len(aday))
        if en_uzun:
            bulunan.append((en_uzun, doc))
    bulunan.sort(key=lambda ikili: (-ikili[0], ikili[1].term))
    gorulen: set[int] = set()
    sonuc: list[GlossaryDoc] = []
    for _, doc in bulunan:
        if doc.term_id in gorulen:
            continue
        gorulen.add(doc.term_id)
        sonuc.append(doc)
    return sonuc


def _tanim_glossary_kayitlari(corpus: Corpus, plan: QueryPlan) -> list[GlossaryDoc]:
    """Tanım sorusu için bir veya birden fazla sözlük kaydı."""
    birincil = _glossary_eslesmeler(corpus, plan.glossary_term)
    if not birincil:
        return []
    k = _fold(plan.raw)
    if "fark" not in k and "ayni" not in k and "farkli" not in k:
        return birincil[:1]
    kayitlar = list(birincil[:1])
    ek_terimler: list[str] = []
    if any(x in k for x in ("ara odeme", "ara odemeli", "ara donem")):
        ek_terimler.append("standart katilma hesabi")
    if any(x in k for x in ("standart katilma", "normal katilma")):
        ek_terimler.append("ara odemeli katilma hesabi")
    for ek in ek_terimler:
        doc = _glossary_bul(corpus, ek)
        if doc and all(d.term_id != doc.term_id for d in kayitlar):
            kayitlar.append(doc)
    if len(kayitlar) == 1 and len(birincil) > 1:
        ikinci = birincil[1]
        if ikinci.term_id != kayitlar[0].term_id:
            kayitlar.append(ikinci)
    return kayitlar[:2]


# Sektör ekseni → ürün tipi. Ölçüldü: "en uygun kredi hangisinde konut için"
# sorgusundan çıkan tek süzgeç `sector=konut_gayrimenkul` oluyor; ürün/oran
# süzgeci yalnızca `product_type`a baktığı için ihtiyaç ve araç finansmanı
# ürünleri kanıt olarak gösteriliyordu. Kullanıcı konut sordu, ekranda
# "Enerya İhtiyaç Finansmanı" ve "Araç Finansmanı" görüyordu.
#
# ⚠️ Yalnızca ürün tipiyle KESİN karşılığı olan sektörler eşlenir. "genel",
# "giyim_aksesuar" gibi sektörlerin finansman ürünü karşılığı yoktur ve
# uydurulmaz.
SEKTOR_URUN_TIPI: Final[dict[str, tuple[str, ...]]] = {
    "konut_gayrimenkul": ("konut_finansmani", "arsa_finansmani"),
    "otomotiv": ("tasit_finansmani", "digital_arac_finansmani"),
    "ulasim_arac_kiralama": ("tasit_finansmani", "digital_arac_finansmani"),
    "egitim_kitap": ("egitim_finansmani",),
    "yatirim_birikim": ("yatirim_urunu", "birikim_katilma_hesabi"),
}


def _hedef_urun_tipleri(plan: QueryPlan) -> set[str]:
    """Plandaki ürün tipi süzgeci; yoksa sektörden türetilir."""
    tipler = set(plan.axis_filters.get("product_type", ()))
    if tipler:
        return tipler
    for sektor in plan.axis_filters.get("sector", ()):
        tipler.update(SEKTOR_URUN_TIPI.get(sektor, ()))
    return tipler


# Toplama alanı -> `ProductRateDoc` alanı. "En uzun vade" sorusu oran alanı
# üzerinden sıralanamaz; sorulan ölçüt hangi alansa o okunur.
_RATE_DOC_ALANI: Final[dict[str, str]] = {
    "profit_rate_pct": "profit_rate_pct",
    "profit_share_rate_pct": "investor_share_pct",
    "term_months_min": "term_months",
    "term_months_max": "term_months",
}


def _rate_docs_filtrele(corpus: Corpus, plan: QueryPlan) -> list[ProductRateDoc]:
    """Plandaki süzgeçleri oran kartlarına uygular.

    ⚠️ İKİ SESSİZ HATA DÜZELTİLDİ:

    1. `"" in "konut_finansmani"` → `True`. Boş `product_type` taşıyan her ürün
       (ölçüldü: 10 ürün) her süzgeçten geçiyordu.
    2. `"finansman" in "konut_finansmani"` → `True`. Genel `finansman` ürünü
       konut sorgusuna sızıyordu; bir ücret tablosu satırı kâr payı sanılıp
       uç değeri kazanıyordu.

    Gevşek eşleşme YEDEKTİR: tipi tam tutan kayıt varsa gevşek olanlar hiç
    kullanılmaz.
    """
    if not corpus.rate_docs:
        return []
    urun_tipleri = _hedef_urun_tipleri(plan)
    tam: list[ProductRateDoc] = []
    gevsek: list[ProductRateDoc] = []
    for doc in corpus.rate_docs.values():
        if plan.bank_codes and doc.bank_code not in plan.bank_codes:
            continue
        if plan.rate_type and doc.rate_type != plan.rate_type:
            continue
        if not urun_tipleri:
            tam.append(doc)
            continue
        tip = doc.product_type or ""
        if tip in urun_tipleri:
            tam.append(doc)
        elif tip and any(hedef in tip or tip in hedef for hedef in urun_tipleri):
            gevsek.append(doc)
    return tam or gevsek


def _oran_ucdegeri(
    corpus: Corpus, plan: QueryPlan, spec: AggregateSpec
) -> tuple[ProductRateDoc | None, list[ProductRateDoc], int]:
    """Ürün oranları üzerinde uç değer arar (kampanya metrikleri değil).

    ⚠️ `aggregate.compute` yalnızca KAMPANYA metriklerine bakar. Ölçüldü
    (100 soruluk gerçek havuz): "En düşük konut finansmanı kâr payı oranı hangi
    katılım bankasında?" — rekabet analizinin en klasik sorusu — "uygun teklif
    bulunmamaktadır" yanıtı dönüyordu. Oran verisi `product_rates` tablosunda,
    kampanya metriklerinde değil.

    Returns:
        (kazanan, berabere_kalanlar, degeri_olmayan_sayisi).
    """
    # Sorulan ölçüt oran değilse (ör. "en uzun vade") o alan üzerinden sıralanır.
    alan = _RATE_DOC_ALANI.get(spec.field or "", "profit_rate_pct")

    tumu = _rate_docs_filtrele(corpus, plan)
    degerli = [d for d in tumu if getattr(d, alan) is not None]
    degersiz = len(tumu) - len(degerli)

    # ⚠️ BAĞLAYICI OLMAYAN SATIR KAZANAN OLAMAZ. Ölçüldü: "en düşük konut
    # finansmanı kâr payı" sorusu, kaynakta oranı yayımlanmamış bir `text`
    # satırını %0 ile kazanan ilan ediyordu; doğru yanıt Ziraat Katılım %2,89.
    adaylar = [d for d in degerli if d.is_binding]
    if not adaylar:
        return None, [], degersiz + len(degerli)

    # Aynı ürünün aynı değeri birden çok tutar bandında tekrar edebilir;
    # beraberlik sayımı bunları ayrı kayıt sanmamalı.
    benzersiz: dict[tuple[int, str, int | None], ProductRateDoc] = {}
    for d in adaylar:
        benzersiz.setdefault((d.product_id, str(getattr(d, alan)), d.term_months), d)

    ters = spec.direction == "max"
    sirali = sorted(
        benzersiz.values(),
        key=lambda d: (Decimal(str(getattr(d, alan))), -d.rate_id),
        reverse=ters,
    )
    kazanan = sirali[0]
    # ⚠️ BERABERLİK GİZLENMEZ (aggregate.compute ile aynı kural).
    berabere = [d for d in sirali[1:] if getattr(d, alan) == getattr(kazanan, alan)]
    return kazanan, berabere, degersiz


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
    # Sorgunun ANLAMLI simgeleri: tek bir rastlantısal eşleşme alaka kanıtı
    # değildir. Ölçüldü: "bana bir şiir yaz" sorgusu yalnızca "bana" simgesiyle
    # 6.98 puan alıp Hayat Finans "Bana Bunu Al" ürününü döndürüyor, sohbet de
    # ilgisiz bir tanıtım metni üretiyordu. Puan eşiği ayırt etmiyor (çöp 6.98 >
    # gerçek 7.73); KAPSAMA oranı ayırt ediyor.
    anlamli = {k for k in terimler if len(k) >= 3 and k not in STOPWORDS and not k.isdigit()}
    gereken = max(1, (len(anlamli) + 1) // 2) if anlamli else 0

    sonuc: list[tuple[int, ProductDoc]] = []
    for sira, vurus in enumerate(vuruslar):
        doc = corpus.product_docs.get(vurus.doc_id)
        if doc is None:
            continue
        if gereken and len(anlamli & set(vurus.matched_terms)) < gereken:
            continue
        if plan.bank_codes and doc.bank_code not in plan.bank_codes:
            continue
        urun_tipleri = _hedef_urun_tipleri(plan)
        if (
            urun_tipleri
            and doc.product_type
            and not any(tip in doc.product_type or doc.product_type in tip for tip in urun_tipleri)
        ):
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
            if domain == "finansman" or (p.rate_type or "") == "financing_rate":
                reason = f"Kâr payı {_yuzde_yaz(p.profit_rate_pct)}"
            else:
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
    """Sözlük eşleşmeleri — tanım metni reason'a YAZILMAZ (çift cevap önlemi)."""
    adaylar = [
        RankCandidate(
            entity_type="glossary",
            id=g.term_id,
            title=g.term,
            bank_name=None,
            source_url=None,
            detail_path=None,
            rank_index=i,
            intent_boost=0.2,
            reason=None,
        )
        for i, g in enumerate(items)
    ]
    return score_candidates(adaylar)


def _decision_from_plan(plan: QueryPlan) -> DomainDecision:
    """QueryPlan üzerindeki yönlendirme alanlarından DomainDecision üretir."""
    if plan.domain_scores:
        skorlar = dict(plan.domain_scores)
    else:
        skorlar = {plan.source_domain: plan.domain_confidence}
    return DomainDecision(
        domain=plan.source_domain,
        confidence=plan.domain_confidence,
        scores=skorlar,
        evidence=(),
        is_ambiguous=plan.domain_ambiguous,
        runner_up=plan.domain_runner_up,
    )


def _routing_report(
    plan: QueryPlan,
    *,
    llm_used: bool = False,
    rejected_slots: tuple[str, ...] | list[str] = (),
    evidence: tuple[str, ...] | list[str] = (),
) -> RoutingReport:
    return RoutingReport(
        domain=plan.source_domain,
        confidence=plan.domain_confidence,
        scores=dict(plan.domain_scores) if plan.domain_scores else {},
        is_ambiguous=plan.domain_ambiguous,
        runner_up=plan.domain_runner_up,
        llm_used=llm_used,
        rejected_slots=list(rejected_slots),
        evidence=list(evidence),
    )


def _alan_cipi(plan: QueryPlan) -> UnderstoodFilter | None:
    """Alan yönlendirmesini 'Anladığım' çipi olarak gösterir."""
    if plan.source_domain in {"sohbet", "kapsam_disi", "tanim"}:
        return None
    etiket = {
        "kampanya": "Kampanya",
        "finansman": "Finansman",
        "katilma": "Katılma hesabı",
    }.get(plan.source_domain, plan.source_domain)
    if plan.domain_ambiguous and plan.domain_runner_up:
        ikinci = {
            "kampanya": "kampanyalar",
            "finansman": "finansman",
            "katilma": "katılma hesabı",
        }.get(plan.domain_runner_up, plan.domain_runner_up)
        display = f"{etiket} — belirsiz, {ikinci} de tarandı"
        evidence = f"güven={plan.domain_confidence:.2f}; belirsiz"
    else:
        display = etiket
        evidence = f"güven={plan.domain_confidence:.2f}"
    return UnderstoodFilter(
        kind="source_domain",
        value=plan.source_domain,
        label="Alan",
        display=display,
        evidence=evidence,
    )


def _with_routing(
    resp: ChatResponse,
    plan: QueryPlan,
    *,
    llm_used: bool = False,
    rejected_slots: tuple[str, ...] | list[str] = (),
) -> ChatResponse:
    """Yanıta routing raporu ve alan çipi ekler."""
    if resp.routing is None:
        resp.routing = _routing_report(plan, llm_used=llm_used, rejected_slots=rejected_slots)
    cip = _alan_cipi(plan)
    if cip is not None and not any(u.kind == "source_domain" for u in resp.understood):
        resp.understood = [cip, *resp.understood]
    return resp


def _yanitlanamadi_mi(answer: AnswerBlock) -> bool:
    """Yanıt "veriyle yanıtlanamıyor" mu diyor?

    Metin eşleşmesi kullanılır çünkü bu şablon üç ayrı katmanda üretiliyor
    (`retrieval/answer.py`, `retrieval/narrate.py`, model istemi) ve hepsi
    aynı cümleyle başlıyor.
    """
    if answer.source == "refusal":
        return True
    metin = (answer.text or "").strip().lower()
    return metin.startswith("bu soruya elimizdeki veriyle yanıt verilemiyor")


def _finalize(
    resp: ChatResponse,
    plan: QueryPlan,
    *,
    top: list[ChatTopMatch] | None = None,
    llm_used: bool = False,
    rejected_slots: tuple[str, ...] | list[str] = (),
) -> ChatResponse:
    """source_domain + top_matches + routing ekler (sözleşme: yalnızca ekleme)."""
    resp.source_domain = plan.source_domain
    resp = _with_routing(resp, plan, llm_used=llm_used, rejected_slots=rejected_slots)

    # ── "Yanıtlanamıyor" diyen yanıt KANIT TAŞIMAZ ─────────
    # Arayüzdeki başlık "Yanıtın dayandığı kanıt" der. Yanıt "elimizdeki
    # veriyle yanıt verilemiyor" ise hiçbir kayıt o yanıtın dayanağı DEĞİLDİR;
    # kart göstermek yanlış bir iddiadır.
    #
    # Ölçüldü: "ben kimim" sorusuna reddetme yanıtı dönerken kanıt olarak
    # süresi dolmuş bir "Hac ve Umre Finansmanı" kampanyası gösteriliyordu.
    # Erişim şeffaflığı şeridi (kaç karttan kaçı getirildi) KORUNUR — gizleme
    # değil, yanlış etiketlemeyi düzeltme.
    if _yanitlanamadi_mi(resp.answer):
        resp.results = []
        resp.products = []
        resp.top_matches = []
        return resp
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
        elif resp.glossary and plan.intent != "tanim":
            # Saf tanım turunda top_matches boş kalır — tanım yalnızca glossary[].
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
    # ⚠️ Banka EVRENİ geçilir: yokluk ve banka sayımı soruları yalnızca
    # süzgeçten geçen kayıtlara bakarak yanıtlanamaz — kaydı olmayan banka
    # `docs` içinde hiç görünmez.
    #
    # ⚠️ AMA sorgu belirli bir bankayı süzdüyse evren O bankadır. "Albaraka'da
    # kaç kampanya var?" sorusunda dökümde "Hayat Finans: 0" göstermek "Hayat
    # Finans'ta kampanya yok" demek olur; gerçek neden onun süzgeçle
    # DIŞLANMASIDIR. İki durum karıştırılamaz.
    evren = tuple(ad for kod, ad in corpus.banks if not plan.bank_codes or kod in plan.bank_codes)

    # Banka kümesi soruları ALAN'a göre farklı evrende hesaplanır. "Kaç banka
    # taşıt finansmanı VERİYOR" ürünü sorar (ölçüldü: 7 banka); "hangi bankada
    # taşıt KAMPANYASI yok" kampanyayı sorar (3 banka). Aynı sayıyı iki soruya
    # da vermek, birinde yanlış yanıt demektir.
    if spec.kind in {"count_banks", "absence"} and plan.source_domain in {
        "finansman",
        "katilma",
    }:
        olan = _urun_bankalari(corpus, plan)
        yok = [ad for ad in evren if ad not in olan]
        hesap = replace(
            aggregate.compute(docs, spec, tum_bankalar=evren),
            banks_with=tuple(sorted(olan)),
            banks_without=tuple(sorted(yok)),
            with_value=len(olan),
            without_value=len(yok),
        )
    else:
        hesap = aggregate.compute(docs, spec, tum_bankalar=evren)
    metin = aggregate.describe(hesap)

    # ── Uç değer: ürün oranı alanında oran tablosundan hesaplanır ─────────
    # ⚠️ `aggregate.compute` yalnızca KAMPANYA metriklerine bakar. Ölçüldü
    # (gerçek havuz): "En düşük konut finansmanı kâr payı oranı hangi katılım
    # bankasında?" sorusu — rekabet analizinin en klasik sorusu — "uygun teklif
    # bulunmamaktadır" yanıtı dönüyordu; oran verisi `product_rates`'te.
    oran_urunleri: list[ChatProductItem] = []
    sifir_notu: str | None = None
    oran_beraberlik: int | None = None
    if spec.kind == "extremum" and plan.source_domain in {"finansman", "katilma"}:
        kazanan_oran, berabere_oran, oransiz = _oran_ucdegeri(corpus, plan, spec)
        if kazanan_oran is not None:
            oran_urunleri = [_product_item(d) for d in [kazanan_oran, *berabere_oran][: req.limit]]

            # ⚠️ YAPISAL ALAN DA DOLDURULUR. Ölçüldü: metin kesin bir kazanan
            # ilan ederken `aggregate` bloğu `total=0` dönüyordu ("hesap
            # yapılmadı") ve arayüzdeki toplama paneli boş kalıyordu. Aynı
            # yanıtın iki yüzü birbiriyle çelişemez.
            oran_alani = _RATE_DOC_ALANI.get(spec.field or "", "profit_rate_pct")
            kazanan_deger = getattr(kazanan_oran, oran_alani)
            vade_mi = oran_alani == "term_months"
            oran_beraberlik = len(berabere_oran)
            hesap = replace(
                hesap,
                value=Decimal(str(kazanan_deger)),
                with_value=1 + oran_beraberlik,
                without_value=oransiz,
                total=1 + oran_beraberlik + oransiz,
                banks_with=tuple(sorted({d.bank_name for d in [kazanan_oran, *berabere_oran]})),
            )

            if vade_mi:
                # "En uzun vade" sorusuna oran cümlesi kurmak yanlış birim üretir.
                yon = "en uzun" if spec.direction == "max" else "en kısa"
                metin = (
                    f"{yon.capitalize()} vade {kazanan_deger} ay ile "
                    f"{kazanan_oran.bank_name} ({kazanan_oran.product_name})."
                )
            else:
                yon = "en yüksek" if spec.direction == "max" else "en düşük"
                metin = (
                    f"{yon.capitalize()} {kazanan_oran.rate_type.replace('_', ' ')} "
                    f"%{kazanan_deger} ile {kazanan_oran.bank_name} "
                    f"({kazanan_oran.product_name})."
                )
            if berabere_oran:
                metin += f" Aynı değeri sunan {len(berabere_oran)} kayıt daha var."
            if oransiz:
                # ⚠️ KAPSAM YAZILIR: kaç kayıtta değer yok bilinmeden uç değer
                # yanıltıcıdır (aggregate.describe ile aynı kural).
                metin += f" {oransiz} kayıtta bu bilgi yok."
            if not vade_mi and kazanan_deger == 0:
                # ⚠️ %0 İKİ ANLAMA GELİR ve kuralla ayırt edilemez:
                #   • gerçek bedelsiz kampanya (ölçüldü: Albaraka Togg,
                #     10-12 ay %0, 36 ay %3,05 — kısa vade bedelsiz)
                #   • kazıma boşluğu (Dünya Katılım Araç, 1,2M₺'de %0)
                # "En düşük oran %0" cümlesini açıklamasız bırakmak, veri
                # boşluğunu en iyi teklif gibi göstermek olur. Veriye
                # dokunulmuyor (provenance korunur), ama belirsizlik SÖYLENİR.
                #
                # ⚠️ UYARI METNE EKLENMEZ, YAPISAL ALANA YAZILIR. Ölçüldü:
                # `metin`e eklenen uyarı anlatıcı katmanında (`_anlat_computed`)
                # yeniden yazılırken DÜŞÜYORDU. Güvenlik bildirimi modelin
                # üslup kararına bırakılamaz.
                sifir_notu = (
                    "%0 değeri iki anlama gelebilir: bedelsiz (vade farksız) bir "
                    "kampanya ya da kaynakta oranın yayımlanmamış olması. Kaydın "
                    "kaynağına bakılması gerekir."
                )

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
            tie_count=oran_beraberlik if oran_beraberlik is not None else len(hesap.ties),
            by_bank=hesap.by_bank,
            banks_with=list(hesap.banks_with),
            banks_without=list(hesap.banks_without),
        ),
        products=oran_urunleri,
        direction_note=sifir_notu,
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


def _urun_bankalari(corpus: Corpus, plan: QueryPlan) -> set[str]:
    """Plandaki ürün tipi süzgecini KARŞILAYAN bankaların adları.

    ⚠️ Banka kümesi soruları alan (`source_domain`) bilmeden yanıtlanamaz.
    Ölçüldü: "kaç banka taşıt finansmanı VERİYOR" sorusu kampanya gövdesinden
    3 banka veriyordu; ürün tablosunda taşıt finansmanı ürünü olan banka
    sayısı 7. Bir banka kampanya yapmadan da ürünü sunabilir — "veriyor"
    ürünü sorar, "kampanyası var" kampanyayı sorar.
    """
    urunler = corpus.product_docs or {}
    urun_tipleri = _hedef_urun_tipleri(plan)
    bankalar: set[str] = set()
    for doc in urunler.values():
        if plan.bank_codes and doc.bank_code not in plan.bank_codes:
            continue
        tip = doc.product_type or ""
        if urun_tipleri and not any(t in tip or (tip and tip in t) for t in urun_tipleri):
            continue
        if plan.source_domain == "katilma":
            ad = _fold(doc.name)
            if not any(k in tip or k in ad for k in ("katilma", "birikim", "ara_donem")):
                continue
        elif plan.source_domain == "finansman" and "finansman" not in tip and not urun_tipleri:
            continue
        bankalar.add(doc.bank_name)
    return bankalar


def _tanim_terimi_kaba(raw: str) -> str:
    """Sözlük eşleşmesi için sorgunun tanım işaretçilerinden arınmış hâli.

    `query._tanim_terimi` kadar titiz değildir; burada tek iş sözlükte
    eşleşme aramaktır, niyet kararı verilmez.
    """
    metin = _fold(raw)
    for isaretci in ("nedir", "ne demek", "ne anlama gelir", "tanimi"):
        metin = metin.replace(isaretci, " ")
    return " ".join(metin.split())


def _plan_imzasi(plan: QueryPlan) -> tuple[object, ...]:
    """Bağlam devrinin planı GERÇEKTEN değiştirip değiştirmediğini ölçer."""
    return (
        plan.bank_codes,
        tuple(sorted((k, v) for k, v in plan.axis_filters.items())),
        plan.rate_type,
        plan.rate_type_candidates,
        plan.free_terms,
    )


async def process_chat_query(session: Session, req: ChatRequest) -> ChatResponse:
    """Doğal dil sorusunu uçtan uca işler (oturum + çok tur + anlatıcı)."""
    baslangic = time.perf_counter()
    oturum = chat_sessions.resolve_or_create(session, req.session_id, title_hint=req.query)
    turn = chat_sessions.next_turn_index(oturum)
    onceki_plan, devir_kimligi = chat_sessions.previous_plan(oturum, req.parent_completion_id)

    plan = parse_query(req.query)
    onceki_imza = _plan_imzasi(plan)
    plan = merge_with_previous(plan, onceki_plan)
    # Devir gerçekten olmadıysa kimliği yanıtta bildirmeyiz: arayüzde "önceki
    # sorudan devralındı" göstermek, devralınmamışken yanlış bilgi olur.
    if _plan_imzasi(plan) == onceki_imza:
        devir_kimligi = None

    # "Peki ONUN koşulları neler?" — anafora, önceki CEVABIN adını verdiği
    # kuruma işaret eder; önceki sorunun süzgecine değil. Ölçüldü: "en uzun
    # vade hangi bankada" → "Vakıf Katılım" cevabından sonra takip sorusu tüm
    # bankalarda arıyor, alakasız yanıt dönüyordu.
    kampanya_atfi = refers_to_focus_entity(req.query)
    if (kampanya_atfi or is_anaphoric_query(req.query)) and not opens_scope(req.query):
        odak_banka, odak_kampanya = chat_sessions.previous_focus(oturum, req.parent_completion_id)

        # ── Kampanya odağı ────────────────────────────────
        # "Bu kampanyanın bitiş tarihi ne zaman?" hiçbir süzgeç sinyali
        # taşımaz; yanıtı önceki cevabın işaret ettiği TEK kayıttır. Ölçüldü
        # (100 soruluk havuz, S3.3): bağlam devri olduğu hâlde sonuç boş
        # dönüyordu, çünkü devir yalnızca bankayı taşıyordu.
        if kampanya_atfi and odak_kampanya is not None:
            # ⚠️ Odak kurulduğunda DEVRALINAN eksen/durum süzgeçleri DÜŞER.
            # Odak tek bir kaydı işaret ediyor; ek süzgeç o kaydı yalnızca
            # YANLIŞLIKLA eleyebilir. Ölçüldü (havuz S3.3): önceki turdan 5
            # süzgeç devralınıyor ve sonuç 0'a düşüyordu.
            plan = replace(
                plan,
                axis_filters={},
                statuses=(),
                focus_campaign_id=odak_kampanya,
                signals=(
                    *plan.signals,
                    QuerySignal(
                        kind="campaign",
                        value=str(odak_kampanya),
                        label="Kampanya",
                        evidence="önceki cevap",
                    ),
                ),
            )
            devir_kimligi = devir_kimligi or req.parent_completion_id

        if not plan.bank_codes and odak_banka:
            plan = replace(
                plan,
                bank_codes=(odak_banka,),
                signals=(
                    *plan.signals,
                    QuerySignal(
                        kind="bank",
                        value=odak_banka,
                        label="Banka",
                        evidence="önceki cevap",
                    ),
                ),
            )
            devir_kimligi = devir_kimligi or req.parent_completion_id

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

    # ── Sözlük ZENGİNLEŞTİRMESİ ───────────────────────────
    # Tanım niyeti artık banka adı / sayısal kısıt varken kurulmuyor (olgusal
    # soru "nedir" ile de bitebilir). Ama tanım tamamen kaybolmamalı:
    # "Karz-ı hasen nedir? Dünya Katılım'da böyle bir ürün var mı?" sorusu hem
    # tanım hem olgu ister. Niyet olgusal kalır, tanım yanıta EKLENİR.
    #
    # Örtüşme denetimi: cevap metni tanımı zaten içeriyorsa tekrar eklenmez
    # (çift cevap — "Kâr Payı Oranı" kartı + aynı metin balonu).
    if not resp.glossary and has_definition_marker(req.query):
        sozluk_doc = _glossary_bul(corpus, plan.glossary_term or _tanim_terimi_kaba(req.query))
        if sozluk_doc is not None:
            cevap = resp.answer.text or ""
            tanim_parca = (sozluk_doc.definition or "")[:40]
            zaten_var = (sozluk_doc.term in cevap and tanim_parca and tanim_parca in cevap) or (
                f"{sozluk_doc.term}:" in cevap
            )
            if not zaten_var:
                resp.glossary = [
                    ChatGlossaryItem(
                        term_id=sozluk_doc.term_id,
                        term=sozluk_doc.term,
                        definition=sozluk_doc.definition,
                        conventional_equivalent=sozluk_doc.conventional_equivalent,
                    )
                ]

    resp.session_id = oturum.session_key
    resp.turn_index = turn
    resp.completion_id = f"cmpl-{uuid4().hex}"
    resp.parent_completion_id = devir_kimligi
    chat_sessions.record_turn(
        session,
        oturum,
        turn_index=turn,
        user_text=req.query,
        plan=plan,
        response=resp,
        completion_id=resp.completion_id,
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

    from app.retrieval.query import karsilastirma_konusu_belirsiz

    if karsilastirma_konusu_belirsiz(plan):
        return _finalize(
            _banka_karsilastirma_netlestirme(plan, corpus, uyari=uyari, elapsed_ms=gecen()),
            plan,
        )

    # ── Düşük güvende LLM router (sayı üretmez) ────────────
    llm_used = False
    rejected_slots: list[str] = []
    router_tool: str | None = None
    karar = _decision_from_plan(plan)
    if karar.is_low_confidence and plan.intent not in {"tanim"}:
        saglayici = _provider_or_none(plan=plan, model_id=req.model_id)
        router = await route_with_llm(plan.raw, karar, provider=saglayici)
        llm_used = router.llm_used
        rejected_slots = list(router.rejected_slots)
        router_tool = router.tool
        if router.domain and router.domain in {
            "kampanya",
            "finansman",
            "katilma",
            "tanim",
            "sohbet",
            "kapsam_disi",
        }:
            plan = replace(
                plan,
                source_domain=router.domain,
                domain_confidence=max(plan.domain_confidence, 0.60),
                domain_ambiguous=False,
                domain_runner_up=None,
            )
            if router.domain == "tanim":
                plan = replace(plan, intent="tanim")
            elif router.domain == "sohbet":
                plan = replace(plan, intent="sohbet")
            elif router.domain == "kapsam_disi":
                plan = replace(plan, intent="kapsam_disi")

    # Router sohbet / kapsam_disi'ye çevirdiyse erken çık.
    if plan.intent == "sohbet":
        return _with_routing(
            _sohbet_yanit(plan, uyari=uyari, elapsed_ms=gecen()),
            plan,
            llm_used=llm_used,
            rejected_slots=rejected_slots,
        )
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
            llm_used=llm_used,
            rejected_slots=rejected_slots,
        )

    # ── tanim — glossary, modele gitmez ───────────────────
    if plan.intent == "tanim":
        docs = _tanim_glossary_kayitlari(corpus, plan)
        if not docs:
            # ⚠️ SÖZLÜKTE YOKSA ARAMAYA DÜŞÜLÜR, "bulunamadı" DENMEZ.
            #
            # Ölçüldü (100 soruluk gerçek test havuzu): "nedir" ile biten her
            # soru tanım niyetine düşüyor. "Hadi Black Kredi Kartı ile Pegasus
            # uçuşlarında iade oranı nedir?" sorusu sözlükte aranıyor,
            # bulunamıyor ve kullanıcıya "sözlükte tanım bulunamadı" deniyordu
            # — oysa yanıt kampanya gövdesinde VAR. Adlandırılmış varlık
            # soruları tanım sorusu değildir; "nedir" iki işi de yapabiliyor.
            #
            # Ayrım önden kesin yapılamadığı için geri çekilme kullanılır:
            # sözlük ıskalarsa soru normal arama olarak yeniden işlenir.
            logger.info(
                "tanim_aramaya_dusuruldu",
                terim=plan.glossary_term,
                sorgu=plan.raw,
            )
            plan = replace(plan, intent="search", glossary_term=None)
        else:
            glossary = [
                ChatGlossaryItem(
                    term_id=doc.term_id,
                    term=doc.term,
                    definition=doc.definition,
                    conventional_equivalent=doc.conventional_equivalent,
                )
                for doc in docs
            ]
            if len(docs) == 1:
                metin = f"«{docs[0].term}» tanımı aşağıda."
            else:
                metin = (
                    f"«{docs[0].term}» ile «{docs[1].term}» arasındaki fark "
                    "aşağıda; her iki terimin tanımı kartlarda."
                )
            return _finalize(
                ChatResponse(
                    query=plan.raw,
                    intent=plan.intent,
                    understood=_understood(plan),
                    answer=AnswerBlock(
                        text=metin,
                        source="computed",
                        is_grounded=True,
                    ),
                    results=[],
                    glossary=glossary,
                    retrieval=RetrievalReport(
                        corpus_size=len(corpus.glossary_docs or {}),
                        returned=len(glossary),
                        lexical_used=False,
                        semantic_used=False,
                        semantic_note=(
                            "Tanım sorusu glossary tablosundan yanıtlandı; model çağrılmadı."
                        ),
                        elapsed_ms=gecen(),
                    ),
                    forbidden_terms_warning=uyari,
                ),
                plan,
                top=[],
            )

    # ── Araç katmanı (finansman / BDDK / katılma getiri) ───
    # Slotlar kullanıcı metninden; model sayı üretmez.
    # ⚠️ Katılma pivot'undan ÖNCE: tutar+vade ile getiri hesabı isteniyorsa
    # `katilma_getiri` çalışmalı; aksi halde yalnızca oran tablosu döner.
    slots = extract_slots(plan.raw, bank_codes=plan.bank_codes)
    from app.retrieval.query import (
        finansman_oran_listesi_mi,
        katilma_kar_payi_paylasim_karsilastirma_mi,
        katilma_oran_listesi_mi,
    )

    arac = detect_tool(plan.raw, source_domain=plan.source_domain, slots=slots)
    if katilma_oran_listesi_mi(plan.raw):
        if arac == "katilma_getiri":
            arac = None
        if router_tool == "katilma_getiri":
            router_tool = None
    if finansman_oran_listesi_mi(plan.raw):
        if arac == "finansman_teklif":
            arac = None
        if router_tool == "finansman_teklif":
            router_tool = None
    arac = arac or router_tool
    if arac is not None and plan.intent not in {"aggregate", "compare"}:
        arac_sonuc = run_tool(session, arac, slots, rate_type=plan.rate_type)
        products = list(arac_sonuc.products) if arac_sonuc.products else []
        comparison = None
        if arac_sonuc.comparison is not None:
            ranking = arac_sonuc.comparison
            comparison = ChatComparisonBlock(
                rate_type=getattr(ranking, "rate_type", plan.rate_type or "financing_rate"),
                criterion=getattr(ranking, "criterion", ""),
                winner_product_id=getattr(getattr(ranking, "winner", None), "product_id", None),
                winner_bank_code=getattr(getattr(ranking, "winner", None), "bank_code", None),
                winner_reason=getattr(ranking, "winner_reason", None),
                ranked=[],
                without_data=[],
                note=getattr(ranking, "note", None),
            )
            if not products and getattr(ranking, "ranked", None):
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
                    for s in ranking.ranked[:5]
                ]
        return _finalize(
            ChatResponse(
                query=plan.raw,
                intent=plan.intent,
                understood=_understood(plan),
                answer=AnswerBlock(
                    text=arac_sonuc.answer_text,
                    source="computed",
                    is_grounded=True,
                ),
                results=[],
                products=products,
                comparison=comparison,
                retrieval=RetrievalReport(
                    corpus_size=corpus.size,
                    returned=len(arac_sonuc.offers) or len(products),
                    lexical_used=False,
                    semantic_used=False,
                    semantic_note=f"Araç çalıştı: {arac}; model sayı üretmedi.",
                    elapsed_ms=gecen(),
                ),
                forbidden_terms_warning=uyari,
                clarification_needed=arac_sonuc.clarification_needed,
                clarification_question=arac_sonuc.clarification_question,
                actions=arac_sonuc.actions,
                offers=arac_sonuc.offers,
                tool_runs=arac_sonuc.tool_runs,
                bddk=arac_sonuc.bddk,
            ),
            plan,
            top=_top_from_products(products, domain=plan.source_domain) if products else [],
            llm_used=llm_used,
            rejected_slots=rejected_slots,
        )

    # ── katılma kavramı (getiri ≠ paylaşım oranı) ───────────
    if katilma_kar_payi_paylasim_karsilastirma_mi(plan.raw):
        return _katilma_kavram_yanit(session, plan, uyari=uyari, elapsed_ms=gecen())

    # ── katılma → oran tablosu (tutar/vade hesabı yoksa) ─
    if (
        plan.source_domain == "katilma"
        and not plan.domain_ambiguous
        and plan.domain_confidence >= LOW_CONFIDENCE
    ):
        return _katilma_yanit(session, plan, req, uyari=uyari, elapsed_ms=gecen())

    # Belirsiz katılma: pivot kısa devresi yok; aşağıdaki dallar çalışır.
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
    # ── ODAK KAMPANYA: erişim ATLANIR ─────────────────────
    # ⚠️ Sert süzgeç kapısı burada YETMEZ, çünkü erişim ondan ÖNCE çalışır.
    # "Bu kampanyanın bitiş tarihi ne zaman?" sorgusunda içerik terimi yoktur;
    # BM25 o kaydı hiç getirmez, dolayısıyla süzgeç kapısı da onu kurtaramaz.
    # Ölçüldü (havuz S3.3): odak kurulmuş, çip görünüyor, sonuç yine 0.
    # Odak tek bir kaydı işaret ettiği için doğru davranış aramak değil,
    # DOĞRUDAN OKUMAKTIR. Anlatım ve tüm denetimler normal akışta çalışır.
    odak_doc = (
        corpus.docs.get(plan.focus_campaign_id) if plan.focus_campaign_id is not None else None
    )
    if odak_doc is not None:
        sonuc = SearchResult(
            hits=(
                SearchHit(
                    doc=odak_doc,
                    score=1.0,
                    lexical_rank=None,
                    semantic_rank=None,
                    matched_terms=(),
                ),
            ),
            filters=FilterReport(),
            lexical_used=False,
            semantic_used=False,
            corpus_size=corpus.size,
            semantic_note=(
                "Soru önceki yanıttaki kampanyaya atıf yaptığı için arama "
                "yapılmadı; kayıt doğrudan okundu."
            ),
        )
    else:
        depo = _embedding_store(session)
        ayarlar = get_settings()
        # ⚠️ Sorgu vektörü Qdrant için de gerekli; yerel depo boş olsa bile
        # üretilmeli. Eski koşul (`if not depo.is_empty`) Qdrant kullanılırken
        # vektörü hiç üretmiyordu ve anlamsal kanal sessizce kapanıyordu.
        qdrant_secili = ayarlar.vector_backend.strip().lower() == "qdrant"
        vektor = (
            await _query_vector(saglayici, plan) if (qdrant_secili or not depo.is_empty) else None
        )
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
