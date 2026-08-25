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
COMPARE_MARKERS: Final[tuple[str, ...]] = ("karsilastir", "kiyasla", "hangisi daha", " ile ")

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
    # Katibim: birincil kaynak alanı.
    source_domain: str = "kampanya"

    @property
    def has_filters(self) -> bool:
        """Herhangi bir yapısal süzgeç çıkarıldı mı?"""
        return bool(self.bank_codes or self.axis_filters or self.numeric or self.statuses)


# Kaynak alanı sinyalleri (LLM'siz).
_KAMPANYA_SINYAL: Final[tuple[str, ...]] = (
    "kampanya",
    "kampanyalar",
    "kart",
    "nakit iade",
    "nakit iadesi",
    "cashback",
    "mil",
    "puan",
    "hediye",
    "indirim",
    "bonus",
)
_FINANSMAN_SINYAL: Final[tuple[str, ...]] = (
    "finansman",
    "konut",
    "tasit",
    "ihtiyac",
    "murabaha",
    "ltv",
)
_KATILMA_SINYAL: Final[tuple[str, ...]] = (
    "katilma",
    "katilim hesabi",
    "katilim hesab",
    "standart katilma",
    "standart katilim",
    "getiri",
    "kar paylasim",
    "kar paylasimi",
    "dagitilan kar",
)

# Katılma vadesi — uzun kalıp önce (3 aylık, "aylık"tan önce).
_KATILMA_VADE: Final[tuple[tuple[tuple[str, ...], int], ...]] = (
    (("3 aylik", "3 ay", "uc aylik"), 3),
    (("6 aylik", "6 ay", "alti aylik"), 6),
    (("yillik", "12 ay", "1 yil", "bir yil"), 12),
    (("aylik", "1 ay", "bir aylik"), 1),
)


def resolve_source_domain(
    katlanmis: str,
    *,
    intent: str,
    rate_type: str | None,
    axis_filters: dict[str, tuple[str, ...]],
) -> str:
    """Sorgu için birincil kaynak alanını seçer.

    Returns:
        kampanya | finansman | katilma | tanim | kapsam_disi
    """
    if intent == "kapsam_disi":
        return "kapsam_disi"
    if intent == "sohbet":
        return "sohbet"
    if intent == "tanim":
        return "tanim"

    if rate_type == "participation_yield" or rate_type == "profit_sharing_ratio":
        return "katilma"
    if rate_type == "financing_rate":
        return "finansman"

    if any(s in katlanmis for s in _KATILMA_SINYAL):
        return "katilma"
    if any(s in katlanmis for s in _FINANSMAN_SINYAL):
        return "finansman"
    if any(s in katlanmis for s in _KAMPANYA_SINYAL):
        return "kampanya"

    urun = axis_filters.get("product_type", ())
    if any("finansman" in d or d in {"kart"} for d in urun):
        if any("birikim" in d or "katilma" in d for d in urun):
            return "katilma"
        if "kart" in urun and not any("finansman" in d for d in urun):
            return "kampanya"
        return "finansman"

    # Finansal sinyal yoksa search bile kampanya varsayılanı (serbest RAG).
    return "kampanya"


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
    """
    return re.search(rf"(?<![a-z0-9]){re.escape(_fold(aranan))}", hedef) is not None


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
            for kelime in sorted(kelimeler, key=len, reverse=True):
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
            if _kelime_var(katlanmis, isaretci) or isaretci in katlanmis:
                if tur not in adaylar:
                    adaylar.append(tur)
                break
    return adaylar


def _tanim_mi(katlanmis: str) -> bool:
    """Tanım sorusu mu?"""
    return any(isaretci in katlanmis for isaretci in DEFINITION_MARKERS)


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
    rate_adaylar = _rate_type_adaylari(katlanmis)
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
    if _tanim_mi(katlanmis):
        niyet = "tanim"
        glossary_term = _tanim_terimi(raw, katlanmis)
    elif _sohbet_mi(katlanmis, finansal=finansal):
        niyet = "sohbet"
    elif _kapsam_disi_mi(katlanmis, finansal=finansal):
        niyet = "kapsam_disi"
    elif toplama is not None:
        niyet = "aggregate"
    elif any(isaretci in katlanmis for isaretci in COMPARE_MARKERS) and len(banka_sinyalleri) > 1:
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

    source_domain = resolve_source_domain(
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
        source_domain=source_domain,
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

    if (not bank_codes or takip) and previous.bank_codes and not kapsam_acildi:
        if not bank_codes:
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

    source_domain = resolve_source_domain(
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
        source_domain=source_domain,
    )


__all__ = [
    "BANK_ALIASES",
    "AggregateSpec",
    "NumericConstraint",
    "QueryPlan",
    "QuerySignal",
    "merge_with_previous",
    "parse_katilma_vadeler",
    "parse_katilma_varyant",
    "parse_query",
    "resolve_source_domain",
]
