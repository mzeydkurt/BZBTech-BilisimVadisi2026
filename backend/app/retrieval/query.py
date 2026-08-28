"""Türkçe doğal dil sorgusunu yapısal süzgeçlere çevirir.

⚠️ KURAL ÖNCE, LLM SON ÇARE. Sorguların büyük kısmı banka adı, taksonomi
terimi, sayı ve karşılaştırma sözcüğünden oluşuyor; bunların hepsi
deterministik olarak okunabilir. Modele sorulan her süzgeç, uydurma süzgeç
riski demektir — ve uydurma süzgeç hata fırlatmaz, sessizce yanlış liste
döndürür.

⚠️ SÖZLÜK BURADA YENİDEN TANIMLANMAZ. Taksonomi terimleri
`app/core/taxonomy.py`, sayı/tarih ayrıştırma `app/core/normalization/`
içinden gelir. İkinci bir kopya açmak, iki sözlüğün sessizce ıraksaması
demekti (Sprint 2'de `PRODUCT_TYPES` bu yüzden tek sözlükte tutuldu).

⚠️ SÜZGEÇ ÇIKARILAMAZSA SORGU REDDEDİLMEZ. Süzgeçsiz serbest metin aramasına
düşülür. "Anlamadım" ile "sonuç yok" ayrı şeylerdir; ikincisini birincinin
yerine göstermek `EmptyState` / `ErrorState` ayrımının aynı hatasıdır.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Final

from app.core.normalization.money import parse_decimal_tr
from app.core.normalization.text import ascii_fold_tr, lower_tr, normalize_text
from app.core.taxonomy import (
    AUDIENCE_KEYWORDS,
    AXIS_VALUES,
    BENEFIT_KEYWORDS,
    PRODUCT_TYPE_KEYWORDS,
    SECTOR_KEYWORDS,
)
from app.retrieval.routing import resolve_source_domain, score_domains

# ── Banka takma adları ────────────────────────────────────
# ⚠️ Kullanıcı bankanın tam adını yazmıyor. `banks.name` ile birebir eşleşme
# arandığında "KT'de kampanya var mı" sorgusu hiçbir banka bulamıyor.
# Anahtarlar `BANK_SEED` içindeki kodlarla birebir aynıdır.
BANK_ALIASES: Final[dict[str, tuple[str, ...]]] = {
    "kuveyt_turk": ("kuveyt turk", "kuveyt türk", "kuveytturk", "kt katilim", "kuveyt", "kt"),
    "albaraka": ("albaraka turk", "albaraka türk", "albaraka", "albarakaturk"),
    "turkiye_finans": ("turkiye finans", "türkiye finans", "turkiyefinans", "tfkb"),
    "vakif_katilim": ("vakif katilim", "vakıf katılım", "vakifkatilim", "vakif"),
    "ziraat_katilim": ("ziraat katilim", "ziraat katılım", "ziraatkatilim", "ziraat"),
    "emlak_katilim": (
        "turkiye emlak katilim",
        "türkiye emlak katılım",
        "emlak katilim",
        "emlak katılım",
        "emlakkatilim",
        "emlak",
    ),
    "hayat_finans": ("hayat finans", "hayatfinans", "hayat"),
    "tom_bank": ("t.o.m.", "tom katilim", "tom bank", "tombank", "tom"),
    "dunya_katilim": ("dunya katilim", "dünya katılım", "dunyakatilim", "dunya"),
    "adil_katilim": ("adil katilim", "adil katılım", "adilkatilim", "adil"),
}

# ── Yalnızca SORGUDA geçerli, çıplak eksen sözcükleri ─────
# ⚠️ `taxonomy.py` DEĞİŞTİRİLMEZ. O sözlük uzun kampanya SAYFALARI için
# ayarlandı: çıplak "finansman" kelimesi her bankanın her sayfasında geçiyor,
# bu yüzden `PRODUCT_TYPE_KEYWORDS["finansman"]` yalnızca "finansman kullan",
# "finansman imkânı" gibi ÖBEKLERİ arıyor. Kısa bir soruda ise çıplak
# "finansman" kelimesi gerçek ve tek sinyaldir — aynı sözlüğü iki bağlamda
# aynı eşikle kullanmak, sorguyu sessizce süzgeçsiz bırakıyordu
# ("En uzun vadeli finansman hangi bankada?" → hiçbir eksen süzgeci yok).
#
# ⚠️ YEDEK OLARAK ÇALIŞIR. Aynı eksende daha özgül bir değer eşleştiyse
# (ör. `konut_finansmani`) çıplak sözcük EKLENMEZ; yoksa her konut sorgusu
# genel finansman kampanyalarını da içine alır ve isabet düşer.
QUERY_ONLY_KEYWORDS: Final[dict[str, dict[str, tuple[str, ...]]]] = {
    "product_type": {
        "finansman": ("finansman", "finanse"),
        "kart": ("kredi karti", "banka karti"),
        "sigorta": ("sigorta",),
        "yatirim_urunu": ("yatirim",),
        "birikim_katilma_hesabi": ("katilma hesabi", "birikim"),
        "dijital_bankacilik": ("dijital bankacilik", "mobil bankacilik"),
    },
}

# ── Sorguda eksen süzgeci ÜRETMEYECEK anahtar kelimeler ───
# ⚠️ BİR SİMGENİN İKİ EKSENDE ROLÜ OLAMAZ — `_karsilastirma_maskele`
# içindeki "altın/altında" vakasıyla AYNI hata sınıfı, farklı yüzü.
#
# `PRODUCT_TYPE_KEYWORDS["alisveris_puani"]` listesinde "nakit iade" var. O
# sözlük uzun kampanya SAYFALARI için doğru: sayfasında nakit iade geçen bir
# kampanya gerçekten bir alışveriş-puanı ürünüdür. Ama "nakit iade" AYNI
# ZAMANDA bir FAYDA'dır (`BENEFIT_KEYWORDS["nakit_iade"]`) ve sorguda tek bir
# sözcük iki ekseni birden dolduruyor. Eksenler VE ile bağlandığı için sonuç
# çift kapı oluyor:
#
#     "Uçak bileti alımlarında nakit iade veren TOM Bank kampanyaları"
#       → benefit=nakit_iade        (doğru)
#       → product_type=alisveris_puani  (istenmeyen)
#     İlgili 5 kampanyanın hepsi `product_type=kart` → süzgeç 0 sonuç.
#
# Ölçüldü: `docs/erisim_recall.md` sorgu e02, geri çağırma 0,00 → 1,00.
#
# ⚠️ `taxonomy.py` DEĞİŞTİRİLMEZ. Sınıflandırma tarafında "nakit iade" →
# `alisveris_puani` çıkarımı DOĞRU kalır; yanlış olan aynı eşiği kısa bir
# soruda kullanmaktı. Ayrım `QUERY_ONLY_KEYWORDS` ile aynı gerekçeye dayanır,
# yalnızca yönü ters.
QUERY_EXCLUDED_KEYWORDS: Final[dict[str, dict[str, tuple[str, ...]]]] = {
    "product_type": {
        "alisveris_puani": ("nakit iade",),
    },
}

# ── Niyet işaretçileri ────────────────────────────────────
# Toplama niyeti erişime hiç girmez; SQL ile yanıtlanır (mimari §5).
AGGREGATE_MARKERS: Final[dict[str, str]] = {
    "en dusuk": "min",
    "en az": "min",
    "en ucuz": "min",
    "en avantajli": "min",
    "en yuksek": "max",
    "en fazla": "max",
    "en cok": "max",
    "en uzun": "max",
    "en buyuk": "max",
    "en kisa": "min",
}
COUNT_MARKERS: Final[tuple[str, ...]] = (
    "kac tane",
    "kac adet",
    "kac kampanya",
    "kac farkli",
    "sayisi",
    "toplam kac",
)
# "Kaç banka X veriyor?" — sayılan şey KAMPANYA DEĞİL, BANKADIR.
# Ölçüldü: bu ifade `count` işaretçilerine girmediği için sorgu `search`e
# düşüyor ve model sayıyı KENDİ üretiyordu. "Kaç banka taşıt finansmanı
# veriyor?" sorusuna "iki banka" yanıtı geldi; gerçek sayı 7. Bu, projenin
# "model sayı üretmez" güvencesinin doğrudan ihlaliydi.
BANK_COUNT_MARKERS: Final[tuple[str, ...]] = (
    "kac banka",
    "kac tane banka",
    "kac kurum",
    "kac katilim bankasi",
)

# "Hangi bankada X YOK?" — yokluk sorusu. Ölçüldü: olumsuzlama tamamen
# görmezden geliniyor, "hangi bankada taşıt finansmanı kampanyası yok"
# sorusuna taşıt finansmanı ORANLARI listeleniyordu. Ters yanıt.
ABSENCE_MARKERS: Final[tuple[str, ...]] = (
    "yok mu",
    "yok",
    "olmayan",
    "bulunmayan",
    "sunmayan",
    "vermeyen",
    "yapmayan",
    "eksik olan",
    "hic yok",
)

# "Hangi bankalar var?" — LİSTE sorusu. Ölçüldü: bu soru serbest metin
# aramasına düşüyor, rastgele 3 kampanya kartı dönüyor ve model o kartlardaki
# banka adlarını "bulunan bankalar" diye sunuyordu: "Dünya Katılım, T.O.M.
# Katılım Bankası ve Albaraka Türk bulunmaktadır." Gerçek sayı 10.
#
# Yanıt erişimden DEĞİL banka evreninden gelir; kapsam sorusunun yanıtı
# örneklem olamaz.
BANK_ROSTER_MARKERS: Final[tuple[str, ...]] = (
    "hangi bankalar var",
    "hangi bankalar",
    "hangi katilim bankalari",
    "bankalari listele",
    "banka listesi",
    "bankalar neler",
    "hangi bankalara bakiyorsun",
    "kapsamdaki bankalar",
    "hangi bankalari biliyorsun",
    "tum bankalar neler",
)

COMPARE_MARKERS: Final[tuple[str, ...]] = ("karsilastir", "kiyasla", "hangisi daha", " ile ")

_BANKA_KARSILASTIRMA_KALIPLARI: Final[tuple[str, ...]] = (
    "hangisi daha",
    "daha avantajli",
    "daha iyi",
    "daha uygun",
    "daha mantikli",
    "daha ucuz",
    "karsilastir",
    "kiyasla",
    "arasında hangisi",
    "arasinda hangisi",
    "hangisini secmeliyim",
    "hangisini seçmeliyim",
)


def _banka_karsilastirma_mi(katlanmis: str, banka_sayisi: int) -> bool:
    """İki veya daha fazla banka adı geçen tercih / karşılaştırma sorusu mu?

    "Kuveyt Türk mü daha avantajlı, Albaraka mı?" → True.
    "Kuveyt Türk kampanyaları" → False.
    """
    if banka_sayisi < 2:
        return False
    if any(k in katlanmis for k in _BANKA_KARSILASTIRMA_KALIPLARI):
        return True
    if any(isaretci in katlanmis for isaretci in COMPARE_MARKERS):
        return True
    # "X mi … Y mi?" tercih kalıbı + üstünlük sıfatı.
    return bool(
        re.search(r"(mi|mu|mı|mü)", katlanmis)
        and any(
            x in katlanmis for x in ("avantaj", "iyi", "uygun", "mantik", "ucuz", "dusuk", "yuksek")
        )
    )


def karsilastirma_konusu_belirsiz(plan: QueryPlan) -> bool:
    """İki banka karşılaştırılıyor ama kampanya/finansman/katılma konusu yok mu?"""
    if len(plan.bank_codes) < 2:
        return False
    katlanmis = _fold(plan.raw)
    if not _banka_karsilastirma_mi(katlanmis, len(plan.bank_codes)) and plan.intent != "compare":
        return False
    if plan.rate_type or plan.axis_filters.get("product_type"):
        return False
    # Konu terimi geçiyorsa belirsizlik yoktur.
    return not any(
        x in katlanmis
        for x in (
            "kampanya",
            "finansman",
            "katilma",
            "katilim hesap",
            "getiri",
            "konut finans",
            "tasit finans",
            "ihtiyac finans",
            "kar payi",
            "oran",
            "taksit avantaj",
            "nakit iade",
        )
    )


# ── Tanım niyeti ──────────────────────────────────────────
DEFINITION_MARKERS: Final[tuple[str, ...]] = (
    "ne demek",
    "ne anlama",
    "nedir",
    "anlami ne",
    "anlamı ne",
    "tanimi",
    "tanımı",
    "ne demektir",
)

# ── Sohbet niyeti (selam / teşekkür / kimsin) ─────────────
# Finansal sinyal yok VE kısa sorgu (≤6 belirteç) iken,
# kapsam_disi'dan ÖNCE çözülür. "merhaba, katılma hesabı açacağım" sohbete düşmez.
_SOHBET_KALIPLARI: Final[tuple[str, ...]] = (
    "merhaba",
    "selam",
    "selamlar",
    "gunaydin",
    "günaydın",
    "iyi gunler",
    "iyi günler",
    "iyi aksamlar",
    "iyi akşamlar",
    "nasilsin",
    "nasılsın",
    "naber",
    "ne haber",
    "tesekkur",
    "teşekkür",
    "tesekkurler",
    "teşekkürler",
    "sagol",
    "sağol",
    "eyvallah",
    "kimsin",
    "sen kimsin",
    "ne yapabilirsin",
    "ne yaparsin",
    "ne yapıyorsun",
    "yardim et",
    "yardım et",
    "gorusuruz",
    "görüşürüz",
    "hosca kal",
    "hoşça kal",
    "bye",
    "hello",
    "hi",
)

# ── Oran türü işaretçileri ────────────────────────────────
# ⚠️ Dağıtılan kâr payı ≠ kâr paylaşım oranı. Belirsizse aday listesi dolar;
# sohbet netleştirme sorar (KAPI 2.3).
RATE_TYPE_MARKERS: Final[dict[str, tuple[str, ...]]] = {
    "financing_rate": (
        "finansman orani",
        "finansman kar payi",
        "konut finansman",
        "tasit finansman",
        "ihtiyac finansman",
        "finansman",
    ),
    "participation_yield": (
        "katilma hesabi",
        "katilim hesabi",  # yaygın yazım hatası → katılma
        "standart katilma",
        "standart katilim",
        "dagitilan kar payi",
        "getiri",
        "vadeli mevduat",
        "katilim fonu getirisi",
    ),
    "profit_sharing_ratio": (
        "kar paylasim",
        "paylasim orani",
        "musteri payi",
        "katilimci payi",
        "90/10",
        "98/2",
    ),
    "interest_free_benevolent_loan": (
        "karz-i hasen",
        "karzi hasen",
        "karz ı hasen",
        "faizsiz borc",
    ),
}

# Konvansiyonel → katılım eşlemesi (sorgu REDDEDİLMEZ; arama kırılmasın).
CONVENTIONAL_QUERY_MAP: Final[tuple[tuple[str, str], ...]] = (
    ("vadeli mevduat", "katilma hesabi"),
    ("faiz orani", "kar payi orani"),
    ("faiz", "kar payi"),
    ("mevduat", "katilim fonu"),
    ("kredi faizi", "finansman kar payi"),
)

# Kapsam dışı — beyaz liste dışı VE açıkça yabancı alan.
# ⚠️ Siyah liste kısa ve kapalı tutulur; "evlenecek çiftlere…" gibi
# serbest metin araması search'te kalır (3C sözleşmesi).
OUT_OF_DOMAIN_MARKERS: Final[tuple[str, ...]] = (
    "hava nasil",
    "hava durumu",
    "yarin hava",
    "bugun hava",
    "mac sonucu",
    "futbol skoru",
    "yemek tarifi",
    "film oner",
    "sarki sozu",
    # ⚠️ Kripto / borsa yatırım tavsiyesi KAPSAM DIŞI. Ölçüldü: "Bitcoin alsam
    # mı?" `search` niyetine düşüyor ve model ürün kartlarına dayanarak cevap
    # üretiyordu. Bir finansal kurum aracının kripto ya da hisse tavsiyesi
    # vermesi hem kapsam hem uyum sorunudur.
    #
    # ⚠️ "döviz" BİLİNÇLİ OLARAK EKLENMEDİ: `yatirim_birikim` sektörünün
    # gerçek anahtar kelimesi ve meşru kampanya sorgularında geçiyor.
    "bitcoin",
    "kripto",
    "hisse senedi",
    "borsada",
    "borsa endeks",
)

# ── Durum işaretçileri ────────────────────────────────────
# ⚠️ `unknown` ile `expired` AYRI. Tarihi bulunamayan kampanya "süresi dolmuş"
# değildir; `compute_status()` bunları ayrı döndürüyor ve sorgu katmanı da
# ayırmak zorunda (bkz. CLAUDE.md).
STATUS_MARKERS: Final[dict[str, tuple[str, ...]]] = {
    "active": ("hala gecerli", "halen gecerli", "gecerli olan", "aktif", "devam eden", "suren"),
    "expired": ("suresi dolmus", "sona ermis", "bitmis", "gecmis", "eski"),
    "upcoming": ("baslayacak", "yakinda", "gelecek"),
    "unknown": ("tarihi belli olmayan", "tarihsiz", "tarihi yok", "tarihi bilinmeyen"),
}

# ── Sayısal alan işaretçileri ─────────────────────────────
# Sayının HANGİ alana ait olduğu, sayıya en yakın işaretçiden okunur.
# ⚠️ İşaretçisiz çıplak sayı süzgece ÇEVRİLMEZ. Sprint 2'de aynı hata
# ölçülmüştü: sayfadaki her çıplak sayı `amount_max` sanılıyordu ("36 ay" ve
# "%80" tutar olarak yazılmıştı). Aynı hatayı sorgu tarafında tekrarlamayız.
NUMERIC_FIELD_MARKERS: Final[dict[str, tuple[str, ...]]] = {
    "profit_rate_pct": ("kar payi", "kar pay", "oran"),
    "term_months_max": ("vade", "ay", "aylik"),
    "installment_count": ("taksit",),
    "reward_amount_try": ("odul", "iade", "hediye", "kazanc", "bonus"),
    "min_spend_try": ("harcama", "alisveris"),
    "financing_amount_max": ("finansman tutari", "tutar", "limit"),
    "cashback_pct": ("nakit iade",),
    "discount_pct": ("indirim",),
    # ⚠️ ÇOK SÖZCÜKLÜ İŞARETÇİ ZORUNLU. Çıplak "toplam" `reward_amount_try`nin
    # "odul" işaretçisiyle sürekli yarışırdı ve seçim en yakın işaretçiye göre
    # yapıldığı için sonuç cümledeki sözcük sırasına bağlı olurdu. Öbek hâlinde
    # yazıldığında yalnızca kullanıcı gerçekten TOPLAM faydayı sorduğunda
    # eşleşir.
    #
    # ⚠️ Bu alan çıkarılıyor (77 kampanya), `campaign_metrics`e yazılıyor,
    # `corpus._METRIC_FIELDS` ve `aggregate.FIELD_LABELS` içinde var — ama
    # buraya girmediği sürece HİÇBİR SORGUDAN ERİŞİLEMİYORDU. Dolu bir kolonun
    # sorulamaması, boş bir kolondan farksızdır.
    "max_total_benefit_try": (
        "toplam fayda",
        "toplam kazanc",
        "toplam odul",
        "azami toplam",
        "toplamda kazan",
    ),
}

# Yüzde taşıyan alanlar; bunlarda "%" işareti beklenir.
PERCENT_FIELDS: Final[frozenset[str]] = frozenset(
    {"profit_rate_pct", "cashback_pct", "discount_pct"}
)

# ── Karşılaştırma yönü ────────────────────────────────────
# Sıra ÖNEMLİ: "altinda" ile "alti" ayrı ele alınmazsa "%2 altı" kaçırılır.
COMPARISON_MARKERS: Final[tuple[tuple[str, str], ...]] = (
    ("altinda", "lte"),
    ("altındaki", "lte"),
    ("alti", "lte"),
    ("asagi", "lte"),
    ("dan az", "lte"),
    ("den az", "lte"),
    ("dan dusuk", "lte"),
    ("den dusuk", "lte"),
    ("dan kisa", "lte"),
    ("den kisa", "lte"),
    ("en fazla", "lte"),
    ("uzerinde", "gte"),
    ("uzeri", "gte"),
    ("ustu", "gte"),
    ("yukari", "gte"),
    ("dan fazla", "gte"),
    ("den fazla", "gte"),
    ("dan yuksek", "gte"),
    ("den yuksek", "gte"),
    ("dan uzun", "gte"),
    ("den uzun", "gte"),
    ("en az", "gte"),
    ("asgari", "gte"),
)

# Sayının hangi alana ait olduğunu ararken bakılacak pencere (karakter).
MARKER_WINDOW: Final[int] = 28

# BM25/gömme kanalına geçmeyecek, anlam taşımayan sorgu sözcükleri.
STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        "bir",
        "bu",
        "su",
        "ne",
        "var",
        "yok",
        "mi",
        "mu",
        "hangi",
        "hangisi",
        "kac",
        "tane",
        "adet",
        "icin",
        "ile",
        "ve",
        "veya",
        "da",
        "de",
        "en",
        "cok",
        "az",
        "gibi",
        "olan",
        "banka",
        "bankasi",
        "bankalar",
        "bankalarda",
        "kampanya",
        "kampanyalar",
        "kampanyasi",
        "kampanyalari",
        "goster",
        "listele",
        "bul",
        "soyle",
        "nedir",
        "nelerdir",
        "mevcut",
    }
)

_SAYI_RE: Final[re.Pattern[str]] = re.compile(r"%?\s*\d[\d.,]*\s*%?")
_KELIME_RE: Final[re.Pattern[str]] = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class QuerySignal:
    """Sorgudan çıkarılan tek bir süzgeç ve onu üreten kanıt.

    ⚠️ `evidence` arayüzde gösterilir. Sistemin soruyu nasıl anladığı
    kullanıcıya açık olmadığında yanlış anlaşılma fark edilemez ve
    düzeltilemez (mimari §7).
    """

    kind: str
    value: str
    label: str
    evidence: str


@dataclass(frozen=True)
class NumericConstraint:
    """`campaign_metrics` üzerinde uygulanacak sert sayısal kısıt.

    ⚠️ SERT KAPI, PUAN DEĞİL. Kısıtı sağlamayan kampanya, metni ne kadar
    benzerse benzesin listeye girmez (mimari §4).
    """

    field: str
    op: str
    value: Decimal
    evidence: str


@dataclass(frozen=True)
class AggregateSpec:
    """Toplama sorusunun hesap tarifi."""

    kind: str
    field: str | None = None
    direction: str | None = None


@dataclass(frozen=True)
class QueryPlan:
    """Bir sorgunun tam yorumu."""

    raw: str
    intent: str
    bank_codes: tuple[str, ...] = ()
    axis_filters: dict[str, tuple[str, ...]] = field(default_factory=dict)
    numeric: tuple[NumericConstraint, ...] = ()
    statuses: tuple[str, ...] = ()
    free_terms: tuple[str, ...] = ()
    aggregate: AggregateSpec | None = None
    signals: tuple[QuerySignal, ...] = ()
    # Sprint 5: oran türü (tekil_sorgu / compare netleştirme).
    rate_type: str | None = None
    rate_type_candidates: tuple[str, ...] = ()
    # Tanım niyetinde aranan terim (ham).
    glossary_term: str | None = None
    # ── Çok turlu odak ────────────────────────────────────
    # Önceki CEVABIN işaret ettiği tek kampanya. "Bu kampanyanın bitiş tarihi
    # ne zaman?" sorusu hiçbir süzgeç sinyali taşımaz; ölçüldü (100 soruluk
    # gerçek havuz, S3.3) — bağlam devri OLDUĞU hâlde sonuç boş dönüyordu,
    # çünkü devir yalnızca BANKAYI taşıyordu, kampanyayı değil.
    focus_campaign_id: int | None = None
    # Katibim: birincil kaynak alanı.
    source_domain: str = "kampanya"
    # Güven puanlı yönlendirme (yalnızca ekleme).
    domain_confidence: float = 1.0
    domain_ambiguous: bool = False
    domain_scores: tuple[tuple[str, float], ...] = ()
    domain_runner_up: str | None = None

    @property
    def has_filters(self) -> bool:
        """Herhangi bir yapısal süzgeç çıkarıldı mı?"""
        return bool(self.bank_codes or self.axis_filters or self.numeric or self.statuses)


# Katılma vadesi — uzun kalıp önce (3 aylık, "aylık"tan önce).
_KATILMA_VADE: Final[tuple[tuple[tuple[str, ...], int], ...]] = (
    (("3 aylik", "3 ay", "uc aylik"), 3),
    (("6 aylik", "6 ay", "alti aylik"), 6),
    (("yillik", "12 ay", "1 yil", "bir yil"), 12),
    (("aylik", "1 ay", "bir aylik"), 1),
)


def parse_katilma_vade(katlanmis: str) -> int | None:
    """Sorgudan katılma vadesini okur (ay). Belirtilmemişse None.

    Birden fazla vade geçiyorsa ilk eşleşeni döner (3 → 6 → 12 → 1 sırası).
    Tüm vadeler için `parse_katilma_vadeler` kullanın.
    """
    for kaliplar, ay in _KATILMA_VADE:
        if any(k in katlanmis for k in kaliplar):
            return ay
    return None


def parse_katilma_vadeler(katlanmis: str) -> tuple[int, ...]:
    """Sorguda geçen tüm katılma vadelerini döner (1, 3, 6, 12 sırasıyla).

    "aylık" yalnız başına 1 ay demektir; "3 aylık" içindeki "aylık" sayılmaz.
    """
    bulunan: set[int] = set()
    if any(k in katlanmis for k in ("3 aylik", "3 ay", "uc aylik")):
        bulunan.add(3)
    if any(k in katlanmis for k in ("6 aylik", "6 ay", "alti aylik")):
        bulunan.add(6)
    if any(k in katlanmis for k in ("yillik", "12 ay", "1 yil", "bir yil")):
        bulunan.add(12)

    kalan = katlanmis
    for k in (
        "3 aylik",
        "3 ay",
        "uc aylik",
        "6 aylik",
        "6 ay",
        "alti aylik",
        "12 ay",
        "1 yil",
        "bir yil",
        "yillik",
    ):
        kalan = kalan.replace(k, " ")
    if any(k in kalan for k in ("aylik", "1 ay", "bir aylik")):
        bulunan.add(1)

    return tuple(ay for ay in (1, 3, 6, 12) if ay in bulunan)


def parse_katilma_varyant(katlanmis: str) -> str:
    """standart → normal; ara ödemeli → ara_odemeli."""
    if any(k in katlanmis for k in ("ara odeme", "ara donem", "ara odemeli")):
        return "ara_odemeli"
    return "normal"


_KATILMA_HESAPLAMA_ISARET: Final[tuple[str, ...]] = (
    "yatirsam",
    "yatirirsem",
    "yatirir",
    "yatirdim",
    "yatiracagim",
    "yatiracagim",
    "ne kadar olur",
    "ne kadar olma",
    "donem sonu",
    "donem sonunda",
    "getiri hesapla",
    "kazancim",
    "kazanirim",
    "param ne kadar",
    "bakiye ne olur",
    "ne kadar kazanir",
    "ne kadar kazanır",
)


def katilma_oran_listesi_mi(raw: str) -> bool:
    """Katılma hesabı oran tablosu sorusu mu (getiri simülasyonu değil)?

    "Ziraat'ın aylık/3/6/12 aylık oranları nedir" → True.
    "10.000 TL yatırsam dönem sonu ne olur" → False.
    """
    k = _fold(raw)
    if any(i in k for i in _KATILMA_HESAPLAMA_ISARET):
        return False
    if "katilma" not in k and "katilim" not in k and "hesap" not in k:
        return False
    oran_sorusu = any(
        x in k
        for x in (
            "oranlari",
            "oranlar",
            "oran nedir",
            "oran ne",
            "kar payi oran",
            "getiri oran",
            "dagitilan kar",
        )
    ) or ("oran" in k and any(x in k for x in ("nedir", "neler", "kac", "ne ")))
    if not oran_sorusu:
        return False
    vadeler = parse_katilma_vadeler(k)
    return len(vadeler) >= 2 or "oranlari" in k or "oranlar" in k


_FINANSMAN_HESAPLAMA_ISARET: Final[tuple[str, ...]] = (
    "hesapla",
    "simule",
    "simulasyon",
    "taksit",
    "ne kadar od",
    "ne kadar öd",
    "aylik taksit",
    "aylık taksit",
    "toplam maliyet",
    "geri odeme",
    "geri ödeme",
    "kullandir",
    "kullandır",
    "almak istiyorum",
    "cikacak",
    "çıkacak",
)


def katilma_kar_payi_paylasim_karsilastirma_mi(raw: str) -> bool:
    """Dağıtılan kâr payı (getiri) ile kâr paylaşım oranı karşılaştırması mı?

    "Kâr payı ile paylaşım oranı aynı mı?" → True (oran tablosu değil, kavram).
    """
    k = _fold(raw)
    has_kar = any(x in k for x in ("kar payi", "dagitilan kar", "getiri oran", "kar payi oran"))
    has_paylasim = any(
        x in k for x in ("paylasim orani", "paylasim oran", "kar paylasim", "musteri payi")
    )
    if not (has_kar and has_paylasim):
        return False
    return any(
        x in k
        for x in (
            "fark",
            "ayni",
            "farkli",
            "karsilastir",
            "karsilastirma",
            "ile",
            "midir",
            "mıdır",
            "mu ",
            "mı ",
            "mi ",
            "ne demek",
            "nedir",
            "karistir",
            "karıştır",
        )
    )


def finansman_oran_listesi_mi(raw: str) -> bool:
    """Finansman kâr payı oranı listesi mi (taksit simülasyonu değil)?

    "Konut finansmanı kâr payı oranları" → True.
    "400.000 TL 48 ay konut finansmanı hesapla" → False.
    """
    k = _fold(raw)
    if katilma_oran_listesi_mi(raw):
        return False
    if any(i in k for i in _FINANSMAN_HESAPLAMA_ISARET):
        return False
    if not any(
        x in k
        for x in (
            "finansman",
            "konut finans",
            "tasit finans",
            "ihtiyac finans",
            "kredi",
        )
    ):
        return False
    return any(
        x in k
        for x in (
            "oranlari",
            "oranlar",
            "oran nedir",
            "oran ne",
            "kar payi oran",
            "kar payi",
            "en dusuk",
            "en yuksek",
            "hangi banka",
            "hangi bankada",
            "kac",
            "kaç",
            "liste",
        )
    ) or ("oran" in k and any(x in k for x in ("nedir", "neler", "ne ")))


def _filtrele_rate_type_adaylari(katlanmis: str, adaylar: list[str]) -> list[str]:
    """Alan bağlamına göre yanlış oran türü adaylarını eler."""
    if not adaylar:
        return adaylar
    k = katlanmis
    katilma = any(x in k for x in ("katilma", "katilim hesap", "standart katilma", "birikim"))
    finansman = any(
        x in k for x in ("finansman", "konut finans", "tasit finans", "ihtiyac finans", "kredi")
    )
    sonuc = list(adaylar)

    if finansman and not katilma:
        sonuc = [t for t in sonuc if t != "participation_yield"]

    if katilma and "participation_yield" in sonuc and "profit_sharing_ratio" in sonuc:
        if katilma_kar_payi_paylasim_karsilastirma_mi(k):
            return sonuc
        paylasim = any(
            x in k
            for x in (
                "paylasim orani",
                "paylasim oran",
                "musteri payi",
                "katilimci payi",
                "90/10",
                "98/2",
            )
        )
        getiri = any(
            x in k
            for x in (
                "getiri",
                "dagitilan",
                "yillik oran",
                "kar payi oran",
                "oranlari",
                "oranlar",
            )
        ) or katilma_oran_listesi_mi(k)
        if paylasim and not getiri:
            sonuc = [t for t in sonuc if t != "participation_yield"]
        elif getiri and not paylasim:
            sonuc = [t for t in sonuc if t != "profit_sharing_ratio"]

    return sonuc


def _fold(text: str | None) -> str:
    """Karşılaştırma için metni sadeleştirir (küçük harf + ASCII katlama).

    ⚠️ Yalnızca EŞLEŞTİRME için. Kanıt metni ham hâliyle saklanır; Türkçe
    karakterler kullanıcıya olduğu gibi gösterilir.
    """
    return ascii_fold_tr(lower_tr(normalize_text(text or "")))


def _kelime_var(hedef: str, aranan: str) -> bool:
    """Aranan ifadeyi kelime sınırına duyarlı arar.

    ⚠️ Sol sınır zorunlu, sağ sınır serbest. Türkçe ekler (-de, -da, -ler,
    'nin) sağda devam ediyor; sağ sınır da zorunlu tutulursa "markette"
    kelimesi "market" terimini bulmaz. `categorizer._kelime_var` ile aynı
    kural — davranış iki katmanda ayrışmasın.

    ⚠️ Kısa kökler (≤3 harf) sağ sınırı da ister. Aksi halde `mil` → `milyon`
    önek eşleşmesi `benefit=puan_mil` üretir ("1 milyon liralık araç…").
    """
    kalip = _fold(aranan)
    if not kalip:
        return False
    if len(kalip) <= 3:
        return re.search(rf"(?<![a-z0-9]){re.escape(kalip)}(?![a-z0-9])", hedef) is not None
    return re.search(rf"(?<![a-z0-9]){re.escape(kalip)}", hedef) is not None


def _karsilastirma_maskele(katlanmis: str) -> str:
    """Karşılaştırma işaretçilerini ve sayıları maskeler.

    BİR SİMGENİN İKİ ROLÜ OLAMAZ — ÖLÇÜLDÜ. Taksonomi sözlüğünde `altın`
    anahtar kelimesi var (sektör `yatirim_birikim`) ve eşleşme sağ sınır
    aramadığı için **"%2'nin altında"** ifadesindeki `altında` sözcüğüne
    uyuyor. Sonuç: "Kâr payı oranı %2'nin altında olan finansman kampanyaları"
    sorgusuna `sector=yatirim_birikim` süzgeci ekleniyor, o süzgeç 7 finansman
    kampanyasının tamamını eliyor ve yanıt **0 sonuç** oluyor. Veri setinde
    koşulu sağlayan 2 kampanya VAR; hata mesajı yok, yalnızca boş liste.

    Türkçede `altın`+`da` gerçekten geçerli bir çekimdir, bu yüzden ek denetimi
    sorunu çözmez. Çözüm rol ayrımı: bir sözcük karşılaştırma yönü olarak
    okunduysa, taksonomi eşleşmesine artık girmez.

    Maskeleme boşlukla yapılır; konumlar korunur, böylece sayısal kısıtların
    pencere hesapları etkilenmez.
    """
    maske = list(katlanmis)

    def sil(baslangic: int, bitis: int) -> None:
        for i in range(baslangic, min(bitis, len(maske))):
            maske[i] = " "

    for isaretci, _yon in COMPARISON_MARKERS:
        kalip = _fold(isaretci)
        if not kalip:
            continue
        baslangic = 0
        while True:
            yer = katlanmis.find(kalip, baslangic)
            if yer == -1:
                break
            sil(yer, yer + len(kalip))
            baslangic = yer + len(kalip)

    for eslesme in _SAYI_RE.finditer(katlanmis):
        sil(eslesme.start(), eslesme.end())

    return "".join(maske)


def _banka_kodlari(katlanmis: str) -> list[QuerySignal]:
    """Sorgudaki banka adlarını kodlara çevirir.

    ⚠️ Takma adlar UZUNDAN KISAYA denenir. "vakif katilim" ile "vakif" aynı
    bankaya işaret ediyor; kısa olan önce denenirse kanıt metni gereksiz
    kırpılır ve arayüzde "Vakıf" yazar, "Vakıf Katılım" yazmaz.
    """
    sonuc: list[QuerySignal] = []
    for kod, takma_adlar in BANK_ALIASES.items():
        for takma in sorted(takma_adlar, key=len, reverse=True):
            if _kelime_var(katlanmis, takma):
                sonuc.append(QuerySignal(kind="bank", value=kod, label="Banka", evidence=takma))
                break
    return sonuc


def _eksen_suzgecleri(katlanmis: str) -> list[QuerySignal]:
    """Taksonomi sözlüklerinden eksen süzgeçleri çıkarır."""
    sozlukler: dict[str, dict[str, tuple[str, ...]]] = {
        "product_type": PRODUCT_TYPE_KEYWORDS,
        "sector": SECTOR_KEYWORDS,
        "audience": AUDIENCE_KEYWORDS,
        "benefit": BENEFIT_KEYWORDS,
    }
    etiketler = {
        "product_type": "Ürün türü",
        "sector": "Sektör",
        "audience": "Hedef kitle",
        "benefit": "Fayda",
    }

    sonuc: list[QuerySignal] = []
    for eksen, sozluk in sozlukler.items():
        for deger, kelimeler in sozluk.items():
            # ⚠️ Eksende geçerli olmayan bir değer süzgece giremez; sözlük ile
            # denetimli kelime listesi ıraksarsa sessiz süzgeç hatası olur.
            if deger not in AXIS_VALUES.get(eksen, ()):
                continue
            # Bu eksende sorguda süzgeç üretmemesi gereken kelimeler
            # (bkz. `QUERY_EXCLUDED_KEYWORDS`).
            haric = QUERY_EXCLUDED_KEYWORDS.get(eksen, {}).get(deger, ())
            for kelime in sorted(kelimeler, key=len, reverse=True):
                if kelime in haric:
                    continue
                if _kelime_var(katlanmis, kelime):
                    sonuc.append(
                        QuerySignal(
                            kind=eksen, value=deger, label=etiketler[eksen], evidence=kelime
                        )
                    )
                    break

    # Yalnızca sorguda geçerli çıplak sözcükler — o eksende hiçbir özgül değer
    # eşleşmediyse devreye girer (bkz. `QUERY_ONLY_KEYWORDS` notu).
    eslesen_eksenler = {sinyal.kind for sinyal in sonuc}
    for eksen, sozluk_ek in QUERY_ONLY_KEYWORDS.items():
        if eksen in eslesen_eksenler:
            continue
        for deger, kelimeler in sozluk_ek.items():
            if deger not in AXIS_VALUES.get(eksen, ()):
                continue
            for kelime in sorted(kelimeler, key=len, reverse=True):
                if _kelime_var(katlanmis, kelime):
                    sonuc.append(
                        QuerySignal(
                            kind=eksen, value=deger, label=etiketler[eksen], evidence=kelime
                        )
                    )
                    break
    return sonuc


def _durumlar(katlanmis: str) -> list[QuerySignal]:
    """Sorgudaki kampanya durumu işaretçilerini okur."""
    etiketler = {
        "active": "Hâlâ geçerli",
        "expired": "Süresi dolmuş",
        "upcoming": "Başlayacak",
        "unknown": "Tarihi bilinmiyor",
    }
    sonuc: list[QuerySignal] = []
    for durum, isaretciler in STATUS_MARKERS.items():
        for isaretci in isaretciler:
            if isaretci in katlanmis:
                sonuc.append(
                    QuerySignal(
                        kind="status", value=durum, label=etiketler[durum], evidence=isaretci
                    )
                )
                break
    return sonuc


def _alan_bul(katlanmis: str, konum: int, yuzde_mi: bool | None) -> str | None:
    """Sayının hangi `campaign_metrics` alanına ait olduğunu bulur.

    Sayının solundaki ve sağındaki pencereye bakılır; işaretçi bulunamazsa
    `None` döner ve sayı süzgece ÇEVRİLMEZ.

    ⚠️ İŞARETÇİ KELİME SINIRINDA ARANIR, `find()` İLE DEĞİL — ÖLÇÜLDÜ.
    `find()` kullanıldığında `term_months_max` işaretçisi `"ay"`,
    **"kâr payı"** ifadesinin içindeki `p-ay-ı`'ya uyuyordu; "Hangi bankada en
    düşük kâr payı oranı var?" sorusu `profit_rate_pct` yerine
    `term_months_max` üzerinden yanıtlanıp **"en düşük kâr payı 1"** diyordu.
    Hata fırlatmıyor, yalnızca yanlış alanı raporluyordu. İşaretçiye baştan
    boşluk koymak da çözmüyor: `normalize_text()` baştaki boşluğu siliyor.

    ⚠️ Yüzde işareti taşıyan sayı tutar alanına yazılamaz, tutar alanına ait
    işaretçi taşıyan sayı da yüzde alanına yazılamaz. Sprint 2'de "%80"
    ifadesinin `amount_max` olarak kaydedildiği hata tam buradan doğmuştu.

    Args:
        katlanmis: Katlanmış sorgu metni.
        konum: Sayının (ya da toplama işaretçisinin) bittiği konum.
        yuzde_mi: `True` yalnızca oran alanları · `False` yalnızca tutar/adet
            alanları · `None` **ayrım yapma**. Toplama sorularında ("en düşük
            kâr payı") ortada sayı yoktur; yüzde ayrımı uygulanırsa doğru alan
            elenir.
    """
    sol = max(0, konum - MARKER_WINDOW)
    pencere = katlanmis[sol : konum + MARKER_WINDOW]

    en_iyi: str | None = None
    en_iyi_uzaklik = MARKER_WINDOW + 1
    for alan, isaretciler in NUMERIC_FIELD_MARKERS.items():
        if yuzde_mi is True and alan not in PERCENT_FIELDS:
            continue
        if yuzde_mi is False and alan in PERCENT_FIELDS:
            continue
        for isaretci in isaretciler:
            eslesme = re.search(rf"(?<![a-z0-9]){re.escape(_fold(isaretci))}", pencere)
            if eslesme is None:
                continue
            uzaklik = abs((sol + eslesme.start()) - konum)
            if uzaklik < en_iyi_uzaklik:
                en_iyi, en_iyi_uzaklik = alan, uzaklik
    return en_iyi


def _yon_bul(katlanmis: str, konum: int, uzunluk: int) -> str | None:
    """Sayının karşılaştırma yönünü bulur (`lte` / `gte`).

    ⚠️ Yön bulunamazsa `None` döner ve kısıt üretilmez. "%2 kâr payı" ifadesi
    bir kısıt değil, bir betimlemedir; onu `lte` saymak listeyi sessizce
    daraltır.
    """
    sag = katlanmis[konum + uzunluk : konum + uzunluk + MARKER_WINDOW]
    sol = katlanmis[max(0, konum - MARKER_WINDOW) : konum]

    for isaretci, yon in COMPARISON_MARKERS:
        katlanmis_isaretci = _fold(isaretci)
        if katlanmis_isaretci in sag or katlanmis_isaretci in sol:
            return yon
    return None


def _sayisal_kisitlar(katlanmis: str) -> list[NumericConstraint]:
    """Sorgudaki sayısal kısıtları çıkarır."""
    sonuc: list[NumericConstraint] = []
    for eslesme in _SAYI_RE.finditer(katlanmis):
        ham = eslesme.group(0)
        yuzde_mi = "%" in ham
        deger = parse_decimal_tr(ham.replace("%", "").strip())
        if deger is None:
            continue

        alan = _alan_bul(katlanmis, eslesme.start(), yuzde_mi)
        if alan is None:
            continue
        yon = _yon_bul(katlanmis, eslesme.start(), len(ham))
        if yon is None:
            continue

        sonuc.append(NumericConstraint(field=alan, op=yon, value=deger, evidence=ham.strip()))
    return sonuc


def _toplama(katlanmis: str) -> AggregateSpec | None:
    """Toplama niyetini ve hesaplanacak alanı belirler.

    ⚠️ İŞARETÇİYİ SAYI İZLİYORSA TOPLAMA DEĞİL KISITTIR. "en az 250 TL ödül
    veren kampanyalar" bir üstünlük sorusu değil, bir eşiktir; toplama sayılırsa
    kullanıcı 608 kampanyanın asgarisini görür ve kendi eşiğini hiç göremez.
    Aynı ifade ("en az") iki işi de yapabildiği için ayrım sayının varlığına
    bakılarak yapılır.
    """
    # ⚠️ SIRA ÖNEMLİ. "Kaç banka" ifadesi "kac" içerdiği için `count`
    # işaretçilerinden ÖNCE denenir; yoksa banka sayımı kampanya sayımına
    # dönüşür ve 7 yerine 482 yanıtı verilir.
    # ⚠️ SIRA: en BELİRLEYİCİ soru önce. Bir testin yakaladığı hatam: liste
    # sorusu başa alınınca "hangi bankalarDA katılma hesabı YOK" da liste
    # sorusuna dönüşüyordu — çünkü "hangi bankalar" eki tutuyor. Yokluk
    # sorusu daha belirleyicidir (olumsuzlama + banka bağlamı ister), o yüzden
    # önce denenir.
    olumsuz = any(_kelime_var(katlanmis, m) for m in ABSENCE_MARKERS)
    banka_baglami = any(_kelime_var(katlanmis, k) for k in ("banka", "kurum"))

    # Yokluk sorusu: "hangi bankada ... yok". Banka bağlamı ŞARTTIR — "tahsis
    # ücreti olmayan ürünler" bir yokluk sorusu DEĞİL, süzgeçli aramadır.
    # Bağlam koşulu olmasa her olumsuzlama banka yokluk sorusuna dönüşürdü.
    if olumsuz and banka_baglami:
        return AggregateSpec(kind="absence")

    if any(_kelime_var(katlanmis, m) for m in BANK_COUNT_MARKERS):
        return AggregateSpec(kind="count_banks")

    # Liste sorusu: kapsamı sorar, içerik süzgeci taşımaz. Olumsuzlama varsa
    # yukarıdaki yokluk dalı çalışmış olur.
    if any(_kelime_var(katlanmis, m) for m in BANK_ROSTER_MARKERS):
        return AggregateSpec(kind="bank_roster")

    for isaretci in COUNT_MARKERS:
        if isaretci in katlanmis:
            return AggregateSpec(kind="count")

    for isaretci, yon in AGGREGATE_MARKERS.items():
        yer = katlanmis.find(isaretci)
        if yer == -1:
            continue
        if _SAYI_RE.match(katlanmis[yer + len(isaretci) :].lstrip()):
            continue
        # ⚠️ "En düşük NE?" sorusunun alanı belirtilmemişse toplama yapılamaz;
        # rastgele bir alan seçmek uydurma cevap üretir.
        # ⚠️ `yuzde_mi=None`: toplama sorusunda sayı yoktur, bu yüzden
        # oran/tutar ayrımı yapılamaz ve yapılmamalıdır.
        alan = _alan_bul(katlanmis, yer + len(isaretci), yuzde_mi=None)
        if alan is None:
            continue
        return AggregateSpec(kind="extremum", field=alan, direction=yon)
    return None


def _serbest_terimler(katlanmis: str, kullanilan: set[str]) -> tuple[str, ...]:
    """Süzgece dönüşmemiş anlamlı sözcükleri döndürür.

    Bu sözcükler BM25 ve gömme kanallarına gider. Süzgece dönüşen sözcükler de
    ATILMAZ — marka adı hem sektör süzgeci hem arama terimi olabilir; yalnızca
    durak sözcükler ve tek harfli parçalar düşer.
    """
    terimler: list[str] = []
    for kelime in _KELIME_RE.findall(katlanmis):
        if len(kelime) < 3 or kelime in STOPWORDS or kelime.isdigit():
            continue
        if kelime in terimler:
            continue
        terimler.append(kelime)
    _ = kullanilan
    return tuple(terimler)


def _konvansiyonel_normalize(katlanmis: str) -> str:
    """Sorgudaki konvansiyonel terimleri katılım eşdeğerine çevirir (arama için)."""
    sonuc = katlanmis
    for eski, yeni in sorted(CONVENTIONAL_QUERY_MAP, key=lambda ikili: -len(ikili[0])):
        if eski in sonuc:
            sonuc = sonuc.replace(eski, yeni)
    return sonuc


def _rate_type_adaylari(katlanmis: str) -> list[str]:
    """Sorgudan olası rate_type adaylarını çıkarır (uzun işaretçi önce)."""
    adaylar: list[str] = []
    for tur, isaretciler in RATE_TYPE_MARKERS.items():
        for isaretci in sorted(isaretciler, key=len, reverse=True):
            # ⚠️ "getirir misin" → participation_yield YANLIŞ EŞLEŞMESİ.
            # "getiri" kökü fiil ekleriyle biter; yalnızca bağımsız sözcük say.
            if isaretci == "getiri":
                eslesme = re.search(r"(?<![a-z0-9])getiri(?![a-z])", katlanmis) is not None
            else:
                eslesme = _kelime_var(katlanmis, isaretci) or isaretci in katlanmis
            if eslesme:
                if tur not in adaylar:
                    adaylar.append(tur)
                break
    return adaylar


def _tanim_mi(katlanmis: str, *, olgusal: bool = False) -> bool:
    """Tanım sorusu mu?

    ⚠️ "nedir" TEK BAŞINA tanım sorusu göstergesi DEĞİLDİR. Türkçede olgusal
    sorular da "nedir" ile biter: "Kuveyt Türk'te aylık TL katılma hesabının
    kâr payı oranı nedir?" bir tanım sorusu değildir.

    Ölçüldü (100 soruluk gerçek test havuzu): yalnızca işaretçiye bakan eski
    kural 49 soruyu tanım sayıyordu; bunların **42'si yanlıştı** ve 16'sı
    kullanıcıya "sözlükte tanım bulunamadı" yanıtı döndürüyordu — oysa yanıt
    kampanya/ürün gövdesinde vardı.

    `olgusal=True` (banka adı ya da sayısal kısıt var) olduğunda soru olgusal
    kabul edilir; yanlış sınıflama 42 → 3'e düştü. Tanım yine kaybolmaz:
    işaretçi varsa sözlük terimi yanıta ZENGİNLEŞTİRME olarak eklenir
    (bkz. `chat_service`, `glossary` alanı).
    """
    if olgusal:
        return False
    return any(isaretci in katlanmis for isaretci in DEFINITION_MARKERS)


_LIMIT_SORU_ISARETCILERI: Final[tuple[str, ...]] = (
    "bddk",
    "ltv",
    "azami finansman",
    "azami oran",
    "azami vade",
    "azami tutar",
    "finansman limiti",
    "finansman limitleri",
    "kredi limiti",
)


def _limit_sorusu_mu(katlanmis: str) -> bool:
    """BDDK / finansman limiti sorusu mu? Tanım niyetine düşmemeli."""
    if any(isaretci in katlanmis for isaretci in _LIMIT_SORU_ISARETCILERI):
        return True
    # "limit/limitler/limitini/limitlerini…" kökü.
    return bool(
        re.search(r"(?<![a-z0-9])limit", katlanmis)
        and any(
            _kelime_var(katlanmis, k)
            for k in ("finansman", "tasit", "konut", "ihtiyac", "arac", "kredi", "vade")
        )
    )


def _sohbet_mi(katlanmis: str, *, finansal: bool) -> bool:
    """Kısa selam/teşekkür/kimsin — finansal sinyal yoksa sohbet.

    Belirteç sayısı ≤6; aksi halde 'merhaba, katılma hesabı açacağım' sohbete düşmez.
    """
    if finansal:
        return False
    belirtecler = [k for k in _KELIME_RE.findall(katlanmis) if k]
    if len(belirtecler) > 6:
        return False
    return any(kalip in katlanmis for kalip in _SOHBET_KALIPLARI)


def _tanim_terimi(raw: str, katlanmis: str) -> str | None:
    """Tanım sorusundan terim parçasını çıkarır."""
    temiz = katlanmis
    for isaretci in DEFINITION_MARKERS:
        temiz = temiz.replace(isaretci, " ")
    for sw in ("bir", "bu", "su", "mi", "mu", "midir", "mudur", "nedir"):
        temiz = re.sub(rf"(?<![a-z0-9]){sw}(?![a-z0-9])", " ", temiz)
    # "X nedir, Y'den farkı ne?" → yalnızca X kısmı.
    if "fark" in temiz:
        for ayirici in (",", " ile ", " ve "):
            if ayirici in temiz:
                on = temiz.split(ayirici, 1)[0].strip()
                if on:
                    temiz = on
                    break
        temiz = re.split(r"\s+normal\s+", temiz, maxsplit=1)[0].strip()
    terim = " ".join(temiz.split()).strip(" ?¿.,;:!")
    if terim:
        return terim
    return raw.strip(" ?¿.,;:!") or None


def _finansal_sinyal_var(
    katlanmis: str,
    *,
    banka: bool,
    eksen: bool,
    kisit: bool,
    durum: bool,
    toplama: bool,
) -> bool:
    """Kapsam içi sinyal var mı? (beyaz liste)"""
    if banka or eksen or kisit or durum or toplama:
        return True
    if any(isaretci in katlanmis for isaretci in COMPARE_MARKERS):
        return True
    if any(isaretci in katlanmis for isaretci in DEFINITION_MARKERS):
        return True
    if _rate_type_adaylari(katlanmis):
        return True
    # Kampanya / bankacılık anahtarları.
    for kelime in (
        "kampanya",
        "banka",
        "finansman",
        "kar payi",
        "oran",
        "vade",
        "taksit",
        "katilma",
        "katilim",
        "hesap",
        "tahsis",
        "faiz",
        "kredi",
        "mevduat",
        "iade",
        "indirim",
        "odul",
        "masraf",
        "kart",
    ):
        if _kelime_var(katlanmis, kelime) or kelime in katlanmis:
            return True
    return False


def _kapsam_disi_mi(katlanmis: str, *, finansal: bool) -> bool:
    """Açıkça yabancı alan ve finansal sinyal yoksa kapsam dışı."""
    if finansal:
        return False
    return any(isaretci in katlanmis for isaretci in OUT_OF_DOMAIN_MARKERS)


def _tekil_urun_sorusu(
    katlanmis: str,
    *,
    banka_sayisi: int,
    axis_filters: dict[str, tuple[str, ...]],
    rate_adaylar: list[str],
) -> bool:
    """Tek banka + ürün/oran sinyali → tekil_sorgu.

    ⚠️ 'kampanya' geçiyorsa kampanya aramasında kalır (TROY kart kampanyası).
    """
    if banka_sayisi != 1:
        return False
    if "kampanya" in katlanmis:
        return False
    if rate_adaylar:
        return True
    if any(ipucu in katlanmis for ipucu in ("orani", "oranlar", "ne kadar")):
        return True
    # Konut/taşıt/ihtiyaç finansmanı ürün soruları.
    urun = axis_filters.get("product_type", ())
    return any("finansman" in deger for deger in urun)


def parse_query(raw: str) -> QueryPlan:
    """Türkçe sorguyu yapısal bir sorgu planına çevirir.

    Args:
        raw: Kullanıcının yazdığı soru.

    Returns:
        Süzgeçler, niyet, serbest arama terimleri ve her süzgecin kanıtı.
        Hiçbir sinyal bulunamazsa süzgeçsiz `search` planı döner — sorgu
        REDDEDİLMEZ (kapsam dışı hariç; o ayrı niyettir).
    """
    katlanmis = _konvansiyonel_normalize(_fold(raw))

    banka_sinyalleri = _banka_kodlari(katlanmis)
    # ⚠️ Taksonomi eşleşmesi MASKELENMİŞ metin üzerinde yapılır: karşılaştırma
    # işaretçileri ve sayılar çıkarılır (bkz. `_karsilastirma_maskele`).
    eksen_sinyalleri = _eksen_suzgecleri(_karsilastirma_maskele(katlanmis))
    durum_sinyalleri = _durumlar(katlanmis)
    kisitlar = _sayisal_kisitlar(katlanmis)
    toplama = _toplama(katlanmis)
    rate_adaylar = _filtrele_rate_type_adaylari(katlanmis, _rate_type_adaylari(katlanmis))
    rate_type = rate_adaylar[0] if len(rate_adaylar) == 1 else None

    axis_filters: dict[str, tuple[str, ...]] = {}
    for sinyal in eksen_sinyalleri:
        mevcut = axis_filters.get(sinyal.kind, ())
        if sinyal.value not in mevcut:
            axis_filters[sinyal.kind] = (*mevcut, sinyal.value)

    sinyaller = [*banka_sinyalleri, *eksen_sinyalleri, *durum_sinyalleri]
    sinyaller.extend(
        QuerySignal(
            kind="numeric",
            value=f"{kisit.field}:{kisit.op}:{kisit.value}",
            label=_KISIT_ETIKETLERI.get(kisit.field, kisit.field),
            evidence=kisit.evidence,
        )
        for kisit in kisitlar
    )
    if rate_type:
        sinyaller.append(
            QuerySignal(
                kind="rate_type",
                value=rate_type,
                label="Oran türü",
                evidence=rate_type,
            )
        )

    # Özgül ürün türü varken genel `finansman` yedeği düşer (çıplak sözcük kuralı).
    if "product_type" in axis_filters:
        degerler = axis_filters["product_type"]
        ozgul = tuple(d for d in degerler if d != "finansman")
        if ozgul and "finansman" in degerler:
            axis_filters["product_type"] = ozgul
            sinyaller = [
                s for s in sinyaller if not (s.kind == "product_type" and s.value == "finansman")
            ]

    glossary_term: str | None = None
    finansal = _finansal_sinyal_var(
        katlanmis,
        banka=bool(banka_sinyalleri),
        eksen=bool(eksen_sinyalleri),
        kisit=bool(kisitlar),
        durum=bool(durum_sinyalleri),
        toplama=toplama is not None,
    )
    # Banka adı, sayısal kısıt veya BDDK/limit sorusu olgusaldır; "nedir"
    # eki tanım niyetine yetmez ("taşıt finansmanında limitler nedir").
    olgusal_sinyal = bool(banka_sinyalleri or kisitlar or _limit_sorusu_mu(katlanmis))
    if _tanim_mi(katlanmis, olgusal=olgusal_sinyal):
        niyet = "tanim"
        glossary_term = _tanim_terimi(raw, katlanmis)
    elif _sohbet_mi(katlanmis, finansal=finansal):
        niyet = "sohbet"
    elif _kapsam_disi_mi(katlanmis, finansal=finansal):
        niyet = "kapsam_disi"
    elif toplama is not None:
        niyet = "aggregate"
    elif len(banka_sinyalleri) > 1 and (
        _banka_karsilastirma_mi(katlanmis, len(banka_sinyalleri))
        or any(isaretci in katlanmis for isaretci in COMPARE_MARKERS)
    ):
        niyet = "compare"
    elif _tekil_urun_sorusu(
        katlanmis,
        banka_sayisi=len(banka_sinyalleri),
        axis_filters=axis_filters,
        rate_adaylar=rate_adaylar,
    ):
        niyet = "tekil_sorgu"
    else:
        niyet = "search"

    karar = score_domains(
        katlanmis,
        intent=niyet,
        rate_type=rate_type,
        axis_filters=axis_filters,
    )

    return QueryPlan(
        raw=raw.strip(),
        intent=niyet,
        bank_codes=tuple(s.value for s in banka_sinyalleri),
        axis_filters=axis_filters,
        numeric=tuple(kisitlar),
        statuses=tuple(s.value for s in durum_sinyalleri),
        free_terms=_serbest_terimler(katlanmis, set()),
        aggregate=toplama,
        signals=tuple(sinyaller),
        rate_type=rate_type,
        rate_type_candidates=tuple(rate_adaylar),
        glossary_term=glossary_term,
        source_domain=karar.domain,
        domain_confidence=karar.confidence,
        domain_ambiguous=karar.is_ambiguous,
        domain_scores=tuple(sorted(karar.scores.items())),
        domain_runner_up=karar.runner_up,
    )


# Sayısal kısıtların arayüzde görünecek adları.
_KISIT_ETIKETLERI: Final[dict[str, str]] = {
    "profit_rate_pct": "Kâr payı oranı",
    "term_months_max": "Vade",
    "installment_count": "Taksit",
    "reward_amount_try": "Ödül",
    "min_spend_try": "Asgari harcama",
    "financing_amount_max": "Finansman tutarı",
    "cashback_pct": "Nakit iade",
    "discount_pct": "İndirim",
    "max_total_benefit_try": "Azami toplam fayda",
}


def merge_with_previous(plan: QueryPlan, previous: QueryPlan | None) -> QueryPlan:
    """Yeni sorguda banka/ürün/oran türü yoksa önceki turdan devral.

    Devralınan her süzgeç `signals` içinde `evidence=\"önceki soru\"` ile işaretlenir;
    arayüz yanlış devralmayı gösterip kaldırabilir.
    """
    if previous is None:
        return plan
    # Sohbet / tanım / kapsam dışı — bağlam taşıma.
    if plan.intent in {"sohbet", "tanim", "kapsam_disi"}:
        return plan

    from app.retrieval.relevance import (
        is_anaphoric_query,
        is_follow_up_query,
        opens_scope,
    )

    takip = is_follow_up_query(plan.raw)
    anafora = is_anaphoric_query(plan.raw)
    kapsam_acildi = opens_scope(plan.raw)

    # Bağlam devri KANITA bağlıdır, süzgecin yokluğuna değil.
    #
    # Ölçüldü (5 senaryonun 4'ü yanlıştı): yeni soru kendi konusunu getirdiği
    # hâlde banka/eksen süzgeci taşınıyordu. "Kuveyt Türk alışveriş puanı" →
    # "taşıt finansmanında en uzun vade hangi bankada" sorusu Kuveyt Türk'e
    # kilitleniyor, kullanıcı bankalar arası sorduğu hâlde tek banka yanıtı
    # dönüyordu. Sessiz hata: yanıt biçimsel olarak geçerli, içerik yanlış.
    #
    # Kural: sorgu kendi ekseni/oranı/toplamasıyla ayakta durabiliyorsa ve
    # önceki tura açık atıf yapmıyorsa, hiçbir şey devralınmaz.
    kendi_konusu = bool(
        plan.axis_filters
        or plan.rate_type
        or plan.rate_type_candidates
        or plan.aggregate
        or plan.glossary_term
        or plan.numeric
    )
    if kendi_konusu and not anafora:
        return plan

    bank_codes = plan.bank_codes
    axis_filters = dict(plan.axis_filters)
    rate_type = plan.rate_type
    rate_candidates = plan.rate_type_candidates
    free_terms = plan.free_terms
    sinyaller = list(plan.signals)
    degisti = False

    # `takip` burada ETKİSİZ: iç koşul `not bank_codes` doğru olduğunda dış
    # koşulun ilk terimi zaten doğrudur. Ölü dal kaldırıldı.
    if not bank_codes and previous.bank_codes and not kapsam_acildi:
        bank_codes = previous.bank_codes
        degisti = True
        for kod in bank_codes:
            sinyaller.append(
                QuerySignal(
                    kind="bank",
                    value=kod,
                    label="Banka",
                    evidence="önceki soru",
                )
            )

    if (not axis_filters or takip) and previous.axis_filters:
        if not axis_filters:
            axis_filters = dict(previous.axis_filters)
            degisti = True
            for eksen, degerler in axis_filters.items():
                for deger in degerler:
                    sinyaller.append(
                        QuerySignal(
                            kind=eksen,
                            value=deger,
                            label=eksen,
                            evidence="önceki soru",
                        )
                    )
        elif takip:
            # Takip sorusunda eksik eksenleri tamamla.
            for eksen, degerler in previous.axis_filters.items():
                if eksen not in axis_filters:
                    axis_filters[eksen] = degerler
                    degisti = True
                    for deger in degerler:
                        sinyaller.append(
                            QuerySignal(
                                kind=eksen,
                                value=deger,
                                label=eksen,
                                evidence="önceki soru",
                            )
                        )

    if rate_type is None and not rate_candidates and previous.rate_type:
        rate_type = previous.rate_type
        rate_candidates = (previous.rate_type,)
        degisti = True
        sinyaller.append(
            QuerySignal(
                kind="rate_type",
                value=rate_type,
                label="Oran türü",
                evidence="önceki soru",
            )
        )

    if takip and previous.free_terms:
        birlesik = list(dict.fromkeys([*previous.free_terms, *free_terms]))
        if tuple(birlesik) != free_terms:
            free_terms = tuple(birlesik)
            degisti = True

    if not degisti:
        return plan

    karar = score_domains(
        _konvansiyonel_normalize(_fold(plan.raw)),
        intent=plan.intent,
        rate_type=rate_type,
        axis_filters=axis_filters,
    )
    return QueryPlan(
        raw=plan.raw,
        intent=plan.intent,
        bank_codes=bank_codes,
        axis_filters=axis_filters,
        numeric=plan.numeric,
        statuses=plan.statuses,
        free_terms=free_terms,
        aggregate=plan.aggregate,
        signals=tuple(sinyaller),
        rate_type=rate_type,
        rate_type_candidates=rate_candidates,
        glossary_term=plan.glossary_term,
        source_domain=karar.domain,
        domain_confidence=karar.confidence,
        domain_ambiguous=karar.is_ambiguous,
        domain_scores=tuple(sorted(karar.scores.items())),
        domain_runner_up=karar.runner_up,
        focus_campaign_id=plan.focus_campaign_id,
    )


def has_definition_marker(raw: str) -> bool:
    """Sorguda tanım işaretçisi ("nedir", "ne demek") var mı?

    Niyet KARARI vermez — olgusal soruya sözlük tanımını ZENGİNLEŞTİRME olarak
    eklemek için kullanılır. "Karz-ı hasen nedir? Dünya Katılım'da böyle bir
    ürün var mı?" sorusu hem tanım hem olgu ister; niyet olgusal olur ama
    tanım kaybolmaz.
    """
    return any(isaretci in _konvansiyonel_normalize(_fold(raw)) for isaretci in DEFINITION_MARKERS)


__all__ = [
    "BANK_ALIASES",
    "AggregateSpec",
    "NumericConstraint",
    "QueryPlan",
    "QuerySignal",
    "finansman_oran_listesi_mi",
    "has_definition_marker",
    "karsilastirma_konusu_belirsiz",
    "katilma_kar_payi_paylasim_karsilastirma_mi",
    "katilma_oran_listesi_mi",
    "merge_with_previous",
    "parse_katilma_vadeler",
    "parse_katilma_varyant",
    "parse_query",
    "resolve_source_domain",
]
