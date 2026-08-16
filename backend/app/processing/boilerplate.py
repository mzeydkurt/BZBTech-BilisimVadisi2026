"""Kampanya metnindeki YABANCI KAMPANYA bloklarını ayıklar (Şartname 5.8).

## Neden bu dosya var

`cleaner.py` HTML'i metne çevirir ve çerez/KVKK gibi tekrarlayan SATIRLARI
atar. Ama bir kampanya sayfasında asıl gürültü satır değil, **bölüm**dür:
sayfanın altındaki "İlgili Kampanyalar" kartları ve tepesindeki mega menü.
Bunlar temizlenmediğinde `clean_text` içinde BAŞKA kampanyaların başlıkları,
markaları ve tarihleri yer alır; çıkarım motoru bunları o kampanyaya aitmiş
gibi okur.

Ölçüldü (495 kampanya, ön işleme öncesi):

    Kampanya metnine yabancı kampanya bloğu karışan   328 / 495  (%66)
    Metninde 4+ farklı tarih bulunan                    56 / 495  (%11)

Somut örnek — Ziraat Katılım #79 (`zen-pirlantada-3-taksit`), 1838 karakter:
kampanyanın kendi dönemi `11-08-2026 - 31-08-2026` iken metnin sonundaki
komşu kampanya kartlarından `31.08.2026` ve `07.09.2026` de aynı metne
giriyor. Tarih çıkarıcısı "metindeki ilk tarih" kuralıyla çalıştığı için
komşu kampanyanın tarihini alabiliyor.

## Neden "başlığı bul, sonrasını kes" YETMİYOR

Üç ayrı tuzak ölçüldü; üçü de sessizce yanlış veri üretir:

**1. Aynı ifade hem koşul metninde hem başlıkta geçiyor.**
`"Kampanya başka kampanyalarla birleştirilemez."` cümlesi 83 Ziraat
kaydında var ve GERÇEK koşul metnidir. Alt dize araması bu satırı bölüm
başlığı sanıp kampanyanın koşullarını siler. Bu yüzden işaretçiler
**tam satır** olarak eşleştirilir, alt dize olarak değil.

**2. Aynı başlık kimi bankada üstte gezinme, kimisinde altta bölüm.**
`"Diğer Kampanyalar"` Ziraat'te sol filtre menüsünde bir KATEGORİ ADI
(satır 15/72), Dünya Katılım'da ise sayfanın en altındaki bölüm başlığı
(satır 11/12). İlk geçtiği yerden kesmek Ziraat'te kampanyanın tamamını
siler. Bu yüzden belirsiz işaretçiler yalnızca metnin son bölümünde
(`TRAILING_ZONE_RATIO`) kesim noktası sayılır.

**3. Ziraat'te ilgili kampanya bloğunun BAŞLIĞI YOK.**
Kartlar doğrudan başlar: `<Kategori> / <Başlık> / Son Gün 31.08.2026 /
Detaylar`. Başlık aranarak bulunamaz; kart deseni (`Son Gün <tarih>`)
üzerinden geriye yürünür.

## Sıra önemlidir

Önce baş (gezinme), sonra kuyruk (ilgili kampanyalar) kesilir. Türkiye
Finans'ta `"Başvuru Merkezi"` HEM üst menüde HEM altbilgide geçiyor; baş
kesilmeden kuyruk işaretçisi aranırsa konum koruması devreye girer ve
altbilgi temizlenmez.

## Güvenlik ağı

Her kesim `MIN_KEEP_CHARS` ile korunur: kesim sonrası metin bu eşiğin
altına düşerse kesim UYGULANMAZ ve uyarı loglanır. Fazla agresif temizlik
gerçek içeriği siler; §6.1'in uyarısı budur. `python dev.py yeniden-isle
--ornek 10` çıktısı gözle doğrulanmak üzere bu amaçla vardır.
"""

from __future__ import annotations

import re
from typing import Final

from app.core.normalization.text import ascii_fold_tr, lower_tr
from app.logging_config import get_logger

logger = get_logger(__name__)

# Kesim sonrası metinde en az bu kadar karakter kalmalıdır. Altına düşen
# kesim, işaretçi yanlış yerde eşleşmiş demektir; uygulanmaz.
MIN_KEEP_CHARS: Final[int] = 200

