"""Alt kampanya desteği: `campaigns.parent_campaign_id` self-FK.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-17

Bir sayfada birden çok kampanya, ya da bir kampanya içinde birden çok alt
paket olabiliyor (ör. Dünya Katılım'ın finansman sayfasında üç ayrı ürün).
Şu ana kadar bir sayfa = bir kampanya varsayılıyordu.

Alt kampanya JSON blok olarak değil AYRI SATIR olarak tutulur: kanıt ve arama
katmanının tamamı (`campaign_extractions`, `gold_annotations`,
`campaign_categories`, `campaign_metrics`, `entity_cards`) tamsayı bir
`campaign_id` bekliyor; JSON blok bunların hiçbirine bağlanamaz.

Kolonlar:
    parent_campaign_id  kök kampanyaya self-FK (CASCADE)
    block_index         sayfadaki sıra
    slug_source         alt slug'ın nereden geldiği: href | anchor | index

⚠️ SQLite'ta kendine referans veren FK için `recreate="always"` verilir.
`downgrade` güvenlidir: alt kampanyalar kök düzlemine iner, `#blok` ekli
slug'lar kalır.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.db.base import NAMING_CONVENTION

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Alt kampanya kolonlarını ekler."""
    with op.batch_alter_table(
        "campaigns",
        naming_convention=NAMING_CONVENTION,
        recreate="always",
    ) as batch:
        batch.add_column(sa.Column("parent_campaign_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("block_index", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("slug_source", sa.Text(), nullable=True))
        batch.create_foreign_key(
            "fk_campaigns_parent_campaign_id_campaigns",
            "campaigns",
            ["parent_campaign_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_check_constraint(
            "slug_source_valid",
            "slug_source IS NULL OR slug_source IN ('href', 'anchor', 'index')",
        )
        batch.create_check_constraint(
            "parent_not_self",
            "parent_campaign_id IS NULL OR parent_campaign_id <> id",
        )

    op.create_index("ix_campaigns_parent_campaign_id", "campaigns", ["parent_campaign_id"])


def downgrade() -> None:
    """Alt kampanya kolonlarını kaldırır; çocuklar kök düzlemine iner."""
    op.drop_index("ix_campaigns_parent_campaign_id", table_name="campaigns")

    with op.batch_alter_table(
        "campaigns",
        naming_convention=NAMING_CONVENTION,
        recreate="always",
    ) as batch:
        batch.drop_constraint("ck_campaigns_parent_not_self", type_="check")
        batch.drop_constraint("ck_campaigns_slug_source_valid", type_="check")
        batch.drop_constraint("fk_campaigns_parent_campaign_id_campaigns", type_="foreignkey")
        batch.drop_column("slug_source")
        batch.drop_column("block_index")
        batch.drop_column("parent_campaign_id")
