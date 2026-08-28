"""Türkçe para tutarı ayrıştırma.

Türkçe sayı biçimi konvansiyonu (İngilizce'nin TERSİDİR):
    5.000   -> beş bin   (nokta = binlik ayırıcı)
    5,000   -> beş       (virgül = ondalık ayırıcı)
    1.250,50 -> bin iki yüz elli TL elli kuruş

Bu modüldeki `parse_decimal_tr` fonksiyonu projedeki tüm sayı ayrıştırmasının
temelidir; `rate.py` de onu kullanır.

KURAL: Tüm dönüş değerleri `Decimal`dir. Finansal veride `float` kullanılmaz —
ikili kayan nokta gösterimi 0.1 + 0.2 != 0.3 gibi sapmalar üretir.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Final

from app.core.normalization.text import lower_tr, normalize_text

# Varsayılan para birimi. Kampanyaların neredeyse tamamı TL bazlıdır.
DEFAULT_CURRENCY: Final[str] = "TRY"

# Para birimi tespiti — küçük harfe çevrilmiş metin üzerinde çalışır.
# Sıra önemlidir: daha özgül kalıplar önce denenir.
_CURRENCY_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("TRY", re.compile(r"₺|\btl\b|\btry\b|türk\s+liras")),
    ("USD", re.compile(r"\$|\busd\b|abd\s+doları|\bdolar")),
    ("EUR", re.compile(r"€|\beur\b|\beuro\b|\bavro\b")),
    ("GBP", re.compile(r"£|\bgbp\b|\bsterlin")),
)

# Çarpan kelimeleri: "5 bin TL" -> 5000
_MULTIPLIERS: Final[dict[str, Decimal]] = {
    "bin": Decimal(1_000),
    "milyon": Decimal(1_000_000),
    "milyar": Decimal(1_000_000_000),
}

# Tutarın sıfır olduğunu belirten ifadeler. Yalnızca metinde hiç sayı yoksa
# devreye girer; "masrafsız 50.000 TL finansman" ifadesinde tutar 50.000'dir.
_ZERO_COST_RE: Final[re.Pattern[str]] = re.compile(
    r"masrafsız|masraf\s+yok|ücretsiz|bedelsiz|komisyonsuz|sıfır\s+masraf|ücret\s+alınmaz"
)

# Aralık bildiren bağlaçlar.
_RANGE_MARKER_RE: Final[re.Pattern[str]] = re.compile(r"\d\s*-\s*\d|\bile\b|\bila\b|arasında|arası")

# Üst sınır bildiren ifadeler: "50.000 TL'ye kadar"
_UPPER_BOUND_RE: Final[re.Pattern[str]] = re.compile(
    r"kadar|varan|azami|maksimum|en\s+fazla|en\s+çok|üst\s+limit"
)

# Alt sınır bildiren ifadeler: "5.000 TL ve üzeri"
_LOWER_BOUND_RE: Final[re.Pattern[str]] = re.compile(
    r"ve\s+üzeri|ve\s+üstü|üzerinde|başlayan|itibaren|en\s+az|asgari|minimum|alt\s+limit"
)

_NUM = r"\d[\d.,]*"
_MULT = r"(?:\s*(bin|milyon|milyar))?"
_CUR = (
    r"(?:₺|\btl\b|\btry\b|türk\s+liras\w*|\$|\busd\b|dolar\w*"
    r"|€|\beur\b|euro|avro|£|\bgbp\b|sterlin\w*)"
)

# Tutar + (çarpan) + para birimi:  "5.000 TL", "5 bin TL", "500₺"
_AMOUNT_BEFORE_CUR_RE: Final[re.Pattern[str]] = re.compile(rf"({_NUM}){_MULT}\s*{_CUR}")
# Para birimi + tutar:  "₺500", "TL 500"
_AMOUNT_AFTER_CUR_RE: Final[re.Pattern[str]] = re.compile(rf"{_CUR}\s*({_NUM}){_MULT}")
# Para birimi olmadan çıplak tutar — son çare.
_BARE_AMOUNT_RE: Final[re.Pattern[str]] = re.compile(rf"({_NUM}){_MULT}")

# Çıplak sayıdan sonra gelen birimler tutar DEĞİLDİR.
#   "120 ay" / "2 yıl" / "2 hafta"  → süre
#   "2. el" / "2.el" / "2 el"       → ikinci el araç (ölçüldü: 2 TL uyduruluyordu)
#   "0 km"                         → sıfır kilometre
_BARE_NON_AMOUNT_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:"
    r"(?:bin|milyon|milyar)?\s*(?:ay(?:lik|lık)?|vade|yil|yıl|gun|gün|hafta)\b"
    r"|['`]?(?:nci|inci)\s*el\b"
    r"|el\b"
    r"|km\b"
    r")"
)

# Açık aralık ifadesi: "50.000 - 2.000.000 TL", "5 bin ile 10 bin TL"
# Gerekçe: bu tür ifadelerde para birimi çoğunlukla YALNIZCA ikinci tutara bitişiktir.
# Para birimine bitişiklik önceliği tek başına kullanılsaydı alt sınır kaybolurdu.
_RANGE_PAIR_RE: Final[re.Pattern[str]] = re.compile(
    rf"({_NUM}){_MULT}\s*{_CUR}?\s*(?:-|\bile\b|\bila\b)\s*({_NUM}){_MULT}\s*{_CUR}?"
)

# Kademeli ödül: "5.000 TL ve üzeri 250 TL"
_TIER_RE: Final[re.Pattern[str]] = re.compile(
    rf"({_NUM})\s*(?:tl|₺)?\s*(?:ve\s+)?(?:üzerindeki|üzerinde|üzerine|üzeri|üstü)"
    rf"\D{{0,60}}?({_NUM})\s*(?:tl|₺)"
)


def parse_decimal_tr(token: str | None) -> Decimal | None:
    """Türkçe biçimli bir sayı dizesini `Decimal`e çevirir.

    Ayırıcı çözümlemesi:
      - Hem nokta hem virgül varsa: SONRAKİ olan ondalık ayırıcıdır
        ("1.250,50" -> 1250.50 · "1,250.50" -> 1250.50)
      - Yalnızca virgül varsa: virgül ondalık ayırıcıdır ("5,000" -> 5)
      - Yalnızca nokta varsa: noktadan sonraki her grup TAM 3 hane ise binlik
        ayırıcıdır ("5.000" -> 5000), değilse ondalık ayırıcıdır ("2.05" -> 2.05)

    Args:
        token: Ayrıştırılacak sayı dizesi (ör. "1.250,50").

    Returns:
        Sayısal değer veya ayrıştırılamazsa None.
    """
    if not token:
        return None

    token = token.strip().rstrip(".,").lstrip(".,")
    if not token or not re.fullmatch(rf"{_NUM}", token):
        return None

    has_comma = "," in token
    has_dot = "." in token

    if has_comma and has_dot:
        if token.rfind(",") > token.rfind("."):
            # Türkçe biçim: noktalar binlik, virgül ondalık.
            token = token.replace(".", "").replace(",", ".")
        else:
            # İngilizce biçim: virgüller binlik, nokta ondalık.
            token = token.replace(",", "")
    elif has_comma:
        # Birden fazla virgül ancak İngilizce binlik gruplaması olabilir;
        # tek virgül Türkçe ondalık ayırıcısıdır.
        token = token.replace(",", "") if token.count(",") > 1 else token.replace(",", ".")
    elif has_dot:
        groups = token.split(".")
        head, rest = groups[0], groups[1:]
        # Geçerli binlik gruplaması: baş grup en fazla 3 hane, kalan gruplar tam 3 hane.
        is_thousands = len(head) <= 3 and bool(rest) and all(len(part) == 3 for part in rest)
        if is_thousands or token.count(".") > 1:
            token = token.replace(".", "")

    try:
        return Decimal(token)
    except InvalidOperation:
        return None


def detect_currency(text: str) -> str:
    """Metindeki para birimini tespit eder.

    Args:
        text: İncelenecek metin.

    Returns:
        ISO 4217 kodu; bulunamazsa varsayılan olarak "TRY".
    """
    lowered = lower_tr(normalize_text(text))
    for code, pattern in _CURRENCY_PATTERNS:
        if pattern.search(lowered):
            return code
    return DEFAULT_CURRENCY


def _apply_multiplier(value: Decimal, multiplier: str | None) -> Decimal:
    """Sayıya "bin"/"milyon"/"milyar" çarpanını uygular."""
    if not multiplier:
        return value
    return value * _MULTIPLIERS.get(multiplier, Decimal(1))


def _iter_amounts(lowered: str) -> list[Decimal]:
    """Metindeki tutarları geçiş sırasına göre listeler.

    Para birimine bitişik tutarlar önceliklidir; hiç yoksa çıplak sayılara düşülür.
    Bu öncelik, "6026'ya SMS gönderin, 500 TL kazanın" gibi metinlerde SMS
    numarasının tutar sanılmasını önler.

    ⚠️ Çıplak sayı + vade birimi tutar DEĞİLDİR: "120 ay vadeli konut" ifadesinde
    120 tutar sanılırsa simülasyon 120 TL / 120 ay ile çalışır (ölçüldü).

    ⚠️ "2. el" / "2.el" ikinci el araçtır, 2 TL değildir. İlk çıplak sayı
    alınırsa "2. el araba 500 bin" sorgusu 2 TL / 12 ay simülasyonuna düşer
    (ölçüldü).
    """
    amounts: list[Decimal] = []
    for pattern in (_AMOUNT_BEFORE_CUR_RE, _AMOUNT_AFTER_CUR_RE):
        for match in pattern.finditer(lowered):
            value = parse_decimal_tr(match.group(1))
            if value is not None:
                amounts.append(_apply_multiplier(value, match.group(2)))
        if amounts:
            return amounts

    for match in _BARE_AMOUNT_RE.finditer(lowered):
        # Sıra işareti artığı ("2.el" → eşleşme "2.", artan "el") ve
        # "2'nci el" tırnağı birimden önce gelebilir.
        after = lowered[match.end() : match.end() + 20].lstrip(" .'`")
        if _BARE_NON_AMOUNT_RE.match(after):
            continue
        value = parse_decimal_tr(match.group(1))
        if value is not None:
            amounts.append(_apply_multiplier(value, match.group(2)))
    return amounts


def parse_money(text: str | None) -> tuple[Decimal | None, str]:
    """Metinden para tutarı ve para birimi çıkarır.

    Args:
        text: Ayrıştırılacak metin (ör. "5.000,50 TL").

    Returns:
        (tutar, para_birimi) ikilisi. Tutar bulunamazsa (None, para_birimi).
        Para birimi her durumda döner; tespit edilemezse "TRY".
    """
    if not text:
        return None, DEFAULT_CURRENCY

    normalized = normalize_text(text)
    lowered = lower_tr(normalized)
    currency = detect_currency(normalized)

    amounts = _iter_amounts(lowered)
    if amounts:
        return amounts[0], currency

    # Sayı yoksa "masrafsız" gibi ifadeler tutarı sıfır yapar.
    if _ZERO_COST_RE.search(lowered):
        return Decimal(0), currency

    return None, currency


def parse_money_range(text: str | None) -> tuple[Decimal | None, Decimal | None, str]:
    """Metinden para aralığı çıkarır.

    Örnekler:
        "50.000 - 2.000.000 TL"    -> (50000, 2000000, "TRY")
        "50.000 TL'ye kadar"       -> (None, 50000, "TRY")
        "5.000 TL ve üzeri"        -> (5000, None, "TRY")
        "500 TL"                   -> (500, 500, "TRY")

    Args:
        text: Ayrıştırılacak metin.

    Returns:
        (alt_sınır, üst_sınır, para_birimi) üçlüsü.
    """
    if not text:
        return None, None, DEFAULT_CURRENCY

    normalized = normalize_text(text)
    lowered = lower_tr(normalized)
    currency = detect_currency(normalized)

    # Açık aralık ifadesi en güvenilir sinyaldir; önce o denenir.
    pair = _RANGE_PAIR_RE.search(lowered)
    if pair:
        low = parse_decimal_tr(pair.group(1))
        high = parse_decimal_tr(pair.group(3))
        if low is not None and high is not None:
            low = _apply_multiplier(low, pair.group(2))
            high = _apply_multiplier(high, pair.group(4))
            return min(low, high), max(low, high), currency

    amounts = _iter_amounts(lowered)

    if not amounts:
        if _ZERO_COST_RE.search(lowered):
            return Decimal(0), Decimal(0), currency
        return None, None, currency

    if len(amounts) >= 2 and _RANGE_MARKER_RE.search(lowered):
        first, second = amounts[0], amounts[1]
        return min(first, second), max(first, second), currency

    value = amounts[0]
    # Alt sınır kontrolü önce yapılır: "5.000 TL ve üzeri harcamaya 250 TL'ye kadar"
    # gibi metinlerde ilk tutar alt sınırdır.
    if _LOWER_BOUND_RE.search(lowered):
        return value, None, currency
    if _UPPER_BOUND_RE.search(lowered):
        return None, value, currency
    return value, value, currency


def parse_tier_structure(text: str | None) -> list[dict[str, Decimal]]:
    """Kademeli ödül yapısını çıkarır.

    Örnek:
        "5.000 TL ve üzeri 250 TL, 10.000 TL ve üzeri 500 TL"
        -> [{"threshold": 5000, "reward": 250}, {"threshold": 10000, "reward": 500}]

    Args:
        text: Ayrıştırılacak metin.

    Returns:
        Eşik ve ödül çiftlerinin listesi; bulunamazsa boş liste.
    """
    if not text:
        return []

    lowered = lower_tr(normalize_text(text))
    tiers: list[dict[str, Decimal]] = []

    for match in _TIER_RE.finditer(lowered):
        threshold = parse_decimal_tr(match.group(1))
        reward = parse_decimal_tr(match.group(2))
        if threshold is None or reward is None:
            continue
        tiers.append({"threshold": threshold, "reward": reward})

    return tiers