# Belirsiz işaretçiler yalnızca metnin bu oranından SONRA geçerse kesim
# noktası sayılır. Karakter uzaklığına göre ölçülür — satır sayısına göre
# değil: gezinme menüleri çok sayıda ama çok kısa satırdan oluşur.
TRAILING_ZONE_RATIO: Final[float] = 0.5

# Kart satırı sayılabilecek en uzun satır. Kampanya kartlarında kategori ve
# başlık kısa satırlardır; koşul cümleleri bundan uzundur.
CARD_LINE_MAX_CHARS: Final[int] = 80

# Cümle sonu noktalaması. Kart satırları bunlarla bitmez, koşul cümleleri biter.
_SENTENCE_END: Final[tuple[str, ...]] = (".", "!", "?", ":", ";")

# Gezinme bloğunu SONLANDIRAN noktalama — `_SENTENCE_END`'den DAR tutulur.
#
# ⚠️ Menü bağlantıları soru ve ünlem işaretiyle bitebiliyor: Kuveyt Türk'ün
# mega menüsünde "Harcama İtirazı (Chargeback) Nasıl Yapılır?",
# "Faizsiz Sigortacılık Nedir?", "Ayın Kampüslüsü'ne Özel Fırsatlar!".
# `!` ve `?` sonlandırıcı sayılırsa gezinme bloğu 21. satırda kesiliyor,
# menünün geri kalan 158 satırı metinde kalıyor ve içindeki BAŞKA kampanya
# adları çıkarıma karışıyordu. Kampanya başlıkları da çoğu zaman `!` ile
# bittiği için bu ayrım çıpanın bulunabilmesi açısından da zorunludur.
_NAV_STOP_SUFFIXES: Final[tuple[str, ...]] = (".", ";", ":")

# ── İşaretçi tabloları ────────────────────────────────────────────────────
#
# Tüm işaretçiler `_fold()` biçimindedir: küçük harf, Türkçe karakterler
# ASCII'ye katlanmış, sondaki noktalama atılmış. Karşılaştırma TAM SATIR
# üzerindedir (bkz. tuzak 1).

# Kesin işaretçiler — nerede geçerlerse geçsinler ilgili kampanya bölümünü
# başlatırlar. Bu ifadeler gezinme menüsünde kullanılmıyor.
RELATED_HEADINGS: Final[frozenset[str]] = frozenset(
    {
        "ilgili kampanyalar",
        "benzer kampanyalar",
        "ilginizi cekebilir",
        "ilginizi cekebilecek kampanyalar",
        "ilginizi cekebilecek diger kampanyalar",
        "bunlar da ilginizi cekebilir",
        "bunlar da ilgini cekebilir",
        "one cikan kampanyalar",
        "son kampanyalar",
        "diger kampanyalarimiz",
        "diger tum kampanyalar",
        "size ozel diger kampanyalar",
    }
)

# Belirsiz işaretçiler — hem üst gezinme hem alt bölüm başlığı olabilirler.
# Yalnızca metnin son bölümünde kesim noktası sayılırlar (bkz. tuzak 2).
AMBIGUOUS_HEADINGS: Final[frozenset[str]] = frozenset(
    {
        "tum kampanyalar",
        "diger kampanyalar",
    }
)

# Bankaya özel kuyruk işaretçileri. Hepsi konum korumasına tabidir; bir
# kısmı (ör. Türkiye Finans'ta "Başvuru Merkezi") sayfanın hem tepesinde
# hem altında geçiyor.
BANK_TRAILING_MARKERS: Final[dict[str, frozenset[str]]] = {
    # Sayfa sonu: "Paraf Kampanyaları / Devam ediyor / Bitiş Tarihi: ... /
    # Paylaş / Diğer Kampanyalar". ⚠️ "Bitiş Tarihi" GERÇEK veridir ve
    # "Paylaş"tan ÖNCE gelir; bu yüzden kesim "Paylaş"tan başlar.
    "dunya_katilim": frozenset({"paylas"}),
    # Altbilgi hizmet menüsü.
    "turkiye_finans": frozenset({"basvuru merkezi", "hesaplama araclari"}),
    # Sayfa sonundaki ürün tanıtım kartı.
    "hayat_finans": frozenset({"biz kart, sizi banka yapan kart"}),
    # Ana sayfa bileşenleri (kur/kâr payı afişleri) kampanya sayfasına
    # sızdığında.
    "emlak_katilim": frozenset({"kurlarimiz", "kar paylari", "tumunu goster"}),
}

