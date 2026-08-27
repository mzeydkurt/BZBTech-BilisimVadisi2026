"""Kural tabanlı çıkarımın tüm düzenli ifadeleri.

⚠️ KALIPLAR HAM `clean_text` ÜZERİNDE ÇALIŞIR, katlanmış metinde değil.
Sebep: her çıkarımın karakter aralığı (`evidence_char_start/end`) kaynağa
BİREBİR uymak zorunda — `clean_text[start:end] == evidence_text`. Katlama
(`ascii_fold_tr`) ya da boşluk sadeleştirme (`normalize_text`) metnin
uzunluğunu değiştirir ve ofsetler kayar; kanıt gösterimi sessizce yanlış
parçayı işaret eder.

Bu yüzden Türkçe harf çeşitleri kalıbın İÇİNE yazılır (`[kK][âaÂA]r`),
metin dönüştürülerek çözülmez.
"""

from __future__ import annotations

import re
from typing import Final

# ⚠️ YAKINLIK KURALI. Bir sayı bulundu diye alan atanmaz; sayının hangi
# kavrama ait olduğu çevresindeki kelimeyle doğrulanır. "5.000 TL ve üzeri
# harcamalarda 250 TL" metninde iki tutar var ve hangisinin eşik hangisinin
# ödül olduğu yalnızca komşu kelimeden anlaşılır.
PROXIMITY_CHARS: Final[int] = 40

# Türkçe harf çeşitleri — büyük/küçük ve şapkalı biçimler.
_KAR = r"[kK][âaÂA]r"
_PAYI = r"[pP]ay[ıiİI]"

# ⚠️ KESME İŞARETİ TEK BİÇİMDE GELMİYOR. Bankaların içerik yönetim sistemi
# tipografik U+2019 (’) üretiyor; ASCII (') yalnızca elle yazılmış metinlerde
# geçiyor. Yalnızca ASCII beklendiğinde "1.000 TL’ye Varan Nakit İade" ve
# "%10’una kadar nakit iade" gibi ifadeler sessizce kaçıyordu — gold set
# üzerinde ölçüldü, `reward_amount_try` ve `cashback_pct` kayıplarının bir
# bölümü doğrudan bu karakterden kaynaklanıyor.
_KESME = r"['’‘ʼ´`]"

# ⚠️ Şartname §5.6 "500 TL, 500₺ ve 500 Türk Lirası aynı değer olarak
# algılanmalıdır" diyor. Para birimi UZUN ADIYLA da yazılabilir; yalnızca
# kısaltma arandığında "500 Türk Lirası" sessizce kaçıyordu.
_TL = r"(?:TL|TL\.|₺|[Tt][üuÜU]rk\s*[Ll]iras[ıiİI])"

# ⚠️ TUTAR ÇARPAN SÖZCÜĞÜYLE YAZILIYOR: "3 milyon TL'ye kadar",
# "200 Bin TL'ye kadar", "1 Milyon TL ye kadar". Gövdede 262 geçiş ölçüldü.
# `parse_money` çarpanı ZATEN çözüyor (`_MULTIPLIERS`); eksik olan kalıbın
# çarpanı eşleşmeye DAHİL ETMESİYDİ — "3 milyon TL" ifadesinde yalnızca "3"
# görülüyor ve tutar 3 TL sanılıyordu. Sayı ile birim arasına en fazla BİR
# çarpan sözcüğü girebilir; serbest bırakılırsa araya cümle sızar.
_CARPAN = r"(?:\s*(?:bin|milyon|milyar))?"
_TUTAR = rf"[\d.,]+{_CARPAN}"

# ⚠️ SADAKAT BİRİMİ ÖDÜL ADINDAN AYRI YAZILIYOR. "750 TL Bankkart Lira"
# ifadesinde tutar ile ödül adı arasında MARKA KELİMESİ var; ödül adını
# tutara bitişik arayan kalıp 6 kampanyayı kaçırıyordu. Program adları
# bütün olarak tanınır.
#
# ⚠️ `Mil` ve `Puan` sonuna `\b` ZORUNLU: aksi hâlde "Miles&Smiles" ve
# "Puanlarınız" gibi kelimelerin içinde eşleşir.
_SADAKAT = r"(?:Bankkart\s*Lira|Paraf\s*?Para|World\s*?Puan|Mil|Puan)"

