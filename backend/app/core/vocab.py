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
    # KATİP KAPI 1.2 — Albaraka/Dünya Katılım konut finansmanında iki ayrı
    # LTV matrisi var (Standart / İkinci Alım); enerji sınıfı boyutuyla ÇAKIŞMAZ,
    # aynı üründe iki farklı kesişimli `product_limits` seti olabilir.
    "alim_sirasi": ("ilk_alim", "sonraki_alim"),
    # KATİP KAPI 1.3 — marka/model bazlı finansman (Togg gibi). Anahtar kümesi
    # KASITLI OLARAK boş bırakılır: hangi marka/modellerin çıkacağı önceden
    # bilinmiyor (bugün Togg, yarın başka bir marka olabilir) — `variant_key`
    # burada `brand`/`model` kolonlarından türetilir (ör. "togg_t10x"), sabit
    # bir sözlükle sınırlanmaz.
    "marka_model": (),
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
    # KATİP: marka/model varyantı (Togg gibi) — tek tablonun HER SATIRI ayrı
    # bir model/varyant (bkz. `alim_sirasi`/`marka_model` boyutları).
    "table_row",
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
    # ⚠️ KATİP dönüşümü: kullanıcının bankanın kendi sayfasından/hesaplayıcısından
    # bizzat tarayıp doğruladığı, otomasyonun (Playwright/HTTP) bu ortamda
    # çalışmadığı durumlarda elle girilen veri. Tahmin DEĞİLDİR — bankanın
    # yayımladığı değerin birebir transkripsiyonudur, bu yüzden `html_table`
    # kadar güvenilir sayılır (bkz. RATE_SOURCE_CONFIDENCE).
    "seed_manual",
    # TOM Bank kâr oranlarını yalnızca PDF olarak yayımlıyor
    # (`krediler_kar_oranlari_*.pdf`) — `ProductLimit.extraction_method`'taki
    # `pdf_table` ile aynı güvenilirlik düzeyinde, bankanın kendi yapısal
    # tablosu, yalnızca PDF paketli.
    "pdf_table",
)

RATE_SOURCE_CONFIDENCE: Final[dict[str, Decimal]] = {
    "html_table": Decimal("1.000"),
    "payment_plan_derived": Decimal("0.950"),
    "calculator_api": Decimal("0.850"),
    "calculator_playwright": Decimal("0.800"),
    "text": Decimal("0.750"),
    "js_default": Decimal("0.500"),
    "none": Decimal("0.000"),
    "seed_manual": Decimal("1.000"),
    "pdf_table": Decimal("1.000"),
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
    # ⚠️ KATİP: Karz-ı Hasen (Dünya Katılım "Enerya") ve vade farksız Eğitim
    # Finansmanı (Hayat Finans) sistemi — kâr payı KAVRAMI yok. `financing_rate`
    # ile 0 oranını KARIŞTIRMAMAK için ayrı bir tür. Kasıtlı olarak
    # `RATE_TYPE_COMPARABLE_FIELD`'a EKLENMEZ: bu ürünler `rank_products`
    # sıralamasına hiç giremez (şartname anlamında finansman değil, faizsiz
    # borç kategorisi).
    "interest_free_benevolent_loan",
)

# Kullanıcıya gösterilecek Türkçe karşılık.
#
# ⚠️ SLUG CÜMLEYE YAZILMAZ. Ölçüldü: `rate_type.replace("_", " ")` ile kurulan
# yanıt kapalı ağ kurulumunda "En düşük financing rate %2.8800 ile Türkiye
# Finans" cümlesini üretiyordu — hem İngilizce hem de projenin bağlayıcı
# terminoloji kuralına aykırı.
RATE_TYPE_LABELS: Final[dict[str, str]] = {
    "financing_rate": "finansman oranı",
    "participation_yield": "katılma getirisi",
    "profit_sharing_ratio": "katılımcı payı",
    "interest_free_benevolent_loan": "karz-ı hasen oranı",
}


def rate_type_label(rate_type: str) -> str:
    """Oran türünün Türkçe karşılığı; bilinmeyen tür ham hâliyle döner."""
    return RATE_TYPE_LABELS.get(rate_type, rate_type)


# ⚠️ FARKLI TÜRLER ASLA AYNI SIRALAMAYA GİRMEZ. Karşılaştırma ucu
# `rate_type` parametresini ZORUNLU tutar; varsayılan seçmez.
#
# ⚠️ `interest_free_benevolent_loan` BİLİNÇLİ OLARAK BURADA YOK — bu sözlükte
# olmayan bir `rate_type` `rank_products`'ta RankingError fırlatır
# (bkz. `comparison_service.py`), karz-ı hasen/eğitim finansmanı ürünlerinin
# sıralamaya sessizce girmesini engeller.
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


# ── KATİP: TKBB entegrasyonu ve ürün mevcudiyeti ──────────
#
# Bir `product_rates` satırının bankanın kendi sitesinden mi yoksa TKBB Veri
# Peteği'nin resmi API'sinden mi geldiği. İkisi AYNI tabloya yazılır (yeni
# tablo açılmaz) ama kaynağı ayırt edilebilir kalmalı — çapraz doğrulama ve
# "hangi veri kimden" izlenebilirliği için.
DATA_SOURCES: Final[tuple[str, ...]] = ("bank_site", "tkbb_veripetegi")

