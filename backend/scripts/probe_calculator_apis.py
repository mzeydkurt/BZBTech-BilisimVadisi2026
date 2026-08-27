"""Doğrulanmış finansman hesaplama API'lerini httpx ile sorgular.

httpx (method=api, is_binding=False):
  - Albaraka — getFinanceCalculate
  - Dünya Katılım — LoanInstallmentValues + LoanCheckRate
  - Vakıf Katılım — InstallmentPayBack
  - Hayat Finans — calculateloansproduct
  - Emlak Katılım — CalculateLoansProduct
  - Kuveyt Türk — ck0d84 LoanCalculator (oturum çerezi; CAPTCHA yok)
  - Türkiye Finans — GetFinanceCalculatorCreditTypeItems (band Value = oran)

Playwright kalır:
  - Ziraat Katılım — ajax/finansmanhesapla httpx'te 493 (WAF); ziraat_product_dropdown

Çalıştırma:
    python -m scripts.probe_calculator_apis
    python -m scripts.probe_calculator_apis --banka dunya_katilim
    python -m scripts.probe_calculator_apis --kuru
    python dev.py hesaplayici-api-sorgula
"""

from __future__ import annotations

import argparse
import json
import sys

from app.logging_config import configure_logging
from app.scrapers.calculator_probes.api_adapters.runner import run_api_probes


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--banka",
        default=None,
        help=(
            "albaraka | dunya_katilim | vakif_katilim | hayat_finans | "
            "emlak_katilim | kuveyt_turk | turkiye_finans"
        ),
    )
    parser.add_argument("--kuru", action="store_true", help="DB'ye yazma")
    args = parser.parse_args(argv)
    ozet = run_api_probes(bank_code=args.banka, dry_run=args.kuru)
    try:
        print(json.dumps(ozet, ensure_ascii=True, indent=2))
    except UnicodeEncodeError:
        sys.stdout.buffer.write(
            (json.dumps(ozet, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        )
    return 0 if not ozet.get("hatalar") else 1


if __name__ == "__main__":
    raise SystemExit(main())
