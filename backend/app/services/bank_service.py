"""Banka iş mantığı."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.db.models import Bank, Campaign


def list_banks(session: Session) -> list[tuple[Bank, int]]:
    """Tüm bankaları kampanya sayılarıyla birlikte döndürür.

    ⚠️ Kampanyası olmayan bankalar (Adil Katılım) listeden
    ÇIKARILMAZ; 0 ile döner. Şartname 5.1 BDDK listesindeki kuruluşların
    tümünün veri setinde bulunmasını gerektirir ve "veri yok" bilgisi de
    başlı başına bir bulgudur.

    Args:
        session: Veritabanı oturumu.

    Returns:
        (banka, kampanya_sayısı) ikililerinin listesi.
    """
    rows = session.execute(
        select(Bank, func.count(Campaign.id))
        .select_from(Bank)
        .outerjoin(
            Campaign,
            (Campaign.bank_id == Bank.id) & (Campaign.parent_campaign_id.is_(None)),
        )
        .group_by(Bank.id)
        .order_by(Bank.name.asc())
    ).all()
    return [(bank, count) for bank, count in rows]


def get_bank(session: Session, code: str) -> tuple[Bank, int]:
    """Tek bir bankayı kampanya sayısıyla döndürür.

    Args:
        session: Veritabanı oturumu.
        code: Banka kodu.

    Returns:
        (banka, kampanya_sayısı) ikilisi.

    Raises:
        NotFoundError: Banka bulunamazsa.
    """
    row = session.execute(
        select(Bank, func.count(Campaign.id))
        .select_from(Bank)
        .outerjoin(
            Campaign,
            (Campaign.bank_id == Bank.id) & (Campaign.parent_campaign_id.is_(None)),
        )
        .where(Bank.code == code)
        .group_by(Bank.id)
    ).first()

    if row is None:
        raise NotFoundError(f"Banka bulunamadı: {code}")

    bank, count = row
    return bank, count
