"""Sohbet oturumu servisi — oluştur / yükle / sonlandır / tur kaydet."""

from __future__ import annotations

import json
import uuid
from dataclasses import replace

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db.base import utc_now
from app.db.models.chat import ChatMessage, ChatSession
from app.retrieval.query import QueryPlan, parse_query
from app.schemas.chat import (
    ChatResponse,
    ChatSessionCreateResponse,
    ChatSessionDetail,
    ChatSessionMessageOut,
    ChatSessionSummary,
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


def previous_plan(
    oturum: ChatSession,
    parent_completion_id: str | None = None,
) -> tuple[QueryPlan | None, str | None]:
    """Bağlamın devralınacağı turu bulur; (plan, o turun completion_id) döner.

    `parent_completion_id` verilirse bağlam O turdan alınır. Kullanıcı sohbet
    geçmişinden eski bir tura dönüp soru sorduğunda "son turu devral" varsayımı
    yanlış bağlam taşıyordu.

    ⚠️ Tanınmayan kimlik SESSİZCE son tura düşmez: bağlam devri hiç yapılmaz.
    Yanlış turdan devralmak, hiç devralmamaktan daha kötü bir yanıt üretir.
    """
    if parent_completion_id:
        for msg in oturum.messages:
            if msg.completion_id == parent_completion_id:
                if not msg.plan_json:
                    return None, msg.completion_id
                return plan_from_json(msg.plan_json), msg.completion_id
        return None, None

    for msg in reversed(oturum.messages):
        if msg.role == "assistant" and msg.plan_json:
            return plan_from_json(msg.plan_json), msg.completion_id
    return None, None


def previous_focus(
    oturum: ChatSession,
    parent_completion_id: str | None = None,
) -> tuple[str | None, int | None]:
    """Önceki cevabın İŞARET ETTİĞİ bankayı döndürür (varsa).

    "Peki onun koşulları neler?" sorusundaki "onun", önceki SORUNUN süzgecine
    değil, önceki CEVABIN adını verdiği kuruma işaret eder. Ölçüldü: "taşıt
    finansmanında en uzun vade hangi bankada" → "Vakıf Katılım" cevabı
    alındıktan sonra takip sorusu tüm bankalarda arıyor, alakasız yanıt
    dönüyordu.

    Ayrıca önceki cevabın işaret ettiği TEK kampanyanın kimliğini döndürür.
    Ölçüldü (100 soruluk gerçek havuz, S3.3): "Bu kampanyanın bitiş tarihi ne
    zaman?" sorusunda bağlam devri OLUYOR ama sonuç boş dönüyordu — devir
    yalnızca bankayı taşıyordu, kampanyayı değil. "Bu kampanya" ifadesinin
    yanıtı tek bir kayıttır.

    Returns:
        (banka_kodu, kampanya_id). Yalnızca TEK bir kurum/kampanya açıkça öne
        çıktığında dolu döner; belirsizse None (yanlış kayda bağlamak, hiç
        bağlamamaktan kötüdür).
    """
    hedef: ChatMessage | None = None
    if parent_completion_id:
        for msg in oturum.messages:
            if msg.completion_id == parent_completion_id:
                hedef = msg
                break
    else:
        for msg in reversed(oturum.messages):
            if msg.role == "assistant" and msg.response_json:
                hedef = msg
                break
    if hedef is None or not hedef.response_json:
        return None, None

    try:
        govde = json.loads(hedef.response_json)
    except json.JSONDecodeError:
        return None, None

    sonuclar = govde.get("results") or []
    toplama = govde.get("aggregate") or {}
    kazanan = toplama.get("winner_campaign_id")

    # 1) Toplama sorusunun kazananı — en güçlü işaret.
    if kazanan is not None:
        for r in sonuclar:
            if r.get("campaign_id") == kazanan and r.get("bank_code"):
                return str(r["bank_code"]), int(kazanan)

    # 2) Tek sonuç varsa o — kampanya odağı da buradan gelir.
    if len(sonuclar) == 1:
        tek = sonuclar[0]
        kod = str(tek["bank_code"]) if tek.get("bank_code") else None
        kid = int(tek["campaign_id"]) if tek.get("campaign_id") is not None else None
        return kod, kid

    # 3) Tüm sonuçlar aynı bankadansa banka bellidir; kampanya DEĞİLDİR.
    kodlar = {r.get("bank_code") for r in sonuclar if r.get("bank_code")}
    if len(kodlar) == 1:
        return str(next(iter(kodlar))), None

    # 4) Birden çok sonuç varsa en üstteki `top_matches` kampanyası odak
    #    sayılmaz: kullanıcı hangisini kastettiğini söylememiştir.
    return None, None


def record_turn(
    session: Session,
    oturum: ChatSession,
    *,
    turn_index: int,
    user_text: str,
    plan: QueryPlan,
    response: ChatResponse,
    completion_id: str,
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
            completion_id=completion_id,
            plan_json=_plan_to_json(plan),
            response_json=json.dumps(govde, ensure_ascii=False),
            created_at=now,
        )
    )
    session.flush()


