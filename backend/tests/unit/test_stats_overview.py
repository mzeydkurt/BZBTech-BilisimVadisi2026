"""Genel bakış istatistik alanları — jüri panosu için eklenen metrikler."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.bank import Bank
from app.db.models.campaign import Campaign
from app.db.models.campaign_category import CampaignCategory
from app.services.campaign_service import today_tr
from app.services.stats_service import get_stats


def _kampanya(
    session: Session,
    banka_kodu: str,
    slug: str,
    *,
    status: str = "active",
    end_date=None,
    title: str | None = None,
) -> Campaign:
    banka = session.scalar(select(Bank).where(Bank.code == banka_kodu))
    assert banka is not None
    kampanya = Campaign(
        bank_id=banka.id,
        external_slug=slug,
        title=title or slug,
        source_url=f"https://ornek.com.tr/{slug}",
        status=status,
        end_date=end_date,
    )
    session.add(kampanya)
    session.flush()
    return kampanya


def test_ending_soon_and_active_by_bank(seeded_session: Session) -> None:
    bugun = today_tr()
    _kampanya(
        seeded_session,
        "albaraka",
        "yakin-biten",
        status="active",
        end_date=bugun + timedelta(days=7),
    )
    _kampanya(
        seeded_session,
        "albaraka",
        "uzak-biten",
        status="active",
        end_date=bugun + timedelta(days=60),
    )
    _kampanya(seeded_session, "kuveyt_turk", "aktif-kt", status="active")

    stats = get_stats(seeded_session)

    assert stats.ending_soon_count >= 1
    albaraka = next(b for b in stats.active_by_bank if b.bank_code == "albaraka")
    assert albaraka.active >= 2
    assert albaraka.total >= albaraka.active


def test_ai_coverage_and_audience_distribution(seeded_session: Session) -> None:
    kampanya = _kampanya(seeded_session, "albaraka", "etiketli")
    seeded_session.add(
        CampaignCategory(
            campaign_id=kampanya.id,
            axis="audience",
            value="bireysel",
            confidence=Decimal("1.000"),
            source="keyword",
        )
    )
    seeded_session.flush()

    stats = get_stats(seeded_session)

    assert 0.0 <= stats.ai_coverage_pct <= 100.0
    assert any(a.value == "bireysel" for a in stats.audience_distribution)


def test_green_campaigns_count(seeded_session: Session) -> None:
    _kampanya(
        seeded_session,
        "albaraka",
        "yesil-sarj",
        title="Elektrikli Araç Şarj İstasyonlarında Bankkart Lira",
    )

    stats = get_stats(seeded_session)

    assert stats.green_campaigns_count >= 1
