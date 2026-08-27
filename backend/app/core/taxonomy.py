"""Kampanya taksonomisi — dört dik eksenin kontrollü sözlükleri.

NEDEN DÖRT EKSEN: Tek eksenli bir kategori listesi yetmiyor. "Konut Finansmanı
Kampanyası" ile "Market Alışverişinde Taksit" aynı listeye konursa ne ürün
türüne ne harcama sektörüne göre süzme yapılabilir. Eksenler DİKTİR: bir
kampanya her eksende ayrı ayrı ve birden fazla etiket alabilir.

    product_type — ne satılıyor (şartnamenin 8 zorunlu türü + ek türler)
    sector       — harcama nerede yapılıyor
    audience     — kime yönelik
    benefit      — müşteri ne kazanıyor

⚠️ SEKTÖR LİSTESİ UYDURMA DEĞİL. Ziraat Katılım'ın sitesinde kullandığı 14
gerçek kategori temel alındı, diğer bankalarda gözlenen konularla genişletildi.
Ziraat'in etiketleri `BANK_CATEGORY_SECTOR` üzerinden birebir eşlenir; o
kampanyalarda sektör çıkarım değil, bankanın kendi verisidir.

⚠️ Bu modül SAFTIR: sözlük ve eşleme tablosu içerir, sınıflandırma mantığı
`app/processing/categorizer.py`'dedir.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

# ── Eksen 1: ürün türü ────────────────────────────────────
#
# İlk sekizi şartnamede ZORUNLU. Kalanlar ek veri alanı olarak sunulur;
# gerçek kampanyalarda karşılığı bulunduğu için eklendi.
PRODUCT_TYPES: Final[tuple[str, ...]] = (
    # Şartnamenin 8 çekirdek türü
    "finansman",
    "ihtiyac_finansmani",
    "konut_finansmani",
    "tasit_finansmani",
    "kart",
    "alisveris_puani",
    "yeni_musteri",
    "yatirim_urunu",
    # Ek türler
    "birikim_katilma_hesabi",
    "sigorta",
    "pos_uye_isyeri",
    "dijital_bankacilik",
    "odeme_fatura",
    "kobi_ticari",
    "isyeri_finansmani",
    # KATİP KAPI 1.1 — yeni banka verisiyle ortaya çıkan türler. Bu tek
    # sözlük hem kampanya taksonomisinde hem `Product.product_type`'ta
    # kullanılır (bkz. `tests/unit/test_product_pages.py`); ayrı bir liste
    # açmak aynı kavramı iki yerde tanımlamak, sessizce ıraksamak olurdu.
    "gayrimenkul_finansmani",
    "alisveris_finansmani",
    "surdurulebilir_finansman",
    "arsa_finansmani",
    "egitim_finansmani",
    # Karz-ı Hasen — vade farksız, kâr payı KAVRAMI yok (bkz.
    # `RATE_TYPES.interest_free_benevolent_loan`). `rank_products`
    # sıralamasına hiç girmez.
    "karz_i_hasen",
    "digital_arac_finansmani",
    "marka_ozel_finansman",
    # TKBB Veri Peteği'nin "ara ödemeli katılma hesabı" — yalnızca 5 bankada
    # sunuluyor, diğerlerinde `availability_status='not_offered'`.
    "ara_donem_kar_odemeli",
)

# ── Eksen 2: harcama sektörü ──────────────────────────────
SECTORS: Final[tuple[str, ...]] = (
    "market_gida",
    "akaryakit",
    "giyim_aksesuar",
    "elektronik_telekom",
    "beyaz_esya_ev",
    "mobilya_dekorasyon",
    "yapi_hirdavat",
    "kuyum_optik_saat",
    "eticaret_pazaryeri",
    "seyahat_konaklama",
    "ulasim_arac_kiralama",
    "restoran_kafe",
    "eglence_dijital",
    "egitim_kitap",
    "saglik_kozmetik",
    "hobi_oyuncak_spor",
    "vergi_fatura_kamu",
    "sigorta",
    "yatirim_birikim",
    "konut_gayrimenkul",
    "kurumsal_kobi",
    # KATİP — daha önce karşılığı olmayan gerçek kampanya konuları.
    "dogalgaz_enerji",
    "otomotiv",
    # Sektörden bağımsız kampanyalar; eşleşme bulunamadığında da kullanılır.
    "genel",
)

# ── Eksen 3: hedef kitle ──────────────────────────────────
AUDIENCES: Final[tuple[str, ...]] = (
    "yeni_musteri",
    "mevcut_musteri",
    "maas_musterisi",
    "emekli",
    "ogrenci",
    "genc",
    "kamu_calisani",
    "banka_calisani",
    "esnaf",
    "ciftci",
    "kobi",
    "ticari_kurumsal",
    "ozel_bankacilik",
    "herkes",
)

# ── Eksen 4: fayda türü ───────────────────────────────────
BENEFITS: Final[tuple[str, ...]] = (
    "nakit_iade",
    "puan_mil",
    "taksit",
    "vade_farksiz_taksit",
    "indirim",
    "hediye_ceki",
    "ucret_muafiyeti",
    "masrafsiz",
    "avantajli_kar_payi",
    "hediye_urun",
    "cekilis",
)

# Eksen adı → o eksende geçerli değerler.
AXIS_VALUES: Final[dict[str, tuple[str, ...]]] = {
    "product_type": PRODUCT_TYPES,
    "sector": SECTORS,
    "audience": AUDIENCES,
    "benefit": BENEFITS,
}


# ── Kanıt kaynağı → güven katsayısı ───────────────────────
#
# Bankanın kendi verisi (adres yolu, kategori etiketi) çıkarım değildir;
# güveni tamdır. Marka eşleşmesi güçlü ama kelime eşleşmesi zayıf sinyaldir.
SOURCE_CONFIDENCE: Final[dict[str, Decimal]] = {
    "url": Decimal("1.000"),
    "bank_category": Decimal("1.000"),
    "merchant": Decimal("0.900"),
    "keyword": Decimal("0.700"),
}

# Hiçbir sektör sinyali bulunamadığında kullanılan değer ve güveni.
# Düşük güven bilinçlidir: SPRINT 3'teki LLM bu kayıtları önceliklendirecek.
FALLBACK_SECTOR: Final[str] = "genel"
FALLBACK_CONFIDENCE: Final[Decimal] = Decimal("0.300")


# ── Bankanın kendi kategori etiketi → kanonik değer ───────
#
# 🎁 BEDAVA VE %100 GÜVENİLİR. Ziraat Katılım kampanya kartlarında sektörü
# kendisi yazıyor (`<span class="item-category">`); Kuveyt Türk ve Türkiye
# Finans adres yolunda taşıyor. Bu eşlemeler çıkarım değil, çeviri tablosudur.
#
# Anahtarlar karşılaştırma öncesi küçük harfe indirilir ve Türkçe karakterler
# katlanır; buradaki yazım okunabilirlik içindir.
BANK_CATEGORY_SECTOR: Final[dict[str, str]] = {
    # Ziraat Katılım — kart üzerindeki etiketler (canlı sayfadan)
    "kuyum, optik ve saat": "kuyum_optik_saat",
    "market ve gıda": "market_gida",
    "e-ticaret": "eticaret_pazaryeri",
    "elektronik ve telekomünikasyon": "elektronik_telekom",
    "yapı sektörü ve iklimlendirme": "yapi_hirdavat",
    "akaryakıt": "akaryakit",
    "eğitim, kitap ve kırtasiye": "egitim_kitap",
    "turizm ve seyahat": "seyahat_konaklama",
    "hobi ve oyuncak": "hobi_oyuncak_spor",
    "mobilya ve dekorasyon": "mobilya_dekorasyon",
    "beyaz eşya ve ev aletleri": "beyaz_esya_ev",
    "giyim ve aksesuar": "giyim_aksesuar",
    "diğer kampanyalar": "genel",
    "genel kampanyalar": "genel",
    # Kuveyt Türk — adres yolundaki kategori
    "seyahat-kampanyalari": "seyahat_konaklama",
}

# Bankanın kategori etiketi ÜRÜN TÜRÜNÜ söylüyorsa buradan eşlenir.
BANK_CATEGORY_PRODUCT_TYPE: Final[dict[str, str]] = {
    # Kuveyt Türk (adres yolu)
    "kart-kampanyalari": "kart",
    "finansman-kampanyalari": "finansman",
    "musteri-ol-kampanyalari": "yeni_musteri",
    "kobi-kampanyalari": "kobi_ticari",
    "pos-kampanyalari": "pos_uye_isyeri",
    # Türkiye Finans (kategori sayfası adı)
    "kart": "kart",
    "finansman": "finansman",
    "ticari": "kobi_ticari",
    "dijital_bankacilik": "dijital_bankacilik",
    "odeme": "odeme_fatura",
    "yatirim": "yatirim_urunu",
    "birikim_fon": "birikim_katilma_hesabi",
    "sigorta": "sigorta",
}


# ── Marka → sektör sözlüğü ────────────────────────────────
#
# Gerçek kampanya başlıklarından çıkarıldı.
#
# ⚠️ KELİME SINIRINA DUYARLI EŞLEŞTİRİLİR. "gain" ve "tod" gibi kısa adlar
# sıradan Türkçe metinde de geçebilir; `categorizer` bunları `\b` sınırıyla
# arar ve tek başına geçtiğinde güveni düşürür.
MERCHANT_SECTOR: Final[dict[str, str]] = {
    # E-ticaret
    "trendyol": "eticaret_pazaryeri",
    "hepsiburada": "eticaret_pazaryeri",
    "n11": "eticaret_pazaryeri",
    "pazarama": "eticaret_pazaryeri",
    "pttavm": "eticaret_pazaryeri",
    # Market
    "a101": "market_gida",
    "migros": "market_gida",
    "carrefour": "market_gida",
    "şok market": "market_gida",
    "bim": "market_gida",
    # Giyim
    "lc waikiki": "giyim_aksesuar",
    "lcwaikiki": "giyim_aksesuar",
    "colin's": "giyim_aksesuar",
    "colins": "giyim_aksesuar",
    "modanisa": "giyim_aksesuar",
    "abdullah kiğılı": "giyim_aksesuar",
    "kiğılı": "giyim_aksesuar",
    # ⚠️ "altınyıldız" gövdede çıplak "altın" anahtarını da içerir; marka
    # eşleşmesi (0.90) giyimi yazar. Çıplak "altın" sektör anahtarından
    # çıkarılmasa bile merchant önceliği doğru sektörü tutar.
    "altınyıldız classics": "giyim_aksesuar",
    "altınyıldız": "giyim_aksesuar",
    "altinyildiz": "giyim_aksesuar",
    "ipekyol": "giyim_aksesuar",
    "network": "giyim_aksesuar",
    "vakko": "giyim_aksesuar",
    "vakkorama": "giyim_aksesuar",
    "kip": "giyim_aksesuar",
    "nocturne": "giyim_aksesuar",
    "mavi": "giyim_aksesuar",
    "koton": "giyim_aksesuar",
    "jack & jones": "giyim_aksesuar",
    "jack and jones": "giyim_aksesuar",
    "ramsey": "giyim_aksesuar",
    "divarese": "giyim_aksesuar",
    "damat tween": "giyim_aksesuar",
    # Mobilya / ev — ⚠️ Koçtaş yapı marketidir (gold: yapi_hirdavat),
    # mobilya zinciri değil; Paraf Koçtaş kampanyaları yanlış mobilyaya düşüyordu.
    "koçtaş": "yapi_hirdavat",
    "koctas": "yapi_hirdavat",
    "enza home": "mobilya_dekorasyon",
    "istikbal": "mobilya_dekorasyon",
    "kelebek": "mobilya_dekorasyon",
    "schafer": "beyaz_esya_ev",
    "vestel": "beyaz_esya_ev",
    # Elektronik
    "apple": "elektronik_telekom",
    "teknosa": "elektronik_telekom",
    "vatan bilgisayar": "elektronik_telekom",
    "xiaomi": "elektronik_telekom",
    "samsung": "elektronik_telekom",
    "media markt": "elektronik_telekom",
    "mediamarkt": "elektronik_telekom",
    # Seyahat
    "pegasus": "seyahat_konaklama",
    "biletinial": "seyahat_konaklama",
    "tatilbudur": "seyahat_konaklama",
    "setur": "seyahat_konaklama",
    # Ulaşım
    "enterprise": "ulasim_arac_kiralama",
    "rentgo": "ulasim_arac_kiralama",
    "ispark": "ulasim_arac_kiralama",
    "otopark": "ulasim_arac_kiralama",
    "otorapor": "ulasim_arac_kiralama",
    "pirelli": "ulasim_arac_kiralama",
    # Restoran / yemek
    "espressolab": "restoran_kafe",
    "gastroclub": "restoran_kafe",
    "the house cafe": "restoran_kafe",
    "yemeksepeti": "restoran_kafe",
    "getir yemek": "restoran_kafe",
    # Mobilya — Troy mağaza kampanyaları
    "troy mağaza": "mobilya_dekorasyon",
    "troy magaz": "mobilya_dekorasyon",
    # Dijital abonelik
    "netflix": "eglence_dijital",
    "spotify": "eglence_dijital",
    "chatgpt": "eglence_dijital",
    "disney+": "eglence_dijital",
    "hbo max": "eglence_dijital",
    "mubi": "eglence_dijital",
    "exxen": "eglence_dijital",
    "tabii": "eglence_dijital",
    "youtube premium": "eglence_dijital",
    # Eğitim
    "idefix": "egitim_kitap",
    # Sağlık / kozmetik
    "restoderm": "saglik_kozmetik",
    "sosyopix": "saglik_kozmetik",
    # Kurumsal — ⚠️ ShipEntegra gold'da eticaret_pazaryeri (e-ihracat pazaryeri
    # kampanyası); çıplak kurumsal_kobi F1'i düşürüyordu.
    "shipentegra": "eticaret_pazaryeri",
    "edenred": "kurumsal_kobi",
    # Gayrimenkul
    "emlak konut": "konut_gayrimenkul",
    # Hobi
    "barçın spor": "hobi_oyuncak_spor",
    "barcin": "hobi_oyuncak_spor",
    # ⚠️ Çiçek e-ticaret; gold: eticaret_pazaryeri (hobi değil).
    "hızlı çiçek": "eticaret_pazaryeri",
    "hizli cicek": "eticaret_pazaryeri",
    # Kuyum
    "zen pırlanta": "kuyum_optik_saat",
    "zen pirlanta": "kuyum_optik_saat",
    # Elektronik (KATİP)
    "casper": "elektronik_telekom",
    # Giyim (KATİP) — Albaraka'nın "DS Damat" kampanyaları
    "ds damat": "giyim_aksesuar",
    "damat": "giyim_aksesuar",
    # Doğalgaz/enerji (KATİP) — Dünya Katılım'ın Enerya Karz-ı Hasen ortağı
    "enerya": "dogalgaz_enerji",
    # ── Çok bankalı Paraf / kart işyeri kampanyaları (Emlak, Dünya, …) ──
    "dyson": "beyaz_esya_ev",
    "itopya": "elektronik_telekom",
    "monster notebook": "elektronik_telekom",
    "monster": "elektronik_telekom",
    "vatan": "elektronik_telekom",
    "touristica": "seyahat_konaklama",
    "yenilio": "elektronik_telekom",
    "vaillant": "yapi_hirdavat",
    "demirdöküm": "yapi_hirdavat",
    "demirdokum": "yapi_hirdavat",
    "porland": "beyaz_esya_ev",
    "copa": "hobi_oyuncak_spor",
    "görgençler": "mobilya_dekorasyon",
    "gorgenciler": "mobilya_dekorasyon",
    "yargıçı": "giyim_aksesuar",
    "yargici": "giyim_aksesuar",
    "marina mayo": "giyim_aksesuar",
    "macrocenter": "market_gida",
    "colin": "giyim_aksesuar",
    "kuba motor": "otomotiv",
    "avansas": "egitim_kitap",
    "lassa": "ulasim_arac_kiralama",
    # ⚠️ Goodyear lastik kampanyası gold'da `genel` (sektörsüz taksit).
    # Markayı ulasim'e bağlamak F1'i düşürüyordu — sözlükten çıkarıldı.
    "bridgestone": "ulasim_arac_kiralama",
    "michelin": "ulasim_arac_kiralama",
    "petlas": "ulasim_arac_kiralama",
    "thy": "seyahat_konaklama",
    "miles&smiles": "seyahat_konaklama",
    "miles and smiles": "seyahat_konaklama",
    "enuygun": "seyahat_konaklama",
    # Paraf / işyeri — gold hizası
    "twist": "giyim_aksesuar",
    "öncehesap": "elektronik_telekom",
    "oncehesap": "elektronik_telekom",
    "vialand": "eglence_dijital",
    "tiktak": "ulasim_arac_kiralama",
    "muhiku": "egitim_kitap",
    "english home": "mobilya_dekorasyon",
    "eve ": "eticaret_pazaryeri",  # "Eve alışverişlerinde" — sol sınır + boşluk
    "alldayesim": "elektronik_telekom",
    "zorlu psm": "eglence_dijital",
    "metatech": "elektronik_telekom",
    "metatechtr": "elektronik_telekom",
    "adv mağaza": "giyim_aksesuar",
    "adv ": "giyim_aksesuar",
    "zsa zsa zsu": "giyim_aksesuar",
    "yoyo": "restoran_kafe",
    "yolcu 360": "seyahat_konaklama",
    "yolcu360": "seyahat_konaklama",
    "bellona": "mobilya_dekorasyon",
    "mondi": "mobilya_dekorasyon",
    "konfor": "mobilya_dekorasyon",
    "alfemo": "mobilya_dekorasyon",
    "divanev": "mobilya_dekorasyon",
    "dogtas": "mobilya_dekorasyon",
    "doğtaş": "mobilya_dekorasyon",
    "puffy": "mobilya_dekorasyon",
    "yatas": "mobilya_dekorasyon",
    "yataş": "mobilya_dekorasyon",
    "cetmen": "mobilya_dekorasyon",
    "çetmen": "mobilya_dekorasyon",
    "vivense": "mobilya_dekorasyon",
    "evidea": "mobilya_dekorasyon",
    "memorial": "saglik_kozmetik",
    "petrol ofisi": "akaryakit",
    # Elektronik / fiyat karşılaştırma (Paraf taksit kampanyaları)
    "incehesap": "elektronik_telekom",
    "incehesap.com": "elektronik_telekom",
    # Çiçek — e-ticaret hediye
    "taze çiçek": "eticaret_pazaryeri",
    "taze cicek": "eticaret_pazaryeri",
}

# ⚠️ Tek başına geçtiğinde sıradan kelimeyle karışabilecek marka adları.
# Bunlar için eşleşme kabul edilir ama güven bir kademe düşürülür.
AMBIGUOUS_MERCHANTS: Final[frozenset[str]] = frozenset(
    {
        "gain",
        "tod",
        "bim",
        "apple",
        "kelebek",
        "setur",
        "monster",
        "vatan",
        "colin",
        "eve ",
        "kip",  # kısa; "ekip" vb. riski düşük ama güven düşür
        "mavi",  # renk sıfatı da olabilir
        "network",  # genel İngilizce kelime
    }
)


# ── Anahtar kelime sözlükleri ─────────────────────────────
#
# En zayıf sinyal. Yalnızca daha güçlü bir kaynak bulunamadığında kullanılır.

PRODUCT_TYPE_KEYWORDS: Final[dict[str, tuple[str, ...]]] = {
    # ⚠️ "KONUT VE TAŞIT FİNANSMANI" BİRLEŞİK BAŞLIK. Albaraka'nın "Dijitale
    # Özel Konut ve Taşıt Finansmanı Kampanyası" başlığında "konut finansman"
    # öbeği GEÇMİYOR (araya "ve taşıt" giriyor); kampanya yalnızca
    # `tasit_finansmani` etiketi alıyordu. Ölçüldü — bu, kampanya tarafındaki
    # TEK konut finansmanı kaydıydı ve "Konut finansmanı kampanyası" sorgusu
    # sıfır sonuç dönüyordu (bkz. `docs/erisim_recall.md`, sorgu e04).
    "konut_finansmani": (
        "konut finansman",
        "konut ve tasit finansman",
        "konut ve taşıt finansman",
        "ev finansman",
        "mortgage",
        "gayrimenkul finansman",
    ),
    "tasit_finansmani": (
        "taşıt finansman",
        "araç finansman",
        "otomobil finansman",
        "motosiklet kampanya",
        "motosiklet finansman",
        "doğa dostu araç",
    ),
    "ihtiyac_finansmani": (
        "ihtiyaç finansman",
        "ihtiyaç kredi",
        "ihtiyaç kart",
        "sağlık kredi",
        "taksitli sağlık",
    ),
    "isyeri_finansmani": ("işyeri finansman", "iş yeri finansman"),
    # ⚠️ Gold set `finansman` kullanıyor (`alisveris_finansmani` değil).
    # TOM Hadi / mağaza finansmanı kampanyaları gold'a göre bu etiketi alır.
    "finansman": (
        "finansman kullan",
        "finansman kampanya",
        "finansmanı",
        "karz-ı hasen",
        "finansman fırsat",
        "finansman imkan",
        "finansman türü",
        "finansman avantaj",
        "varan destek",
        "vade farksız destek",
        "bana bunu al",
        "alışveriş finansman",
        "mağaza finansman",
        "alışveriş kredi",
        "hadi alışveriş",
        "hadi taksitli",
        "hadi'den",
        "hadi’den",
        "veresiye",
        "eyt finansman",
        "hac ve umre",
        "hac finansman",
        "umre finansman",
    ),
    "alisveris_finansmani": (
        "taksitli alışveriş kredi",
        "mağazadan alışveriş kredi",
    ),
    # ⚠️ KART MARKA ADIYLA ANILIYOR. Bankalar kartı ürün adıyla değil marka
    # adıyla yazıyor: "Biz Kart", "Hadi Kartı", "VKart", "Paraf", "TROY".
    # Yalnızca "kredi kartı"/"banka kartı" arandığında bu kampanyalar ürün
    # türü ALMIYORDU — 19 kampanyanın ikinci etiketsiz kalmasının başlıca
    # sebebi buydu. `kartı`/`kart ` genel biçimleri de eklendi.
    "kart": (
        "kredi kartı",
        "bankkart",
        "kart kampanya",
        "banka kartı",
        "kartınız",
        "kartı",
        "kartla",
        "troy",
        "paraf",
        "vkart",
        "world kart",
        "biz kart",
        "hadi kredi kart",
        "hadi black",
        "hadi kart",
        "sağlam kart",
        "bankkart lira",
        "pratik finansman kart",
        # ⚠️ Albaraka'nın kart katman isimleri — "kart" kelimesi hiç geçmiyor
        # ("Trend'lilere Tüm Banka ATM'leri Ücretsiz" #619, "Eflatun'lulara..."
        # #605). ⚠️ Gerçek başlıkta İYELİK EKİ APOSTROFLA ayrılıyor
        # ("Trend’lilere", "Eflatun’lulara" — kıvrık tırnak U+2019); eşleştirme
        # kelime sınırını yalnızca SOLDAN arıyor (`_kelime_var`), bu yüzden
        # apostrof dahil biçim ZORUNLU — apostrofsuz "trendli" bu başlıkta hiç
        # eşleşmiyordu. Hem kıvrık (’) hem düz (') tırnak eklendi.
        "trend kart",
        "trend’li",
        "trend'li",
        "eflatun kart",
        "eflatun’lu",
        "eflatun'lu",
        "kart",
        # Harcama / sadakat kalıpları — "kart" kelimesi geçmese de kart ürünü
        "harcamanıza",
        "harcamanızda",
        "harcamalarında",
        "harcamalarınızda",
        "harcamalarında iade",
        "sadakat program",
        "sadakat programı",
        "harcadıkça kazan",
        "işlem yaptıkça",
        "hızlı geçiş",
        "vade farksız",
        "vade farksız taksit",
    ),
    "alisveris_puani": (
        "bankkart lira",
        "worldpuan",
        "world puan",
        "paraf para",
        "parafpara",
        "puan kazan",
        "mil kazan",
        "nakit iade",
    ),
    "yeni_musteri": (
        "yeni müşteri",
        "müşterimiz ol",
        "ilk kez müşteri",
        "müşteri ol",
        "yakınını davet",
        "arkadaşını davet",
        "arkadaşını getir",
        "davet kod",
        "davet et",
        "hoş geldin",
    ),
    # ⚠️ Gümüş/platin/paladyum da kıymetli maden hesabı; yalnızca "altın"
    # arandığında Hayat Finans'ın gümüş kampanyası boşta kalıyordu.
    "yatirim_urunu": (
        "yatırım fon",
        "hisse",
        "altın hesab",
        "döviz hesab",
        "kıymetli maden",
        "gümüş",
        "platin hesab",
        "paladyum",
    ),
    "birikim_katilma_hesabi": (
        "katılma hesab",
        "birikim hesab",
        "katılım fonu",
        "vadeli hesap",
        "avantajlı hesap",
        "günlük hesap",
        "cari hesap",
    ),
    "sigorta": ("sigorta poliçe", "sigortası", "bes ", "bireysel emeklilik"),
    # ⚠️ Çıplak "pos"/"pos "/"sanal pos" YOK. "Paraf POS üzerinden" bireysel
    # mağaza taksit kalıbı (A101, Koçtaş…); "poşet" de önek tuzağıydı.
    # Gerçek ürün: üye işyeri terminali / POS cihazı / "Meyve Dalından POS".
    "pos_uye_isyeri": (
        "üye işyeri",
        "pos cihaz",
        "pos kampanya",
        "meyve dalından pos",
        "işyerine özel pos",
        "pos başvuru",
    ),
    "dijital_bankacilik": (
        "mobil uygulama",
        "internet şube",
        "dijital bankacılık",
        "mobilden",
        "masraflara son",
        "masrafsız bankacılık",
        "mobil'de şimdi",
        "mobil’de şimdi",
    ),
    "odeme_fatura": ("fatura ödeme", "vergi ödeme", "mtv ödeme", "mtv ", "otomatik ödeme"),
    "kobi_ticari": ("kobi", "ticari müşteri", "esnaf", "işletme"),
}

SECTOR_KEYWORDS: Final[dict[str, tuple[str, ...]]] = {
    "market_gida": ("market", "gıda", "süt ürün", "bakliyat"),
    "akaryakit": (
        "akaryakıt",
        "benzin",
        "motorin",
        "yakıt",
        "araç şarj",
        "şarj istasyon",
        "elektrikli araç şarj",
        "şarj harcama",
    ),
    "giyim_aksesuar": ("giyim", "ayakkabı", "tekstil", "moda", "aksesuar"),
    "elektronik_telekom": (
        "elektronik",
        "telekomünikasyon",
        "cep telefon",
        "bilgisayar",
        "akıllı telefon",
    ),
    "beyaz_esya_ev": (
        "beyaz eşya",
        "ev aletleri",
        "buzdolab",
        "çamaşır makine",
        "süpürge",
        "klima",
        "televizyon",
    ),
    "mobilya_dekorasyon": ("mobilya", "dekorasyon", "koltuk", "yatak odası"),
    "yapi_hirdavat": ("yapı market", "hırdavat", "iklimlendirme", "klima", "inşaat malzeme"),
    "kuyum_optik_saat": ("kuyum", "optik", "gözlük", "pırlanta", "mücevher", "saat"),
    "eticaret_pazaryeri": ("e-ticaret", "online alışveriş", "pazaryeri", "internetten alışveriş"),
    "seyahat_konaklama": (
        "uçak bilet",
        "otel",
        "tatil",
        "seyahat",
        "konaklama",
        "turizm",
        "umre",
        "hac ve umre",
        "hac finansman",
        "havaliman",
        "yurt dışı uçak",
        "yurt içi uçak",
    ),
    "ulasim_arac_kiralama": (
        "araç kiralama",
        "otopark",
        "toplu taşıma",
        "lastik",
        "araç bakım",
        "vale harcama",
        "ispark",
    ),
    # ⚠️ EV şarj gold'da akaryakit (yakıt/enerji harcaması); ulasim değil.
    "restoran_kafe": (
        "restoran",
        "kafe",
        "yeme içme",
        "kahve",
        "yemek harcama",
        "restoran harcama",
    ),
    "eglence_dijital": (
        "dijital abonelik",
        "dijital üyelik",
        "sinema",
        "müzik",
        "oyun",
        "streaming",
        "kültür sanat",
        "internet kampanya",
        "gb internet",
    ),
    "egitim_kitap": ("eğitim", "kitap", "kırtasiye", "okul", "üniversite", "kurs"),
    "saglik_kozmetik": (
        "sağlık",
        "kozmetik",
        "eczane",
        "kişisel bakım",
        "hastane",
        # ⚠️ Veteriner klinik gold: saglik_kozmetik (hobi değil).
        "veteriner",
        "veteriner klinik",
    ),
    "hobi_oyuncak_spor": (
        "hobi",
        "oyuncak",
        "spor",
        "outdoor",
        "petshop",
    ),
    # ⚠️ Çıplak "fatura"/"vergi" ve hatta "fatura ödeme" ÇIKARILDI.
    # İhtiyaç finansmanı gövdesinde "fatura ödemelerinde kullanın" sektörü
    # vergiye çekiyordu; ürün `odeme_fatura` o sinyali ayrıca taşır.
    # Sektör için yalnızca kamu/MTV/vergi ödeme kampanyaları.
    "vergi_fatura_kamu": (
        "vergi ödeme",
        "vergi ve fatura",
        "mtv ödeme",
        "mtv ",
        "trafik ceza",
        "kamu ödeme",
        "yurt dışı çıkış harc",
        "çıkış harc",
        "vergi borcu",
        "sgk prim",
    ),
    "sigorta": ("sigorta",),
    # ⚠️ Çıplak "altın" ÇIKARILDI: "Altınyıldız" markası "altın…" önekiyle
    # yatirim_birikim oluyordu. Çıplak "birikim" de "Hadi birikim segmenti"
    # gibi kitle adlarında restoran kampanyasını yatırıma çekiyordu.
    "yatirim_birikim": (
        "altın puan",
        "altın kazan",
        "altın hesab",
        "altın birik",
        "altın katılma",
        "çeyrek altın",
        "gram altın",
        "ziynet altın",
        "külçe altın",
        "döviz",
        "yatırım fon",
        "fon işlem",
        "fon alım",
        "yatırım",
        "birikim hesab",
        "fx",
        "gümüş işlem",
        "dar makas",
        "hisse senedi",
        "hisse işlem",
        "avantajlı hesap",
    ),
    # ⚠️ Çıplak "emlak" ölçüldükten sonra ÇIKARILDI: bankanın kendi adı
    # ("Emlak Katılım") başlıkta/açıklamada geçtiğinde gerçek emlak/konut
    # konusu olmayan kampanyaları da bu sektöre düşürüyordu. "konut",
    # "gayrimenkul", "tapu" gerçek emlak sinyalini zaten yakalıyor.
    "konut_gayrimenkul": ("konut", "gayrimenkul", "tapu"),
    # ⚠️ Çıplak "pos" / "kurumsal" / "kobi" / "işletme" ÇIKARILDI.
    #
    # "Paraf POS'undan" bireysel mağaza taksit kampanyalarının standart
    # kalıbı; POS burada kartın geçtiği terminal, KOBİ ürünü değil. Ayrıca
    # `_kelime_var` sağ sınır aramadığı için "pos" → "poşet" (çay poşeti)
    # gibi yanlış önek eşleşmeleri üretiyordu.
    #
    # Gerçek kurumsal/KOBİ sinyali: üye işyeri, sanal/taksitli POS ürünü,
    # işletmeye hitap, KOBİ'ye özel ifadeler.
    # ⚠️ "sanal pos" de ÇIKARILDI: "Paraf üyesi X sanal Pos'u üzerinden"
    # bireysel taksit kalıbı (Demirdöküm/Vaillant). Gerçek üye-işyeri POS
    # ürünleri "POS Kampanyası" + "işletmeniz" ile yakalanıyor.
    "kurumsal_kobi": (
        "üye işyeri",
        "pos cihaz",
        "pos kampanya",
        "taksitli pos",
        "kurumsal müşteri",
        "kurumsal finansman",
        "kobi'lere",
        "kobi'lerimize",
        "kobiler",
        "kobilerimize",
        "küçük işletme",
        "işletmeniz",
        "işletmeler",
        "işletme sahibi",
        "e-ihracat",
        "ihracatçı",
        "masterkobi",
    ),
    "dogalgaz_enerji": ("doğalgaz", "enerji", "elektrik fatura"),
    "otomotiv": (
        "otomotiv",
        "otomobil",
        "araç alım",
        "motosiklet",
        "scooter",
    ),
}

AUDIENCE_KEYWORDS: Final[dict[str, tuple[str, ...]]] = {
    # ⚠️ ÇIPLAK "müşteri ol" VE "ilk kez" SÖZLÜKTEN ÇIKARILDI — ölçüldü.
    #
    # "Müşteri Ol" bankaların neredeyse her sayfasında duran bir GEZİNTİ
    # DÜĞMESİ. Sinyal sayıldığında gold set'te `mevcut_musteri` etiketli 41
    # kampanyanın 9'una yanlış `yeni_musteri` yazıyordu. Anlamı da tek yönlü
    # değil: "Müşteri Ol, 4 taksit" kampanyası mevcut müşteride de geçerli
    # olabilir.
    #
    # "ilk kez" tek başına yanıltıcı: "İlk Ek Kredi Kartınıza 1.000 TL"
    # kampanyası MEVCUT müşteriye ait — ek kart almak için zaten müşteri
    # olmak gerekiyor.
    #
    # Belirsiz kalanlar `categorizer.OWNERSHIP_RE` varsayılanına bırakılır.
    "yeni_musteri": (
        "yeni müşteri",
        "yeni müşterilerine",
        "yeni mobil müşteri",
        "ilk kez müşteri",
        "müşterimiz olan",
        "arkadaşını getir",
        "arkadaşını davet",
    ),
    # ⚠️ "müşterilerimiz" ANAHTAR DEĞİL: neredeyse her kampanya metni
    # "müşterilerimize özel" diyor ve bu ifade yeni müşteri kampanyalarında da
    # geçiyor. Ölçümde her kampanyaya hem `yeni_musteri` hem `mevcut_musteri`
    # etiketi takılmasına yol açtı.
    "mevcut_musteri": (
        "mevcut müşteri",
        "hâlihazırda müşteri",
        "mevcut veya yeni müşteri",
    ),
    "maas_musterisi": ("maaş müşteri", "maaşını bankamız", "maaş alan"),
    "emekli": ("emekli", "emeklilik maaş", "emekli müşteri", "emeklilerimize"),
    "ogrenci": ("öğrenci", "üniversiteli", "kampüs", "kampuse"),
    "genc": ("genç", "18-25"),
    "kamu_calisani": ("kamu çalışan", "memur", "kamu personel"),
    "banka_calisani": ("banka çalışan", "personelimiz"),
    "esnaf": ("esnaf",),
    "ciftci": ("çiftçi", "tarım", "tohum kart"),
    # ⚠️ Çıplak "kobi" ÇIKARILDI: Albaraka vb. sitelerde gezinti menüsünde
    # "KOBİ / Finansmanlar" her sayfa gövdesine sızıyor; restoran/ATM
    # kampanyaları yanlış `audience=kobi` alıyordu.
    # ⚠️ "masterkobi" audience'tan çıkarıldı: "Diğer Kampanyalar" bloklarında
    # her sayfada geçebiliyor (örn. Bridgestone detayı). Sektör sözlüğünde
    # başlıkta kaldı.
    "kobi": (
        "kobi'lere",
        "kobi'lerimize",
        "kobiler",
        "kobilerimize",
        "kobi müşteri",
        "küçük işletme",
        "esnaf ve kobi",
        "net ihracatçı",
    ),
    "ticari_kurumsal": (
        "ticari müşteri",
        "kurumsal müşteri",
        "şirket",
        "tüzel firma",
        "tüzel şirket",
        "iş ortağım",
        "isim için",
        "veteriner klinik",
    ),
    "ozel_bankacilik": ("özel bankacılık", "private banking"),
}

# ── Kampanya kanalı (Campaign.segment) — taksonomi ekseni DEĞİL ──
#
# `bireysel|kurumsal|kobi|ticari|tarim` değerleri `Campaign.segment` alanına
# yazılır. Scraper URL/listing'den dolduramadığında metin/URL yedek çıkarımı
# için kullanılır. Şartname 5.3 hedef kitle (`audience`) ile karıştırılmaz.
SEGMENTS: Final[tuple[str, ...]] = (
    "bireysel",
    "kurumsal",
    "kobi",
    "ticari",
    "tarim",
)

# Adres yolu / klasör → hedef kitle. Gövde kelimesi değil: "Müşteri Ol"
# düğmesi her sayfada var, `musteri-ol-kampanyalari` klasörü yalnızca
# yeni müşteri listesinde. Çıplak `/kobi/` segment'tir, buraya konmaz.
AUDIENCE_URL_PATHS: Final[dict[str, str]] = {
    "musteri-ol-kampanyalari": "yeni_musteri",
    "musteri-ol": "yeni_musteri",
    "kobi-kampanyalari": "kobi",
    "kampuse": "ogrenci",
    "kampus": "ogrenci",
}

# Adres yolu parçası → segment (Kuveyt / Vakıf kalıbı).
SEGMENT_URL_PATHS: Final[dict[str, str]] = {
    "kendim-icin": "bireysel",
    "kendimicin": "bireysel",
    "bireysel": "bireysel",
    "isim-icin": "kurumsal",
    "isimicin": "kurumsal",
    "kurumsal": "kurumsal",
    "ticari": "ticari",
    "kobi": "kobi",
    "tarim": "tarim",
    "tarım": "tarim",
}

SEGMENT_KEYWORDS: Final[dict[str, tuple[str, ...]]] = {
    "kurumsal": (
        "kurumsal müşteri",
        "kurumsal kampanya",
        "işim için",
        "isim için",
        "şirketler için",
    ),
    "ticari": ("ticari müşteri", "ticari kampanya", "ticari finansman"),
    "kobi": ("kobi müşteri", "kobi'lere", "kobiler için", "küçük işletme"),
    "tarim": ("tarım müşteri", "çiftçiye özel", "tarımsal"),
    "bireysel": (
        "bireysel müşteri",
        "kendim için",
        "bireysel kampanya",
        "bireysel müşterilerimize",
    ),
}

BENEFIT_KEYWORDS: Final[dict[str, tuple[str, ...]]] = {
    "nakit_iade": ("nakit iade", "iade kazan", "para iade", "cashback", "geri ödeme"),
    "puan_mil": ("bankkart lira", "worldpuan", "paraf para", "puan", "mil"),
    # ⚠️ "Vade farkı bizden/iade" de vade farksız taksittir; banka aynı şeyi
    # üç ayrı biçimde yazıyor.
    "vade_farksiz_taksit": (
        "vade farksız",
        "peşin fiyatına",
        "vade farkı iade",
        "vade farkın bizden",
        "vade farkı bizden",
    ),
    "taksit": ("taksit", "taksitlendirme", "aya varan taksit"),
    "indirim": ("indirim", "indirimli"),
    "ucret_muafiyeti": (
        "ücret alınmaz",
        "ücretsiz",
        "komisyon yok",
        "dosya masrafı alınmam",
        "sıfır komisyon",
    ),
    "masrafsiz": ("masrafsız",),
    "hediye_ceki": ("alışveriş çeki", "hediye çeki", "hediye kartı"),
    "avantajli_kar_payi": ("avantajlı kâr payı", "özel oranlı", "düşük maliyetli finansman"),
    "hediye_urun": ("hediye ürün", "hediyeniz", "ikram"),
    "cekilis": ("çekiliş", "talihli", "kura"),
}


def is_valid(axis: str, value: str) -> bool:
    """Değerin verilen eksende tanımlı olup olmadığını söyler.

    Args:
        axis: Eksen adı (`product_type`, `sector`, `audience`, `benefit`).
        value: Denetlenecek etiket.

    Returns:
        Etiket o eksende tanımlıysa True.
    """
    return value in AXIS_VALUES.get(axis, ())