# Bilgi taşımayan arayüz satırları. Bölüm kesmez, yalnızca satır atarlar.
# Yalnızca düğme/bağlantı etiketleri listelenir; veri taşıyan hiçbir satır
# bu listede DEĞİLDİR.
CHROME_LINES: Final[frozenset[str]] = frozenset(
    {
        "paylas",
        "kampanyayi paylas",
        "sayfayi yazdir",
        "facebook'da paylas",
        "twitter'da paylas",
        "linkedin'de paylas",
        "whatsapp'ta paylas",
        "sayfa goruntusu",
        "sayfa icerigi",
        "hemen indir",
        "detaylar",
        "detayli bilgi",
        "kampanya detayi",
        "incele",
        "tumunu goster",
        "devamini oku",
    }
)

# Ziraat Katılım kampanya kartının tarih satırı. Kartların başlığı olmadığı
# için blok bu desenden geriye yürünerek bulunur (bkz. tuzak 3).
#
# ⚠️ Ziraat'in kampanya sayfasında kendi dönemi "Kampanya Dönemi" başlığı
# altında `11-08-2026 / - / 31-08-2026` biçiminde verilir; "Son Gün" ifadesi
# YALNIZCA kartlarda geçer. Bu ayrım kesimin güvenli olmasını sağlar.
CARD_DATE_RE: Final[re.Pattern[str]] = re.compile(
    r"^son g[uü]n\s+\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\s*$",
    re.IGNORECASE,
)

# Gezinme satırı sayılabilecek en uzun satır. Menü bağlantıları kısadır;
# koşul cümleleri bundan uzundur.
NAV_LINE_MAX_CHARS: Final[int] = 90

# Baştaki blokta KORUNAN satırları belirler: tarih taşıyan satır gezinme
# değildir.
#
# ⚠️ T.O.M. Bank kampanyanın KENDİ tarihini başlıktan ÖNCE veriyor:
#   "Hemen İndir / Kampanya Tarihleri / 01 Mart - 16 Mart 2025 / <başlık>"
# Baştaki bloğu koşulsuz atmak bu kampanyaların en temiz tarih sinyalini
# siliyordu (3 kayıtta ölçüldü). Bu yüzden gezinme bloğu atılırken tarih
# taşıyan satırlar korunur.
_DATE_HINT_RE: Final[re.Pattern[str]] = re.compile(
    r"\d{1,2}\s*[./-]\s*\d{1,2}\s*[./-]\s*\d{2,4}"
    r"|\d{1,2}\s+(ocak|subat|mart|nisan|mayis|haziran|temmuz|agustos|eylul|ekim|kasim|aralik)",
    re.IGNORECASE,
)


def _fold(value: str) -> str:
    """Satırı karşılaştırma biçimine indirger.

    Küçük harfe çevirir (Türkçe kurallarıyla), Türkçe karakterleri ASCII'ye
    katlar ve sondaki noktalamayı atar. Böylece `"İlgili Kampanyalar"`,
    `"ilgili kampanyalar"` ve `"İLGİLİ KAMPANYALAR:"` aynı anahtara düşer.

    Args:
        value: Ham satır.

    Returns:
        Karşılaştırmaya hazır anahtar.
    """
    return ascii_fold_tr(lower_tr(value.strip())).strip(" .:!?-–—…").strip()


def _line_offsets(lines: list[str]) -> list[int]:
    """Her satırın metin içindeki karakter başlangıcını döndürür.

    Konum koruması satır sayısına göre değil karakter uzaklığına göre
    ölçülür; gezinme menüleri çok sayıda ama çok kısa satırdan oluştuğu için
    satır oranı yanıltıcıdır.

    Args:
        lines: Metnin satırları.

    Returns:
        Satır başına karakter uzaklığı.
    """
    offsets: list[int] = []
    toplam = 0
    for line in lines:
        offsets.append(toplam)
        toplam += len(line) + 1
    return offsets


def _is_nav_line(line: str) -> bool:
    """Satır bir gezinme bağlantısına benziyor mu?

    Gezinme satırları kısadır ve cümle noktalamasıyla bitmez. Koşul
    cümleleri her ikisinin de tersidir.

    Args:
        line: Sınanacak satır.

    Returns:
        Gezinme satırıysa True.
    """
    stripped = line.strip()
    if not stripped:
        return True
    return len(stripped) <= NAV_LINE_MAX_CHARS and not stripped.endswith(_NAV_STOP_SUFFIXES)


