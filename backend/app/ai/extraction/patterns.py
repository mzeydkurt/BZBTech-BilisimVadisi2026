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

_TL = r"(?:TL|₺)"

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

# ── Kâr payı oranı ────────────────────────────────────────
# "%2,05 kâr payı" · "kâr payı oranı %2,05" · "%2,05 oranlı"
PROFIT_RATE: Final[re.Pattern[str]] = re.compile(
    rf"(?:{_KAR}\s*{_PAYI}(?:\s*oran[ıiİI])?\s*[:\-]?\s*%\s*\d+(?:[.,]\d+)?"
    rf"|%\s*\d+(?:[.,]\d+)?\s*(?:oran[lı]|{_KAR}\s*{_PAYI}))",
    re.IGNORECASE,
)

# ⚠️ "vade farksız" ve "peşin fiyatına" ORAN SIFIR demektir — bilinmeyen
# değil. İkisi karıştırılırsa "en düşük kâr payı" karşılaştırması bu
# kampanyaları hiç görmez.
ZERO_RATE: Final[re.Pattern[str]] = re.compile(
    r"(vade\s*farks[ıi]z|pe[şs]in\s*fiyat[ıi]na)", re.IGNORECASE
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
    r"\d{1,3}\s*[-–]\s*\d{1,3}\s*ay\b|\d{1,3}\s*ay(?:a\s*kadar)?\b|\d{1,2}\s*y[ıi]l\b",
    re.IGNORECASE,
)

# ── Tutar eşiği ve ödül ───────────────────────────────────
# "5.000 TL ve üzeri" · "asgari 5.000 TL" · "en az 1.000 TL"
MIN_SPEND: Final[re.Pattern[str]] = re.compile(
    r"(?:asgari|en\s*az|minimum)\s*[\d.,]+\s*(?:TL|₺)"
    r"|[\d.,]+\s*(?:TL|₺)\s*(?:ve\s*)?[üu]zeri",
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
    rf"([\d.,]+)\s*{_TL}\s*{_KESME}?\s*[yn]?[ae]\s*(?:kadar|ula[şs]an)"
    rf"|([\d.,]+)\s*{_TL}\s*ve\s*alt[ıi]",
    re.IGNORECASE,
)

# ⚠️ FİNANSMAN BAĞLAMI. Aynı aralık ifadesi hem harcama eşiği hem finansman
# limiti olabiliyor; ayrımı çevredeki kelime yapar. Bağlam yoksa yalnızca
# harcama alanları doldurulur — finansman limiti UYDURULMAZ.
FINANCING_CONTEXT: Final[re.Pattern[str]] = re.compile(
    r"finansman|taksit|kredi|[öo]deme\s*kolayl[ıi][ğg][ıi]", re.IGNORECASE
)

# Ödül adları. "nakit ödül" (Hayat Finans) eskiden listede yoktu.
_ODUL_ADI = (
    r"(?:nakit\s*iade|iade|nakit\s*[öo]d[üu]l|[öo]d[üu]l"
    r"|hediye|puan|para|lira|indirim|de[ğg]erinde)"
)

# "250 TL nakit iade" · "500 TL Bankkart Lira" · "2.000 TL nakit ödül"
REWARD_AMOUNT: Final[re.Pattern[str]] = re.compile(
    rf"[\d.,]+\s*{_TL}\s*{_VARAN}(?:{_SADAKAT}\b|{_ODUL_ADI})",
    re.IGNORECASE,
)

# "200 TL ParafPara" · "10.000 Mil'e Varan" · "500 TL Bankkart Lira"
#
# ⚠️ `TL` İSTEĞE BAĞLI: "10.000 Mil" tutarı TL cinsinden DEĞİLDİR ve gold
# set'te yalnızca `loyalty_points` doluyor, `reward_amount_try` boş kalıyor.
# `reward_amount_try` kalıbı `TL` zorunlu tutarak bu ayrımı korur.
LOYALTY_POINTS: Final[re.Pattern[str]] = re.compile(
    rf"[\d.,]+\s*(?:{_TL}\s*)?{_VARAN}{_SADAKAT}\b",
    re.IGNORECASE,
)

# ⚠️ TOPLU ÜST SINIR TEK ÖDÜL DEĞİLDİR. "kişi başı maksimum 2.000 TL,
# toplamda 5 kişi için maksimum 10.000 TL nakit ödül" metninde kampanyanın
# bir kişiye vaat ettiği ödül 2.000'dir; 10.000 bütün davetlerin toplam
# tavanıdır. Bu önek görülen eşleşme ödül adayı sayılmaz.
AGGREGATE_CAP: Final[re.Pattern[str]] = re.compile(
    r"toplamda?\s*\d+\s*ki[şs]i|ki[şs]i\s*i[çc]in", re.IGNORECASE
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

DISCOUNT_PCT: Final[re.Pattern[str]] = re.compile(
    r"%\s*\d+(?:[.,]\d+)?\s*(?:'?[yn]?[ae]\s*varan\s*)?indirim"
    r"|indirim\s*[:\-]?\s*%\s*\d+(?:[.,]\d+)?",
    re.IGNORECASE,
)

# ── Ücret ve masraf ───────────────────────────────────────
ALLOCATION_FEE: Final[re.Pattern[str]] = re.compile(
    r"tahsis\s*[üu]creti\s*[:\-]?\s*%?\s*\d+(?:[.,]\d+)?"
    r"|%\s*\d+(?:[.,]\d+)?\s*tahsis",
    re.IGNORECASE,
)

FILE_FEE: Final[re.Pattern[str]] = re.compile(
    r"dosya\s*masraf[ıi]\s*[:\-]?\s*[\d.,]+\s*(?:TL|₺)", re.IGNORECASE
)

# "masrafsız" · "dosya masrafı alınmamaktadır" · "ücret alınmaz"
NO_FEE: Final[re.Pattern[str]] = re.compile(
    r"masrafs[ıi]z|dosya\s*masraf[ıi]\s*al[ıi]n[mM][aA]"
    r"|[üu]cret\s*al[ıi]nm[aa]z|komisyon\s*(?:yok|al[ıi]nm[aa]z)|s[ıi]f[ıi]r\s*komisyon",
    re.IGNORECASE,
)

# ── Finansman tutarı ──────────────────────────────────────
FINANCING_AMOUNT: Final[re.Pattern[str]] = re.compile(
    r"[\d.,]+\s*(?:TL|₺)\s*(?:'?[yn]?[ae]\s*kadar\s*)?finansman"
    r"|finansman\s*(?:tutar[ıi])?\s*[:\-]?\s*[\d.,]+\s*(?:TL|₺)",
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