# "'ye varan" · "’ye kadar" · "'e varan" — tutar ile ödül adı arasına giren
# tek ek. Sınırsız doldurma YOK: araya kelime girmesine izin verilirse
# metindeki herhangi bir tutar herhangi bir ödüle bağlanır.
_VARAN = rf"(?:{_KESME}?\s*[yn]?[ae]\s*(?:varan|kadar)\s*)?"

# Aynı ek, tutar–birim çiftinden SONRA gelen ve ZORUNLU olan biçimi.
# ⚠️ Kesme işareti yerine BOŞLUK da yazılıyor ("1 Milyon TL ye kadar",
# gövdede 12 geçiş): `{_KESME}?` isteğe bağlı olduğu için bu biçim de
# eşleşir, ama araya giren boşluk `\s*` ile açıkça karşılanmak zorunda.
#
# ⚠️ "VARAN" BURADA YOK ve olmaması ÖLÇÜLDÜ. `MAX_SPEND` kalıbına "varan"
# eklenince "500 TL'ye varan nakit iade" ifadesi harcama TAVANI sayıldı:
# 30 kampanyada uydurma `max_spend_try` doğdu ve alanın F1'i 0,67 → 0,57
# düştü. "kadar" ve "ulaşan" bir SINIRI anlatır, "varan" bir ÖDÜLÜ.
# Finansman tutarında ("1.000.000 TL'ye varan finansman") ikisi de sınır
# anlatır; oraya ayrı ek yazılır.
_UST_SINIR_EKI = rf"{_KESME}?\s*[yn]?[ae]\s*(?:kadar|ula[şs]an)"

# Finansman tavanında "varan" da sınır anlatır ("1.000.000 TL'ye varan
# finansman" bir üst limittir, ödül değil).
_FINANSMAN_SINIR_EKI = rf"{_KESME}?\s*[yn]?[ae]\s*(?:kadar|varan|ula[şs]an)"

# ⚠️ Şartname §5.6: "%2,05, % 2.05 ve 2.05 % aynı değer olarak
# yorumlanmalıdır." Yüzde işareti sayının SONUNA da yazılabiliyor; yalnızca
# önde arandığında "2.05 %" hiç okunmuyordu.
#
# ⚠️ "YÜZDE" SÖZCÜK OLARAK DA YAZILIYOR. `normalization/rate.py` bu biçimi
# ilk günden çözüyordu ama çıkarım kalıbı yalnızca `%` işaretini arıyordu:
# "kâr payı oranı yüzde 2,05" cümlesi ayrıştırıcıya hiç ULAŞMIYORDU.
# Gövdede 104 geçiş ölçüldü (paraf değişmezlik kümesi, E2).
_YUZDE_SAYI = r"(?:%\s*\d+(?:[.,]\d+)?|\d+(?:[.,]\d+)?\s*%|y[üu]zde\s*\d+(?:[.,]\d+)?)"

# ⚠️ Şartname §5.2 farklı ifade biçimlerini örnekliyor: "özel oranlı
# finansman", "avantajlı kâr payı fırsatı", "düşük maliyetli finansman".
# Bu ifadelerde oran, "kâr payı" kelimesinden UZAKTA duruyor:
#     "Özel oranlı finansman imkânı %1,89 ile sunulmaktadır."
# Kalıp "kâr payı" bitişikliği aradığı için %1,89 kaçıyordu.
_ORAN_BAGLAMI = (
    r"(?:[öo]zel\s*oranl[ıi]"
    r"|avantajl[ıi]\s*(?:oran|k[âa]r\s*pay[ıi])"
    r"|kampanyal[ıi]\s*oran"
    r"|d[üu][şs][üu]k\s*maliyetli"
    r"|indirimli\s*oran)"
)

