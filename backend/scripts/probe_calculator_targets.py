"""Verilen banka hesaplayıcı URL'lerinden Playwright ile örnek oran sorgusu.

Kullanıcı tarafından belirtilen hesaplama sayfalarını sırayla dener;
ürün dropdown'ındaki her seçeneği max tutar/vade ile sorgular.

⚠️ Çıktılar bağlayıcı DEĞİLDİR (`is_binding=False`).
⚠️ İstekler arası ≥2 sn bekleme.

Çalıştırma:
    python -m scripts.probe_calculator_targets
    python -m scripts.probe_calculator_targets --banka kuveyt_turk
    python -m scripts.probe_calculator_targets --kuru
    python -m scripts.probe_calculator_targets --url turkiyefinans
"""

from __future__ import annotations

import argparse
import json
import sys

from app.logging_config import configure_logging
from app.scrapers.calculator_probes.runner import run_probe_targets


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--banka", default=None, help="Yalnızca bu banka kodu")
    parser.add_argument("--url", default=None, help="URL parçası süzgeci")
    parser.add_argument("--kuru", action="store_true", help="DB'ye yazma")
    args = parser.parse_args(argv)
    try:
        ozet = run_probe_targets(
            bank_code=args.banka,
            dry_run=args.kuru,
            url_filter=args.url,
        )
    except RuntimeError as exc:
        print(str(exc))
        return 2
    print(json.dumps(ozet, ensure_ascii=False, indent=2))
    return 0 if not ozet.get("hatalar") else 1


if __name__ == "__main__":
    raise SystemExit(main())
