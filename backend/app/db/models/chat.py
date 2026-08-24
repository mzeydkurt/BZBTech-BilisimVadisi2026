"""Sohbet oturumu ve mesaj geçmişi — kanıt zinciri için soft-end.

DELETE /chat/sessions/{key} satır silmez; `ended_at` yazar. Geçmiş yüklenince
kartlar `response_json` üzerinden geri gelir.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UtcDateTime, utc_now


class ChatSession(Base):
    """Tek bir sohbet oturumu (`session_key` = API'deki session_id)."""

    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utc_now)
    last_activity_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utc_now)
    ended_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)

    messages: Mapped[list[ChatMessage]] = relationship(
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        # id: aynı turda önce user (önce yazılır), sonra assistant.
        order_by="ChatMessage.turn_index, ChatMessage.id",
    )


class ChatMessage(Base):
    """Oturumdaki tek bir tur (user veya assistant)."""

    __tablename__ = "chat_messages"
    __table_args__ = (
        UniqueConstraint("session_id", "turn_index", "role", name="uq_chat_messages_turn_role"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_domain: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utc_now)

    session: Mapped[ChatSession] = relationship("ChatSession", back_populates="messages")
