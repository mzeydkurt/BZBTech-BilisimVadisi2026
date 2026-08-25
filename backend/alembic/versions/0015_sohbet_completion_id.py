"""Sohbet turlarına `completion_id` ekler.

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-25

Çok turlu bağlamın hangi cevaba bağlandığını AÇIK hâle getirir. Önceki
davranış "son turu devral"dı; kullanıcı bir cevabı yeniden ürettiğinde veya
geçmişten eski bir tura döndüğünde yanlış bağlam taşınıyordu.

`completion_id` yalnızca assistant satırlarında doludur (user satırında NULL);
kısmi tekil dizin bunu zorlar.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_messages", sa.Column("completion_id", sa.Text(), nullable=True))
    # Kısmi dizin: user satırlarındaki NULL'lar tekillik kısıtına girmez.
    op.create_index(
        "ix_chat_messages_completion_id",
        "chat_messages",
        ["completion_id"],
        unique=True,
        sqlite_where=sa.text("completion_id IS NOT NULL"),
        postgresql_where=sa.text("completion_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_chat_messages_completion_id", table_name="chat_messages")
    op.drop_column("chat_messages", "completion_id")
