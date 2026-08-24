"""Oran türüne göre müşteri için avantajlı yön — tek kaynak.

⚠️ İKİ YERDE AYRI YAZILMAZ. `comparison_service` ve sohbet yanıt denetimi
aynı fonksiyondan okur; biri güncellenir diğeri unutulursa ters yönlü
"avantajlı" cümlesi jüriye kadar sessizce sızar.

Yön anlamı:
  True  → yüksek değer müşteri için avantajlı (getiri, paylaşım)
  False → düşük değer müşteri için avantajlı (finansman maliyeti)
  None  → yön yok (karz-ı hasen); avantaj cümlesi kurulmaz
"""

from __future__ import annotations

from typing import Final

# rate_type → yüksek mi avantajlı?
_YON: Final[dict[str, bool]] = {
    "financing_rate": False,
    "participation_yield": True,
    "profit_sharing_ratio": True,
}

_YON_NOTLARI: Final[dict[str, str]] = {
    "financing_rate": "Finansman oranında düşük değer müşteri için avantajlıdır.",
    "participation_yield": (
        "Katılma hesabı dağıtılan kâr payında yüksek değer müşteri için avantajlıdır."
    ),
    "profit_sharing_ratio": (
        "Kâr paylaşım oranında (müşteri payı) yüksek değer müşteri için avantajlıdır."
    ),
}


def avantajli_yon(rate_type: str) -> bool | None:
    """Müşteri için yüksek değer mi avantajlı?

    Args:
        rate_type: `financing_rate` | `participation_yield` |
            `profit_sharing_ratio` | `interest_free_benevolent_loan`.

    Returns:
        `True` yüksek iyi · `False` düşük iyi · `None` yön yok / bilinmiyor.
    """
    if rate_type == "interest_free_benevolent_loan":
        return None
    return _YON.get(rate_type)


def yon_notu(rate_type: str) -> str | None:
    """Arayüzde gösterilecek yön açıklaması; yön yoksa `None`."""
    if avantajli_yon(rate_type) is None:
        return None
    return _YON_NOTLARI.get(rate_type)


__all__ = ["avantajli_yon", "yon_notu"]
