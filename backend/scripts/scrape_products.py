"""Ürün / finansman kazıma CLI'ı.

⚠️ AĞA ÇIKAR. İş mantığı `app/scrapers/products.py` içindedir; bu dosya ince
bir sarmalayıcıdır (argparse + çıktı + çıkış kodu).

Çıkış kodu: 0 başarı · 1 kısmi/hatalı · 2 kullanım hatası.
"""

from __future__ import annotations

import argparse
import sys

from app.logging_config import configure_logging
from app.scrapers.models import ProductRunResult
from app.scrapers.products import run_products
from app.scrapers.registry import available_banks


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Komut satırı argümanlarını ayrıştırır."""
    parser = argparse.ArgumentParser(
        prog="scrape_products",
        description="Bankaların ürün/finansman sayfalarından limit, varyant ve oran çıkarır.",
    )
    hedef = parser.add_mutually_exclusive_group(required=True)
    hedef.add_argument("--banka", "--bank", dest="banka", help="Tek banka kodu")
    hedef.add_argument("--tumu", "--all", dest="tumu", action="store_true", help="Tüm bankalar")
    parser.add_argument("--kuru", action="store_true", help="Yazma yapma, yalnızca raporla")
    return parser.parse_args(argv)


def _rapor(sonuc: ProductRunResult) -> None:
    """Tek bankanın özetini basar."""
    # `run.py` ile aynı istisna: CLI çıktısı `print` kullanır.
    print(  # noqa: T201
        f"  {sonuc.bank_code:16} {sonuc.status:8}"
        f" keşif={sonuc.urls_discovered:3}"
        f" çekim={sonuc.urls_fetched:3}"
        f" yeni ürün={sonuc.products_new:3}"
        f" güncel={sonuc.products_updated:3}"
        f" yeni oran={sonuc.rates_new:4}"
        f" hata={sonuc.errors_count}"
    )
    for hata in sonuc.errors[:5]:
        print(f"      ! {hata}")  # noqa: T201


def main(argv: list[str] | None = None) -> int:
    """Ürün kazımasını çalıştırır."""
    args = _parse_args(argv)
    configure_logging()

    kodlar = available_banks() if args.tumu else [args.banka]
    bilinmeyen = [k for k in kodlar if k not in available_banks()]
    if bilinmeyen:
        print(f"Bilinmeyen banka kodu: {', '.join(bilinmeyen)}", file=sys.stderr)  # noqa: T201
        return 2

    print("Ürün kazıması" + (" (KURU ÇALIŞTIRMA)" if args.kuru else ""))  # noqa: T201
    kismi = False
    for kod in kodlar:
        sonuc = run_products(kod, dry_run=args.kuru)
        _rapor(sonuc)
        if sonuc.status != "success":
            kismi = True

    return 1 if kismi else 0


if __name__ == "__main__":
    raise SystemExit(main())