# ── Kâr payı oranı ────────────────────────────────────────
# "%2,05 kâr payı" · "kâr payı oranı %2,05" · "%2,05 oranlı" · "2.05 %"
# · "özel oranlı finansman ... %1,89"
PROFIT_RATE: Final[re.Pattern[str]] = re.compile(
    rf"(?:{_KAR}\s*{_PAYI}(?:\s*oran[ıiİI])?\s*[:\-]?\s*{_YUZDE_SAYI}"
    rf"|{_YUZDE_SAYI}\s*(?:oran[lı]|{_KAR}\s*{_PAYI})"
    # ⚠️ Bağlam ile oran arasına en fazla İKİ kelime girebilir. Sınır
    # gevşetilirse cümledeki herhangi bir yüzde orana bağlanır ve indirim
    # ya da iade oranları kâr payı sanılır — `profit_rate_pct` kesinliği
    # 0.48'e kadar düşüyordu.
    rf"|{_ORAN_BAGLAMI}(?:\s+\S+){{0,2}}\s+{_YUZDE_SAYI}"
    rf")",
    re.IGNORECASE,
)

# ⚠️ "vade farksız" ve "peşin fiyatına" ORAN SIFIR demektir — bilinmeyen
# değil. İkisi karıştırılırsa "en düşük kâr payı" karşılaştırması bu
# kampanyaları hiç görmez.
# ⚠️ "vade farkı yok" biçimi `normalization/rate.py`de çözülüyordu ama
# çıkarım kalıbında yoktu; aynı olgunun iki yazımından biri sessizce
# kaçıyordu (paraf değişmezlik kümesi, E2).
ZERO_RATE: Final[re.Pattern[str]] = re.compile(
    r"(vade\s*farks[ıi]z|vade\s*fark[ıi]\s*yok|pe[şs]in\s*fiyat[ıi]na)", re.IGNORECASE
)

# ── Katılma hesabı paylaşım oranı ─────────────────────────
# ⚠️ PAYLAŞIM ORANI YÜZDE OLARAK YAZILMIYOR. Katılım bankaları bunu
# `98/2` biçiminde — banka payı / müşteri payı — yayımlıyor
# ("98/2 kâr paylaşım oranı ile birikime başlayın"). MÜŞTERİ PAYI ikinci
# sayıdır; yüzde arayan bir kalıp bu ifadeyi hiç görmez.
#
# ⚠️ Bu alan finansmandaki `profit_rate_pct` ile KARIŞTIRILMAZ: yönü ters,
# biri müşterinin ödediği, diğeri müşteriye dağıtılan paydır.
PROFIT_SHARE_RATIO: Final[re.Pattern[str]] = re.compile(
    rf"\d{{1,3}}\s*/\s*(\d{{1,3}})\s*(?:{_KAR}\s*)?payla[şs][ıi]m\s*oran"
    rf"|payla[şs][ıi]m\s*oran[ıi]\s*[:\-]?\s*\d{{1,3}}\s*/\s*(\d{{1,3}})",
    re.IGNORECASE,
)

# ⚠️ TUZAK: "avantajlı kâr payı" bir ORAN BELİRTMEZ. Eşleşirse alan
# çıkarılmaz; sayı arayan kalıp bu ifadeyi zaten yakalamaz ama LLM'e
# "zaten bulundu" denmemesi için ayrıca işaretlenir.
VAGUE_RATE: Final[re.Pattern[str]] = re.compile(
    rf"avantaj[lı]{{1,2}}\s*{_KAR}\s*{_PAYI}|[öo]zel\s*oran[lı]{{1,2}}", re.IGNORECASE
)