# Bir `products` satırının bankanın gerçekten sunup sunmadığı. "Ürün yok" ile
# "veri henüz toplanmadı" AYRI durumlardır — TKBB'de "ara ödemeli katılma
# hesabı" yalnızca 5 bankada var, diğer 4 bankada satır hiç yok (`not_offered`,
# `unknown` değil).
AVAILABILITY_STATUSES: Final[tuple[str, ...]] = ("offered", "not_offered", "unknown")

# ── KATİP KAPI 6: Finansmanlar sekmesinin kapsamı ─────────
#
# "Finansman" sekmesine giren `product_type` değerleri. Katılma hesabı
# ürünleri (`katilma_hesabi`, `ozel_katilma_hesabi`, `altin_katilma_hesabi`,
# `ara_donem_kar_odemeli`, `devlet_katkili_hesap`, `birikim_katilma_hesabi`)
# BİLİNÇLİ OLARAK burada YOK — onlar Katılım Hesabı sekmesine (KAPI 7) gider.
# `karz_i_hasen`/`egitim_finansmani` dahildir: kâr paysız olsalar da esasen
# birer finansman ürünüdür, yalnızca oran sütununda "Kâr Payı Alınmaz" gösterilir.
FINANSMAN_TIPLERI: Final[frozenset[str]] = frozenset(
    {
        "finansman",
        "ihtiyac_finansmani",
        "konut_finansmani",
        "tasit_finansmani",
        "isyeri_finansmani",
        "gayrimenkul_finansmani",
        "alisveris_finansmani",
        "surdurulebilir_finansman",
        "arsa_finansmani",
        "egitim_finansmani",
        "karz_i_hasen",
        "digital_arac_finansmani",
        "marka_ozel_finansman",
    }
)

# ── KATİP KAPI 7: Katılım Hesabı sekmesinin kapsamı ───────
#
# ⚠️ `birikim_katilma_hesabi` GERÇEK VERİDE ZATEN KULLANILAN DEĞER —
# SPRINT 2-4'ün scraper'ları katılma hesabı ürünlerinin neredeyse tamamını
# (Dünya Katılım, Emlak Katılım, Kuveyt Türk, Türkiye Finans, Vakıf Katılım,
# Ziraat Katılım) bu tek tip altında topladı (`app/core/taxonomy.py`'nin
# kampanya taksonomisiyle aynı isim). KAPI 1.1'in önerdiği ince taneli
# değerler (`katilma_hesabi`, `ozel_katilma_hesabi`, ...) henüz hiçbir
# scraper tarafından üretilmiyor ama KATİP'in yeni banka verisiyle
# (KAPI 2-4) üretilmeye başlayabilir — iki kümenin BİRLEŞİMİ tutulur, yoksa
# bu sekme gerçek veriyle boş görünür (ölçüldü).
KATILIM_HESABI_TIPLERI: Final[frozenset[str]] = frozenset(
    {
        "birikim_katilma_hesabi",
        "katilma_hesabi",
        "ozel_katilma_hesabi",
        "altin_katilma_hesabi",
        "ara_donem_kar_odemeli",
        "devlet_katkili_hesap",
    }
)

# TKBB Veri Peteği'nin vade etiketleri → `product_rates.term_months`. Yalnızca
# bu 4 vade pivot tabloya girer; farklı bir vadedeki (ör. 18 ay) satır pivot
# dışında kalır ama veritabanında durur (bkz. `docs/TKBB_VERI_PETEGI_BULGULARI.md`).
KATILIM_HESABI_VADE_ETIKETI: Final[dict[int, str]] = {
    1: "aylik",
    3: "3_aylik",
    6: "6_aylik",
    12: "yillik",
}


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
# Kampanya ↔ ürün bağının hangi sinyalden kurulduğu. Güç sırası:
#   title — ürün adı kampanya BAŞLIĞINDA geçiyor (en güçlü)
#   slug  — ürün adresi kampanya adresinde geçiyor
#   body  — ürün adı yalnızca GÖVDE metninde geçiyor (zayıf: geçerken
#           anılmış olabilir, "Bankkart ile alışveriş" gibi)
#
# ⚠️ ÜRÜN TÜRÜNDEN BAĞ KURULMAZ; listede bilerek yok. Tür eşlemesi ürünün
# oran tablosunu aynı türdeki HER kampanyaya kopyalamak demektir.
CAMPAIGN_PRODUCT_MATCH_METHODS: Final[tuple[str, ...]] = ("title", "slug", "body")

# Yöntem → güven. `body` düşük tutulur; tüketen taraf eşiğe göre süzer.
CAMPAIGN_PRODUCT_CONFIDENCE: Final[dict[str, Decimal]] = {
    "title": Decimal("0.900"),
    "slug": Decimal("0.850"),
    "body": Decimal("0.600"),
}


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

# Span (cümle parçası) kanıtından MUAF alanlar — kılavuz §2b.
#
# ⚠️ Bu alanların değeri metnin BÜTÜNÜNDEN çıkar, tek bir cümle parçasından
# değil: metin "seyahat_konaklama" yazmaz, "kobi" yazmaz, ödül türü için
# "puan" değil "ParafPara" yazar. Zorlama bir span sahte kesinlik üretir —
# kararın gerçekte başlık, sektör ve üye işyeri listesinin birlikte
# okunmasından doğduğunu gizler.
#
# ⚠️ Bu bir gevşetme DEĞİLDİR: çıkarım alanlarında (tutar, oran, tarih,
# vade) kanıt hâlâ zorunludur ve `gold-durum` iki grubu ayrı sayar.
SPAN_KANITINDAN_MUAF: Final[frozenset[str]] = frozenset(
    {"product_type", "sector", "target_customer", "reward_type", "has_no_fee"}
)

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
