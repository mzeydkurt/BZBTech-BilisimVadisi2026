"""Kontrollü sözlükler — ürün varyantları ve oran kaynakları.

NEDEN KONTROLLÜ SÖZLÜK: Kâr payı oranı yalnızca tutar ve vadeye bağlı değil,
ürünün ALT TÜRÜNE de bağlı. Bir bankanın "sıfır araç" oranıyla başka bankanın
"2. el araç" oranını karşılaştırmak yanlış sonuç üretir. Varyant boyutu serbest
metin bırakılırsa aynı kavram on farklı biçimde yazılır ("0 km", "Sıfır Araç",
"sifir-arac") ve karşılaştırma sessizce bozulur.

Bu yüzden iki alan AYRI tutulur:
  - `variant_label` — kaynaktaki insan okunur etiket, BİREBİR saklanır
  - `variant_key`   — buradaki kanonik anahtar, karşılaştırma bunun üzerinden yapılır

Eşleme kuralları `docs/variant_mapping.md`'de belgelenir.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

# ── Ürün varyant boyutları ────────────────────────────────
#
# Boyut (dimension) → o boyuttaki kanonik varyant anahtarları.
# Bir ürün birden fazla boyutta varyantlanabilir: "2. el konut" (konut_durumu)
# + "enerji sınıfı B" (enerji_sinifi) ayrı iki kırılımdır.
VARIANT_VOCAB: Final[dict[str, tuple[str, ...]]] = {
    "arac_durumu": (
        "sifir_arac",
        "ikinci_el_arac",
        "ticari_arac",
        "elektrikli_arac",
        "hibrit_arac",
    ),
    "konut_durumu": (
        "sifir_konut",
        "ikinci_el_konut",
        "kentsel_donusum",
        "tamamlayici_konut",
        "arsa",
        "isyeri",
        "toki",
    ),
    "enerji_sinifi": (
        "enerji_a",
        "enerji_b",
        "enerji_diger",
    ),
    "sigorta": (
        "sigortali",
        "sigortasiz",
    ),
    "musteri_tipi": (
        "standart",
        "maas_musterisi",
        "kamu_calisani",
        "banka_calisani",
        "yeni_musteri",
        "esnaf",
        "ciftci",
    ),
    "ozel": (
        "karz_i_hasen",
        "cevre_dostu",
        "surdurulebilirlik",
    ),
}

# Tüm boyut adları.
VARIANT_DIMENSIONS: Final[tuple[str, ...]] = tuple(VARIANT_VOCAB)

# Tüm kanonik varyant anahtarları (boyuttan bağımsız arama için).
VARIANT_KEYS: Final[frozenset[str]] = frozenset(
    key for keys in VARIANT_VOCAB.values() for key in keys
)

# Varyantın hangi kanıttan çıkarıldığı. Bir hesaplayıcı dropdown'ından okunan
# varyant, metinden tahmin edilenden daha güvenilirdir.
VARIANT_SOURCES: Final[tuple[str, ...]] = (
    "dropdown_option",
    "separate_page",
    "table_column",
    "text",
)

# Tutar/vade limitinin nereden çıkarıldığı. HTML attribute (slider min/max)
# en güvenilir kaynaktır; metinden çıkarım en zayıfıdır.
LIMIT_SOURCES: Final[tuple[str, ...]] = (
    "html_attr",
    "html_table",
    "text",
    "calculator",
    "none",
)

# Teminat türü.
COLLATERAL_TYPES: Final[tuple[str, ...]] = ("konut", "tasit", "yok", "diger")


# ── Oran kaynağı ve güven sıralaması ──────────────────────
#
# Her oranın nereden geldiği kayıt altına alınır: bankacılıkta kaynaksız veri
# kabul edilemez. `confidence` değerleri karşılaştırma motorunda (SPRINT 4)
# hangi oranın birincil sayılacağını belirler.
RATE_SOURCES: Final[tuple[str, ...]] = (
    "html_table",
    "payment_plan_derived",
    "calculator_api",
    "calculator_playwright",
    "text",
    "js_default",
    "none",
)

RATE_SOURCE_CONFIDENCE: Final[dict[str, Decimal]] = {
    "html_table": Decimal("1.000"),
    "payment_plan_derived": Decimal("0.950"),
    "calculator_api": Decimal("0.850"),
    "calculator_playwright": Decimal("0.800"),
    "text": Decimal("0.750"),
    "js_default": Decimal("0.500"),
    "none": Decimal("0.000"),
}

# JS bundle'ındaki varsayılan sabit, bankanın gerçekten uyguladığı oran DEĞİLDİR;
# çoğu zaman geliştiricinin bıraktığı örnek değerdir. Kaydedilir ama
# karşılaştırmaya SOKULMAZ.
RATE_SOURCES_NOT_COMPARABLE: Final[frozenset[str]] = frozenset({"js_default", "none"})


# ── ORAN TÜRÜ — SPRINT 2.5'İN EN KRİTİK AYRIMI ────────────
#
# ⚠️ "KÂR PAYI" ÜÇ FARKLI ŞEY DEMEK. Aynı kolona yazılırlarsa karşılaştırma
# elma ile armudu sıralar ve hata SESSİZ olur:
#
#   profit_sharing_ratio  bölüşüm oranı   "90/10" · "98/2"   → investor/bank_share_pct
#   participation_yield   katılma getirisi "%31,22"          → profit_rate_pct
#   financing_rate        finansman maliyeti "%4,15"          → profit_rate_pct
#
# Aynı bankanın aynı ürününde İKİSİ DE olabilir ve ikisi de doğrudur:
# katılma hesabının hem bölüşüm oranı (90/10) hem getirisi (%31,22) yayımlanır.
#
# ⚠️ Türkiye Finans'ta iki sayfanın adı TEK HARF farklı:
#     Kar-Payi-Oranlari.aspx     → participation_yield
#     Kar-Paylasim-Oranlari.aspx → profit_sharing_ratio
# Karıştırılırsa fark edilmez.
RATE_TYPES: Final[tuple[str, ...]] = (
    "financing_rate",
    "participation_yield",
    "profit_sharing_ratio",
)

# ⚠️ FARKLI TÜRLER ASLA AYNI SIRALAMAYA GİRMEZ. Karşılaştırma ucu
# `rate_type` parametresini ZORUNLU tutar; varsayılan seçmez.
RATE_TYPE_COMPARABLE_FIELD: Final[dict[str, str]] = {
    "financing_rate": "profit_rate_pct",
    "participation_yield": "profit_rate_pct",
    "profit_sharing_ratio": "investor_share_pct",
}

# Para birimi. ⚠️ XAU/XAG'de tutar alanları GRAM cinsindendir, TL değil.
CURRENCIES: Final[tuple[str, ...]] = ("TRY", "USD", "EUR", "XAU", "XAG")

# Katılma hesabı kademesi — banka müşteriyi bakiyeye göre kademeliyor ve
# paylaşım oranı kademeye göre değişiyor.
ACCOUNT_TIERS: Final[tuple[str, ...]] = ("klasik", "gumus", "altin", "platin", "platin_plus")

CUSTOMER_TYPES: Final[tuple[str, ...]] = ("gercek_kisi", "tuzel_kisi")

# Limit matrisi satırının nereden okunduğu.
LIMIT_EXTRACTION_METHODS: Final[tuple[str, ...]] = ("html_table", "pdf_table", "text")


def rate_confidence(rate_source: str) -> Decimal:
    """Oran kaynağının güven katsayısını döndürür.

    Args:
        rate_source: `RATE_SOURCES` içindeki bir değer.

    Returns:
        0 ile 1 arasında güven katsayısı; bilinmeyen kaynak için 0.

    """
    return RATE_SOURCE_CONFIDENCE.get(rate_source, Decimal("0.000"))


def is_comparable(rate_source: str) -> bool:
    """Bu kaynaktan gelen oranın karşılaştırmaya girip giremeyeceğini söyler.

    Args:
        rate_source: `RATE_SOURCES` içindeki bir değer.

    Returns:
        Karşılaştırmaya girebiliyorsa True.

    """
    return rate_source not in RATE_SOURCES_NOT_COMPARABLE


def is_valid_variant(dimension: str, key: str) -> bool:
    """Varyant anahtarının verilen boyuta ait olup olmadığını doğrular.

    Args:
        dimension: `VARIANT_VOCAB` boyut adı (ör. "arac_durumu").
        key: Kanonik varyant anahtarı (ör. "sifir_arac").

    Returns:
        Anahtar o boyutta tanımlıysa True.

    """
    return key in VARIANT_VOCAB.get(dimension, ())


# ── Kampanya taksonomisi eksenleri ────────────────────────
#
# Dört DİK eksen: bir kampanya her eksende ayrı ayrı etiketlenir. Kontrollü
# değer listeleri ileride tanımlanacak; burada yalnızca eksen adları
# ve etiketin hangi kanıttan geldiği sabitlenir.
TAXONOMY_AXES: Final[tuple[str, ...]] = ("product_type", "sector", "audience", "benefit")

# Etiketin kaynağı. `llm` SPRINT 3'te doldurulacak; SPRINT 2'de üretilmez.
CATEGORY_SOURCES: Final[tuple[str, ...]] = (
    "url",
    "bank_category",
    "keyword",
    "merchant",
    "llm",
)


# ── Hesaplayıcı ───────────────────────────────────────────

# Hesaplayıcının nasıl çalıştığı. `api` sunucuya istek atar (sorgulanabilir),
# `js_client_side` tarayıcıda hesaplar (oran bundle'da), `js_with_rate_fetch`
# oranı sunucudan çekip tarayıcıda hesaplar.
CALCULATOR_MECHANISMS: Final[tuple[str, ...]] = (
    "api",
    "js_client_side",
    "js_with_rate_fetch",
    "unknown",
    "none",
)

# Envanter sonrası örnekleme kararı.
SAMPLING_DECISIONS: Final[tuple[str, ...]] = ("full", "grid", "pilot_only", "skip")

# Tek bir sorgunun hangi yöntemle alındığı.
PROBE_METHODS: Final[tuple[str, ...]] = (
    "api",
    "js_default",
    "playwright",
    "payment_plan_derived",
)


# ── Çıkarım motoru (SPRINT 3) ─────────────────────────────

# Çıkarım çalıştırmasının kipi. `rule_only` LLM'e hiç çağrı yapmaz ve
# ablasyon tablosunun baseline kolonudur; `llm_only` kuralı devre dışı
# bırakır ve yalnızca karşılaştırma için kullanılır.
EXTRACTION_MODES: Final[tuple[str, ...]] = ("hybrid", "rule_only", "llm_only")

# Çalıştırmanın bitiş durumu. `partial` bazı kampanyaların atlandığını,
# `cancelled` kullanıcının durdurduğunu belirtir; ikisinde de o ana kadar
# kaydedilen çıkarımlar KORUNUR.
EXTRACTION_RUN_STATUSES: Final[tuple[str, ...]] = (
    "running",
    "success",
    "partial",
    "failed",
    "cancelled",
)

# ⚠️ Gold set etiketleme yöntemi — YANLILIK KONTROLÜNÜN TEMELİ.
# `blind`: etiketleyici sistemin çıktısını GÖRMEDEN etiketler.
# `assisted`: kural tabanlı çıkarım ön-doldurur, etiketleyici onaylar/düzeltir.
# İkisi ayrı tutulmazsa F1 sahte şişer: sistemin cevabını gören etiketleyici
# ona meyleder ve model kendi cevabına karşı ölçülmüş olur.
ANNOTATION_METHODS: Final[tuple[str, ...]] = ("blind", "assisted")

# `gold_annotations.note` işareti: kanıt METİNDEN BETİKLE bağlandı, insan
# seçmedi (`dev.py kanit-bagla`). `gold-durum` raporu bu işareti taşıyan
# kanıtları insan seçimlerinden AYRI sayar; tek bir "kanıtlı etiket" sayısı
# verilseydi rapor, sahip olmadığımız bir titizliği iddia ederdi.
OTO_KANIT_NOTU: Final[str] = "oto-kanit"

# Kart ve gömme üretilebilen varlık türleri.
ENTITY_TYPES: Final[tuple[str, ...]] = (
    "campaign",
    "product",
    "product_rate",
    "glossary",
    "bank",
)

# LLM önbelleğindeki görev türü. Önbellek anahtarı göreve göre ayrışır:
# aynı metin farklı görevlerde farklı yanıt üretir.
LLM_TASKS: Final[tuple[str, ...]] = ("extract", "classify", "summarize")