# "%20 indirim" / "%80 LTV" / "%10 nakit iade" kâr payı değildir.
# Eşleşme penceresinde bunlar varsa ve "kâr payı" yoksa aday elenir.
RATE_TRAP: Final[re.Pattern[str]] = re.compile(
    r"indirim|nakit\s*iade|teminat|pe[şs]inat"
    r"|enerji\s*s[ıi]n[ıi]f|\bLTV\b|kredi\s*oran",
    re.IGNORECASE,
)

# ── Taksit ────────────────────────────────────────────────
# ⚠️ "4 aya varan TAKSİT" taksit sayısıdır, VADE DEĞİLDİR. Vade kalıbı
# "taksit" kelimesi geçen eşleşmeleri dışlar.
INSTALLMENT: Final[re.Pattern[str]] = re.compile(
    r"\d{1,3}\s*(?:aya\s*varan\s*)?taksit|taksit\s*say[ıi]s[ıi]\s*[:\-]?\s*\d{1,3}",
    re.IGNORECASE,
)

# ── Vade ──────────────────────────────────────────────────
# "120 ay" · "120 aya kadar" · "3-36 ay" · "10 yıl"
TERM: Final[re.Pattern[str]] = re.compile(
    r"\d{1,3}\s*[-–]\s*\d{1,3}\s*ay\b|\d{1,3}\s*ay(?:a\s*(?:kadar|varan))?\b|\d{1,2}\s*y[ıi]l\b",
    re.IGNORECASE,
)

# ── Tutar eşiği ve ödül ───────────────────────────────────
# "5.000 TL ve üzeri" · "asgari 5.000 TL" · "en az 1.000 TL"
# ⚠️ Birim `_TL` ile aranır (şartname §5.6: "500 TL, 500₺ ve 500 Türk
# Lirası aynı değer"), tutar `_TUTAR` ile (çarpan sözcüğü dahil).
# "5.000 TL'den başlayan" alt sınır işaretçisi `normalization/money.py`de
# `_LOWER_BOUND_RE` içinde vardı ama çıkarım kalıbında YOKTU.
MIN_SPEND: Final[re.Pattern[str]] = re.compile(
    rf"(?:asgari|en\s*az|minimum)\s*{_TUTAR}\s*{_TL}"
    rf"|{_TUTAR}\s*{_TL}\s*(?:ve\s*)?[üu]zeri"
    rf"|{_TUTAR}\s*{_TL}\s*{_KESME}?\s*[dt]en\s*(?:ba[şs]layan|itibaren)",
    re.IGNORECASE,
)

# "1.000 TL - 100.000 TL arası" · "2.000 TL- 300.000 TL arasındaki"
# İki uç TEK eşleşmede yakalanır; `parse_money` bir dizedeki İLK tutarı
# döndürdüğü için uçlar ayrı gruplara alınmak zorunda.
SPEND_RANGE: Final[re.Pattern[str]] = re.compile(
    rf"([\d.,]+)\s*{_TL}\s*[-–—]\s*([\d.,]+)\s*{_TL}\s*aras",
    re.IGNORECASE,
)

# "100.000 TL’ye kadar" · "150.000 TL'ye ulaşan" · "75 TL ve altı"
MAX_SPEND: Final[re.Pattern[str]] = re.compile(
    rf"({_TUTAR})\s*{_TL}\s*{_UST_SINIR_EKI}"
    rf"|({_TUTAR})\s*{_TL}\s*ve\s*alt[ıi]",
    re.IGNORECASE,
)

# ⚠️ FİNANSMAN BAĞLAMI. Aynı aralık ifadesi hem harcama eşiği hem finansman
# limiti olabiliyor; ayrımı çevredeki kelime yapar. Bağlam yoksa yalnızca
# harcama alanları doldurulur — finansman limiti UYDURULMAZ.
#
# ⚠️ `taksit` ve çıplak `kredi` BİLEREK YOK. Kart kampanyasında "6 taksit" +
# "100.000 TL'ye kadar" geçince tutar finansman tavanı yazılıyordu (gold'da
# `financing_amount_max` FP'nin büyük kısmı). Gerçek limit `FINANCING_AMOUNT`
# kalıbıyla ("… kadar finansman") zaten yakalanır.
FINANCING_CONTEXT: Final[re.Pattern[str]] = re.compile(
    r"finansman|[öo]deme\s*kolayl[ıi][ğg][ıi]", re.IGNORECASE
)

