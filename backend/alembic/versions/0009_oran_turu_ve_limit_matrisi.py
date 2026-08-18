"""Oran türü ayrımı + `product_limits` matris tablosu (SPRINT 2.5).

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-18

⚠️ BU GÖÇÜN SEBEBİ SESSİZ BİR VERİ HATASI. "Kâr payı" katılım bankacılığında
ÜÇ ayrı büyüklüğü anlatıyor ve üçü de tek kolona (`profit_rate_pct`)
yazılıyordu:

    financing_rate        finansman maliyeti        %4,15
    participation_yield   katılma hesabı getirisi   %31,22
    profit_sharing_ratio  bölüşüm oranı             90/10

Aynı bankanın aynı ürününde ikisi birden olabilir ve ikisi de doğrudur.
Ayrım yapılmadan "en düşük kâr payı" sıralaması bir bankanın bölüşüm oranını
başka bankanın finansman maliyetiyle kıyaslar — hata FIRLAMAZ, yalnızca
sonuç yanlış çıkar.

Türkiye Finans'ta iki sayfanın adı tek harf farklı ve İKİSİ DE whitelist'te:
    Kar-Payi-Oranlari.aspx     → participation_yield
    Kar-Paylasim-Oranlari.aspx → profit_sharing_ratio

GERİYE DOLDURMA: mevcut 253 satırın tamamı finansman/oran tablolarından
geldi, hepsi `financing_rate` işaretlenir. Katılma hesabı oranları henüz
toplanmadı (SPRINT 2.5 KAPI F2A).

`product_limits`: "tutar bandı → finansman oranı → azami vade" matrisleri.
Oran YAYIMLAMAYAN bankalarda karşılaştırmayı mümkün kılan tek veri budur.
LTV hücreleri şu an `product_rates`'te `profit_rate_pct=NULL` ile duruyor;
taşınması ayrı adımda yapılır (bu göç yalnızca tabloyu açar).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.db.base import NAMING_CONVENTION

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Oran türü alanlarını, izleme alanlarını ve limit tablosunu ekler."""
    # ── product_rates ─────────────────────────────────────
    with op.batch_alter_table("product_rates", naming_convention=NAMING_CONVENTION) as batch:
        batch.add_column(sa.Column("rate_type", sa.Text(), nullable=True))
        batch.add_column(sa.Column("investor_share_pct", sa.Numeric(6, 3), nullable=True))
        batch.add_column(sa.Column("bank_share_pct", sa.Numeric(6, 3), nullable=True))
        batch.add_column(sa.Column("term_days_min", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("term_days_max", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("term_label", sa.Text(), nullable=True))
        batch.add_column(sa.Column("currency", sa.Text(), nullable=True))
        batch.add_column(sa.Column("account_tier", sa.Text(), nullable=True))
        batch.add_column(sa.Column("customer_type", sa.Text(), nullable=True))
        batch.add_column(sa.Column("is_gross", sa.Boolean(), nullable=True))
        batch.add_column(sa.Column("is_binding", sa.Boolean(), nullable=True))

    # ⚠️ Mevcut satırların tamamı finansman/oran tablolarından geldi.
    op.execute("UPDATE product_rates SET rate_type = 'financing_rate' WHERE rate_type IS NULL")
    op.execute("UPDATE product_rates SET currency = 'TRY' WHERE currency IS NULL")
    # Ödeme planından TÜRETİLEN oran bankanın taahhüdü değildir.
    op.execute(
        "UPDATE product_rates SET is_binding = "
        "CASE WHEN rate_source = 'payment_plan_derived' THEN 0 ELSE 1 END "
        "WHERE is_binding IS NULL"
    )

    with op.batch_alter_table("product_rates", naming_convention=NAMING_CONVENTION) as batch:
        batch.alter_column("rate_type", existing_type=sa.Text(), nullable=False)
        batch.alter_column("currency", existing_type=sa.Text(), nullable=False)
        batch.alter_column("is_binding", existing_type=sa.Boolean(), nullable=False)
        batch.create_check_constraint(
            "rate_type_valid",
            "rate_type IN ('financing_rate', 'participation_yield', 'profit_sharing_ratio')",
        )
        batch.create_check_constraint(
            "rate_currency_valid", "currency IN ('TRY', 'USD', 'EUR', 'XAU', 'XAG')"
        )
        batch.create_check_constraint(
            "account_tier_valid",
            "account_tier IS NULL OR account_tier IN "
            "('klasik', 'gumus', 'altin', 'platin', 'platin_plus')",
        )
        batch.create_check_constraint(
            "customer_type_valid",
            "customer_type IS NULL OR customer_type IN ('gercek_kisi', 'tuzel_kisi')",
        )
        batch.create_check_constraint(
            "investor_share_range_valid",
            "investor_share_pct IS NULL OR (investor_share_pct >= 0 "
            "AND investor_share_pct <= 100)",
        )
        batch.create_check_constraint(
            "term_days_range_valid",
            "term_days_min IS NULL OR term_days_max IS NULL OR term_days_min <= term_days_max",
        )

    # ── products: izleme alanları ─────────────────────────
    with op.batch_alter_table("products", naming_convention=NAMING_CONVENTION) as batch:
        batch.add_column(sa.Column("is_active", sa.Boolean(), nullable=True))
        batch.add_column(sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))

    op.execute("UPDATE products SET is_active = 1 WHERE is_active IS NULL")
    op.execute("UPDATE products SET first_seen_at = created_at WHERE first_seen_at IS NULL")
    op.execute("UPDATE products SET last_seen_at = updated_at WHERE last_seen_at IS NULL")

    with op.batch_alter_table("products", naming_convention=NAMING_CONVENTION) as batch:
        batch.alter_column("is_active", existing_type=sa.Boolean(), nullable=False)

    # ── product_limits ────────────────────────────────────
    op.create_table(
        "product_limits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("band_key", sa.Text(), nullable=False, server_default=""),
        sa.Column("asset_value_min", sa.Numeric(16, 2), nullable=True),
        sa.Column("asset_value_max", sa.Numeric(16, 2), nullable=True),
        sa.Column("financing_ratio_pct", sa.Numeric(6, 3), nullable=True),
        sa.Column("term_months_min", sa.Integer(), nullable=True),
        sa.Column("term_months_max", sa.Integer(), nullable=True),
        sa.Column("amount_max", sa.Numeric(16, 2), nullable=True),
        sa.Column("energy_class", sa.Text(), nullable=True),
        sa.Column("vehicle_age_min", sa.Integer(), nullable=True),
        sa.Column("vehicle_age_max", sa.Integer(), nullable=True),
        sa.Column("currency", sa.Text(), nullable=False, server_default="TRY"),
        sa.Column("source_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("evidence_text", sa.Text(), nullable=True),
        sa.Column("extraction_method", sa.Text(), nullable=False, server_default="html_table"),
        sa.Column("source_document_id", sa.Integer(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"], name="fk_product_limits_product_id_products",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"], ["source_documents.id"],
            name="fk_product_limits_source_document_id_source_documents", ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "extraction_method IN ('html_table', 'pdf_table', 'text')",
            name="ck_product_limits_limit_extraction_method_valid",
        ),
        sa.CheckConstraint(
            "currency IN ('TRY', 'USD', 'EUR', 'XAU', 'XAG')",
            name="ck_product_limits_limit_currency_valid",
        ),
        sa.CheckConstraint(
            "asset_value_min IS NULL OR asset_value_max IS NULL "
            "OR asset_value_min <= asset_value_max",
            name="ck_product_limits_asset_value_range_valid",
        ),
        sa.CheckConstraint(
            "financing_ratio_pct IS NULL "
            "OR (financing_ratio_pct >= 0 AND financing_ratio_pct <= 100)",
            name="ck_product_limits_financing_ratio_range_valid",
        ),
        sa.CheckConstraint(
            "vehicle_age_min IS NULL OR vehicle_age_max IS NULL "
            "OR vehicle_age_min <= vehicle_age_max",
            name="ck_product_limits_limit_vehicle_age_range_valid",
        ),
        sa.UniqueConstraint(
            "product_id", "band_key", "extraction_method",
            name="uq_product_limits_product_id_band_key_extraction_method",
        ),
    )
    op.create_index("ix_product_limits_product_id", "product_limits", ["product_id"])


def downgrade() -> None:
    """Oran türü alanlarını, izleme alanlarını ve limit tablosunu kaldırır."""
    # ── product_limits ────────────────────────────────────
    op.drop_index("ix_product_limits_product_id", table_name="product_limits")
    op.drop_table("product_limits")

    # ── products: izleme alanları ─────────────────────────
    with op.batch_alter_table("products", naming_convention=NAMING_CONVENTION) as batch:
        batch.alter_column("is_active", existing_type=sa.Boolean(), nullable=True)
    with op.batch_alter_table("products", naming_convention=NAMING_CONVENTION) as batch:
        batch.drop_column("last_seen_at")
        batch.drop_column("first_seen_at")
        batch.drop_column("is_active")

    # ── product_rates ─────────────────────────────────────
    with op.batch_alter_table("product_rates", naming_convention=NAMING_CONVENTION) as batch:
        batch.drop_constraint("rate_type_valid", type_="check")
        batch.drop_constraint("rate_currency_valid", type_="check")
        batch.drop_constraint("account_tier_valid", type_="check")
        batch.drop_constraint("customer_type_valid", type_="check")
        batch.drop_constraint("investor_share_range_valid", type_="check")
        batch.drop_constraint("term_days_range_valid", type_="check")
    with op.batch_alter_table("product_rates", naming_convention=NAMING_CONVENTION) as batch:
        batch.drop_column("is_binding")
        batch.drop_column("is_gross")
        batch.drop_column("customer_type")
        batch.drop_column("account_tier")
        batch.drop_column("currency")
        batch.drop_column("term_label")
        batch.drop_column("term_days_max")
        batch.drop_column("term_days_min")
        batch.drop_column("bank_share_pct")
        batch.drop_column("investor_share_pct")
        batch.drop_column("rate_type")