def session_detail(oturum: ChatSession) -> ChatSessionDetail:
    msgs: list[ChatSessionMessageOut] = []
    # Savunma: relationship sırası bozulursa bile user → assistant.
    sirali = sorted(
        oturum.messages,
        key=lambda m: (m.turn_index, 0 if m.role == "user" else 1, m.id),
    )
    for m in sirali:
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
                completion_id=m.completion_id,
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


def list_sessions(
    session: Session, *, limit: int = 50, include_empty: bool = False
) -> tuple[list[ChatSessionSummary], int]:
    """Sohbet geçmişini en son etkinliğe göre listeler.

    ⚠️ BOŞ OTURUMLAR VARSAYILAN OLARAK GİZLENİR. `POST /chat/sessions` her
    sayfa açılışında bir oturum açıyor; kullanıcı hiç soru sormadan çıkarsa
    geçmiş, tek satırı bile olmayan kayıtlarla dolar ve gerçek sohbetler
    aralarında kaybolur. Gizlenen kayıt SİLİNMEZ — `include_empty` ile görünür.

    ⚠️ MESAJ İÇERİĞİ ÇEKİLMEZ, YALNIZCA SAYI VE İLK SORU. Yüzlerce oturumun
    tüm mesajlarını taşımak yanıtı megabaytlara çıkarır.

    Args:
        session: Veritabanı oturumu.
        limit: Döndürülecek en fazla kayıt.
        include_empty: Hiç mesajı olmayan oturumlar da dönsün.

    Returns:
        `(satırlar, toplam)` — `toplam`, süzgeçten geçen tüm oturum sayısı.
    """
    mesaj_sayisi = (
        select(
            ChatMessage.session_id.label("session_id"),
            func.count(ChatMessage.id).label("adet"),
            func.min(ChatMessage.turn_index).label("ilk_tur"),
        )
        .group_by(ChatMessage.session_id)
        .subquery()
    )

    stmt = (
        select(ChatSession, mesaj_sayisi.c.adet)
        .outerjoin(mesaj_sayisi, mesaj_sayisi.c.session_id == ChatSession.id)
        .order_by(ChatSession.last_activity_at.desc())
    )
    if not include_empty:
        stmt = stmt.where(mesaj_sayisi.c.adet.is_not(None))

    satirlar = session.execute(stmt).all()
    toplam = len(satirlar)

    ozetler: list[ChatSessionSummary] = []
    for oturum, adet in satirlar[:limit]:
        ilk_soru = next(
            (
                mesaj.content
                for mesaj in sorted(oturum.messages, key=lambda m: (m.turn_index, m.role))
                if mesaj.role == "user"
            ),
            None,
        )
        ozetler.append(
            ChatSessionSummary(
                session_key=oturum.session_key,
                # Başlık yoksa ilk sorudan türetilir; "Adsız oturum" göstermek
                # kullanıcının hangi sohbet olduğunu anlamasını engeller.
                title=oturum.title or (ilk_soru[:60] if ilk_soru else None),
                created_at=oturum.created_at,
                last_activity_at=oturum.last_activity_at,
                ended_at=oturum.ended_at,
                # Bir tur = kullanıcı + asistan; mesaj sayısının yarısı.
                turn_count=int((adet or 0) // 2) or (1 if adet else 0),
                first_query=ilk_soru,
            )
        )
    return ozetler, toplam
