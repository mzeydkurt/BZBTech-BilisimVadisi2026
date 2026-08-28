"""Oranı/limiti boş finansman ürünlerini metinden zenginleştirir veya ayıklar.

1) description / clean_text → tutar-vade limiti (`limits_source=text`)
2) Açık kâr oranı ifadesi → `product_rates` (`rate_source=text`, is_binding=False)
3) Karşılaştırılabilir finansman OLMAYAN satırlar → `is_active=False`
   (kampanyaya taşınmaz; ürün≠kampanya. Servis sayfaları finanstan çıkar.)

Çalıştırma:
    python -m scripts.enrich_no_data_financing
    python -m scripts.enrich_no_data_financing --kuru
    python -m scripts.enrich_no_data_financing --banka albaraka
    python dev.py finansman-metin-zenginlestir
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from decimal import Decimal
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.normalization.text import lower_tr
from app.core.vocab import FINANSMAN_TIPLERI, rate_confidence
from app.db.models.bank import Bank
from app.db.models.product import Product, ProductRate
from app.db.session import SessionLocal
from app.logging_config import configure_logging, get_logger
from app.processing.limits import extract_limits_from_text, extract_profit_rate_from_text
from app.processing.product_description import extract_product_description

logger = get_logger(__name__)

# Finansman karşılaştırma listesinde DURMAMALI — ürün satırı kalır ama pasif.
# Kampanya tablosuna taşınmaz (kalıcı ürün sayfası / servis; kampanya değil).
_PASIF_ADLAR: Final[tuple[str, ...]] = (
    "toki işlemleri",
    "tokı işlemleri",
    "hazır limit",
    "hazir limit",
)

# Menü kabuğu — açıklama sayılmaz, temizlenir.
_COPUR_ACIKLAMA = re.compile(
    r"tümü\s+tümü\s+tarım|tumu\s+tumu\s+tarim|ticari\s+ve\s+kurumsal\s+finansmanlar",
    re.IGNORECASE,
)


def _pasif_mi(ad: str) -> bool:
    dusuk = lower_tr(ad)
    return any(p in dusuk for p in _PASIF_ADLAR)


def _metin_topla(urun: Product) -> str:
    """Yalnızca güvenilir tanıtım metni — ham clean_text dökümü yok.

    Ham arşiv metni menü/ücret tablosu kirletir (ör. 1–125.000 TL / 1–60 ay).
    """
    parcalar: list[str] = []
    if urun.description and not _COPUR_ACIKLAMA.search(urun.description):
        parcalar.append(urun.description)
    belge = urun.source_document
    if belge and belge.clean_text:
        aciklama = extract_product_description(belge.clean_text, urun.name)
        if aciklama and not _COPUR_ACIKLAMA.search(aciklama):
            parcalar.append(aciklama)
    return "\n".join(parcalar)


def _limit_guvenilir_mi(lim) -> bool:
    """Şüpheli çıkarımı reddet (ücret/BDDK tablosu artığı)."""
    if lim.amount_min is not None and lim.amount_min < 500:
        return False
    # "1-60 ay" / "1-125.000 TL" genelde tablo başlığı.
    if lim.term_months_min == 1 and (lim.term_months_max or 0) >= 24:
        return False
    if lim.amount_min == 1:
        return False
    return True


def calistir(*, bank_code: str | None, dry_run: bool) -> dict:
    session = SessionLocal()
    ozet = {
        "limit_yazilan": 0,
        "oran_yazilan": 0,
        "pasif": 0,
        "aciklama_temiz": 0,
        "atlanan": 0,
        "ornekler": [],
    }
    try:
        stmt = (
            select(Product)
            .options(
                selectinload(Product.rates),
                selectinload(Product.limits),
                selectinload(Product.source_document),
                selectinload(Product.bank),
            )
            .where(
                Product.product_type.in_(FINANSMAN_TIPLERI),
                Product.parent_product_id.is_(None),
            )
            .order_by(Product.id)
        )
        if bank_code:
            banka = session.scalar(select(Bank).where(Bank.code == bank_code))
            if banka is None:
                return {"hata": f"banka yok: {bank_code}"}
            stmt = stmt.where(Product.bank_id == banka.id)

        for urun in session.scalars(stmt):
            banka_adi = urun.bank.name if urun.bank else "?"

            # ── Pasif: servis / hazır limit ──
            if urun.is_active and _pasif_mi(urun.name or ""):
                ozet["pasif"] += 1
                ozet["ornekler"].append(
                    {"islem": "pasif", "bank": banka_adi, "urun": urun.name}
                )
                if not dry_run:
                    urun.is_active = False
                    urun.non_binding_notice = (
                        (urun.non_binding_notice or "")
                        + " [metin-zenginleştirme: finansman karşılaştırma dışı servis/limit]"
                    ).strip()
                continue

            # Çöp açıklama temizliği
            if urun.description and _COPUR_ACIKLAMA.search(urun.description):
                belge = urun.source_document
                yeni = None
                if belge and belge.clean_text:
                    yeni = extract_product_description(belge.clean_text, urun.name)
                ozet["aciklama_temiz"] += 1
                if not dry_run:
                    urun.description = yeni

            # Zaten oran + limit varsa atla
            if urun.rates and (
                urun.amount_min is not None
                or urun.amount_max is not None
                or urun.term_months_min is not None
                or urun.term_months_max is not None
                or urun.limits
            ):
                ozet["atlanan"] += 1
                continue

            metin = _metin_topla(urun)
            if not metin.strip():
                ozet["atlanan"] += 1
                continue

            # Limit
            if not (
                urun.amount_min
                or urun.amount_max
                or urun.term_months_min
                or urun.term_months_max
                or urun.limits
            ):
                lim = extract_limits_from_text(metin)
                if not lim.is_empty and _limit_guvenilir_mi(lim):
                    ozet["limit_yazilan"] += 1
                    ozet["ornekler"].append(
                        {
                            "islem": "limit",
                            "bank": banka_adi,
                            "urun": urun.name,
                            "amount": f"{lim.amount_min}-{lim.amount_max}",
                            "term": f"{lim.term_months_min}-{lim.term_months_max}",
                        }
                    )
                    if not dry_run:
                        if lim.amount_min is not None and urun.amount_min is None:
                            urun.amount_min = lim.amount_min
                        if lim.amount_max is not None and urun.amount_max is None:
                            urun.amount_max = lim.amount_max
                        if lim.term_months_min is not None and urun.term_months_min is None:
                            urun.term_months_min = lim.term_months_min
                        if lim.term_months_max is not None and urun.term_months_max is None:
                            urun.term_months_max = lim.term_months_max
                        if lim.allowed_terms and not urun.allowed_terms:
                            urun.allowed_terms = lim.allowed_terms
                        if lim.ltv_max_pct is not None and urun.ltv_max_pct is None:
                            urun.ltv_max_pct = lim.ltv_max_pct
                        urun.limits_source = "text"
                        urun.limits_evidence = lim.evidence

            # Oran (yoksa)
            if not urun.rates:
                oran, kanit = extract_profit_rate_from_text(metin)
                from app.services.calculator_probe_service import probe_orani_guvenilir_mi

                guvenilir = False
                if oran is not None:
                    guvenilir, _ = probe_orani_guvenilir_mi(
                        profit_rate_pct=oran,
                        term_months=urun.term_months_max or 0,
                        monthly_installment=None,
                        total_repayment=None,
                        product_name=urun.name,
                        description=urun.description,
                        evidence_text=kanit,
                        product_type=urun.product_type,
                    )
                if oran is not None and guvenilir:
                    ozet["oran_yazilan"] += 1
                    ozet["ornekler"].append(
                        {
                            "islem": "oran",
                            "bank": banka_adi,
                            "urun": urun.name,
                            "oran": str(oran),
                            "kanit": (kanit or "")[:80],
                        }
                    )
                    if not dry_run:
                        anahtar = (
                            f"text|t{urun.term_months_max or '-'}|"
                            f"a{urun.amount_min or '-'}-{urun.amount_max or '-'}"
                        )
                        mevcut = session.scalar(
                            select(ProductRate).where(
                                ProductRate.product_id == urun.id,
                                ProductRate.rate_source == "text",
                                ProductRate.band_key == anahtar,
                                ProductRate.effective_date == date.today(),
                            )
                        )
                        if mevcut is None:
                            session.add(
                                ProductRate(
                                    product_id=urun.id,
                                    profit_rate_pct=oran,
                                    term_months=urun.term_months_max,
                                    amount_min=urun.amount_min,
                                    amount_max=urun.amount_max,
                                    rate_source="text",
                                    confidence=rate_confidence("text"),
                                    is_binding=False,
                                    evidence_text=(kanit or "")[:500],
                                    effective_date=date.today(),
                                    band_key=anahtar,
                                    rate_type="financing_rate",
                                )
                            )
                        else:
                            mevcut.profit_rate_pct = oran
                            mevcut.evidence_text = (kanit or "")[:500]

        if not dry_run:
            session.commit()
    finally:
        session.close()
    ozet["kuru"] = dry_run
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
