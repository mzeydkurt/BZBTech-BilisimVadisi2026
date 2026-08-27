"""httpx API adapter'larından probe okuması üretip DB'ye yazar."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.db.models import Bank, CalculatorInventory
from app.db.session import SessionLocal
from app.logging_config import get_logger
from app.scrapers.calculator_probes.api_adapters import FinancingCalculation
from app.scrapers.calculator_probes.api_adapters import albaraka as albaraka_api
from app.scrapers.calculator_probes.api_adapters import dunya as dunya_api
from app.scrapers.calculator_probes.api_adapters import emlak as emlak_api
from app.scrapers.calculator_probes.api_adapters import hayat as hayat_api
from app.scrapers.calculator_probes.api_adapters import kuveyt as kuveyt_api
from app.scrapers.calculator_probes.api_adapters import turkiye_finans as tf_api
from app.scrapers.calculator_probes.api_adapters import vakif as vakif_api
from app.scrapers.calculator_probes.common import ProbeReading, oran_gecerli
from app.scrapers.calculator_probes.matcher import urun_bul
from app.services.calculator_probe_service import upsert_probe_and_rate

logger = get_logger(__name__)

_ADAPTERS = {
    "albaraka": albaraka_api.probe_all,
    "dunya_katilim": dunya_api.probe_all,
    "vakif_katilim": vakif_api.probe_all,
    "hayat_finans": hayat_api.probe_all,
    "emlak_katilim": emlak_api.probe_all,
    "kuveyt_turk": kuveyt_api.probe_all,
    "turkiye_finans": tf_api.probe_all,
}


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(x) for x in obj]
    return obj


def _yaz(session: Any, okuma: ProbeReading, *, dry_run: bool) -> bool:
    urun = urun_bul(session, okuma)
    if urun is None:
        logger.info("api_probe_urun_eslesmedi", bank=okuma.bank_code, variant=okuma.variant_label)
        return False
    if dry_run:
        return True
    banka = session.scalar(select(Bank).where(Bank.code == okuma.bank_code))
    env = None
    if banka:
        env = session.scalar(
            select(CalculatorInventory).where(
                CalculatorInventory.bank_id == banka.id,
                CalculatorInventory.page_url == okuma.source_url,
            )
        )
    upsert_probe_and_rate(
        session,
        product=urun,
        inventory=env,
        amount=okuma.amount,
        term_months=okuma.term_months,
        method="api",
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
            "method": "httpx_api",
        },
        response_raw=json.dumps(_json_safe(okuma.raw_meta), ensure_ascii=False)[:8000]
        if okuma.raw_meta
        else None,
    )
    return True


def run_api_probes(
    *,
    bank_code: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Doğrulanmış API adapter'ları çalıştırır."""
    bankalar = [bank_code] if bank_code else list(_ADAPTERS)
    tum: list[FinancingCalculation] = []
    yazilan = 0
    eslesmeyen = 0
    hatalar: list[str] = []

    session = SessionLocal()
    try:
        for kod in bankalar:
            fn = _ADAPTERS.get(kod)
            if fn is None:
                hatalar.append(f"{kod}: httpx adapter yok (Playwright/probe kullanın)")
                continue
            try:
                sonuclar = fn()
            except Exception as exc:
                hatalar.append(f"{kod}: {exc}")
                logger.warning("api_probe_banka_hata", bank=kod, hata=str(exc))
                continue
            tum.extend(sonuclar)
            for calc in sonuclar:
                okuma = calc.to_probe_reading()
                if not oran_gecerli(okuma.profit_rate_pct) and okuma.monthly_installment is None:
                    continue
                if _yaz(session, okuma, dry_run=dry_run):
                    yazilan += 1
                    if not dry_run:
                        session.commit()
                else:
                    eslesmeyen += 1
    finally:
        session.close()

    return {
        "bankalar": bankalar,
        "okuma_sayisi": len(tum),
        "yazilan": yazilan,
        "eslesmeyen": eslesmeyen,
        "hatalar": hatalar,
        "kuru": dry_run,
        "ornekler": [
            {
                "bank": c.bank_code,
                "variant": c.product_label,
                "amount": str(c.amount),
                "term": c.term_months,
                "oran": str(c.profit_rate_pct) if c.profit_rate_pct else None,
                "taksit": str(c.monthly_installment) if c.monthly_installment else None,
                "toplam": str(c.total_payment) if c.total_payment else None,
                "endpoint": c.source_endpoint[:120],
            }
            for c in tum[:80]
        ],
    }
