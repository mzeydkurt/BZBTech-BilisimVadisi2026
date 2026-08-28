"""Başlangıç verisi: 10 katılım bankası + katılım bankacılığı terminoloji sözlüğü.

Kamuya açık kampanya sayfası olmayan bankalar da (Adil Katılım) veri setinde
bulunur; eksik verinin gerekçesi `notes` alanında açıkça yazılıdır. "Veri yok"
bilgisi de başlı başına bir bulgudur ve gizlenmez.

Not: İktisat Katılım proje kapsamı dışında bırakılmıştır (faaliyete henüz
geçmemiş olması nedeniyle); kapsam 10 banka ile sınırlıdır.

Bu betik IDEMPOTENT'tir: tekrar tekrar çalıştırılabilir, kayıt çoğaltmaz.
Mevcut kayıtların alanları güncellenir, yenileri eklenir.

Çalıştırma:
    python -m app.db.seed
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Bank, Campaign, GlossaryTerm
from app.db.session import SessionLocal
from app.logging_config import get_logger

logger = get_logger(__name__)

# ── 10 KATILIM BANKASI ────────────────────────────────────
# Alan adları ve domainler 8 Ağustos 2026'da doğrudan siteden doğrulanmıştır.
# `legacy_domains`: 302 ile kanonik adrese yönlenen eski alan adları. Scraper
# cross-host yönlendirmeyi takip eder; bu liste belgeleme amaçlı tutulur.
# `brand_color`: arayüzde bankayı ayırt etmek için kullanılan yaklaşık vurgu rengi
# (bankanın resmî marka varlığı değildir).
BANK_SEED: list[dict[str, Any]] = [
    {
        "code": "kuveyt_turk",
        "name": "Kuveyt Türk",
        "legal_name": "Kuveyt Türk Katılım Bankası A.Ş.",
        "website": "https://www.kuveytturk.com.tr",
        "legacy_domains": None,
        "bddk_status": "active",
        "tkbb_member": True,
        "data_status": "rich",
        "brand_color": "#00857C",
        "notes": (
            "Segment ayrımı URL'de açık (kendim-icin / isim-icin). Liste sayfası ilk 9 "
            "kampanyayı gösteriyor, gerisi AJAX arkasında. Sitemap'te kampanya URL'i yok."
        ),
    },
    {
        "code": "albaraka",
        "name": "Albaraka Türk",
        "legal_name": "Albaraka Türk Katılım Bankası A.Ş.",
        "website": "https://www.albaraka.com.tr",
        "legacy_domains": ["albarakaturk.com.tr"],
        "bddk_status": "active",
        "tkbb_member": True,
        "data_status": "rich",
        "brand_color": "#00A651",
        "notes": (
            "albarakaturk.com.tr adresi 302 ile albaraka.com.tr'ye yönleniyor. Tarih verisi "
            "bankalar arasında en tutarlı olan. robots.txt /*slug ve /tr/ticari-ve-kurumsal* "
            "yollarını yasaklıyor; bu yollara uyulur ve geçmiş kampanya arşivi kapsam dışıdır."
        ),
    },
    {
        "code": "turkiye_finans",
        "name": "Türkiye Finans",
        "legal_name": "Türkiye Finans Katılım Bankası A.Ş.",
        "website": "https://www.turkiyefinans.com.tr",
        "legacy_domains": None,
        "bddk_status": "active",
        "tkbb_member": True,
        "data_status": "limited",
        "brand_color": "#0F62A8",
        "notes": (
            "Sitemap kırık (login sayfasına yönleniyor), kullanılmıyor. Hiçbir kampanya "
            "sayfasında yapısal tarih alanı yok — start_date/end_date çoğunlukla NULL kalır. "
            "Buna karşılık gerçek HTML oran tabloları var (vade x kâr payı oranı). "
            "Tablo başlıklarında zero-width space ve nbsp bulunuyor."
        ),
    },
    {
        "code": "vakif_katilim",
        "name": "Vakıf Katılım",
        "legal_name": "Vakıf Katılım Bankası A.Ş.",
        "website": "https://www.vakifkatilim.com.tr",
        "legacy_domains": None,
        "bddk_status": "active",
        "tkbb_member": True,
        "data_status": "rich",
        "brand_color": "#00693C",
        "notes": (
            "Kampanya listesi JS ile yükleniyor (keşif tarayıcı gerektirir), detay sayfaları "
            "tam SSR. Geçersiz slug'da soft-404 üretiyor: HTTP 200 ile '404' başlıklı sayfa."
        ),
    },
    {
        "code": "ziraat_katilim",
        "name": "Ziraat Katılım",
        "legal_name": "Ziraat Katılım Bankası A.Ş.",
        "website": "https://www.ziraatkatilim.com.tr",
        "legacy_domains": None,
        "bddk_status": "active",
        "tkbb_member": True,
        "data_status": "rich",
        "brand_color": "#C8102E",
        "notes": (
            "WAF bazı yollarda standart dışı HTTP 493 döndürüyor — kalıcı hata sayılmaz, "
            "yeniden denenir. Kampanya keşfi 15 kategori sayfası üzerinden yapılır. "
            "?IsArchived=true parametresi geçmiş kampanya arşivini açar. Üç ayrı tarih formatı var."
        ),
    },
    {
        "code": "emlak_katilim",
        "name": "Türkiye Emlak Katılım",
        "legal_name": "Türkiye Emlak Katılım Bankası A.Ş.",
        "website": "https://www.emlakkatilim.com.tr",
        "legacy_domains": ["emlakbank.com.tr"],
        "bddk_status": "active",
        "tkbb_member": True,
        "data_status": "rich",
        "brand_color": "#E4002B",
        "notes": (
            "emlakbank.com.tr adresi 302 ile emlakkatilim.com.tr'ye yönleniyor. robots.txt "
            "tamamen açık, WAF yok, SSR, sayfalama yok — en kolay hedef. Kategori etiketi yok. "
            "Arşiv yok: biten kampanyalar siteden kalkıyor, ham HTML saklamak zorunlu."
        ),
    },
    {
        "code": "hayat_finans",
        "name": "Hayat Finans",
        "legal_name": "Hayat Finans Katılım Bankası A.Ş.",
        "website": "https://www.hayatfinans.com.tr",
        "legacy_domains": None,
        "bddk_status": "active",
        "tkbb_member": True,
        "data_status": "rich",
        "brand_color": "#00B0A6",
        "notes": (
            "Dijital banka ama içerik zengin. Kampanya listesi istemci tarafında oluşuyor; "
            "keşif için sitemap.xml birincil kaynaktır. Biten kampanyalar sert HTTP 404 "
            "döndürüyor ve geri gelmiyor — ham HTML arşivi kritik."
        ),
    },
    {
        "code": "tom_bank",
        "name": "T.O.M. Katılım Bankası",
        "legal_name": "T.O.M. Katılım Bankası A.Ş.",
        "website": "https://www.tombank.com.tr",
        "legacy_domains": ["hadiyanindakibanka.com", "haditombank.com"],
        "bddk_status": "active",
        "tkbb_member": True,
        "data_status": "rich",
        "brand_color": "#5B2D8E",
        "notes": (
            "Çok domainli: kurumsal sitede yalnızca 1 kampanya var, kampanyaların yaklaşık "
            "%90'ı tombankhadi.com adresinde. Yalnızca tombank.com.tr taranırsa veri "
            "setinde yanlışlıkla 'kampanya yok' sonucu çıkar."
        ),
    },
    {
        "code": "dunya_katilim",
        "name": "Dünya Katılım",
        "legal_name": "Dünya Katılım Bankası A.Ş.",
        "website": "https://www.dunyakatilim.com.tr",
        "legacy_domains": None,
        "bddk_status": "active",
        "tkbb_member": True,
        "data_status": "rich",
        "brand_color": "#1B4F9C",
        "notes": (
            "Ağır boilerplate: her sayfada 800-1500 kelimelik çerez ve footer metni var, "
            "kampanya metninden fazla olabiliyor. Slug'larda camelCase bulunuyor "
            "(küçük harfe çevirmek 404 üretir). Kampanya sayfaları siliniyor."
        ),
    },
    {
        "code": "adil_katilim",
        "name": "Adil Katılım",
        "legal_name": "Adil Katılım Bankası A.Ş.",
        "website": "https://www.adilkatilim.com.tr",
        "legacy_domains": None,
        "bddk_status": "active",
        "tkbb_member": True,
        "data_status": "none",
        "brand_color": "#6B7280",
        "notes": (
            "Lisanslı ancak ticari faaliyete geçmemiş: kampanya ve ürün sayfası YOK. "
            "Var olmayan her URL için HTTP 200 ile ana sayfa HTML'i döndürüyor "
            "(soft-404 catch-all) — içerik hash karşılaştırması zorunlu. "
            "Kampanya sayısı 0'dır; kayıt şartname 5.1 kapsamı için tutulur."
        ),
    },
]

# ── TERMİNOLOJİ SÖZLÜĞÜ ───────────────────────────────────
# Şartname 5.5'te açıkça sayılan 5 kavram ZORUNLUDUR (ilk 5 kayıt), üzerine eklenmiştir.
GLOSSARY_SEED: list[dict[str, Any]] = [
    {
        "term": "Kâr Payı Oranı",
        "conventional_equivalent": "faiz oranı",
        "category": "oran",
        "definition": (
            "Finansman işleminde (konut, taşıt, ihtiyaç) mal veya hizmet üzerinden "
            "hesaplanan kâr payı oranı. Katılma hesabı getirisi veya kâr paylaşım "
            "oranı ile karıştırılmamalıdır."
        ),
        "aliases": ["kar payi orani", "kâr payı oranı", "kar payı oranı", "kârpayı oranı"],
        "is_forbidden_conventional": False,
    },
    {
        "term": "Finansman Maliyeti",
        "conventional_equivalent": "kredi maliyeti",
        "category": "maliyet",
        "definition": (
            "Kullandırılan finansman kapsamında oluşan toplam geri ödeme tutarı ve "
            "müşterinin katlandığı toplam maliyet."
        ),
        "aliases": ["finansman maliyeti", "toplam maliyet"],
        "is_forbidden_conventional": False,
    },
    {
        "term": "Katılım Fonu",
        "conventional_equivalent": "mevduat",
        "category": "hesap",
        "definition": (
            "Katılım bankacılığı prensiplerine uygun olarak değerlendirilen, fon sahipleri "
            "ile banka arasında kâr-zarar paylaşımına dayanan hesap türü."
        ),
        "aliases": ["katilim fonu", "katılım fonu"],
        "is_forbidden_conventional": False,
    },
    {
        "term": "Masrafsız Finansman",
        "conventional_equivalent": "masrafsız kredi",
        "category": "urun",
        "definition": (
            "Finansman işlemi kapsamında tahsis ücreti, dosya masrafı veya benzeri ek "
            "maliyetlerin uygulanmadığı finansman türü."
        ),
        "aliases": ["masrafsiz finansman", "masrafsız finansman", "masrafsız"],
        "is_forbidden_conventional": False,
    },
    {
        "term": "Avantajlı Finansman",
        "conventional_equivalent": "indirimli kredi",
        "category": "urun",
        "definition": (
            "Standart finansman koşullarına göre daha uygun maliyet, kâr payı oranı veya "
            "ek fayda sunan kampanyalı finansman ürünü."
        ),
        "aliases": ["avantajli finansman", "avantajlı finansman", "özel oranlı finansman"],
        "is_forbidden_conventional": False,
    },
    # ── Ek kavramlar ──────────────────────────────────────
    {
        "term": "Katılma Hesabı",
        "conventional_equivalent": "vadeli mevduat hesabı",
        "category": "hesap",
        "definition": (
            "Kâr-zarar ortaklığına dayalı, önceden sabit bir getiri taahhüdü içermeyen "
            "vadeli hesap türü. Standart ve ara ödemeli alt türleri vardır."
        ),
        "aliases": ["katilma hesabi", "katılma hesabı"],
        "is_forbidden_conventional": False,
    },
    {
        "term": "Standart Katılma Hesabı",
        "conventional_equivalent": "vadeli mevduat hesabı",
        "category": "hesap",
        "definition": (
            "Vade sonunda anapara ve dağıtılan kâr payının birlikte hesaba aktarıldığı "
            "klasik katılma hesabı. TKBB veri peteğinde «Katılma Hesabı» satırı olarak "
            "yayımlanır; vade boyunca ara dönem ödemesi yapılmaz."
        ),
        "aliases": [
            "standart katilma",
            "standart katilma hesabi",
            "standart katılma hesabı",
            "normal katilma hesabi",
            "normal katılma hesabı",
        ],
        "is_forbidden_conventional": False,
    },
    {
        "term": "Ara Ödemeli Katılma Hesabı",
        "conventional_equivalent": "ara dönem faiz ödemeli mevduat",
        "category": "hesap",
        "definition": (
            "Vade içinde belirli dönemlerde (ör. 3 veya 6 ayda bir) kâr payı ödemesi "
            "yapılabilen katılma hesabı. Standart katılma hesabında kâr payı genellikle "
            "yalnızca vade sonunda dağıtılır; ara ödemeli hesapta müşteri vade bitmeden "
            "de kâr payı alabilir. TKBB'de getiri oranları standart hesaptan ayrı "
            "satırda yayımlanır; tüm katılım bankaları bu ürünü sunmayabilir."
        ),
        "aliases": [
            "ara odemeli katilma",
            "ara odemeli katilma hesabi",
            "ara ödemeli katılma",
            "ara ödemeli katılma hesabı",
            "ara donem kar odemeli",
            "ara dönem kâr ödemeli",
        ],
        "is_forbidden_conventional": False,
    },
    {
        "term": "Kâr Paylaşım Oranı",
        "conventional_equivalent": None,
        "category": "oran",
        "definition": (
            "Katılma hesabında bankanın dağıttığı kârdan müşteriye düşen pay "
            "(ör. %90 müşteri / %10 banka). Dağıtılan kâr payı (getiri) yüzdesi "
            "değildir; iki gösterge ayrı tablolarda yer alır."
        ),
        "aliases": ["kar paylasim orani", "kâr paylaşım oranı", "kar paylaşım oranı"],
        "is_forbidden_conventional": False,
    },
    {
        "term": "Dağıtılan Kâr Payı (Getiri)",
        "conventional_equivalent": "mevduat faizi",
        "category": "oran",
        "definition": (
            "Katılma hesabında dönem sonunda müşteriye aktarılan yıllık getiri "
            "oranıdır (TKBB veri peteğinde vade vade yayımlanır). Kâr paylaşım "
            "oranından farklıdır; getiri hesabında bu oran kullanılır."
        ),
        "aliases": [
            "dagitilan kar payi",
            "dağıtılan kâr payı",
            "katilma getirisi",
            "katılma getirisi",
            "katilma hesabi getiri",
        ],
        "is_forbidden_conventional": False,
    },
    {
        "term": "Stopaj (Katılma Getirisi)",
        "conventional_equivalent": "vergi kesintisi",
        "category": "vergi",
        "definition": (
            "Katılma hesabından elde edilen kâr payı getirisine uygulanan kaynakta "
            "kesinti. Brüt getiriden düşülerek net getiri hesaplanır; oranlar "
            "mevzuat ve Cumhurbaşkanı Kararı ile belirlenir."
        ),
        "aliases": ["stopaj", "stopaj orani", "stopaj kesintisi", "vergi kesintisi"],
        "is_forbidden_conventional": False,
    },
    {
        "term": "Finansman",
        "conventional_equivalent": "kredi",
        "category": "urun",
        "definition": (
            "Katılım bankasının, alım-satım veya ortaklık esaslı yöntemlerle müşteriye "
            "kullandırdığı fon."
        ),
        "aliases": ["finansman", "finansman kullandırımı"],
        "is_forbidden_conventional": False,
    },
    {
        "term": "Tahsis Ücreti",
        "conventional_equivalent": None,
        "category": "ucret",
        "definition": "Finansman tahsisi karşılığında bir kez alınan ücret.",
        "aliases": ["tahsis ucreti", "tahsis ücreti", "dosya masrafı"],
        "is_forbidden_conventional": False,
    },
    {
        "term": "Vade",
        "conventional_equivalent": None,
        "category": "vade",
        "definition": "Finansmanın geri ödeme süresi; genellikle ay cinsinden ifade edilir.",
        "aliases": ["vade", "vade süresi"],
        "is_forbidden_conventional": False,
    },
    {
        "term": "Kâr Payı",
        "conventional_equivalent": "faiz",
        "category": "oran",
        "definition": (
            "Katılım bankacılığında, alım-satım veya ortaklık işleminden doğan ve "
            "taraflar arasında paylaşılan kazanç."
        ),
        "aliases": ["kar payi", "kâr payı", "kar payı"],
        "is_forbidden_conventional": False,
    },
    {
        "term": "Vade Farksız Taksit",
        "conventional_equivalent": "faizsiz taksit",
        "category": "vade",
        "definition": (
            "Peşin fiyat üzerine ek bir maliyet bindirilmeden yapılan taksitli ödeme; "
            "kampanya metinlerinde 'peşin fiyatına taksit' olarak da geçer."
        ),
        "aliases": ["vade farksiz", "vade farksız", "peşin fiyatına taksit"],
        "is_forbidden_conventional": False,
    },
    {
        "term": "Murabaha",
        "conventional_equivalent": "ticari alım-satım finansmanı",
        "category": "yontem",
        "definition": (
            "Bankanın peşin satın aldığı malı, kâr koyarak müşteriye vadeli satması esasına "
            "dayanan finansman yöntemi."
        ),
        "aliases": ["murabaha", "peşin alım vadeli satış"],
        "is_forbidden_conventional": False,
    },
    {
        "term": "Mudarabe",
        "conventional_equivalent": "emek-sermaye ortaklığı",
        "category": "yontem",
        "definition": (
            "Bir tarafın sermaye, diğer tarafın emek koyarak oluşturduğu kâr-zarar ortaklığı "
            "modeli."
        ),
        "aliases": ["mudarabe", "emek sermaye ortaklığı"],
        "is_forbidden_conventional": False,
    },
    {
        "term": "Müşareke",
        "conventional_equivalent": "sermaye ortaklığı",
        "category": "yontem",
        "definition": (
            "Tarafların sermaye koyarak kâr ve zarara oranları nispetinde ortak olduğu finansman "
            "yöntemi."
        ),
        "aliases": ["musareke", "müşareke", "sermaye ortaklığı"],
        "is_forbidden_conventional": False,
    },
    {
        "term": "İcare",
        "conventional_equivalent": "finansal kiralama / leasing",
        "category": "yontem",
        "definition": (
            "Bir varlığın kullanım hakkının belirli bir süre ve kira bedeli karşılığında "
            "devredilmesi esasına dayanan yöntem."
        ),
        "aliases": ["icare", "kiralama finansmanı"],
        "is_forbidden_conventional": False,
    },
    {
        "term": "Selem",
        "conventional_equivalent": "ön ödemeli sipariş finansmanı",
        "category": "yontem",
        "definition": (
            "Bedeli peşin ödenip teslimatı ileri bir tarihte yapılan standart malların finansman "
            "yöntemi."
        ),
        "aliases": ["selem"],
        "is_forbidden_conventional": False,
    },
    {
        "term": "İstisna",
        "conventional_equivalent": "eser/imalat finansmanı",
        "category": "yontem",
        "definition": (
            "Sipariş üzerine imal edilecek veya inşa edilecek eser ve malların finansmanı yöntemi."
        ),
        "aliases": ["istisna", "imalat finansmanı"],
        "is_forbidden_conventional": False,
    },
    {
        "term": "Sukuk",
        "conventional_equivalent": "tahvil/bono",
        "category": "yatirim",
        "definition": (
            "Sermaye piyasalarında faizsiz prensiplere uygun olarak ihraç edilen kira sertifikası "
            "veya varlığa dayalı menkul kıymet."
        ),
        "aliases": ["sukuk", "kira sertifikası"],
        "is_forbidden_conventional": False,
    },
    {
        "term": "Tekafül",
        "conventional_equivalent": "sigorta",
        "category": "sigorta",
        "definition": (
            "Katılımcıların karşılıklı yardımlaşma ve dayanışma esasına dayalı olarak oluşturduğu "
            "faizsiz sigortacılık sistemi."
        ),
        "aliases": ["tekaful", "tekafül", "katılım sigortacılığı"],
        "is_forbidden_conventional": False,
    },
    {
        "term": "Karz-ı Hasen",
        "conventional_equivalent": "faizsiz karşılıksız borç",
        "category": "urun",
        "definition": (
            "Hiçbir kâr payı veya vade farkı eklenmeksizin yalnızca anaparanın geri ödenmesi "
            "esasına dayanan borçlandırma."
        ),
        "aliases": ["karz i hasen", "karzı hasen", "faizsiz borç"],
        "is_forbidden_conventional": False,
    },
    {
        "term": "Katılım Bankası",
        "conventional_equivalent": "İslami / faizsiz banka",
        "category": "kurum",
        "definition": (
            "Faizsiz finans prensipleriyle çalışan banka kurumu. "
            "Katılma hesabı (ürün) veya katılım fonu (fon sahipliği) ile karıştırılmamalıdır."
        ),
        "aliases": ["katilim bankasi", "katılım bankası", "islami banka"],
        "is_forbidden_conventional": False,
    },
    {
        "term": "Katılım Fonu",
        "conventional_equivalent": "mevduat / fon sahipliği",
        "category": "urun",
        "definition": (
            "Katılım bankasında fon sahiplerinin hesap tarafındaki genel adıdır. "
            "Vadeli kâr-zarar ortaklıklı ürün ise katılma hesabıdır; kurum adı katılım bankasıdır."
        ),
        "aliases": ["katilim fonu", "katılım fonu"],
        "is_forbidden_conventional": False,
    },
    {
        "term": "LTV (Kredi / Teminat Oranı)",
        "conventional_equivalent": "kredi/değer oranı",
        "category": "limit",
        "definition": (
            "Finansman tutarının gayrimenkul veya taşıtın ekspertiz/fatura değerine azami oranı "
            "(Loan-to-Value)."
        ),
        "aliases": ["ltv", "kredi değer oranı", "teminat oranı"],
        "is_forbidden_conventional": False,
    },
    # ── YASAKLI KONVANSİYONEL TERİMLER ────────────────────
    # `conventional_equivalent` bu satırlarda kullanılması GEREKEN katılım karşılığını taşır.
    # PART 3'teki terminoloji koruması bu kayıtları kullanacaktır.
    {
        "term": "faiz",
        "conventional_equivalent": "kâr payı",
        "category": "yasakli",
        "definition": "Konvansiyonel bankacılık terimi. Katılım bankacılığında kullanılmaz.",
        "aliases": ["faiz", "interest"],
        "is_forbidden_conventional": True,
    },
    {
        "term": "faiz oranı",
        "conventional_equivalent": "kâr payı oranı",
        "category": "yasakli",
        "definition": "Konvansiyonel bankacılık terimi. Katılım bankacılığında kullanılmaz.",
        "aliases": ["faiz orani", "faiz oranı", "interest rate"],
        "is_forbidden_conventional": True,
    },
    {
        "term": "kredi",
        "conventional_equivalent": "finansman",
        "category": "yasakli",
        "definition": "Konvansiyonel bankacılık terimi. Katılım bankacılığında kullanılmaz.",
        "aliases": ["kredi", "loan"],
        "is_forbidden_conventional": True,
    },
    {
        "term": "kredi faizi",
        "conventional_equivalent": "finansman kâr payı",
        "category": "yasakli",
        "definition": "Konvansiyonel bankacılık terimi. Katılım bankacılığında kullanılmaz.",
        "aliases": ["kredi faizi"],
        "is_forbidden_conventional": True,
    },
    {
        "term": "mevduat",
        "conventional_equivalent": "katılım fonu",
        "category": "yasakli",
        "definition": "Konvansiyonel bankacılık terimi. Katılım bankacılığında kullanılmaz.",
        "aliases": ["mevduat", "deposit"],
        "is_forbidden_conventional": True,
    },
    {
        "term": "vadeli mevduat",
        "conventional_equivalent": "katılma hesabı",
        "category": "yasakli",
        "definition": "Konvansiyonel bankacılık terimi. Katılım bankacılığında kullanılmaz.",
        "aliases": ["vadeli mevduat", "time deposit"],
        "is_forbidden_conventional": True,
    },
]


def seed_banks(session: Session) -> tuple[int, int]:
    """Banka kayıtlarını ekler veya günceller.

    Returns:
        (eklenen, güncellenen) sayıları.
    """
    inserted = 0
    updated = 0

    for row in BANK_SEED:
        bank = session.scalar(select(Bank).where(Bank.code == row["code"]))
        if bank is None:
            session.add(Bank(**row))
            inserted += 1
            continue

        changed = False
        for field, value in row.items():
            if getattr(bank, field) != value:
                setattr(bank, field, value)
                changed = True
        if changed:
            updated += 1

    session.flush()
    return inserted, updated


def seed_glossary(session: Session) -> tuple[int, int]:
    """Terminoloji sözlüğü kayıtlarını ekler veya günceller.

    Returns:
        (eklenen, güncellenen) sayıları.
    """
    inserted = 0
    updated = 0

    for row in GLOSSARY_SEED:
        entry = session.scalar(select(GlossaryTerm).where(GlossaryTerm.term == row["term"]))
        if entry is None:
            session.add(GlossaryTerm(**row))
            inserted += 1
            continue

        changed = False
        for field, value in row.items():
            if getattr(entry, field) != value:
                setattr(entry, field, value)
                changed = True
        if changed:
            updated += 1

    session.flush()
    return inserted, updated


def remove_obsolete_banks(session: Session) -> int:
    """Kapsamdan çıkarılan bankaları veritabanından siler.

    Seed listesi tek doğruluk kaynağıdır: listeden çıkarılan bir banka
    veritabanında kalmaya devam ederse API hâlâ o bankayı döndürür ve kapsam
    ile veri birbirinden ayrışır.

    ⚠️ GÜVENLİK KİLİDİ: Kampanyası bulunan bir banka SİLİNMEZ, yalnızca
    uyarı loglanır. Aksi hâlde seed'de yapılan bir yazım hatası, toplanmış
    kampanya verisini zincirleme silebilirdi.

    Args:
        session: Veritabanı oturumu.

    Returns:
        Silinen banka sayısı.
    """
    gecerli_kodlar = {row["code"] for row in BANK_SEED}
    silinen = 0

    for bank in session.scalars(select(Bank).where(Bank.code.notin_(gecerli_kodlar))):
        kampanya_sayisi = (
            session.scalar(
                select(func.count()).select_from(Campaign).where(Campaign.bank_id == bank.id)
            )
            or 0
        )

        if kampanya_sayisi:
            logger.warning(
                "kapsam_disi_banka_silinmedi",
                banka=bank.code,
                kampanya_sayisi=kampanya_sayisi,
                not_="Kampanyası olan banka otomatik silinmez; elle karar verin.",
            )
            continue

        logger.info("kapsam_disi_banka_silindi", banka=bank.code)
        session.delete(bank)
        silinen += 1

    session.flush()
    return silinen


def run_seed(session: Session) -> dict[str, int]:
    """Tüm seed verisini uygular ve özet döndürür."""
    banks_inserted, banks_updated = seed_banks(session)
    banks_removed = remove_obsolete_banks(session)
    glossary_inserted, glossary_updated = seed_glossary(session)
    session.commit()

    summary = {
        "banks_inserted": banks_inserted,
        "banks_updated": banks_updated,
        "banks_removed": banks_removed,
        "glossary_inserted": glossary_inserted,
        "glossary_updated": glossary_updated,
        "banks_total": len(BANK_SEED),
        "glossary_total": len(GLOSSARY_SEED),
    }
    logger.info("seed_tamamlandi", **summary)
    return summary


def main() -> None:
    """CLI girişi: `python -m app.db.seed`."""
    with SessionLocal() as session:
        run_seed(session)


if __name__ == "__main__":
    main()
