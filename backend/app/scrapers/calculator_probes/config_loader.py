"""Finansman hesaplayıcı hedeflerini JSON config'ten yükler."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.scrapers.calculator_probes.targets import ProbeTarget

CONFIG_PATH = Path(__file__).resolve().parents[3] / "data" / "config" / "calculator_banks.json"


@dataclass(frozen=True)
class CalculatorPage:
    """Tek bir banka hesaplayıcı / ürün sayfası hedefi."""

    bank_code: str
    bank_name: str
    label: str
    url: str
    strategy: str = "discover"
    product_hint: str | None = None
    product_filter: tuple[str, ...] | None = None
    surface: str = "calculator"
    """home | calculator | product"""


def _load_raw() -> dict[str, Any]:
    if not CONFIG_PATH.is_file():
        raise FileNotFoundError(f"Hesaplayıcı config yok: {CONFIG_PATH}")
    with CONFIG_PATH.open(encoding="utf-8") as f:
        veri: dict[str, Any] = json.load(f)
    return veri


@lru_cache(maxsize=1)
def load_calculator_pages() -> tuple[CalculatorPage, ...]:
    """Config'teki tüm hesaplayıcı sayfalarını döndürür."""
    raw = _load_raw()
    sayfalar: list[CalculatorPage] = []
    for banka in raw.get("banks") or []:
        kod = banka["code"]
        ad = banka.get("name") or kod
        for calc in banka.get("calculators") or []:
            filtre = calc.get("product_filter")
            sayfalar.append(
                CalculatorPage(
                    bank_code=kod,
                    bank_name=ad,
                    label=calc["label"],
                    url=calc["url"],
                    strategy=calc.get("strategy") or "discover",
                    product_hint=calc.get("product_hint"),
                    product_filter=tuple(filtre) if filtre else None,
                    surface=calc.get("surface") or "calculator",
                )
            )
    return tuple(sayfalar)


def pages_for_bank(
    bank_code: str | None = None,
    *,
    surface: str | None = None,
) -> tuple[CalculatorPage, ...]:
    """İsteğe bağlı banka / yüzey süzgeci."""
    pages = load_calculator_pages()
    if bank_code:
        pages = tuple(p for p in pages if p.bank_code == bank_code)
    if surface:
        pages = tuple(p for p in pages if p.surface == surface)
    return pages


def probe_targets_from_config(bank_code: str | None = None) -> tuple[ProbeTarget, ...]:
    """Mevcut Playwright stratejisi olan sayfaları ProbeTarget'a çevirir.

    `strategy=discover` olanlar yalnızca network keşfinde kullanılır.
    """
    from app.scrapers.calculator_probes.targets import ProbeTarget

    hedefler: list[ProbeTarget] = []
    for p in pages_for_bank(bank_code):
        if p.strategy == "discover":
            continue
        hedefler.append(
            ProbeTarget(
                bank_code=p.bank_code,
                url=p.url,
                strategy=p.strategy,
                label=p.label,
                product_filter=p.product_filter,
            )
        )
    return tuple(hedefler)
