"""Hibrit erişim — iki kanalın birleştirilmesi ve sert süzgeç kapısı.

⚠️ SERT SÜZGEÇ PUANLAMAYA KARIŞTIRILMAZ. Süzgeç bir KAPIDIR: "kâr payı %2'nin
altında" diyen bir sorguda %4,20'lik kampanya, metni ne kadar benzerse benzesin
listeye GİRMEZ. Yumuşak sıralamaya bırakılırsa liste doğru görünür ama yanlış
olur — ve yanlışlığı hata mesajı vermez.

⚠️ BİRLEŞTİRME PUAN TOPLAMAYLA DEĞİL SIRA İLE YAPILIR (Reciprocal Rank
Fusion). BM25 puanı sınırsız (0..20+), kosinüs benzerliği 0..1 aralığında.
Bunları toplamak, BM25'in anlamsal kanalı tamamen ezmesi demektir; ölçek
normalize edilse bile eşik veriye göre kayar. RRF yalnızca SIRAYA bakar,
ölçekten bağımsızdır.

⚠️ SÜZGEÇLE ELENEN SAYISI RAPORLANIR. Kaç kaydın hangi süzgece takıldığı
yanıtta döner; "8 sonuç bulundu" demek ile "2 kayıt kâr payı süzgecine takıldı,
8 sonuç kaldı" demek kullanıcı için aynı şey değildir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from app.logging_config import get_logger
from app.retrieval.corpus import CampaignDoc, Corpus
from app.retrieval.lexical import tokenize
from app.retrieval.query import NumericConstraint, QueryPlan
from app.retrieval.semantic import EmbeddingStore

logger = get_logger(__name__)

# RRF sabiti. 60 alan standardıdır: küçük değerler ilk sırayı aşırı
# ödüllendirip ikinci kanalı etkisizleştirir.
RRF_K: Final[int] = 60

# Kanal başına alınacak aday sayısı. Süzgeç kapısı SONRA uygulandığı için
# aday havuzu istenen sonuçtan geniş tutulur; aksi hâlde sert süzgeç listeyi
# boşaltır ve "sonuç yok" yanıtı süzgeçten değil dar havuzdan doğar.
CHANNEL_CANDIDATES: Final[int] = 120


@dataclass(frozen=True)
class SearchHit:
    """Erişim sonucu — hangi kanaldan geldiği ve neden geldiği kayıtlı."""

    doc: CampaignDoc
    score: float
    lexical_rank: int | None
    semantic_rank: int | None
    matched_terms: tuple[str, ...]

    @property
    def channels(self) -> tuple[str, ...]:
        """Bu kaydı getiren kanallar."""
        kanallar: list[str] = []
        if self.lexical_rank is not None:
            kanallar.append("lexical")
        if self.semantic_rank is not None:
            kanallar.append("semantic")
        return tuple(kanallar)


@dataclass(frozen=True)
class FilterReport:
    """Sert süzgecin ne elediğinin dökümü."""

    # Süzgeç adı → elenen kayıt sayısı.
    rejected: dict[str, int] = field(default_factory=dict)
    candidates_before: int = 0
    candidates_after: int = 0

    @property
    def total_rejected(self) -> int:
        """Toplam elenen kayıt sayısı."""
        return sum(self.rejected.values())


@dataclass(frozen=True)
class SearchResult:
    """Erişim katmanının tam çıktısı."""

    hits: tuple[SearchHit, ...]
    filters: FilterReport
    lexical_used: bool
    semantic_used: bool
    corpus_size: int
    # Anlamsal kanal neden kullanılmadı — arayüzde bildirilir.
    semantic_note: str | None = None


def _kisit_gecti(doc: CampaignDoc, kisit: NumericConstraint) -> bool | None:
    """Kampanya sayısal kısıtı sağlıyor mu?

    Returns:
        `True` sağlıyor · `False` sağlamıyor · `None` **değer yok**.

    ⚠️ ÜÇ DURUM AYRI. Değeri olmayan kampanyayı "sağlamıyor" saymak, kâr payı
    oranı çıkarılamamış 400+ kampanyayı her oran sorgusunda siler. "Sağlıyor"
    saymak ise uydurma sonuç üretir. Karar çağırana bırakılır ve raporlanır.
    """
    deger = doc.metrics.get(kisit.field)
    if deger is None:
        return None
    if kisit.op == "lte":
        return deger <= kisit.value
    if kisit.op == "gte":
        return deger >= kisit.value
    return deger == kisit.value


def _suzgecten_gecir(
    docs: list[CampaignDoc], plan: QueryPlan
) -> tuple[list[CampaignDoc], FilterReport]:
    """Sert süzgeçleri kapı olarak uygular.

    ⚠️ Aynı eksende birden çok değer VEYA ile bağlanır (kampanya etiketlerinden
    biri yeterli), ayrı eksenler VE ile bağlanır. "Emeklilere market
    kampanyası" hem `audience=emekli` hem `sector=market_gida` istiyor;
    ikisini VEYA yapmak sorguyu anlamsızlaştırır.
    """
    elenen: dict[str, int] = {}
    kalan: list[CampaignDoc] = []

    for doc in docs:
        if plan.bank_codes and doc.bank_code not in plan.bank_codes:
            elenen["banka"] = elenen.get("banka", 0) + 1
            continue
        if plan.statuses and doc.status not in plan.statuses:
            elenen["durum"] = elenen.get("durum", 0) + 1
            continue

        eksen_takildi: str | None = None
        for eksen, degerler in plan.axis_filters.items():
            if not set(degerler) & set(doc.axis_values.get(eksen, frozenset())):
                eksen_takildi = eksen
                break
        if eksen_takildi is not None:
            anahtar = f"eksen:{eksen_takildi}"
            elenen[anahtar] = elenen.get(anahtar, 0) + 1
            continue

        kisit_takildi: str | None = None
        for kisit in plan.numeric:
            sonuc = _kisit_gecti(doc, kisit)
            if sonuc is None:
                # ⚠️ DEĞER YOK → ELENİR ama AYRI sayılır. Kullanıcı sayısal bir
                # eşik verdiyse o alanı olmayan kaydı göstermek yanıltıcıdır;
                # ama bunun sebebi "eşiği geçmedi" değil "veri yok" ve yanıtta
                # böyle yazılır.
                kisit_takildi = f"{kisit.field}:veri_yok"
                break
            if not sonuc:
                kisit_takildi = f"{kisit.field}:esik"
                break
        if kisit_takildi is not None:
            elenen[kisit_takildi] = elenen.get(kisit_takildi, 0) + 1
            continue

        kalan.append(doc)

    return kalan, FilterReport(
        rejected=elenen, candidates_before=len(docs), candidates_after=len(kalan)
    )


def search(
    plan: QueryPlan,
    corpus: Corpus,
    *,
    query_vector: list[float] | None = None,
    store: EmbeddingStore | None = None,
    limit: int = 8,
) -> SearchResult:
    """Sorgu planına göre kampanya getirir.

    Args:
        plan: `parse_query()` çıktısı.
        corpus: Kurulu arama gövdesi.
        query_vector: Sorgunun gömme vektörü; yoksa anlamsal kanal atlanır.
        store: Yüklü gömme deposu; boşsa anlamsal kanal atlanır.
        limit: Döndürülecek en fazla sonuç.

    Returns:
        Sıralı sonuçlar, süzgeç dökümü ve hangi kanalların çalıştığı.
    """
    # Arama terimleri: süzgece dönüşmüş sözcükler de dahil edilir. Marka adı
    # hem sektör süzgeci hem arama terimi olabilir.
    terimler = list(plan.free_terms) or tokenize(plan.raw)

    sozcuksel = corpus.index.search(terimler, limit=CHANNEL_CANDIDATES) if terimler else []
    sozcuksel_sira = {vurus.doc_id: sira for sira, vurus in enumerate(sozcuksel, start=1)}
    eslesen_terimler = {vurus.doc_id: vurus.matched_terms for vurus in sozcuksel}

    anlamsal_sira: dict[int, int] = {}
    anlamsal_not: str | None = None
    if store is None or store.is_empty:
        anlamsal_not = (
            "Gömme vektörleri üretilmemiş; arama yalnızca sözcüksel kanalla yapıldı "
            "(`python dev.py gomme-uret`)."
        )
    elif not query_vector:
        anlamsal_not = "Sorgu vektörü üretilemedi; anlamsal kanal atlandı."
    else:
        anlamsal = store.search(query_vector, limit=CHANNEL_CANDIDATES)
        anlamsal_sira = {vurus.doc_id: sira for sira, vurus in enumerate(anlamsal, start=1)}

    # ⚠️ HİÇBİR KANAL ADAY ÜRETMEDİYSE gövdenin tamamı süzgece verilir.
    # "Ziraat Katılım'da hâlâ geçerli kampanyalar" sorgusunda arama terimi
    # yoktur — sorgu tamamen süzgeçten oluşur. Boş liste döndürmek, süzgecin
    # gerçekten sonuç vermediği izlenimini yaratırdı.
    aday_kimlikleri = set(sozcuksel_sira) | set(anlamsal_sira)
    if not aday_kimlikleri:
        if not plan.has_filters:
            return SearchResult(
                hits=(),
                filters=FilterReport(candidates_before=0, candidates_after=0),
                lexical_used=bool(terimler),
                semantic_used=bool(anlamsal_sira),
                corpus_size=corpus.size,
                semantic_note=anlamsal_not,
            )
        aday_kimlikleri = set(corpus.docs)

    adaylar = [corpus.docs[kimlik] for kimlik in aday_kimlikleri if kimlik in corpus.docs]
    kalan, rapor = _suzgecten_gecir(adaylar, plan)

    vuruslar: list[SearchHit] = []
    for doc in kalan:
        sozcuksel_yer = sozcuksel_sira.get(doc.campaign_id)
        anlamsal_yer = anlamsal_sira.get(doc.campaign_id)
        puan = 0.0
        if sozcuksel_yer is not None:
            puan += 1.0 / (RRF_K + sozcuksel_yer)
        if anlamsal_yer is not None:
            puan += 1.0 / (RRF_K + anlamsal_yer)
        vuruslar.append(
            SearchHit(
                doc=doc,
                score=puan,
                lexical_rank=sozcuksel_yer,
                semantic_rank=anlamsal_yer,
                matched_terms=eslesen_terimler.get(doc.campaign_id, ()),
            )
        )

    # ⚠️ İkinci sıralama ölçütü kampanya kimliği DEĞİL durum: yalnızca süzgeçten
    # gelen (puanı 0) kayıtlarda hangi kampanyanın önce geldiği kimliğe
    # bırakılırsa süresi dolmuş kampanyalar geçerli olanların önüne geçebilir.
    durum_sirasi = {"active": 0, "unknown": 1, "upcoming": 2, "expired": 3}
    vuruslar.sort(
        key=lambda vurus: (
            -vurus.score,
            durum_sirasi.get(vurus.doc.status, 9),
            vurus.doc.campaign_id,
        )
    )

    return SearchResult(
        hits=tuple(vuruslar[:limit]),
        filters=rapor,
        lexical_used=bool(sozcuksel),
        semantic_used=bool(anlamsal_sira),
        corpus_size=corpus.size,
        semantic_note=anlamsal_not,
    )


def extremum(
    docs: list[CampaignDoc], *, field_name: str, direction: str
) -> tuple[CampaignDoc | None, int, int]:
    """Bir alanın en küçük/en büyük değerini taşıyan kampanyayı bulur.

    ⚠️ TOPLAMA ERİŞİME GİRMEZ. Getirilen 8 kartın asgarisi, 608 kampanyanın
    asgarisi değildir. Bu fonksiyon süzgeçten geçmiş TÜM kayıtlar üzerinde
    çalışır (mimari §5).

    Returns:
        (kazanan, değeri olan kayıt sayısı, değeri olmayan kayıt sayısı).
        Değeri olmayan sayı raporlanmak ZORUNDA: `NULL` "sıfır" değildir ve
        kaç kaydın hesabın dışında kaldığı gizlenemez.
    """
    degerli = [doc for doc in docs if field_name in doc.metrics]
    degersiz = len(docs) - len(degerli)
    if not degerli:
        return None, 0, degersiz

    ters = direction == "max"
    kazanan = sorted(
        degerli,
        key=lambda doc: (doc.metrics[field_name], -doc.campaign_id),
        reverse=ters,
    )[0]
    return kazanan, len(degerli), degersiz


def count(docs: list[CampaignDoc]) -> dict[str, int]:
    """Süzgeçten geçen kayıtları banka bazında sayar."""
    sonuc: dict[str, int] = {}
    for doc in docs:
        sonuc[doc.bank_name] = sonuc.get(doc.bank_name, 0) + 1
    return dict(sorted(sonuc.items(), key=lambda ikili: (-ikili[1], ikili[0])))


def filter_all(corpus: Corpus, plan: QueryPlan) -> tuple[list[CampaignDoc], FilterReport]:
    """Gövdenin tamamına sert süzgeci uygular (toplama soruları için)."""
    return _suzgecten_gecir(list(corpus.docs.values()), plan)


__all__ = [
    "CHANNEL_CANDIDATES",
    "RRF_K",
    "FilterReport",
    "SearchHit",
    "SearchResult",
    "count",
    "extremum",
    "filter_all",
    "search",
]