# Ödül adları. "nakit ödül" (Hayat Finans) eskiden listede yoktu.
_ODUL_ADI = (
    r"(?:nakit\s*iade|iade|nakit\s*[öo]d[üu]l|[öo]d[üu]l"
    r"|hediye|puan|para|lira|indirim|de[ğg]erinde)"
)

# "250 TL nakit iade" · "500 TL Bankkart Lira" · "2.000 TL nakit ödül"
REWARD_AMOUNT: Final[re.Pattern[str]] = re.compile(
    rf"{_TUTAR}\s*{_TL}\s*{_VARAN}(?:{_SADAKAT}\b|{_ODUL_ADI})",
    re.IGNORECASE,
)

# "200 TL ParafPara" · "10.000 Mil'e Varan" · "500 TL Bankkart Lira"
#
# ⚠️ `TL` İSTEĞE BAĞLI: "10.000 Mil" tutarı TL cinsinden DEĞİLDİR ve gold
# set'te yalnızca `loyalty_points` doluyor, `reward_amount_try` boş kalıyor.
# `reward_amount_try` kalıbı `TL` zorunlu tutarak bu ayrımı korur.
LOYALTY_POINTS: Final[re.Pattern[str]] = re.compile(
    rf"{_TUTAR}\s*(?:{_TL}\s*)?{_VARAN}{_SADAKAT}\b",
    re.IGNORECASE,
)

# ⚠️ TOPLU ÜST SINIR TEK ÖDÜL DEĞİLDİR. "kişi başı maksimum 2.000 TL,
# toplamda 5 kişi için maksimum 10.000 TL nakit ödül" metninde kampanyanın
# bir kişiye vaat ettiği ödül 2.000'dir; 10.000 bütün davetlerin toplam
# tavanıdır. Bu önek görülen eşleşme ödül adayı sayılmaz.
AGGREGATE_CAP: Final[re.Pattern[str]] = re.compile(
    r"toplamda?\s*\d+\s*ki[şs]i|ki[şs]i\s*i[çc]in", re.IGNORECASE
)

# ── Kademeli ödül yapısı ──────────────────────────────────
# "5.000 TL ve üzeri harcamaya 250 TL, 10.000 TL ve üzeri harcamaya 500 TL"
#
# ⚠️ KALIP HAM `clean_text` ÜZERİNDE ÇALIŞIR, `parse_tier_structure` İLE
# DEĞİL. `normalization/money.py` içindeki `parse_tier_structure` aynı işi
# yapıyor ama NORMALİZE EDİLMİŞ metin üzerinde: `normalize_text` metnin
# uzunluğunu değiştirdiği için oradan dönen eşleşmenin konumu `clean_text`e
# UYMAZ ve `clean_text[start:end] == evidence_text` değişmezi (KAPI A4)
# sessizce bozulur. Kanıt gösterimi metnin yanlış yerini işaret eder.
#
# ⚠️ EŞİK İLE ÖDÜL ARASI EN FAZLA 60 KARAKTER. Sınır gevşetilirse cümledeki
# herhangi bir eşik cümledeki herhangi bir tutara bağlanır.
TIER: Final[re.Pattern[str]] = re.compile(
    rf"({_TUTAR})\s*{_TL}\s*(?:ve\s*)?[üu]zeri(?:nde|ndeki|ne)?"
    rf"\D{{0,60}}?({_TUTAR})\s*{_TL}",
    re.IGNORECASE,
)

