"""Ürün oranlarında güncel satır seçimi.

`product_rates` tekilliği `effective_date` içerir: her kazıma günü aynı bant
için yeni satır açılır, eski satır korunur (zaman serisi). Arayüz,
karşılaştırma, simülatör ve sohbet gövdesi yalnızca her bandın en yeni
tarihli satırını göstermeli; arşiv DB'de kalır.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
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


def rate_covers_amount(
    amount: Decimal,
    *,
    rate_min: Decimal | None,
    rate_max: Decimal | None,
    product_min: Decimal | None = None,
    product_max: Decimal | None = None,
) -> bool:
    """İstenen tutar bu oran satırına uygulanabilir mi?

    Hesaplayıcı / ödeme planı sorgusu tek bir örnek tutar yazar
    (`amount_min == amount_max`). Bu bir yayımlanmış kapalı bant değildir;
    aksi halde 150.000 TL örneği 400.000 TL simülasyonunu "oran yok" gösterir.

    Gerçek aralık (`min < max`, ör. Ziraat ücret sayfası 0–400.000) hâlâ
    dışarıdaki tutarı eler. Ürün tavanı (Jet `amount_max`) aşıldıysa satır
    kullanılmaz; tavanı aşan örnek (800 bin probe, ürün max 400 bin) de elenir.

    ⚠️ `product_max < 10.000` tavan sayılmaz: Emlak taşıt sayfasında `400`
    (muhtemel "400 bin" / slider) yazılmıştı ve 400.000 TL talebini eziyordu.
    """
    if product_max is not None and product_max < Decimal("10000"):
        product_max = None
    if product_min is not None and product_min < Decimal("0"):
        product_min = None
    if product_min is not None and amount < product_min:
        return False
    if product_max is not None and amount > product_max:
        return False
    if rate_min is not None and rate_max is not None and rate_min == rate_max:
        return product_max is None or rate_min <= product_max
    if rate_min is not None and amount < rate_min:
        return False
    return rate_max is None or amount <= rate_max


__all__ = ["rate_covers_amount", "select_current_rates"]
