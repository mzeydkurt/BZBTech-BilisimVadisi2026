"""Sohbet oturumu servisi — oluştur / yükle / sonlandır / tur kaydet."""

from __future__ import annotations

import json
import uuid
from dataclasses import replace

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.base import utc_now
from app.db.models.chat import ChatMessage, ChatSession
from app.retrieval.query import QueryPlan, parse_query
from app.schemas.chat import (
    ChatResponse,
    ChatSessionCreateResponse,
    ChatSessionDetail,
    ChatSessionMessageOut,
)


def _plan_to_json(plan: QueryPlan) -> str:
    """QueryPlan'ı JSON'a çevirir (merge için banka/oran/eksen korunur)."""
    veri = {
        "raw": plan.raw,
        "intent": plan.intent,
        "bank_codes": list(plan.bank_codes),
        "axis_filters": {k: list(v) for k, v in plan.axis_filters.items()},
        "rate_type": plan.rate_type,
        "rate_type_candidates": list(plan.rate_type_candidates),
        "source_domain": plan.source_domain,
        "signals": [
            {
                "kind": s.kind,
                "value": s.value,
                "label": s.label,
                "evidence": s.evidence,
            }
            for s in plan.signals
        ],
    }
    return json.dumps(veri, ensure_ascii=False)


def plan_from_json(raw: str | None) -> QueryPlan | None:
    """Kayıtlı plan_json → QueryPlan."""
    if not raw:
        return None
    try:
        veri = json.loads(raw)
    except json.JSONDecodeError:
        return None
    sorgu = veri.get("raw")
    if not isinstance(sorgu, str) or not sorgu.strip():
        return None
    plan = parse_query(sorgu)
    bank = tuple(veri.get("bank_codes") or plan.bank_codes)
    axis_raw = veri.get("axis_filters") or {}
    axis = {k: tuple(v) for k, v in axis_raw.items()} if axis_raw else plan.axis_filters
    rate = veri.get("rate_type") or plan.rate_type
    return replace(
        plan,
        bank_codes=bank,
        axis_filters=axis,
        rate_type=rate,
        rate_type_candidates=tuple(veri.get("rate_type_candidates") or plan.rate_type_candidates),
        source_domain=veri.get("source_domain") or plan.source_domain,
    )


def create_session(session: Session, *, title: str | None = None) -> ChatSession:
    kayit = ChatSession(session_key=str(uuid.uuid4()), title=title)
    session.add(kayit)
    session.flush()
    return kayit


def get_session_by_key(session: Session, session_key: str) -> ChatSession | None:
    return session.scalar(
        select(ChatSession)
        .where(ChatSession.session_key == session_key)
        .options(selectinload(ChatSession.messages))
    )


def end_session(session: Session, session_key: str) -> ChatSession | None:
    """ended_at yazar; satırları silmez."""
    kayit = get_session_by_key(session, session_key)
    if kayit is None:
        return None
    if kayit.ended_at is None:
        kayit.ended_at = utc_now()
        kayit.last_activity_at = utc_now()
        session.flush()
    return kayit


def resolve_or_create(
    session: Session,
    session_id: str | None,
    *,
    title_hint: str | None = None,
) -> ChatSession:
    if session_id:
        mevcut = get_session_by_key(session, session_id)
        if mevcut is not None and mevcut.ended_at is None:
            return mevcut
    baslik = (title_hint or "")[:80] or None
    return create_session(session, title=baslik)


def next_turn_index(oturum: ChatSession) -> int:
    if not oturum.messages:
        return 0
    return max(m.turn_index for m in oturum.messages) + 1


def previous_plan(oturum: ChatSession) -> QueryPlan | None:
    for msg in reversed(oturum.messages):
        if msg.role == "assistant" and msg.plan_json:
            return plan_from_json(msg.plan_json)
    return None


def record_turn(
    session: Session,
    oturum: ChatSession,
    *,
    turn_index: int,
    user_text: str,
    plan: QueryPlan,
    response: ChatResponse,
) -> None:
    now = utc_now()
    if oturum.title is None and user_text.strip():
        oturum.title = user_text.strip()[:80]
    oturum.last_activity_at = now

    session.add(
        ChatMessage(
            session_id=oturum.id,
            turn_index=turn_index,
            role="user",
            content=user_text,
            intent=plan.intent,
            source_domain=plan.source_domain,
            created_at=now,
        )
    )
    govde = response.model_dump(mode="json")
    session.add(
        ChatMessage(
            session_id=oturum.id,
            turn_index=turn_index,
            role="assistant",
            content=response.answer.text,
            intent=response.intent,
            source_domain=response.source_domain,
            answer_source=response.answer.source,
            plan_json=_plan_to_json(plan),
            response_json=json.dumps(govde, ensure_ascii=False),
            created_at=now,
        )
    )
    session.flush()


def session_detail(oturum: ChatSession) -> ChatSessionDetail:
    msgs: list[ChatSessionMessageOut] = []
    for m in oturum.messages:
        resp = None
        if m.response_json:
            try:
                resp = json.loads(m.response_json)
            except json.JSONDecodeError:
                resp = None
        msgs.append(
            ChatSessionMessageOut(
                turn_index=m.turn_index,
                role=m.role,
                content=m.content,
                response_json=resp,
                intent=m.intent,
                source_domain=m.source_domain,
                answer_source=m.answer_source,
                created_at=m.created_at.isoformat() if m.created_at else None,
            )
        )
    return ChatSessionDetail(
        session_id=oturum.session_key,
        session_key=oturum.session_key,
        title=oturum.title,
        ended_at=oturum.ended_at.isoformat() if oturum.ended_at else None,
        created_at=oturum.created_at.isoformat() if oturum.created_at else None,
        last_activity_at=(oturum.last_activity_at.isoformat() if oturum.last_activity_at else None),
        messages=msgs,
    )


def create_response(oturum: ChatSession) -> ChatSessionCreateResponse:
    return ChatSessionCreateResponse(
        session_id=oturum.session_key,
        title=oturum.title,
        created_at=oturum.created_at.isoformat() if oturum.created_at else None,
    )
