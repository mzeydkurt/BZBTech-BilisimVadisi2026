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
    # Mobilya / ev
    "koçtaş": "mobilya_dekorasyon",
    "koctas": "mobilya_dekorasyon",
    "enza home": "mobilya_dekorasyon",
    "istikbal": "mobilya_dekorasyon",
    "kelebek": "mobilya_dekorasyon",
    "schafer": "beyaz_esya_ev",
    "vestel": "beyaz_esya_ev",
    # Elektronik
    "apple": "elektronik_telekom",
    "teknosa": "elektronik_telekom",
    "vatan bilgisayar": "elektronik_telekom",
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
    # Restoran
    "espressolab": "restoran_kafe",
    "gastroclub": "restoran_kafe",
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
    # Kurumsal
    "shipentegra": "kurumsal_kobi",
    "edenred": "kurumsal_kobi",
    # Gayrimenkul
    "emlak konut": "konut_gayrimenkul",
    # Hobi
    "barçın spor": "hobi_oyuncak_spor",
    "barcin": "hobi_oyuncak_spor",
    "hızlı çiçek": "hobi_oyuncak_spor",
    # Kuyum
    "zen pırlanta": "kuyum_optik_saat",
    "zen pirlanta": "kuyum_optik_saat",
}

# ⚠️ Tek başına geçtiğinde sıradan kelimeyle karışabilecek marka adları.
# Bunlar için eşleşme kabul edilir ama güven bir kademe düşürülür.
AMBIGUOUS_MERCHANTS: Final[frozenset[str]] = frozenset(
    {"gain", "tod", "bim", "apple", "kelebek", "setur"}
)


# ── Anahtar kelime sözlükleri ─────────────────────────────
#
# En zayıf sinyal. Yalnızca daha güçlü bir kaynak bulunamadığında kullanılır.

PRODUCT_TYPE_KEYWORDS: Final[dict[str, tuple[str, ...]]] = {
    "konut_finansmani": ("konut finansman", "ev finansman", "mortgage", "gayrimenkul finansman"),
    "tasit_finansmani": ("taşıt finansman", "araç finansman", "otomobil finansman"),
    "ihtiyac_finansmani": ("ihtiyaç finansman", "ihtiyaç kredi"),
    "isyeri_finansmani": ("işyeri finansman", "iş yeri finansman"),
    "finansman": ("finansman kullan", "finansman kampanya", "karz-ı hasen"),
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
    ),
    "alisveris_puani": ("bankkart lira", "worldpuan", "paraf para", "puan kazan"),
    "yeni_musteri": ("yeni müşteri", "müşterimiz ol", "ilk kez", "müşteri ol"),
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
    # ⚠️ "POS" tek başına da ürün adı: "Meyve Dalından POS Vakıf Katılım'dan".
    "pos_uye_isyeri": ("üye işyeri", "pos cihaz", "sanal pos", "pos "),
    "dijital_bankacilik": ("mobil uygulama", "internet şube", "dijital bankacılık", "mobilden"),
    "odeme_fatura": ("fatura ödeme", "vergi ödeme", "mtv", "otomatik ödeme"),
    "kobi_ticari": ("kobi", "ticari müşteri", "esnaf", "işletme"),
}

SECTOR_KEYWORDS: Final[dict[str, tuple[str, ...]]] = {
    "market_gida": ("market", "gıda", "süt ürün", "bakliyat"),
    "akaryakit": ("akaryakıt", "benzin", "motorin", "yakıt"),
    "giyim_aksesuar": ("giyim", "ayakkabı", "tekstil", "moda", "aksesuar"),
    "elektronik_telekom": ("elektronik", "telekomünikasyon", "cep telefon", "bilgisayar"),
    "beyaz_esya_ev": ("beyaz eşya", "ev aletleri", "buzdolab", "çamaşır makine", "süpürge"),
    "mobilya_dekorasyon": ("mobilya", "dekorasyon", "koltuk", "yatak odası"),
    "yapi_hirdavat": ("yapı market", "hırdavat", "iklimlendirme", "klima", "inşaat malzeme"),
    "kuyum_optik_saat": ("kuyum", "optik", "gözlük", "pırlanta", "mücevher", "saat"),
    "eticaret_pazaryeri": ("e-ticaret", "online alışveriş", "pazaryeri", "internetten alışveriş"),
    "seyahat_konaklama": ("uçak bilet", "otel", "tatil", "seyahat", "konaklama", "turizm"),
    "ulasim_arac_kiralama": ("araç kiralama", "otopark", "toplu taşıma", "lastik", "araç bakım"),
    "restoran_kafe": ("restoran", "kafe", "yeme içme", "kahve"),
    "eglence_dijital": ("dijital abonelik", "sinema", "müzik", "oyun", "streaming"),
    "egitim_kitap": ("eğitim", "kitap", "kırtasiye", "okul", "üniversite", "kurs"),
    "saglik_kozmetik": ("sağlık", "kozmetik", "eczane", "kişisel bakım", "hastane"),
    "hobi_oyuncak_spor": ("hobi", "oyuncak", "spor", "outdoor", "çiçek"),
    "vergi_fatura_kamu": ("vergi", "fatura", "mtv", "trafik ceza", "kamu ödeme"),
    "sigorta": ("sigorta",),
    "yatirim_birikim": ("altın", "döviz", "fon", "yatırım", "birikim"),
    "konut_gayrimenkul": ("konut", "gayrimenkul", "emlak", "tapu"),
    "kurumsal_kobi": ("üye işyeri", "pos", "kurumsal", "kobi", "işletme"),
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
    "yeni_musteri": ("yeni müşteri", "ilk kez müşteri", "müşterimiz olan"),
    # ⚠️ "müşterilerimiz" ANAHTAR DEĞİL: neredeyse her kampanya metni
    # "müşterilerimize özel" diyor ve bu ifade yeni müşteri kampanyalarında da
    # geçiyor. Ölçümde her kampanyaya hem `yeni_musteri` hem `mevcut_musteri`
    # etiketi takılmasına yol açtı.
    "mevcut_musteri": ("mevcut müşteri", "hâlihazırda müşteri"),
    "maas_musterisi": ("maaş müşteri", "maaşını bankamız", "maaş alan"),
    "emekli": ("emekli", "emeklilik maaş"),
    "ogrenci": ("öğrenci", "üniversiteli"),
    "genc": ("genç", "18-25"),
    "kamu_calisani": ("kamu çalışan", "memur"),
    "banka_calisani": ("banka çalışan", "personelimiz"),
    "esnaf": ("esnaf",),
    "ciftci": ("çiftçi", "tarım"),
    "kobi": ("kobi",),
    "ticari_kurumsal": ("ticari müşteri", "kurumsal müşteri", "şirket"),
    "ozel_bankacilik": ("özel bankacılık", "private banking"),
}

BENEFIT_KEYWORDS: Final[dict[str, tuple[str, ...]]] = {
    "nakit_iade": ("nakit iade", "iade kazan", "para iade", "cashback", "geri ödeme"),
    "puan_mil": ("bankkart lira", "worldpuan", "paraf para", "puan", "mil"),
    "vade_farksiz_taksit": ("vade farksız", "peşin fiyatına"),
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
    "hediye_urun": ("hediye ürün", "hediyeniz"),
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
