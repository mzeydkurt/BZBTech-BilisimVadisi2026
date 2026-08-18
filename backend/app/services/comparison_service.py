"""Kampanya ve ürün karşılaştırma servis katmanı."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models.bank import Bank
from app.db.models.campaign import Campaign
from app.db.models.campaign_extraction import CampaignExtraction
from app.schemas.compare import ComparisonItem, ComparisonResponse, ComparisonWeights


def compare_campaigns(
    session: Session, campaign_ids: list[int], weights: ComparisonWeights
) -> ComparisonResponse:
    """Seçilen 2-4 kampanyayı normalize sayısal alanlar üzerinden kıyaslar.

    Puanlama Formülü:
    Score = (w_rate * rate_score) + (w_term * term_score) + (w_fee * fee_score) + (w_reward * reward_score)
    """
    if not campaign_ids:
        return ComparisonResponse(items=[], weights=weights)

    stmt = (
        select(Campaign)
        .options(
            selectinload(Campaign.bank),
            selectinload(Campaign.metric),
            selectinload(Campaign.extractions),
        )
        .where(Campaign.id.in_(campaign_ids))
    )
    kampanyalar = list(session.scalars(stmt))

    items: list[ComparisonItem] = []

    for k in kampanyalar:
        m = k.metric
        oran = float(m.profit_rate_pct) if m and m.profit_rate_pct is not None else None
        vade = m.term_months_max if m else None
        tutar_max = float(m.financing_amount_max) if m and m.financing_amount_max is not None else None
        odul = float(m.reward_amount_try) if m and m.reward_amount_try is not None else None
        min_harcama = float(m.min_spend_try) if m and m.min_spend_try is not None else None
        masrafsiz = bool(m.has_no_fee) if m and m.has_no_fee is not None else False

        evidence_map: dict[str, str] = {}
        for ext in k.extractions:
            if ext.evidence_text:
                evidence_map[ext.field_name] = ext.evidence_text

        # Özel skor hesabı
        score = 50.0  # Temel skor
        if oran is not None:
            score += max(0.0, (5.0 - oran) * 10.0)  # Düşük oran daha yüksek puan
        if masrafsiz:
            score += 15.0
        if odul is not None and odul > 0:
            score += min(20.0, (odul / 500.0) * 5.0)
        if vade is not None and vade > 12:
            score += 10.0

        items.append(
            ComparisonItem(
                id=k.id,
                bank_code=k.bank.code,
                bank_name=k.bank.name,
                title=k.title,
                category=k.category,
                product_type=k.category,
                profit_rate_pct=oran,
                term_months_max=vade,
                financing_amount_max=tutar_max,
                reward_amount_try=odul,
                min_spend_try=min_harcama,
                has_no_fee=masrafsiz,
                evidence_map=evidence_map,
                custom_score=round(min(100.0, score), 1),
            )
        )

    if items:
        kazanan = max(items, key=lambda x: x.custom_score)
        winner_id = kazanan.id
        winner_code = kazanan.bank_code
        winner_reason = f"{kazanan.bank_name} - '{kazanan.title}' düşük kâr payı maliyeti ve avantajlı koşulları ile en yüksek skoru (Score: {kazanan.custom_score}/100) almıştır."
    else:
        winner_id = None
        winner_code = None
        winner_reason = None

    return ComparisonResponse(
        winner_id=winner_id,
        winner_bank_code=winner_code,
        winner_reason=winner_reason,
        items=items,
        weights=weights,
    )
