"""Playwright ile JS liste genişletme + httpx detay çekimi.

    python -m scripts.scrape_js_campaigns
    python -m scripts.scrape_js_campaigns --banka kuveyt_turk
    python -m scripts.scrape_js_campaigns --kuru

Banka scraper dosyalarına Playwright gömülmez. Toplanan URL'ler mevcut
`parse_detail` + upsert (`bank_id`, `external_slug`) ile işlenir.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from app.db.models import Bank
from app.db.session import SessionLocal
from app.logging_config import get_logger
from app.scrapers.js_listing import expand_all
from app.scrapers.models import DiscoveredUrl, ScrapeRunResult
from app.scrapers.registry import get_scraper

logger = get_logger(__name__)


def _calistir(*, bank_filter: str | None, dry_run: bool) -> int:
    bank_codes = {bank_filter} if bank_filter else None
    harita = expand_all(bank_codes=bank_codes)
    if not harita:
        print("JS listeden URL toplanamadı (Playwright kurulu mu?).")
        return 1

    toplam_yeni = toplam_guncel = 0
    with SessionLocal() as session:
        for kod, urls in harita.items():
            scraper = get_scraper(kod)
            try:
                bank = session.scalar(select(Bank).where(Bank.code == kod))
                if bank is None:
                    print(f"  {kod}: banka kaydı yok — seed çalıştırın.")
                    continue
                result = ScrapeRunResult(bank_code=kod)
                seen_slugs: set[str] = set()
                recorded: set[str] = set()
                print(f"\n{kod}: {len(urls)} URL (JS liste)")
                for url in urls:
                    hint = DiscoveredUrl(
                        url=url,
                        doc_type="campaign",
                        discovery_method="js_listing",
                    )
                    if dry_run:
                        print(f"  [kuru] {url}")
                        continue
                    try:
                        scraper._process_url(  # noqa: SLF001 — bilerek ortak upsert yolu
                            session,
                            bank,
                            hint,
                            result,
                            seen_slugs,
                            recorded,
                            dry_run=False,
                        )
                    except Exception as exc:
                        result.add_error(f"{url}: {exc}")
                        logger.warning("js_scrape_url_hata", url=url, hata=str(exc))
                if not dry_run:
                    session.commit()
                print(
                    f"  yeni={result.campaigns_new} güncellenen={result.campaigns_updated} "
                    f"hata={result.errors_count}"
                )
                toplam_yeni += result.campaigns_new
                toplam_guncel += result.campaigns_updated
            finally:
                scraper.close()

    print(f"\nToplam: yeni={toplam_yeni} güncellenen={toplam_guncel}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="JS liste + httpx kampanya tamamlaması")
    parser.add_argument("--banka", default=None, help="Tek banka kodu")
    parser.add_argument("--kuru", action="store_true", help="Yazma; yalnızca URL yazdır")
    args = parser.parse_args(argv)
    return _calistir(bank_filter=args.banka, dry_run=args.kuru)


if __name__ == "__main__":
    sys.exit(main())
