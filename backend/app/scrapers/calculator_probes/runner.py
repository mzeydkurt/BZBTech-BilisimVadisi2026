"""Hedef hesaplayıcı URL'lerini sorgular ve DB'ye yazar."""

from __future__ import annotations

import json
from dataclasses import asdict
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import Bank, CalculatorInventory, Product
from app.db.session import SessionLocal
from app.logging_config import get_logger
from app.scrapers.browser import browser_page, is_playwright_available, playwright_kurulum_mesaji
from app.scrapers.calculator_probes.common import ProbeReading, oran_gecerli
from app.scrapers.calculator_probes.matcher import urun_bul
from app.scrapers.calculator_probes.strategies import probe_target
from app.scrapers.calculator_probes.targets import PROBE_TARGETS, ProbeTarget
from app.services.calculator_probe_service import upsert_probe_and_rate

logger = get_logger(__name__)


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(x) for x in obj]
    return obj


def _envanter(session: Session, bank_id: int, url: str) -> CalculatorInventory | None:
    return session.scalar(
        select(CalculatorInventory).where(
            CalculatorInventory.bank_id == bank_id,
            CalculatorInventory.page_url == url,
        )
    )


def _oran_gecerli(oran: Decimal | None) -> bool:
    return oran_gecerli(oran)


def _yaz(
    session: Session,
    okuma: ProbeReading,
    *,
    dry_run: bool,
) -> tuple[bool, int | None]:
    urun = urun_bul(session, okuma)
    if urun is None:
        logger.info(
            "probe_urun_eslesmedi",
            bank=okuma.bank_code,
            variant=okuma.variant_label,
        )
        return False, None
    if dry_run:
        return True, urun.id
    banka = session.scalar(select(Bank).where(Bank.code == okuma.bank_code))
    env = _envanter(session, banka.id, okuma.source_url) if banka else None
    upsert_probe_and_rate(
        session,
        product=urun,
        inventory=env,
        amount=okuma.amount,
        term_months=okuma.term_months,
        method="playwright",
        profit_rate_pct=okuma.profit_rate_pct,
        monthly_installment=okuma.monthly_installment,
        total_repayment=okuma.total_repayment,
        allocation_fee=okuma.allocation_fee,
        annual_cost_pct=okuma.annual_cost_pct,
        endpoint_url=okuma.source_url,
        probe_variant=okuma.variant_label,
        request_payload={
            "variant": okuma.variant_label,
            "amount": str(okuma.amount),
            "term_months": okuma.term_months,
            "notice": (okuma.notice_text or "")[:500],
        },
        response_raw=json.dumps(_json_safe(okuma.raw_meta), ensure_ascii=False)[:8000]
        if okuma.raw_meta
        else (okuma.notice_text or "")[:8000],
    )
    if okuma.notice_text and not urun.non_binding_notice:
        urun.non_binding_notice = okuma.notice_text[:500]
    return True, urun.id


def run_probe_targets(
    *,
    bank_code: str | None = None,
    dry_run: bool = False,
    url_filter: str | None = None,
) -> dict[str, Any]:
    """Tüm (veya filtrelenmiş) hedef URL'leri Playwright ile sorgular."""
    if not is_playwright_available():
        raise RuntimeError(playwright_kurulum_mesaji())

    hedefler = list(PROBE_TARGETS)
    if bank_code:
        hedefler = [h for h in hedefler if h.bank_code == bank_code]
    if url_filter:
        hedefler = [h for h in hedefler if url_filter in h.url]

    tum_okumalar: list[ProbeReading] = []
    yazilan = 0
    eslesmeyen = 0
    hatalar: list[str] = []

    session = SessionLocal()
    try:
        with browser_page() as page:
            for hedef in hedefler:
                logger.info("probe_hedef", label=hedef.label, url=hedef.url)
                try:
                    okumalar = probe_target(page, hedef)
                except Exception as exc:
                    msg = f"{hedef.label}: {exc}"
                    logger.warning("probe_hedef_hata", hata=msg)
                    hatalar.append(msg)
                    continue
                tum_okumalar.extend(okumalar)
                for okuma in okumalar:
                    if not _oran_gecerli(okuma.profit_rate_pct) and okuma.monthly_installment is None:
                        logger.info(
                            "probe_bos",
                            variant=okuma.variant_label,
                            bank=okuma.bank_code,
                            oran=str(okuma.profit_rate_pct),
                        )
                        continue
                    yazildi, _pid = _yaz(session, okuma, dry_run=dry_run)
                    if yazildi:
                        yazilan += 1
                        if not dry_run:
                            session.commit()
                    else:
                        eslesmeyen += 1
    finally:
        session.close()

    return {
        "hedef_sayisi": len(hedefler),
        "okuma_sayisi": len(tum_okumalar),
        "yazilan": yazilan,
        "eslesmeyen": eslesmeyen,
        "hatalar": hatalar,
        "kuru": dry_run,
        "ornekler": [
            {
                "bank": o.bank_code,
                "variant": o.variant_label,
                "amount": str(o.amount),
                "term": o.term_months,
                "oran": str(o.profit_rate_pct) if o.profit_rate_pct else None,
                "taksit": str(o.monthly_installment) if o.monthly_installment else None,
            }
            for o in tum_okumalar[:30]
        ],
    }
