"""Partner / niş finansman ürünlerine aile oranını miras bırakır.

Örnek:
  Kuveyt «Hepsiburada Alışveriş Finansmanı» ← «Alışveriş Finansmanı» oranı
  Albaraka «Diş Sağlığı» ← aynı bankadaki ihtiyaç ailesi oranı (etiketli)

⚠️ Bağlayıcı değildir (`is_binding=False`). Kaynak ürüne atıf `evidence_text`.
Oran uydurulmaz — donörde oran yoksa atlanır.

Çalıştırma:
    python dev.py finansman-aile-orani
    python dev.py finansman-aile-orani --kuru
    python dev.py finansman-aile-orani --banka kuveyt_turk
    python -m scripts.inherit_family_rates --kuru
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from decimal import Decimal
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.normalization.text import ascii_fold_tr, lower_tr
from app.core.vocab import FINANSMAN_TIPLERI, rate_confidence
from app.db.models.bank import Bank
from app.db.models.product import Product, ProductRate
from app.db.session import SessionLocal
from app.logging_config import configure_logging, get_logger

logger = get_logger(__name__)

# (banka_kodu, çocuk adında geçen parçalar, donör adında geçen parçalar)
_KURALLAR: Final[tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...]] = (
    (
        "kuveyt_turk",
        ("hepsiburada", "lc waikiki", "taksitlio", "trendyol", "teknosa"),
        ("alisveris finansmani",),
    ),
    (
        "albaraka",
        (
            "dis sagligi",
            "genel saglik",
            "seyahat",
            "esya dekorasyon",
            "dogal enerji",
            "dogalgaz",
            "bina tamamlama",
            "sms",
            "bayide",
            "tadilat",
            "jet finansman",
        ),
        ("pratik finansman kart", "egitim finansmani"),
    ),
    (
        "ziraat_katilim",
        (
            "alisveris finansmani",
            "aninda finansman",
            "dayanikli tuketim",
            "dogalgaz",
        ),
        ("ihtiyac finansmani",),
    ),
)


def _fold(ad: str) -> str:
    return ascii_fold_tr(lower_tr(ad or ""))


def _eslesir(ad: str, anahtarlar: tuple[str, ...]) -> bool:
    f = _fold(ad)
    return any(a in f for a in anahtarlar)


def _donor_bul(urunler: list[Product], anahtarlar: tuple[str, ...]) -> Product | None:
    adaylar: list[tuple[int, Product]] = []
    for u in urunler:
        if not u.rates:
            continue
        f = _fold(u.name or "")
        if any(
            p in f
            for p in (
                "hepsiburada",
                "waikiki",
                "taksitlio",
                "trendyol",
                "teknosa",
                "dis sagligi",
                "genel saglik",
            )
        ):
            continue
        for i, a in enumerate(anahtarlar):
            if a in f:
                adaylar.append((100 - i * 10 + len(u.rates), u))
                break
    if not adaylar:
        return None
    adaylar.sort(key=lambda x: -x[0])
    return adaylar[0][1]


def _oran_sec(donor: Product) -> ProductRate | None:
    sirali = sorted(
        donor.rates,
        key=lambda r: (
            1 if r.is_binding else 0,
            float(r.confidence or 0),
            1 if r.profit_rate_pct is not None else 0,
        ),
        reverse=True,
    )
    for r in sirali:
        if r.profit_rate_pct is not None:
            return r
    return sirali[0] if sirali else None


def calistir(*, bank_code: str | None, dry_run: bool) -> dict:
    session = SessionLocal()
    ozet: dict = {
        "yazilan": 0,
        "guncellenen": 0,
        "zaten_var": 0,
        "atlanan": 0,
        "ornekler": [],
        "kuru": dry_run,
    }
    try:
        stmt = (
            select(Product)
            .options(selectinload(Product.rates), selectinload(Product.bank))
            .where(
                Product.product_type.in_(FINANSMAN_TIPLERI),
                Product.parent_product_id.is_(None),
                Product.is_active.is_(True),
            )
        )
        if bank_code:
            banka = session.scalar(select(Bank).where(Bank.code == bank_code))
            if banka is None:
                return {"hata": f"banka yok: {bank_code}"}
            stmt = stmt.where(Product.bank_id == banka.id)

        tum = list(session.scalars(stmt))
        by_bank: dict[int, list[Product]] = {}
        for u in tum:
            by_bank.setdefault(u.bank_id, []).append(u)

        for _bank_id, urunler in by_bank.items():
            kod = urunler[0].bank.code if urunler[0].bank else ""
            for kural_bank, cocuk_key, donor_key in _KURALLAR:
                if kural_bank != kod:
                    continue
                donor = _donor_bul(urunler, donor_key)
                if donor is None:
                    ozet["atlanan"] += 1
                    continue
                oran = _oran_sec(donor)
                if oran is None:
                    continue
                anahtar = f"inherit|{donor.id}|{oran.id}"
                for cocuk in urunler:
                    if cocuk.id == donor.id:
                        continue
                    if not _eslesir(cocuk.name or "", cocuk_key):
                        continue

                    ornek = {
                        "cocuk": cocuk.name,
                        "donor": donor.name,
                        "oran": str(oran.profit_rate_pct),
                        "bank": kod,
                    }
                    mevcut = next(
                        (r for r in cocuk.rates if r.band_key == anahtar),
                        None,
                    )
                    if mevcut is None and cocuk.rates:
                        # Başka kaynaktan oran var — miras gerekmez
                        ozet["zaten_var"] += 1
                        ornek["durum"] = "zaten_var"
                        ozet["ornekler"].append(ornek)
                        continue

                    if dry_run:
                        ozet["yazilan"] += 1
                        ornek["durum"] = "yazilacak" if mevcut is None else "guncellenecek"
                        ozet["ornekler"].append(ornek)
                        continue

                    kanit = (
                        f"Aile oranı mirası ← {donor.name} (kaynak: {oran.rate_source})"
                    )[:500]
                    if mevcut is not None:
                        mevcut.profit_rate_pct = oran.profit_rate_pct
                        mevcut.evidence_text = kanit
                        ozet["guncellenen"] += 1
                        ornek["durum"] = "guncellendi"
                        ozet["ornekler"].append(ornek)
                        continue

                    session.add(
                        ProductRate(
                            product_id=cocuk.id,
                            profit_rate_pct=oran.profit_rate_pct,
                            term_months=oran.term_months or cocuk.term_months_max,
                            amount_min=oran.amount_min or cocuk.amount_min,
                            amount_max=oran.amount_max or cocuk.amount_max,
                            rate_source="text",
                            confidence=min(rate_confidence("text"), Decimal("0.55")),
                            is_binding=False,
                            evidence_text=kanit,
                            effective_date=date.today(),
                            band_key=anahtar,
                            rate_type=oran.rate_type or "financing_rate",
                        )
                    )
                    notice = f"Oran «{donor.name}» ailesinden miras; bağlayıcı değil."
                    if cocuk.non_binding_notice:
                        if notice not in cocuk.non_binding_notice:
                            cocuk.non_binding_notice = (
                                f"{cocuk.non_binding_notice} {notice}"
                            )[:500]
                    else:
                        cocuk.non_binding_notice = notice
                    ozet["yazilan"] += 1
                    ornek["durum"] = "yazildi"
                    ozet["ornekler"].append(ornek)

        if not dry_run:
            session.commit()
    finally:
        session.close()
    return ozet


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--banka", default=None)
    parser.add_argument("--kuru", action="store_true")
    args = parser.parse_args(argv)
    ozet = calistir(bank_code=args.banka, dry_run=args.kuru)
    print(json.dumps(ozet, ensure_ascii=True, indent=2, default=str))
    return 0 if "hata" not in ozet else 1


if __name__ == "__main__":
    raise SystemExit(main())
