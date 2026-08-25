"""Tutarsız hesaplayıcı oranlarını raporlar; istenirse karantinaya alır.

`calculator_probe_service.probe_orani_guvenilir_mi` kapısı YENİ yazımları
engelliyor. Bu betik, kapı eklenmeden ÖNCE yazılmış satırları aynı kuralla
değerlendirir.

⚠️ VARSAYILAN KİP RAPORDUR. `--uygula` verilmedikçe hiçbir satır değişmez.
⚠️ Satır SİLİNMEZ: `product_rates.profit_rate_pct` NULL'a çekilir ve
   `evidence_text` içine red nedeni eklenir. Ham `calculator_probes` satırı
   olduğu gibi kalır — kanıt zinciri korunur.

Kullanım:
    python scripts/karantina_probe_oranlari.py           # rapor
    python scripts/karantina_probe_oranlari.py --uygula   # NULL'a çek
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db.models.bank import Bank  # noqa: E402
from app.db.models.calculator import CalculatorProbe  # noqa: E402
from app.db.models.product import Product, ProductRate  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.services.calculator_probe_service import probe_orani_guvenilir_mi  # noqa: E402

PROBE_KAYNAKLARI = ("calculator_playwright", "calculator_api")


def _probe_bul(
    session: Session, urun_id: int, tutar: Decimal | None, vade: int | None
) -> CalculatorProbe | None:
    """Oranı üreten probe satırını tutar+vade ile eşler."""
    if tutar is None or vade is None:
        return None
    return session.scalar(
        select(CalculatorProbe).where(
            CalculatorProbe.product_id == urun_id,
            CalculatorProbe.probe_amount == tutar,
            CalculatorProbe.probe_term_months == vade,
        )
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--uygula", action="store_true", help="Satırları NULL'a çeker")
    args = ap.parse_args()

    with SessionLocal() as session:
        satirlar = session.execute(
            select(ProductRate, Product, Bank)
            .join(Product, Product.id == ProductRate.product_id)
            .join(Bank, Bank.id == Product.bank_id)
            .where(
                ProductRate.rate_source.in_(PROBE_KAYNAKLARI),
                ProductRate.profit_rate_pct.is_not(None),
            )
            .order_by(Bank.code, Product.name)
        ).all()

        toplam = len(satirlar)
        red: list[tuple[str, str, ProductRate, str]] = []

        for oran_satiri, urun, banka in satirlar:
            probe = _probe_bul(
                session, urun.id, oran_satiri.amount_min, oran_satiri.term_months
            )
            tamam, neden = probe_orani_guvenilir_mi(
                profit_rate_pct=oran_satiri.profit_rate_pct,
                term_months=oran_satiri.term_months or 0,
                monthly_installment=probe.monthly_installment if probe else None,
                total_repayment=probe.total_repayment if probe else None,
            )
            if not tamam:
                red.append((banka.code, urun.name, oran_satiri, neden or "?"))

        print(f"Probe kaynaklı oran satırı : {toplam}")
        print(f"Kapıdan geçmeyen           : {len(red)}")
        print(f"Kalacak                    : {toplam - len(red)}")
        print()
        if red:
            print(f"{'banka':16} {'ürün':30} {'vade':>5} {'oran':>10}  neden")
            print("-" * 100)
            for kod, ad, satir, neden in red:
                print(
                    f"{kod:16} {str(ad)[:30]:30} {str(satir.term_months):>5} "
                    f"{str(satir.profit_rate_pct):>10}  {neden}"
                )

        if not args.uygula:
            print()
            print("RAPOR KİPİ — hiçbir satır değişmedi. Uygulamak için: --uygula")
            return 0

        for _kod, _ad, satir, neden in red:
            satir.profit_rate_pct = None
            mevcut = satir.evidence_text or ""
            satir.evidence_text = f"{mevcut}\n[karantina] {neden}".strip()
        session.commit()
        print()
        print(f"{len(red)} satırın oranı NULL'a çekildi; evidence_text'e neden yazıldı.")
        print("Ham calculator_probes satırları değişmedi.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
