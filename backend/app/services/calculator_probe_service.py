"""Hesaplayıcı örnek tutar seçimi ve probe → product_rates yazımı.

⚠️ Hesaplayıcı çıktısı bağlayıcı DEĞİLDİR (`is_binding=False`).
⚠️ Statik tabloda oran varken probe yazılmaz (hiyerarşi: html_table > probe).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.vocab import FINANSMAN_TIPLERI, rate_confidence
from app.db.base import utc_now
from app.db.models.calculator import CalculatorInventory, CalculatorProbe
from app.db.models.product import Product, ProductRate
from app.processing.limits import derive_rate_from_payment_plan
from app.scrapers.products import band_key
from app.scrapers.models import RawProductRate
from app.services.bddk_limits_service import family_for_product_type, max_term_for_ihtiyac_amount

# Ürün ailesine göre örnek tutar × vade çiftleri (BDDK bantlarıyla hizalı).
_PROBE_SAMPLES: Final[dict[str, tuple[tuple[Decimal, int], ...]]] = {
    "ihtiyac": (
        (Decimal("10000"), 36),
        (Decimal("200000"), 24),
        (Decimal("1000000"), 12),
    ),
    "konut": ((Decimal("1000000"), 120),),
    "tasit": (
        (Decimal("400000"), 48),
        (Decimal("800000"), 36),
        (Decimal("1200000"), 24),
    ),
}

_DEFAULT_SAMPLES: Final[tuple[tuple[Decimal, int], ...]] = ((Decimal("1000000"), 36),)


@dataclass(frozen=True)
class ProbeSample:
    """Tek bir hesaplayıcı sorgu noktası."""

    amount: Decimal
    term_months: int


def probe_samples_for_product(product_type: str | None) -> list[ProbeSample]:
    """Ürün türüne / BDDK ailesine göre örnek tutar-vade listesi."""
    aile = family_for_product_type(product_type)
    ciftler = _PROBE_SAMPLES.get(aile or "", _DEFAULT_SAMPLES)
    return [ProbeSample(amount=a, term_months=v) for a, v in ciftler]


def products_needing_probe(session: Session, *, bank_code: str | None = None) -> list[Product]:
    """Statik finansman oranı olmayan finansman ürünlerini döndürür."""
    from sqlalchemy.orm import selectinload

    stmt = (
        select(Product)
        .options(selectinload(Product.rates))
        .where(
            Product.product_type.in_(FINANSMAN_TIPLERI),
            Product.parent_product_id.is_(None),
        )
        .order_by(Product.id)
    )
    if bank_code:
        from app.db.models.bank import Bank

        banka = session.scalar(select(Bank).where(Bank.code == bank_code))
        if banka is None:
            return []
        stmt = stmt.where(Product.bank_id == banka.id)

    adaylar: list[Product] = []
    for urun in session.scalars(stmt):
        baglayici = [
            o
            for o in urun.rates
            if o.rate_type == "financing_rate"
            and o.profit_rate_pct is not None
            and o.rate_source in ("html_table", "pdf_table", "seed_manual")
            and o.is_binding
        ]
        if not baglayici:
            adaylar.append(urun)
    return adaylar


def upsert_probe_and_rate(
    session: Session,
    *,
    product: Product,
    inventory: CalculatorInventory | None,
    amount: Decimal,
    term_months: int,
    method: str,
    profit_rate_pct: Decimal | None = None,
    monthly_installment: Decimal | None = None,
    total_repayment: Decimal | None = None,
    allocation_fee: Decimal | None = None,
    annual_cost_pct: Decimal | None = None,
    endpoint_url: str | None = None,
    request_payload: dict | None = None,
    response_raw: str | None = None,
    probe_variant: str | None = None,
) -> CalculatorProbe:
    """Probe kaydı yazar; oran çıkarılabiliyorsa product_rates'e non-binding satır ekler."""
    oran = profit_rate_pct
    if oran is None and monthly_installment is not None and term_months > 0:
        toplam = total_repayment or (monthly_installment * Decimal(term_months))
        oran = derive_rate_from_payment_plan(amount, toplam, term_months)

    mevcut = session.scalar(
        select(CalculatorProbe).where(
            CalculatorProbe.product_id == product.id,
            CalculatorProbe.probe_amount == amount,
            CalculatorProbe.probe_term_months == term_months,
            CalculatorProbe.probe_variant == probe_variant,
        )
    )
    if mevcut is None:
        mevcut = CalculatorProbe(
            product_id=product.id,
            bank_id=product.bank_id,
            inventory_id=inventory.id if inventory else None,
            probe_amount=amount,
            probe_term_months=term_months,
            probe_variant=probe_variant,
            method=method,
            probed_at=utc_now(),
            is_binding=False,
        )
        session.add(mevcut)

    mevcut.profit_rate_pct = oran
    mevcut.monthly_installment = monthly_installment
    mevcut.total_repayment = total_repayment
    mevcut.total_profit_share = (
        (total_repayment - amount) if total_repayment is not None else None
    )
    mevcut.allocation_fee = allocation_fee
    mevcut.annual_cost_pct = annual_cost_pct
    mevcut.endpoint_url = endpoint_url
    mevcut.request_payload = request_payload
    mevcut.response_raw = response_raw
    mevcut.probed_at = utc_now()
    mevcut.is_binding = False
    session.flush()

    if oran is not None:
        rate_source = (
            "calculator_api" if method == "api" else "calculator_playwright"
        )
        raw = RawProductRate(
            rate_source=rate_source,
            rate_type="financing_rate",
            term_months=term_months,
            profit_rate_pct=oran,
            allocation_fee_pct=(
                (allocation_fee / amount * Decimal(100)).quantize(Decimal("0.0001"))
                if allocation_fee is not None and amount > 0
                else None
            ),
            annual_cost_pct=annual_cost_pct,
            amount_min=amount,
            amount_max=amount,
            evidence_text=(
                f"Hesaplayıcı sorgusu: {amount} TL / {term_months} ay"
                + (f" → taksit {monthly_installment} TL" if monthly_installment else "")
                + f" → aylık kâr payı %{oran} (bağlayıcı değil)"
            ),
        )
        anahtar = band_key(raw)
        oran_satiri = session.scalar(
            select(ProductRate).where(
                ProductRate.product_id == product.id,
                ProductRate.rate_source == rate_source,
                ProductRate.effective_date.is_(None),
                ProductRate.band_key == anahtar,
            )
        )
        if oran_satiri is None:
            oran_satiri = ProductRate(
                product_id=product.id,
                band_key=anahtar,
                rate_source=rate_source,
                rate_type="financing_rate",
                confidence=rate_confidence(rate_source),
                is_binding=False,
            )
            session.add(oran_satiri)
        oran_satiri.term_months = term_months
        oran_satiri.profit_rate_pct = oran
        oran_satiri.allocation_fee_pct = raw.allocation_fee_pct
        oran_satiri.annual_cost_pct = annual_cost_pct
        oran_satiri.amount_min = amount
        oran_satiri.amount_max = amount
        oran_satiri.evidence_text = raw.evidence_text
        oran_satiri.is_binding = False
        # Ürün bağlayıcı değil sayılır (hesaplayıcı tahmini içeriyor)
        product.is_binding = False
        if not product.non_binding_notice:
            product.non_binding_notice = (
                "Bazı oranlar bankanın hesaplama aracından alınmıştır; "
                "bilgilendirme amaçlıdır, bağlayıcı teklif değildir."
            )

    session.flush()
    return mevcut


def suggest_term_for_amount(product_type: str | None, amount: Decimal, fallback: int) -> int:
    """İhtiyaçta BDDK azami vade; diğerlerinde verilen yedek."""
    if family_for_product_type(product_type) == "ihtiyac":
        return max_term_for_ihtiyac_amount(amount)[0]
    return fallback