# ── Azami toplam fayda ────────────────────────────────────
# "Toplamda 2.000 TL Worldpuan" · "toplam 750 TL" · "toplamda 5.000 TL"
#
# ⚠️ TOPLU KİŞİ TAVANI BURAYA GİRMEZ. "toplamda 5 kişi için maksimum
# 25.000 TL" ifadesi BİR MÜŞTERİNİN alabileceği azami fayda değil, bütün
# davetlerin toplam tavanıdır; `AGGREGATE_CAP` ile ayıklanır (bkz.
# `_total_benefit`). İkisi karıştırılırsa alan bir kampanyada 12,5 kat
# fazla gösterir.
TOTAL_BENEFIT: Final[re.Pattern[str]] = re.compile(
    rf"toplam(?:da|[ıi]nda)?\s*(?:(?:en\s*fazla|maksimum|azami)\s*)?"
    rf"({_TUTAR})\s*{_TL}",
    re.IGNORECASE,
)

# ── Yüzde ödüller ─────────────────────────────────────────
# ⚠️ ORAN İLE "iade" ARASINA ÇEKİM EKİ GİRİYOR: "%18’i kadar nakit iade",
# "%10’una kadar nakit iade". Araya yalnızca SINIRLI bir ek + "kadar" /
# "oranında" alınır; serbest doldurma metindeki herhangi bir yüzdeyi
# uzaktaki bir "iade" kelimesine bağlardı.
CASHBACK_PCT: Final[re.Pattern[str]] = re.compile(
    rf"%\s*\d+(?:[.,]\d+)?\s*{_KESME}?\s*[a-zçğıöşü]{{0,4}}\s*"
    rf"(?:kadar\s*|oran[ıi]nda\s*)?(?:nakit\s*)?iade"
    rf"|(?:nakit\s*)?iade\s*[:\-]?\s*%\s*\d+(?:[.,]\d+)?",
    re.IGNORECASE,
)

# ⚠️ `oran[ıi]nda` köprüsü CASHBACK_PCT'de vardı, burada yoktu: aynı
# ifade biçimi iade tarafında okunuyor, indirim tarafında kaçıyordu.
DISCOUNT_PCT: Final[re.Pattern[str]] = re.compile(
    rf"%\s*\d+(?:[.,]\d+)?\s*{_KESME}?\s*[a-zçğıöşü]{{0,4}}\s*"
    rf"(?:kadar\s*|varan\s*|oran[ıi]nda\s*)?indirim"
    rf"|indirim\s*[:\-]?\s*%\s*\d+(?:[.,]\d+)?",
    re.IGNORECASE,
)

# ── Ücret ve masraf ───────────────────────────────────────
ALLOCATION_FEE: Final[re.Pattern[str]] = re.compile(
    r"tahsis\s*[üu]creti\s*[:\-]?\s*%?\s*\d+(?:[.,]\d+)?"
    r"|%\s*\d+(?:[.,]\d+)?\s*tahsis",
    re.IGNORECASE,
)

FILE_FEE: Final[re.Pattern[str]] = re.compile(
    rf"dosya\s*masraf[ıi]\s*[:\-]?\s*{_TUTAR}\s*{_TL}", re.IGNORECASE
)

# ⚠️ OLUMSUZ ÇEKİM TEK BİR FİİLLE YAZILMIYOR. Gövdede ölçülen biçimler:
# "alınmaz", "alınmamaktadır", "alınmayacaktır", "yansıtılmayacaktır" (85),
# "talep edilmemektedir" (15), "yok" / "yoktur" (19). Her biri için ayrı
# alternatif yazmak yerine olumsuzluk TEK yerde toplanır.
#
# ⚠️ OLUMLU ÇEKİM KESİNLİKLE DIŞARIDA KALMAK ZORUNDA ve bu gövdede
# GERÇEK BİR RİSK: "yansıtılmaktadır" 111 kez geçiyor (ParafPara ödülü
# karta yansıtılır — ücret muafiyeti DEĞİL, tersi). Türkçe olumsuzluk eki
# `-ma/-me` gövdeden sonra gelir:
#
#     al-ın-ma-z          olumsuz  ✓
#     al-ın-ma-makta-dır  olumsuz  ✓
#     al-ın-makta-dır     OLUMLU   ✗  ← eşleşmemeli
#
# Bu yüzden çekim ekleri `(?:az|amakta|ayacak)` olarak SAYILARAK yazılır;
# `al[ıi]nm\w*` gibi gevşek bir kalıp olumlu biçimi de yutar ve "ücret
# alınmaktadır" cümlesi "masrafsız" sayılır.
_OLUMSUZ = (
    r"(?:al[ıi]nm(?:az|amakta|ayacak)\w*"
    r"|yans[ıi]t[ıi]lm(?:az|amakta|ayacak)\w*"
    r"|talep\s*edilm(?:ez|emekte|eyecek)\w*"
    r"|tahsil\s*edilm(?:ez|emekte|eyecek)\w*"
    r"|bulunm(?:az|amakta)\w*"
    r"|yok(?:tur)?\b)"
)

