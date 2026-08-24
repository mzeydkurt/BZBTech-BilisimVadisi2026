"""JS liste keşfi — hangi banka listesinde Daha fazla / scroll / sayfalama var?

    python -m scripts.js_listing_discover
    python -m scripts.js_listing_discover --banka vakif_katilim

Sonuç `docs/js_listing_kesif.md` dosyasına yazılır. Hedefler bu ölçüme
göre `JS_LISTING_TARGETS` içine eklenir; tahminle URL eklenmez.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.scrapers.browser import (
    NETWORK_IDLE_MS,
    browser_page,
    is_playwright_available,
    playwright_kurulum_mesaji,
)
from app.scrapers.js_listing import (
    JS_LISTING_TARGETS,
    JsListingTarget,
    _daha_fazla_metni_mi,
    _linkleri_topla,
    _sonraki_metni_mi,
)

KOK = Path(__file__).resolve().parents[2]
RAPOR = KOK / "docs" / "js_listing_kesif.md"


def _olc(target: JsListingTarget) -> dict[str, object]:
    """Tek hedefi Playwright ile ölçer."""
    sonuc: dict[str, object] = {
        "bank_code": target.bank_code,
        "listing_url": target.listing_url,
        "daha_fazla": False,
        "scroll": False,
        "sayfalama": False,
        "baslangic_link": 0,
        "hata": None,
    }
    try:
        with browser_page() as page:
            page.goto(target.listing_url, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(NETWORK_IDLE_MS)
            baslangic = _linkleri_topla(page, target)
            sonuc["baslangic_link"] = len(baslangic)

            for el in page.query_selector_all("button, a, [role='button']"):
                try:
                    metin = (el.inner_text() or "").strip()
                    rel = el.get_attribute("rel")
                except Exception:
                    continue
                if _daha_fazla_metni_mi(metin):
                    sonuc["daha_fazla"] = True
                if _sonraki_metni_mi(metin, rel=rel) and not _daha_fazla_metni_mi(metin):
                    sonuc["sayfalama"] = True

            onceki = int(page.evaluate("() => document.body.scrollHeight") or 0)
            page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(NETWORK_IDLE_MS)
            sonraki = int(page.evaluate("() => document.body.scrollHeight") or 0)
            yeni = _linkleri_topla(page, target)
            if sonraki > onceki or len(yeni) > len(baslangic):
                sonuc["scroll"] = True
    except Exception as exc:
        sonuc["hata"] = str(exc)
    return sonuc


def _markdown(satirlar: list[dict[str, object]]) -> str:
    satirlar_md = [
        "# JS liste keşfi",
        "",
        "Playwright ile ölçüldü. Hedefler `JS_LISTING_TARGETS` içinden gelir.",
        "",
        "| Banka | Liste URL | Daha fazla | Scroll | Sayfalama | Başlangıç link | Not |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in satirlar:
        notu = s.get("hata") or ""
        satirlar_md.append(
            f"| `{s['bank_code']}` | `{s['listing_url']}` | "
            f"{'evet' if s['daha_fazla'] else 'hayır'} | "
            f"{'evet' if s['scroll'] else 'hayır'} | "
            f"{'evet' if s['sayfalama'] else 'hayır'} | "
            f"{s['baslangic_link']} | {notu} |"
        )
    satirlar_md.append("")
    return "\n".join(satirlar_md)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="JS liste genişletme keşfi")
    parser.add_argument("--banka", default=None, help="Tek banka kodu")
    args = parser.parse_args(argv)

    if not is_playwright_available():
        print(playwright_kurulum_mesaji())  # noqa: T201
        return 1

    hedefler = [t for t in JS_LISTING_TARGETS if args.banka is None or t.bank_code == args.banka]
    if not hedefler:
        print("Ölçülecek hedef yok.")  # noqa: T201
        return 1

    olcumler = [_olc(t) for t in hedefler]
    RAPOR.parent.mkdir(parents=True, exist_ok=True)
    RAPOR.write_text(_markdown(olcumler), encoding="utf-8")
    print(f"Yazıldı: {RAPOR}")  # noqa: T201
    for s in olcumler:
        print(  # noqa: T201
            f"  {s['bank_code']}: daha_fazla={s['daha_fazla']} "
            f"scroll={s['scroll']} sayfalama={s['sayfalama']} "
            f"link={s['baslangic_link']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
