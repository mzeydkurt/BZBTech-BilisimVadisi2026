"""Ürün ve oran tekilliği: `products.external_key`, `product_rates.band_key`.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-17

`products` tablosunda hiç unique kısıt yoktu; ürün kazıması her çalıştırmada
aynı ürünü yeniden ekleyerek tabloyu sessizce şişirirdi. Mevcut kolonlarla
bileşik anahtar kurulamıyor çünkü `variant_key` NULL olabiliyor ve SQLite'ta
`NULL != NULL`.

    products.external_key      = "{url-slug}#{variant_key|variant_label|base}"
    product_rates.band_key     = bant boyutlarının NULL-güvenli kodlaması

`product_rates` tekilliğine `effective_date` de girer: banka oranı güncelleyip
yeni gün çekildiğinde yeni satır açılır, eski satır korunur. Böylece oran zaman
serisi kendiliğinden oluşur.

Tablolar boş (0 satır) olduğu için NOT NULL doğrudan verilebilir.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.db.base import NAMING_CONVENTION

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Tekillik anahtarlarını ekler."""
    with op.batch_alter_table("products", naming_convention=NAMING_CONVENTION) as batch:
        batch.add_column(sa.Column("external_key", sa.Text(), nullable=True))

    # Tablo boş; var olan satır için doldurma gerekmez ama güvenli olsun diye
    # kimliksiz satır kalırsa id'den türetilir.
    op.execute("UPDATE products SET external_key = 'urun-' || id WHERE external_key IS NULL")

    with op.batch_alter_table("products", naming_convention=NAMING_CONVENTION) as batch:
        batch.alter_column("external_key", existing_type=sa.Text(), nullable=False)
        batch.create_unique_constraint(
            "uq_products_bank_id_external_key", ["bank_id", "external_key"]
        )

    with op.batch_alter_table("product_rates", naming_convention=NAMING_CONVENTION) as batch:
        batch.add_column(sa.Column("band_key", sa.Text(), nullable=True))

    op.execute("UPDATE product_rates SET band_key = 'oran-' || id WHERE band_key IS NULL")

    with op.batch_alter_table("product_rates", naming_convention=NAMING_CONVENTION) as batch:
        batch.alter_column("band_key", existing_type=sa.Text(), nullable=False)
        batch.create_unique_constraint(
            "uq_product_rates_product_id_rate_source_effective_date_band_key",
            ["product_id", "rate_source", "effective_date", "band_key"],
        )


def downgrade() -> None:
    """Tekillik anahtarlarını kaldırır."""
    with op.batch_alter_table("product_rates", naming_convention=NAMING_CONVENTION) as batch:
        batch.drop_constraint(
            "uq_product_rates_product_id_rate_source_effective_date_band_key", type_="unique"
        )
        batch.drop_column("band_key")

    with op.batch_alter_table("products", naming_convention=NAMING_CONVENTION) as batch:
        batch.drop_constraint("uq_products_bank_id_external_key", type_="unique")
        batch.drop_column("external_key")
