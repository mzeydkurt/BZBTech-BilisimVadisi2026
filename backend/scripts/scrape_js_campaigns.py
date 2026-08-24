"""Playwright ile JS liste genişletme + httpx detay çekimi.

    python -m scripts.scrape_js_campaigns
    python -m scripts.scrape_js_campaigns --banka kuveyt_turk
    python -m scripts.scrape_js_campaigns --kuru
    python -m scripts.scrape_js_campaigns --rapor

Banka scraper dosyalarına Playwright gömülmez. Toplanan URL'ler mevcut
`parse_detail` + upsert (`bank_id`, `external_slug`) ile işlenir.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import func, select

from app.db.models import Bank, Campaign
from app.db.session import SessionLocal
from app.logging_config import get_logger
from app.scrapers.js_listing import expand_all, expand_all_detailed
from app.scrapers.models import DiscoveredUrl, ScrapeRunResult
from app.scrapers.registry import get_scraper

logger = get_logger(__name__)

KOK = Path(__file__).resolve().parents[2]
RAPOR = KOK / "docs" / "js_listing_kapsama.md"


def _kapsama_yaz(sonuclar: list) -> None:
    """Hedef başına kapsama raporunu markdown olarak yazar."""
    RAPOR.parent.mkdir(parents=True, exist_ok=True)
    satirlar = [
        "# JS liste kapsama raporu",
        "",
        "| Banka | Liste URL | Strateji | Tur | Limit doldu | URL | Not |",
        "|---|---|---|---|---|---|---|",
    ]
    with SessionLocal() as session:
        for r in sonuclar:
            notu = ""
            if r.limit_doldu:
                notu = "**LİMİT DOLDU — sessiz kırpma riski**"
            elif not r.urls:
                notu = "0 URL"
            mevcut = 0
            if r.urls:
                # Kabaca: aynı bankadaki kampanya sayısı ile karşılaştırılmaz;
                # yalnızca toplanan URL sayısı raporlanır.
                bank = session.scalar(select(Bank).where(Bank.code == r.bank_code))
                if bank is not None:
                    mevcut = (
                        session.scalar(
                            select(func.count())
                            .select_from(Campaign)
                            .where(Campaign.bank_id == bank.id)
                        )
                        or 0
                    )
            satirlar.append(
                f"| `{r.bank_code}` | `{r.listing_url}` | {r.strateji} | "
                f"{r.tur_sayisi} | {'EVET' if r.limit_doldu else 'hayır'} | "
                f"{len(r.urls)} (DB kampanya≈{mevcut}) | {notu} |"
            )
    satirlar.append("")
    RAPOR.write_text("\n".join(satirlar), encoding="utf-8")
    print(f"Kapsama raporu: {RAPOR}")  # noqa: T201


def _calistir(*, bank_filter: str | None, dry_run: bool, rapor: bool) -> int:
    bank_codes = {bank_filter} if bank_filter else None

    if rapor:
        detay = expand_all_detailed(bank_codes=bank_codes)
        _kapsama_yaz(detay)
        if not any(r.urls for r in detay):
            print("JS listeden URL toplanamadı (Playwright kurulu mu?).")  # noqa: T201
            return 1

    harita = expand_all(bank_codes=bank_codes)
    if not harita:
        print("JS listeden URL toplanamadı (Playwright kurulu mu?).")  # noqa: T201
        return 1

    toplam_yeni = toplam_guncel = 0
    with SessionLocal() as session:
        for kod, urls in harita.items():
            scraper = get_scraper(kod)
            try:
                bank = session.scalar(select(Bank).where(Bank.code == kod))
                if bank is None:
                    print(f"  {kod}: banka kaydı yok — seed çalıştırın.")  # noqa: T201
                    continue
                result = ScrapeRunResult(bank_code=kod)
                seen_slugs: set[str] = set()
                recorded: set[str] = set()
                print(f"\n{kod}: {len(urls)} URL (JS liste)")  # noqa: T201
                for url in urls:
                    hint = DiscoveredUrl(
                        url=url,
                        doc_type="campaign",
                        discovery_method="js_listing",
                    )
                    if dry_run:
                        print(f"  [kuru] {url}")  # noqa: T201
                        continue
                    try:
                        scraper._process_url(
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
                print(  # noqa: T201
                    f"  yeni={result.campaigns_new} güncellenen={result.campaigns_updated} "
                    f"hata={result.errors_count}"
                )
                toplam_yeni += result.campaigns_new
                toplam_guncel += result.campaigns_updated
            finally:
                scraper.close()

    print(f"\nToplam: yeni={toplam_yeni} güncellenen={toplam_guncel}")  # noqa: T201
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="JS liste + httpx kampanya tamamlaması")
    parser.add_argument("--banka", default=None, help="Tek banka kodu")
    parser.add_argument("--kuru", action="store_true", help="Yazma; yalnızca URL yazdır")
    parser.add_argument(
        "--rapor",
        action="store_true",
        help="docs/js_listing_kapsama.md kapsama raporu üret",
    )
    args = parser.parse_args(argv)
    return _calistir(bank_filter=args.banka, dry_run=args.kuru, rapor=args.rapor)


if __name__ == "__main__":
    sys.exit(main())
