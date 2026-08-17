"""Gösterge paneli istatistikleri."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Bank, Campaign, ScrapeRun
from app.schemas.stats import BankCampaignCount, CategoryCount, StatsResponse
from app.services.campaign_service import ISTANBUL_TZ


def _count_by_status(session: Session, status: str) -> int:
    """Belirli durumdaki kampanya sayısını döndürür."""
    return (
        session.scalar(
            select(func.count())
            .select_from(Campaign)
            .where(Campaign.status == status, Campaign.parent_campaign_id.is_(None))
        )
        or 0
    )


def get_stats(session: Session) -> StatsResponse:
    """Genel bakış sayfası için tüm istatistikleri hesaplar.

    Args:
        session: Veritabanı oturumu.

    Returns:
        İstatistik yanıtı.
    """
    total_banks = session.scalar(select(func.count()).select_from(Bank)) or 0
    # ⚠️ Yalnızca kök kampanyalar sayılır; alt kampanyalar ayrı raporlanır.
    total_campaigns = (
        session.scalar(
            select(func.count()).select_from(Campaign).where(Campaign.parent_campaign_id.is_(None))
        )
        or 0
    )

    # Bankaya göre dağılım: kampanyası olmayan bankalar da 0 ile listelenir
    # (şartname 5.1). LEFT OUTER JOIN bu yüzden zorunludur.
    bank_rows = session.execute(
        select(Bank.code, Bank.name, func.count(Campaign.id))
        .select_from(Bank)
        .outerjoin(
            Campaign,
            (Campaign.bank_id == Bank.id) & (Campaign.parent_campaign_id.is_(None)),
        )
        .group_by(Bank.code, Bank.name)
        .order_by(func.count(Campaign.id).desc(), Bank.name.asc())
    ).all()

    campaigns_by_bank = [
        BankCampaignCount(bank_code=code, bank_name=name, count=count)
        for code, name, count in bank_rows
    ]
    banks_with_data = sum(1 for item in campaigns_by_bank if item.count > 0)

    category_rows = session.execute(
        select(Campaign.category, func.count(Campaign.id))
        .group_by(Campaign.category)
        .order_by(func.count(Campaign.id).desc())
    ).all()
    campaigns_by_category = [
        CategoryCount(category=category, count=count) for category, count in category_rows
    ]

    last_scrape = session.scalar(
        select(ScrapeRun.finished_at)
        .where(ScrapeRun.finished_at.is_not(None))
        .order_by(ScrapeRun.finished_at.desc())
        .limit(1)
    )
    last_scrape_at: datetime | None = (
        last_scrape.astimezone(ISTANBUL_TZ) if last_scrape is not None else None
    )

    return StatsResponse(
        total_banks=total_banks,
        banks_with_data=banks_with_data,
        total_campaigns=total_campaigns,
        active_campaigns=_count_by_status(session, "active"),
        upcoming_campaigns=_count_by_status(session, "upcoming"),
        expired_campaigns=_count_by_status(session, "expired"),
        unknown_status_campaigns=_count_by_status(session, "unknown"),
        campaigns_by_bank=campaigns_by_bank,
        campaigns_by_category=campaigns_by_category,
        last_scrape_at=last_scrape_at,
    )
