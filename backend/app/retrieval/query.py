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

    @property
    def has_filters(self) -> bool:
        """Herhangi bir yapısal süzgeç çıkarıldı mı?"""
        return bool(self.bank_codes or self.axis_filters or self.numeric or self.statuses)


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


def parse_query(raw: str) -> QueryPlan:
    """Türkçe sorguyu yapısal bir sorgu planına çevirir.

    Args:
        raw: Kullanıcının yazdığı soru.

    Returns:
        Süzgeçler, niyet, serbest arama terimleri ve her süzgecin kanıtı.
        Hiçbir sinyal bulunamazsa süzgeçsiz `search` planı döner — sorgu
        REDDEDİLMEZ.
    """
    katlanmis = _fold(raw)

    banka_sinyalleri = _banka_kodlari(katlanmis)
    # ⚠️ Taksonomi eşleşmesi MASKELENMİŞ metin üzerinde yapılır: karşılaştırma
    # işaretçileri ve sayılar çıkarılır (bkz. `_karsilastirma_maskele`).
    eksen_sinyalleri = _eksen_suzgecleri(_karsilastirma_maskele(katlanmis))
    durum_sinyalleri = _durumlar(katlanmis)
    kisitlar = _sayisal_kisitlar(katlanmis)
    toplama = _toplama(katlanmis)

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

    if toplama is not None:
        niyet = "aggregate"
    elif any(isaretci in katlanmis for isaretci in COMPARE_MARKERS) and len(banka_sinyalleri) > 1:
        niyet = "compare"
    else:
        niyet = "search"

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
