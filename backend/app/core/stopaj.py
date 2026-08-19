"""Katılma hesabı stopaj (gelir vergisi kesintisi) oranları.

Oranlar bankaların kendi katılma hesabı sayfalarından okundu; Emlak Katılım,
Kuveyt Türk ve Ziraat Katılım bağımsız olarak aynı tabloyu yayımlıyor. Ayrıntı
ve kaynak bağlantıları: `docs/stopaj_oranlari.md`.

⚠️ Stopaj `product_rates`'e YAZILMAZ. Vergi oranıdır, kâr bölüşüm oranı
değildir; banka sayfasında ikisi yan yana durduğu için karıştırılması kolaydır.

⚠️ Oran bankaya göre DEĞİŞMEZ, mevzuatla belirlenir. Bir bankaya özel stopaj
uygulandığını gösteren bir veri görülürse önce sayfanın yanlış okunmadığı
doğrulanmalıdır.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

# Tablonun bankaların canlı sayfalarına karşı en son doğrulandığı tarih.
STOPAJ_GECERLILIK: Final[str] = "2026-08-19"

STOPAJ_DAYANAK: Final[str] = (
    "193 sayılı Gelir Vergisi Kanunu geçici md. 67; oranlar Cumhurbaşkanı "
    "Kararı ile belirlenir (2006/10731 sayılı BKK ve değişiklikleri)."
)

# Türk lirası katılma hesabında stopaj VADEYE göre kademelenir: uzun vade
# daha az vergilenir. Eşikler gün cinsinden üst sınırdır.
_TRY_KADEMELER: Final[tuple[tuple[int | None, Decimal], ...]] = (
    (180, Decimal("17.5")),  # 6 aya kadar
    (365, Decimal("15.0")),  # 6 ay - 1 yıl (1 yıllık dahil)
    (None, Decimal("10.0")),  # 1 yıldan uzun
)

# Yabancı parada vade kademesi YOKTUR; tüm vadelerde tek oran uygulanır.
_DOVIZ_ORANI: Final[Decimal] = Decimal("25.0")

# Kıymetli madende de vade kademesi yoktur.
_MADEN_ORANI: Final[Decimal] = Decimal("15.0")

_DOVIZLER: Final[frozenset[str]] = frozenset({"USD", "EUR"})
_MADENLER: Final[frozenset[str]] = frozenset({"XAU", "XAG"})


def stopaj_orani(currency: str, term_days: int) -> Decimal:
    """Para birimi ve vadeye düşen stopaj oranını yüzde olarak döndürür.

    Args:
        currency: `CURRENCIES` içinden bir değer (TRY, USD, EUR, XAU, XAG).
        term_days: Vade gün sayısı.

    Returns:
        Yüzde cinsinden stopaj oranı (ör. 1 aylık TL için `Decimal("17.5")`).

    Raises:
        ValueError: `term_days` pozitif değilse.

    """
    if term_days <= 0:
        raise ValueError(f"term_days pozitif olmalı: {term_days}")

    para = currency.upper()
    if para in _DOVIZLER:
        return _DOVIZ_ORANI
    if para in _MADENLER:
        return _MADEN_ORANI

    for ust_gun, oran in _TRY_KADEMELER:
        if ust_gun is None or term_days <= ust_gun:
            return oran

    # `_TRY_KADEMELER` son kademesi `None` olduğu için buraya düşülmez.
    raise AssertionError("stopaj kademesi bulunamadı")  # pragma: no cover


def stopaj_aciklamasi(currency: str, term_days: int) -> str:
    """Uygulanan stopaj oranını dayanağıyla birlikte tek cümlede anlatır.

    Yanıtta gösterilir: kullanıcı net tutarın nasıl bulunduğunu görebilmeli,
    sayı gökten inmemelidir.
    """
    oran = stopaj_orani(currency, term_days)
    return (
        f"{currency.upper()} / {term_days} gün vade için %{oran} stopaj "
        f"uygulandı. Dayanak: {STOPAJ_DAYANAK} "
        f"(oranlar {STOPAJ_GECERLILIK} tarihinde banka sayfalarından doğrulandı)."
    )
