"""Doğal dil arama, FTS5 sorgulama ve katılım bankacılığı terminoloji denetçisi."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models.bank import Bank
from app.db.models.campaign import Campaign
from app.db.models.glossary import GlossaryTerm
from app.schemas.chat import ChatRequest, ChatResponse, ChatResultItem


def process_chat_query(session: Session, req: ChatRequest) -> ChatResponse:
    """Kullanıcının doğal dil sorusunu işler, yasaklı kelimeleri denetler ve yanıt üretir."""
    q_clean = req.query.strip().casefold()

    # 1. Yasaklı Konvansiyonel Terim Denetimi
    forbidden_terms = list(
        session.scalars(
            select(GlossaryTerm).where(GlossaryTerm.is_forbidden_conventional.is_(True))
        )
    )

    warning_msg: str | None = None
    for term_obj in forbidden_terms:
        if term_obj.term.casefold() in q_clean:
            warning_msg = (
                f"Katılım bankacılığı ilkeleri gereği '{term_obj.term}' terimi yerine "
                f"'{term_obj.conventional_equivalent}' terimi kullanılmalıdır. "
                "Sonuçlar katılım finans esaslarına göre filtrelenmiştir."
            )
            break

    # 2. SQL / Metin Arama
    stmt = (
        select(Campaign)
        .options(selectinload(Campaign.bank), selectinload(Campaign.metric))
        .order_by(Campaign.id.desc())
    )

    if req.bank_code:
        banka = session.scalar(select(Bank).where(Bank.code == req.bank_code))
        if banka:
            stmt = stmt.where(Campaign.bank_id == banka.id)

    # Anahtar kelimelere göre süz
    raw_query = req.query.strip()
    words = [w for w in raw_query.split() if len(w) > 2]
    if words:
        filters = [
            Campaign.title.ilike(f"%{w}%")
            | Campaign.description.ilike(f"%{w}%")
            | Campaign.conditions_text.ilike(f"%{w}%")
            for w in words[:3]
        ]
        stmt = stmt.where(*filters)

    kampanyalar = list(session.scalars(stmt.limit(5)))

    results: list[ChatResultItem] = []
    for k in kampanyalar:
        m = k.metric
        oran = float(m.profit_rate_pct) if m and m.profit_rate_pct is not None else None
        results.append(
            ChatResultItem(
                campaign_id=k.id,
                bank_code=k.bank.code,
                bank_name=k.bank.name,
                title=k.title,
                summary=k.summary_ai or (k.description[:150] + "..." if k.description else None),
                evidence_text=k.conditions_text[:200] if k.conditions_text else None,
                source_url=k.source_url,
                profit_rate_pct=oran,
            )
        )

    if results:
        answer = (
            f"Sorgunuz için katılım bankalarından {len(results)} adet ilgili "
            "kampanya ve finansman seçeneği bulundu."
        )
    else:
        answer = (
            "Aradığınız kriterlere uygun sonuç bulunamadı. "
            "Lütfen farklı anahtar kelimelerle deneyiniz."
        )

    return ChatResponse(
        query=req.query,
        answer_text=answer,
        forbidden_terms_warning=warning_msg,
        results=results,
    )
