"""Hesaplayıcı URL hedefleri.

Kaynak: `backend/data/config/calculator_banks.yaml`
Probe yalnızca `strategy != discover` olan satırları kullanır.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProbeTarget:
    bank_code: str
    url: str
    strategy: str
    label: str
    """Rapor adı."""
    product_filter: tuple[str, ...] | None = None
    """Albaraka gibi birleşik sayfada yalnızca ilgili ürün ailesi."""


def _load_probe_targets() -> tuple[ProbeTarget, ...]:
    from app.scrapers.calculator_probes.config_loader import probe_targets_from_config

    return probe_targets_from_config()


PROBE_TARGETS: tuple[ProbeTarget, ...] = _load_probe_targets()
