"""Katılım Hesabı sekmesi API şeması (KATİP KAPI 7).

TKBB Veri Peteği'nin kendi dashboard görünümünü taklit eder: satır banka,
sütun `{vade}|{para_birimi}` bileşik anahtarı.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


class KatilimHesabiCrossCheck(BaseModel):
    """İki bağımsız kaynağın (TKBB / banka sitesi) çapraz doğrulaması.

    ⚠️ Yalnızca HER İKİ kaynak da aynı hücrede değere sahipse doldurulur;
    tek kaynak varsa bu alan hiç eklenmez (uydurma yok).
    """

    bank_site_value: Decimal | None = None
    tkbb_value: Decimal | None = None
    match: str = Field(description="ayni | yakin | farkli")


class KatilimHesabiRow(BaseModel):
    """Tek bir bankanın pivot satırı."""

    bank_code: str
    bank_name: str
    values: dict[str, Decimal] = Field(
        default_factory=dict, description='"{vade}|{para_birimi}" -> değer'
    )
    data_source: str = Field(description="Bu satırın birincil kaynağı: bank_site | tkbb_veripetegi")
    cross_check: KatilimHesabiCrossCheck | None = None


class KatilimHesabiResponse(BaseModel):
    """Katılım Hesabı sekmesinin pivot yanıtı."""

    rate_type: str
    variant: str
    rows: list[KatilimHesabiRow] = Field(default_factory=list)
    not_offered_banks: list[str] = Field(
        default_factory=list,
        description="Bu ürünü/varyantı hiç sunmayan bankalar (veri eksik değil, ürün yok)",
    )
    data_quality_notes: list[str] = Field(default_factory=list)
