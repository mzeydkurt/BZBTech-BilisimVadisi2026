"""En güncel ürün oranının seçimi — eski kazıma tarihleri gizlenir."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.bank import Bank
from app.db.models.product import Product, ProductRate
from app.services.product_rate_current import select_current_rates


def test_select_current_rates_ayni_bantta_en_yeni_tarih() -> None:
    eski = SimpleNamespace(
        id=1,
        product_id=10,
        rate_source="html_table",
        band_key="t12|…",
        effective_date=date(2026, 8, 19),
        term_months=12,
    )
    yeni = SimpleNamespace(
        id=2,
        product_id=10,
        rate_source="html_table",
        band_key="t12|…",
        effective_date=date(2026, 8, 23),
        term_months=12,
    )
    diger = SimpleNamespace(
        id=3,
        product_id=10,
        rate_source="html_table",
        band_key="t48|…",
        effective_date=date(2026, 8, 23),
        term_months=48,
    )
    sonuc = select_current_rates([eski, yeni, diger])
    assert {o.id for o in sonuc} == {2, 3}


def test_urun_detayi_eski_tarihli_oranlari_gizler(
    api_client: httpx.Client, seeded_session: Session
) -> None:
    banka = seeded_session.scalar(select(Bank).where(Bank.code == "albaraka"))
    assert banka is not None
    urun = Product(
        bank_id=banka.id,
        external_key="albaraka:togg-test",
        name="Togg Finansmanı Test",
        product_type="tasit_finansmani",
    )
    seeded_session.add(urun)
    seeded_session.flush()

    band = "12|||||"
    for gun, oran_id_hint in ((19, Decimal("0.00")), (21, Decimal("0.00")), (23, Decimal("0.00"))):
        seeded_session.add(
            ProductRate(
                product_id=urun.id,
                band_key=band,
                rate_type="financing_rate",
                profit_rate_pct=oran_id_hint,
                term_months=12,
                currency="TRY",
                rate_source="html_table",
                effective_date=date(2026, 8, gun),
                evidence_text=f"T10F V2 | 12 | 1.000.000 | 0,00% ({gun})",
            )
        )
    seeded_session.add(
        ProductRate(
            product_id=urun.id,
            band_key="48|||||",
            rate_type="financing_rate",
            profit_rate_pct=Decimal("2.99"),
            term_months=48,
            currency="TRY",
            rate_source="html_table",
            effective_date=date(2026, 8, 19),
            evidence_text="eski 48",
        )
    )
    seeded_session.add(
        ProductRate(
            product_id=urun.id,
            band_key="48|||||",
            rate_type="financing_rate",
            profit_rate_pct=Decimal("2.99"),
            term_months=48,
            currency="TRY",
            rate_source="html_table",
            effective_date=date(2026, 8, 23),
            evidence_text="yeni 48",
        )
    )
    seeded_session.flush()

    veri = api_client.get(f"/api/v1/products/{urun.id}").json()
    assert len(veri["rates"]) == 2
    tarihler = {r["effective_date"] for r in veri["rates"]}
    assert tarihler == {"2026-08-23"}
    assert all("eski" not in (r.get("evidence_text") or "") for r in veri["rates"])
    assert {r["term_months"] for r in veri["rates"]} == {12, 48}


def test_strip_product_id_from_answer() -> None:
    from app.retrieval.relevance import strip_citation_markers

    assert strip_citation_markers("Albaraka Togg ürün id: 12 uygun.") == "Albaraka Togg uygun."
    assert "45" not in strip_citation_markers("Kampanya #45 taksitli.")