def _carries_date(line: str) -> bool:
    """Satır tarih bilgisi taşıyor mu?

    Args:
        line: Sınanacak satır.

    Returns:
        Sayısal ya da Türkçe ay adlı tarih içeriyorsa True.
    """
    return bool(_DATE_HINT_RE.search(ascii_fold_tr(lower_tr(line))))


def _card_block_start(lines: list[str]) -> int | None:
    """Başlıksız kampanya kartı bloğunun başladığı satırı bulur.

    Ziraat Katılım'ın kampanya sayfasında ilgili kampanyalar bölümünün
    başlığı yoktur; kartlar `<Kategori> / <Başlık> / Son Gün <tarih> /
    Detaylar` biçiminde doğrudan başlar. `Son Gün` satırı bulunduktan sonra
    kartın kendi başlangıcına ulaşmak için geriye, kısa ve cümle olmayan
    satırlar boyunca yürünür.

    Args:
        lines: Metnin satırları.

    Returns:
        Blok başlangıç satırı; kart bulunamazsa None.
    """
    for index, line in enumerate(lines):
        if not CARD_DATE_RE.match(line.strip()):
            continue

        start = index
        while start > 0:
            onceki = lines[start - 1].strip()
            if len(onceki) > CARD_LINE_MAX_CHARS or onceki.endswith(_SENTENCE_END):
                break
            start -= 1
        return start

    return None


def strip_leading_navigation(text: str, title: str | None) -> str:
    """Kampanya başlığından önceki gezinme bloğunu atar.

    Kampanya başlığı, 495 kaydın 492'sinde metinde TAM SATIR olarak geçiyor
    ve gerçek içeriğin nerede başladığını güvenilir biçimde işaretliyor.
    Ölçülen başlangıç satırları: Ziraat 30 (sol filtre menüsünden sonra),
    Kuveyt Türk 179 (mega menüden sonra), Türkiye Finans 13, Vakıf 6.

    ⚠️ Kuveyt Türk'ün mega menüsü gövde metninin %40'ından fazlasını
    kapladığı için `cleaner._drop_noise` onu bilinçli olarak KORUR
    (Emlak Katılım'da içerik `<nav>` içinde kalıyor, bkz. CLAUDE.md kural 1).
    Menü bu yüzden metne giriyor ve içinde BAŞKA kampanyaların başlıkları
    bulunuyor. Etiket düzeyinde çözülemeyen bu durum metin düzeyinde
    başlık çıpasıyla çözülür.

    Üç koruma:

    **1. Çıpadan ÖNCEKİ HER satır gezinme satırı olmalı.** Oran değil,
    kesinlik aranır. Ölçüldü (Ziraat #183): kampanya kendi kartında da
    geçtiği için başlık üç kez bulunuyor — sol menüde (0), içeriğin
    tepesinde (30) ve alttaki ilgili kampanya kartında (60). "Satırların
    %70'i gezinmeye benziyorsa kes" kuralı üçüncüsünü seçiyor, çünkü
    aradaki kart satırları da kısa; kampanyanın tüm koşulları siliniyordu.
    Kesintisiz gezinme koşulu doğru çıpayı (30) seçer: 30'dan önce yalnızca
    menü, 60'tan önce koşul cümleleri var.

    **2. Tarih taşıyan satırlar KORUNUR.** T.O.M. Bank kampanyanın kendi
    tarihini başlıktan önce yazıyor (bkz. `_DATE_HINT_RE`).

    **3. Kesim sonrası en az `MIN_KEEP_CHARS` karakter kalmalı.**

    Args:
        text: Temizlenecek metin.
        title: Kampanya başlığı; yoksa metin değişmeden döner.

    Returns:
        Gezinme bloğu atılmış metin.
    """
    if not text or not title:
        return text

    lines = text.split("\n")
    hedef = _fold(title)
    if not hedef:
        return text

    # Kesintisiz gezinme bloğunun bittiği satır: buradan sonrası içeriktir.
    #
    # ⚠️ Son satırla sınırlanır. Kısa sayfalarda (ör. 404 gövdesi) HER satır
    # gezinmeye benzeyebiliyor; sınırlanmazsa döngü dizinin bir ötesini
    # okuyup IndexError fırlatıyordu.
    gezinme_sonu = 0
    while gezinme_sonu < len(lines) and _is_nav_line(lines[gezinme_sonu]):
        gezinme_sonu += 1
    gezinme_sonu = min(gezinme_sonu, len(lines) - 1)

    # En SONRAKİ uygun çıpa seçilir: Ziraat'te başlık hem sol menüde (0) hem
    # içeriğin tepesinde (30) geçiyor; doğru olan ikincisidir.
    for index in range(gezinme_sonu, 0, -1):
        if _fold(lines[index]) != hedef:
            continue

        kalan = lines[index:]
        if len("\n".join(kalan)) < MIN_KEEP_CHARS:
            continue

        # Gezinme bloğunda veri taşıyan satır varsa geride bırakılmaz.
        korunan = [line for line in lines[:index] if _carries_date(line)]
        return "\n".join(korunan + kalan)

    return text


