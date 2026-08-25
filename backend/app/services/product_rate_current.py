"""Ürün oranlarında güncel satır seçimi.

`product_rates` tekilliği `effective_date` içerir: her kazıma günü aynı bant
için yeni satır açılır, eski satır korunur (zaman serisi). Arayüz,
karşılaştırma, simülatör ve sohbet gövdesi yalnızca her bandın en yeni
tarihli satırını göstermeli; arşiv DB'de kalır.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Protocol, TypeVar


class _RateLike(Protocol):
    id: int
    product_id: int
    rate_source: str
    band_key: str
    effective_date: date | None


T = TypeVar("T", bound=_RateLike)


def _tarih_anahtari(d: date | None) -> tuple[int, date]:
    """None tarihleri en eski say; karşılaştırma için sıralanabilir anahtar."""
    if d is None:
        return (0, date.min)
    return (1, d)


def select_current_rates(rates: Sequence[T]) -> list[T]:
    """Her `(product_id, rate_source, band_key)` için en yeni `effective_date`.

    Aynı tarihte birden fazla satır varsa yüksek `id` (daha yeni yazım) kazanır.
    Girdi sırası korunmaz; çıktı `term` bilgisi olmayan nesnelerde `id` ile
    kararlı sıralanır.
    """
    if not rates:
        return []

    en_iyi: dict[tuple[int, str, str], T] = {}
    for oran in rates:
        anahtar = (oran.product_id, oran.rate_source or "", oran.band_key or "")
        mevcut = en_iyi.get(anahtar)
        if mevcut is None:
            en_iyi[anahtar] = oran
            continue
        yeni_t = _tarih_anahtari(oran.effective_date)
        eski_t = _tarih_anahtari(mevcut.effective_date)
        if yeni_t > eski_t or (yeni_t == eski_t and oran.id > mevcut.id):
            en_iyi[anahtar] = oran

    sonuc = list(en_iyi.values())
    sonuc.sort(
        key=lambda o: (
            getattr(o, "term_months", None) is None,
            getattr(o, "term_months", None) or 0,
            o.id,
        )
    )
    return sonuc


__all__ = ["select_current_rates"]
