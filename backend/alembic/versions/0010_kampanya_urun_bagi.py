"""kampanya urun bagi

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-19

⚠️ Autogenerate çıktısı ELDEN GEÇİRİLDİ. SQLite CHECK kısıtlarını yansıtmadığı
için `--autogenerate` var olan kısıtları "yeni eklendi" sanıp `campaigns`,
`products` ve `campaign_extractions` tablolarını gereksiz yere yeniden
kuruyordu. Bu göç YALNIZCA yeni tabloyu oluşturur.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Kampanya ↔ ürün bağı tablosunu oluşturur."""
    op.create_table(
        "campaign_products",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("match_method", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "match_method IN ('title', 'slug', 'body')",
            name=op.f("ck_campaign_products_campaign_product_match_method_valid"),
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name=op.f("ck_campaign_products_campaign_product_confidence_range"),
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["campaigns.id"],
            name=op.f("fk_campaign_products_campaign_id_campaigns"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_campaign_products_product_id_products"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_campaign_products")),
        sa.UniqueConstraint("campaign_id", "product_id", name="uq_campaign_products_pair"),
    )
    with op.batch_alter_table("campaign_products", schema=None) as batch_op:
        batch_op.create_index("ix_campaign_products_campaign_id", ["campaign_id"], unique=False)
        batch_op.create_index("ix_campaign_products_product_id", ["product_id"], unique=False)


def downgrade() -> None:
    """Tabloyu düşürür.

    ⚠️ Bağlar KAYBOLUR ama yeniden üretilebilir: `dev.py urun-esle` kampanya
    metinlerinden hesaplar, elle girilmiş veri değildir.
    """
    with op.batch_alter_table("campaign_products", schema=None) as batch_op:
        batch_op.drop_index("ix_campaign_products_product_id")
        batch_op.drop_index("ix_campaign_products_campaign_id")
    op.drop_table("campaign_products")