def strip_related_sections(text: str, bank_code: str | None = None) -> str:
    """İlgili/diğer kampanya bölümünü ve altbilgiyi metnin sonundan atar.

    En erken geçerli kesim noktası kullanılır: bir sayfada birden fazla
    işaretçi bulunabilir (Dünya Katılım'da hem `Paylaş` hem
    `Diğer Kampanyalar`), gerçek bölüm ilkinden başlar.

    Args:
        text: Temizlenecek metin.
        bank_code: Bankaya özel işaretçiler için banka kodu.

    Returns:
        İlgili kampanya bölümü atılmış metin.
    """
    if not text:
        return text

    lines = text.split("\n")
    offsets = _line_offsets(lines)
    toplam = len(text)
    esik = toplam * TRAILING_ZONE_RATIO
    banka_isaretcileri = BANK_TRAILING_MARKERS.get(bank_code or "", frozenset())

    kesim: int | None = None

    def _aday(index: int) -> None:
        nonlocal kesim
        if kesim is None or index < kesim:
            kesim = index

    for index, line in enumerate(lines):
        anahtar = _fold(line)
        if not anahtar:
            continue
        # Kesin işaretçi konumdan bağımsız keser; belirsiz olan yalnızca
        # metnin son bölümünde kesim noktası sayılır (bkz. tuzak 2).
        belirsiz = anahtar in AMBIGUOUS_HEADINGS or anahtar in banka_isaretcileri
        if anahtar in RELATED_HEADINGS or (belirsiz and offsets[index] >= esik):
            _aday(index)

    if bank_code == "ziraat_katilim":
        kart = _card_block_start(lines)
        if kart is not None:
            _aday(kart)

    if kesim is None:
        return text

    kalan = "\n".join(lines[:kesim]).strip()
    if len(kalan) < MIN_KEEP_CHARS:
        # İşaretçi yanlış yerde eşleşti; kesmek gerçek içeriği silerdi.
        logger.warning(
            "boilerplate_kesim_reddedildi",
            banka=bank_code,
            kesim_satiri=kesim,
            kalan_uzunluk=len(kalan),
            toplam_uzunluk=toplam,
        )
        return text

    return kalan


def strip_chrome_lines(text: str) -> str:
    """Bilgi taşımayan arayüz satırlarını (paylaş, indir, detaylar) atar.

    Bölüm kesmez; yalnızca `CHROME_LINES` ile tam eşleşen satırları çıkarır.

    Args:
        text: Temizlenecek metin.

    Returns:
        Arayüz satırları atılmış metin.
    """
    if not text:
        return text

    kept = [line for line in text.split("\n") if _fold(line) not in CHROME_LINES]
    return "\n".join(kept).strip()


def strip_boilerplate_sections(
    text: str,
    *,
    bank_code: str | None = None,
    title: str | None = None,
) -> str:
    """Yabancı kampanya bloklarını metinden ayıklar — modülün giriş noktası.

    ⚠️ SIRA ÖNEMLİDİR. Önce baştaki gezinme, sonra kuyruk kesilir: Türkiye
    Finans'ta `"Başvuru Merkezi"` hem üst menüde hem altbilgide geçiyor.
    Baş kesilmeden kuyruk aranırsa üstteki geçiş konum korumasına takılır ve
    altbilgi temizlenmeden kalır.

    Args:
        text: `cleaner.clean_html()` çıktısı.
        bank_code: Bankaya özel kurallar için banka kodu.
        title: Kampanya başlığı; gezinme kesiminin çıpası.

    Returns:
        Temizlenmiş metin.
    """
    if not text:
        return text

    text = strip_leading_navigation(text, title)
    text = strip_related_sections(text, bank_code)
    return strip_chrome_lines(text)
