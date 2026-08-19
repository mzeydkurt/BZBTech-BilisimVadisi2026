"""Kâr payı oranı ayrıştırma.

TERMİNOLOJİ: Bu modül "kâr payı oranı" ayrıştırır. Katılım bankacılığında
faiz kavramı bulunmaz; kod ve dokümantasyonda o terim kullanılmaz.

Yüzde işareti Türkçe metinde sayının SOLUNDA yazılır ("%2,05"), ancak bankaların
sayfalarında sağda yazımına da ("2,05%") ve "yüzde" kelimesiyle yazımına da
rastlanır. Üç biçim de desteklenir.

TASARIM KARARI: Çıplak sayı (ör. "2,05") oran SAYILMAZ. Yüzde işareti veya
"yüzde" kelimesi zorunludur. Aksi hâlde metindeki her sayı — SMS numarası, şube
kodu, puan — yanlışlıkla oran olarak çıkarılırdı.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Final

from app.core.normalization.money import parse_decimal_tr
from app.core.normalization.text import lower_tr, normalize_text

_NUM = r"\d[\d.,]*"

# Yüzde ifadesinin üç yazım biçimi. Metindeki konumuna göre en erken eşleşme seçilir.
_RATE_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(rf"%\s*({_NUM})"),  # %2,05  ·  % 2.05
    re.compile(rf"({_NUM})\s*%"),  # 2,05%  ·  2.05 %
    re.compile(rf"yüzde\s*({_NUM})"),  # yüzde 2,05
)

# "Vade farksız" = kâr payı farkı uygulanmıyor, yani oran sıfır.
# "Peşin fiyatına taksit" de aynı anlama gelir.
_ZERO_RATE_RE: Final[re.Pattern[str]] = re.compile(
    r"vade\s+farksız|vade\s+farkı\s+yok|vade\s+farksızdır|peşin\s+fiyatına"
)

_RANGE_MARKER_RE: Final[re.Pattern[str]] = re.compile(
    r"\d\s*-\s*|%\s*\d[\d.,]*\s*-|\bile\b|\bila\b|arasında|arası"
)

_UPPER_BOUND_RE: Final[re.Pattern[str]] = re.compile(
    r"varan|kadar|azami|maksimum|en\s+fazla|en\s+çok|üst\s+limit"
)

_LOWER_BOUND_RE: Final[re.Pattern[str]] = re.compile(
    r"başlayan|itibaren|en\s+az|asgari|minimum|ve\s+üzeri|ve\s+üstü|alt\s+limit"
)


def _find_rates(lowered: str) -> list[Decimal]:
    """Metindeki tüm oran değerlerini geçiş sırasına göre listeler.

    Args:
        lowered: Normalize edilmiş ve küçük harfe çevrilmiş metin.

    Returns:
        Metinde göründükleri sırayla oran değerleri.
    """
    found: list[tuple[int, Decimal]] = []
    seen_positions: set[int] = set()

    for pattern in _RATE_PATTERNS:
        for match in pattern.finditer(lowered):
            value = parse_decimal_tr(match.group(1))
            if value is None:
                continue
            # Aynı sayı birden fazla kalıpla eşleşebilir; sayının konumu tekilleştirir.
            position = match.start(1)
            if position in seen_positions:
                continue
            seen_positions.add(position)
            found.append((position, value))

    found.sort(key=lambda item: item[0])
    return [value for _, value in found]


def parse_rate(text: str | None) -> Decimal | None:
    """Metinden kâr payı oranını yüzde cinsinden çıkarır.

    Örnekler:
        "%2,05"          -> 2.05
        "2.05 %"         -> 2.05
        "yüzde 2,05"     -> 2.05
        "%50'ye varan"   -> 50
        "vade farksız"   -> 0
        "avantajlı kâr payı fırsatı" -> None

    Args:
        text: Ayrıştırılacak metin.

    Returns:
        Yüzde değeri (100'lük tabanda, ör. %2,05 için Decimal("2.05")) veya
        oran bulunamazsa None.
    """
    if not text:
        return None

    lowered = lower_tr(normalize_text(text))

    rates = _find_rates(lowered)
    if rates:
        return rates[0]

    # Sayı yoksa "vade farksız" ifadesi oranı sıfırlar.
    if _ZERO_RATE_RE.search(lowered):
        return Decimal(0)

    return None


def parse_rate_range(text: str | None) -> tuple[Decimal | None, Decimal | None]:
    """Metinden kâr payı oranı aralığını çıkarır.

    Örnekler:
        "%1,89 - %2,45"    -> (1.89, 2.45)
        "%50'ye varan"     -> (None, 50)
        "%2,05'ten başlayan" -> (2.05, None)
        "%2,05"            -> (2.05, 2.05)

    Args:
        text: Ayrıştırılacak metin.

    Returns:
        (alt_sınır, üst_sınır) ikilisi; oran bulunamazsa (None, None).
    """
    if not text:
        return None, None

    lowered = lower_tr(normalize_text(text))
    rates = _find_rates(lowered)

    if not rates:
        if _ZERO_RATE_RE.search(lowered):
            return Decimal(0), Decimal(0)
        return None, None

    if len(rates) >= 2 and _RANGE_MARKER_RE.search(lowered):
        first, second = rates[0], rates[1]
        return min(first, second), max(first, second)

    value = rates[0]
    if _UPPER_BOUND_RE.search(lowered):
        return None, value
    if _LOWER_BOUND_RE.search(lowered):
        return value, None
    return value, value


_PROFIT_SHARING_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:%\s*)?(\d{1,2}(?:[.,]\d+)?)\s*(?:/|[-–—]|\b|\\\s*)\s*(?:%\s*)?(\d{1,2}(?:[.,]\d+)?)"
)


def parse_profit_sharing_ratio(text: str | None) -> tuple[Decimal | None, Decimal | None]:
    """Bölüşüm oranını (investor_share, bank_share) olarak çıkarır.

    Örnekler:
        "90/10"          -> (90.0, 10.0)
        "%90 - %10"      -> (90.0, 10.0)
        "89.1 / 10.9"    -> (89.1, 10.9)
        "98/2"           -> (98.0, 2.0)

    Args:
        text: Ayrıştırılacak metin.

    Returns:
        (investor_share_pct, bank_share_pct) ikilisi; okunamazsa (None, None).
    """
    if not text:
        return None, None

    lowered = lower_tr(normalize_text(text))

    # Öncelikle "90/10" veya "%90 - %10" biçimlerini ara
    m = re.search(
        r"(?:%\s*)?(\d{1,2}(?:[.,]\d+)?)\s*(?:/|[-–—])\s*(?:%\s*)?(\d{1,2}(?:[.,]\d+)?)",
        lowered,
    )
    if m:
        inv = parse_decimal_tr(m.group(1))
        bnk = parse_decimal_tr(m.group(2))
        if (
            inv is not None
            and bnk is not None
            and Decimal("0") <= inv <= Decimal("100")
            and Decimal("0") <= bnk <= Decimal("100")
        ):
            return inv, bnk

    # Çıplak tek yüzde (ör. %90) varsa: investor=90, bank=10
    rate = parse_rate(lowered)
    if rate is not None and Decimal("0") < rate < Decimal("100"):
        return rate, Decimal("100") - rate

    return None, None