# ⚠️ ÇIPLAK "ÜCRET" KABUL EDİLMEZ ve bunun sebebi ölçüldü. `[üu]cret`
# alternatifi konunca "Sonradan taksitlendirmeden İŞLEM ÜCRETİ
# alınmamaktadır" gibi KÜÇÜK PUNTOLU dipnotlar da eşleşiyor; kampanya
# masrafsız sayılıp `has_no_fee=true` ve `file_fee_try=0` yazılıyordu —
# gold set'te iki alan birden yanlış pozitif oluyor.
#
# Ayrım ÜCRETİN KAPSAMINDA: ürün düzeyindeki bir ücretin kaldırılması
# kampanyanın vaadidir ("ömür boyu KART ÜCRETİ yok" — gövdede 15 geçiş),
# işlem düzeyindeki bir ücret ise sözleşme dipnotudur ("işlem ücreti",
# "para çekme ücreti", "hesap işletim ücreti"). Bu yüzden kabul edilen
# ücret adları SAYILARAK yazılır; genel `[üu]cret` alternatifi YOKTUR.
_UCRET_ADI = (
    r"(?:dosya\s*masraf"
    r"|tahsis\s*[üu]cret"
    r"|(?:kart|[üu]yelik|y[ıi]ll[ıi]k|aidat|kullan[ıi]m|ekspertiz|de[ğg]erleme)"
    r"\s*[üu]cret"
    r"|masraf"
    r"|komisyon)"
)

# "masrafsız" · "dosya masrafı alınmamaktadır" · "ücret alınmaz"
# · "tahsis ücreti yansıtılmayacaktır" · "kart ücreti yok"
# · "ücret veya komisyon talep edilmemektedir" · "sıfır dosya masrafı"
#
# ⚠️ Ücret adı ile olumsuz fiil arasına EN FAZLA İKİ SÖZCÜK girebilir
# ("ücret veya komisyon talep edilmemektedir", "masraf veya komisyon
# alınmaz"). Sınır gevşetilirse cümlenin başındaki "ücret" ile sonundaki
# bir olumsuzluk birbirine bağlanır ve ücretli bir kampanya masrafsız
# görünür.
NO_FEE: Final[re.Pattern[str]] = re.compile(
    rf"masrafs[ıi]z"
    rf"|{_UCRET_ADI}\w*\s*(?:(?:ve|veya|ya\s*da|ile)\s+\w+\s+){{0,1}}{_OLUMSUZ}"
    rf"|s[ıi]f[ıi]r\s*(?:\w+\s+){{0,1}}(?:komisyon|masraf|[üu]cret)\w*",
    re.IGNORECASE,
)

