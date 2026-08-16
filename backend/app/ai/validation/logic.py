"""Katman 5 — mantık kuralları.

Tek tek doğru görünen değerler BİRLİKTE tutarsız olabilir: bitiş tarihi
başlangıçtan önce, asgari harcama azamiden büyük, %250 kâr payı. Bu katman
alanları birbirine karşı denetler.

⚠️ İHLAL EDEN KAYIT SİLİNMEZ. `is_validated=False` ve `validation_note`
ile işaretlenir. Silinirse "sistem bu alanı hiç bulamadı" ile "buldu ama
tutarsızdı" ayrımı kaybolur; ikincisi bir çıkarım hatasıdır ve ölçülmelidir.

⚠️ EKSİK ALAN İHLAL DEĞİLDİR. `min_spend < max_spend` kuralı yalnızca İKİSİ
DE varken çalışır. Bulunmayan bir alanı ihlal saymak, "bilgi yok"u hataya
çevirirdi — oysa bilgi yokken susmak istenen davranıştır.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Final


@dataclass(frozen=True)
class LogicRule:
    """Alanlar arası tek bir tutarlılık kuralı."""

    name: str
    fields: tuple[str, ...]
    check: Callable[[Mapping[str, Any]], bool]
    message: str


def _sayi(deger: Any) -> Decimal | None:
    """Değeri Decimal'e çevirir; çevrilemezse None."""
    if deger is None:
        return None
    try:
        return Decimal(str(deger))
    except (InvalidOperation, ValueError):
        return None


def _tarih_sirasi(degerler: Mapping[str, Any]) -> bool:
    """Bitiş, başlangıçtan önce olamaz.

    ⚠️ Eşitlik GEÇERLİDİR: tek günlük kampanyalar var.
    """
    return str(degerler["start_date"]) <= str(degerler["end_date"])


def _aralik(alt_adi: str, ust_adi: str) -> Callable[[Mapping[str, Any]], bool]:
    """Alt sınırın üst sınırı aşmadığını denetleyen kural üretir."""

    def denetle(degerler: Mapping[str, Any]) -> bool:
        alt, ust = _sayi(degerler[alt_adi]), _sayi(degerler[ust_adi])
        return alt is None or ust is None or alt <= ust

    return denetle


def _sinir(alan: str, en_az: Decimal, en_cok: Decimal) -> Callable[[Mapping[str, Any]], bool]:
    """Değerin makul aralıkta olduğunu denetleyen kural üretir."""

    def denetle(degerler: Mapping[str, Any]) -> bool:
        sayi = _sayi(degerler[alan])
        return sayi is None or en_az <= sayi <= en_cok

    return denetle


# ⚠️ SEKİZ KURAL (şartname §8.4). Sınırlar gerçek veriye göre seçildi:
# 360 ay = 30 yıl konut finansmanı, 60 taksit üst sınırı bankacılık
# düzenlemesiyle uyumlu.
RULES: Final[tuple[LogicRule, ...]] = (
    LogicRule(
        "tarih_sirasi",
        ("start_date", "end_date"),
        _tarih_sirasi,
        "bitiş tarihi başlangıçtan önce",
    ),
    LogicRule(
        "kar_payi_araligi",
        ("profit_rate_pct",),
        _sinir("profit_rate_pct", Decimal(0), Decimal(100)),
        "kâr payı oranı 0-100 aralığı dışında",
    ),
    LogicRule(
        "harcama_araligi",
        ("min_spend_try", "max_spend_try"),
        _aralik("min_spend_try", "max_spend_try"),
        "asgari harcama azamiden büyük",
    ),
    LogicRule(
        "vade_araligi",
        ("term_months_max",),
        _sinir("term_months_max", Decimal(1), Decimal(360)),
        "vade 1-360 ay aralığı dışında",
    ),
    LogicRule(
        "taksit_araligi",
        ("installment_count",),
        _sinir("installment_count", Decimal(1), Decimal(60)),
        "taksit sayısı 1-60 aralığı dışında",
    ),
    LogicRule(
        "odul_negatif_degil",
        ("reward_amount_try",),
        _sinir("reward_amount_try", Decimal(0), Decimal(10_000_000)),
        "ödül tutarı negatif ya da aşırı",
    ),
    LogicRule(
        "iade_orani",
        ("cashback_pct",),
        _sinir("cashback_pct", Decimal(0), Decimal(100)),
        "iade oranı 0-100 aralığı dışında",
    ),
    LogicRule(
        "finansman_araligi",
        ("financing_amount_min", "financing_amount_max"),
        _aralik("financing_amount_min", "financing_amount_max"),
        "asgari finansman azamiden büyük",
    ),
)


def check_logic(values: Mapping[str, Any]) -> dict[str, str]:
    """Kampanyanın alanlarını mantık kurallarına karşı denetler.

    Args:
        values: Alan adı → normalize edilmiş değer. Bulunmayan alanlar
            sözlükte HİÇ olmamalıdır (None ile değil).

    Returns:
        İhlal eden alan adı → açıklama. İhlal yoksa boş sözlük.
    """
    ihlaller: dict[str, str] = {}

    for kural in RULES:
        # ⚠️ Kuralın dokunduğu alanların hepsi yoksa kural ÇALIŞTIRILMAZ.
        if not all(alan in values and values[alan] is not None for alan in kural.fields):
            continue
        if kural.check(values):
            continue
        for alan in kural.fields:
            ihlaller[alan] = kural.message

    return ihlaller
