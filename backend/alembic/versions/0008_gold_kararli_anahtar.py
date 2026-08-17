"""Gold set ve kartlar için kararlı anahtar.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-17

`gold_annotations` 880 satırlık ELLE ETİKETLEME işidir ve `campaign_id`
(autoincrement) ile bağlıdır. Kampanya verisi silinip yeniden kazındığında
id'ler değişir ve bu emek öksüz kalır. Kararlı anahtar
`(bank_code, external_slug)`'dır.

    gold_annotations.campaign_key     "{bank_code}:{external_slug}"  NOT NULL
    gold_annotations.reanchor_method  slug | url | baslik | manual
    gold_annotations.campaign_id      NULLABLE'a çevrilir
    entity_cards.entity_key           polimorfik kartlar için aynı amaç

`campaign_id` nullable oluyor ki yeniden bağlanamayan satır SİLİNMEK zorunda
kalmasın; kimlik `campaign_key`'de durur, `campaign_id` yalnızca hızlı JOIN
için tutulan türetilmiş bağdır.

⚠️ DOWNGRADE GÜVENLİ DEĞİLDİR. `campaign_id IS NULL` olan satırlar geri
dönüşte NOT NULL kısıtını çiğner ve göç bu satırları SİLER. Downgrade öncesi
`python dev.py disa-aktar` ZORUNLUDUR.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.db.base import NAMING_CONVENTION

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Kararlı anahtarları ekler ve `campaign_id`'yi nullable yapar."""
    with op.batch_alter_table("gold_annotations", naming_convention=NAMING_CONVENTION) as batch:
        batch.add_column(sa.Column("campaign_key", sa.Text(), nullable=True))
        batch.add_column(sa.Column("reanchor_method", sa.Text(), nullable=True))

    # Mevcut 880 satır doldurulur.
    op.execute(
        """
        UPDATE gold_annotations SET campaign_key = (
            SELECT b.code || ':' || c.external_slug
            FROM campaigns c JOIN banks b ON b.id = c.bank_id
            WHERE c.id = gold_annotations.campaign_id
        )
        WHERE campaign_key IS NULL
        """
    )
    # Kampanyası silinmiş satır kalırsa kimliksiz bırakılmaz.
    op.execute(
        "UPDATE gold_annotations SET campaign_key = 'bilinmeyen:' || campaign_id "
        "WHERE campaign_key IS NULL"
    )

    with op.batch_alter_table("gold_annotations", naming_convention=NAMING_CONVENTION) as batch:
        batch.alter_column("campaign_key", existing_type=sa.Text(), nullable=False)
        batch.alter_column("campaign_id", existing_type=sa.Integer(), nullable=True)
        batch.drop_constraint("uq_gold_annotations_campaign_id_field_name", type_="unique")
        batch.create_unique_constraint(
            "uq_gold_annotations_campaign_key_field_name",
            ["campaign_key", "field_name", "annotator"],
        )

    with op.batch_alter_table("entity_cards", naming_convention=NAMING_CONVENTION) as batch:
        batch.add_column(sa.Column("entity_key", sa.Text(), nullable=True))


def downgrade() -> None:
    """⚠️ `campaign_id IS NULL` satırları SİLER. Önce dışa aktarın."""
    op.execute("DELETE FROM gold_annotations WHERE campaign_id IS NULL")

    with op.batch_alter_table("entity_cards", naming_convention=NAMING_CONVENTION) as batch:
        batch.drop_column("entity_key")

    with op.batch_alter_table("gold_annotations", naming_convention=NAMING_CONVENTION) as batch:
        batch.drop_constraint("uq_gold_annotations_campaign_key_field_name", type_="unique")
        batch.create_unique_constraint(
            "uq_gold_annotations_campaign_id_field_name",
            ["campaign_id", "field_name", "annotator"],
        )
        batch.alter_column("campaign_id", existing_type=sa.Integer(), nullable=False)
        batch.drop_column("reanchor_method")
        batch.drop_column("campaign_key")