# ── Ekspertiz / değerleme ücreti bankada mı ───────────────
# ⚠️ ŞARTNAMENİN KENDİ ÖRNEĞİNDE GEÇİYOR. Örnek Temsili Senaryo-1'in
# B Bankası satırı "Ekspertiz ücretsiz" diyor; alan konut finansmanının
# ayırt edici maliyet kalemlerinden biri.
#
# ⚠️ "Ekspertiz Ücreti: 1.500 TL" EŞLEŞMEZ. Olumsuzluk ZORUNLU: ücret adının
# geçmesi ücretin KALDIRILDIĞI anlamına gelmez, tersi de olabilir. Gövdede
# ölçüldü — ekspertiz geçen tek kayıt bir ücret TABLOSU satırı ve bankanın
# ücret aldığını söylüyor.
APPRAISAL_FEE_COVERED: Final[re.Pattern[str]] = re.compile(
    rf"(?:ekspertiz|de[ğg]erleme)\s*(?:[üu]creti?|masraf[ıi]?)?\s*"
    rf"(?:{_OLUMSUZ}|[üu]cretsiz|bedelsiz|masrafs[ıi]z|bizden|bankam[ıi]zdan)",
    re.IGNORECASE,
)

# ── Finansman tutarı ──────────────────────────────────────
FINANCING_AMOUNT: Final[re.Pattern[str]] = re.compile(
    rf"{_TUTAR}\s*{_TL}\s*(?:{_FINANSMAN_SINIR_EKI}\s*)?(?:\w+\s+)?finansman"
    rf"|finansman\s*(?:tutar[ıi])?\s*[:\-]?\s*{_TUTAR}\s*{_TL}",
    re.IGNORECASE,
)

# ── Tarih ─────────────────────────────────────────────────
# Yalnızca KANIT ARALIĞINI bulmak için; ayrıştırma `parse_date_range_tr`e
# devredilir (7 biçim orada çözülüyor, burada tekrarlanmaz).
_AY = (
    r"(?:Ocak|Şubat|Subat|Mart|Nisan|Mayıs|Mayis|Haziran|Temmuz|"
    r"Ağustos|Agustos|Eylül|Eylul|Ekim|Kasım|Kasim|Aralık|Aralik)"
)
DATE_SPAN: Final[re.Pattern[str]] = re.compile(
    # "01.01.2026 - 31.12.2026" · "6.08.2026 - 31.12.2026"
    r"\d{1,2}[./-]\d{1,2}[./-]\d{4}\s*[-–—]\s*\d{1,2}[./-]\d{1,2}[./-]\d{4}"
    # "10 Temmuz – 7 Ağustos 2026" · "1-31 Ağustos 2026"
    rf"|\d{{1,2}}\s*(?:{_AY})?\s*[-–—]\s*\d{{1,2}}\s*{_AY}\s*\d{{4}}"
    # "02 Ocak 2026 - 31 Aralık 2026"
    rf"|\d{{1,2}}\s*{_AY}\s*\d{{4}}\s*[-–—]\s*\d{{1,2}}\s*{_AY}\s*\d{{4}}"
    # "Son Gün 07.09.2026" · "31.12.2026 tarihine kadar"
    r"|(?:[Ss]on\s*[Gg][üu]n\s*)?\d{1,2}[./-]\d{1,2}[./-]\d{4}"
    r"(?:\s*[Tt]arihine\s*[Kk]adar|\s*[Tt]arihinde\s*[Ss]ona)?"
    rf"|\d{{1,2}}\s*{_AY}\s*\d{{4}}",
    re.IGNORECASE,
)

# ── Ödül türü ─────────────────────────────────────────────
# ⚠️ SIRA ÖNEMLİ: "nakit iade" önce denenir; yalnızca "iade" ile eşleşen
# genel kalıp onu gölgelemesin.
REWARD_TYPE_MARKERS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("nakit_iade", re.compile(r"nakit\s*iade|para\s*iade|cashback", re.IGNORECASE)),
    ("puan", re.compile(r"worldpuan|paraf\s*para|bankkart\s*lira|puan\b|mil\b", re.IGNORECASE)),
    ("hediye", re.compile(r"hediye\s*[çc]eki|al[ıi]şveri[şs]\s*[çc]eki|hediye", re.IGNORECASE)),
    ("ucret_muafiyeti", NO_FEE),
    ("indirim", re.compile(r"indirim", re.IGNORECASE)),
    ("taksit", re.compile(r"taksit", re.IGNORECASE)),
)
