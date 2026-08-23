"""Finansman hesaplayıcı network discovery (tüm bankalar).

Config: `backend/data/config/calculator_banks.yaml`

Çalıştırma:
    python -m scripts.discover_calculator_apis
    python -m scripts.discover_calculator_apis --banka kuveyt_turk
    python -m scripts.discover_calculator_apis --url finansman-hesaplama
    python dev.py kesif-hesaplayici-api
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.logging_config import configure_logging
from app.scrapers.browser import is_playwright_available, playwright_kurulum_mesaji
from app.scrapers.calculator_probes.network_discovery import (
    run_discovery,
    technical_summary,
)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--banka", default=None, help="Yalnızca bu banka kodu")
    parser.add_argument("--url", default=None, help="URL parçası süzgeci")
    parser.add_argument(
        "--surface",
        default=None,
        choices=["home", "calculator", "product"],
        help="Yalnızca ana sayfa / hesaplama aracı / ürün sayfası",
    )
    args = parser.parse_args(argv)

    if not is_playwright_available():
        print(playwright_kurulum_mesaji())
        return 2

    raporlar = run_discovery(
        bank_code=args.banka,
        url_filter=args.url,
        surface=args.surface,
    )
    ozet = technical_summary(raporlar)

    out = Path(__file__).resolve().parent.parent / "data" / "debug" / "network"
    out.mkdir(parents=True, exist_ok=True)
    ozet_yolu = out / "technical_summary.json"
    ozet_yolu.write_text(
        json.dumps(ozet, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    # Windows cp1254 konsolu sıfır genişlikli karakterlerde patlar; dosyaya yazıldı.
    try:
        print(json.dumps(ozet, ensure_ascii=True, indent=2, default=str))
    except UnicodeEncodeError:
        print(f"Konsol yazdırılamadı; özet dosyada: {ozet_yolu}")
    print(f"\n# Özet: {ozet_yolu}", file=sys.stderr)
    print(
        f"# Sayfa: {len(raporlar)}  Adaylı: {sum(1 for r in ozet if r.get('NETWORK_ENDPOINT'))}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
