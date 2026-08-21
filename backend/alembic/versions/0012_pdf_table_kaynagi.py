"""`rate_source` sözlüğüne `pdf_table` eklenir (TOM Bank).

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-21

TOM Bank kâr oranlarını yalnızca PDF olarak yayımlıyor
(`krediler_kar_oranlari_*.pdf`, kurumsal sitede — kampanya tarafında hiç
kullanılmayan `www.tombank.com.tr`). `ProductLimit.extraction_method`'ta
`pdf_table` zaten rezerve edilmiş bir değerdi (CLAUDE.md'nin öngördüğü gibi)
ama `ProductRate.rate_source`'ta karşılığı yoktu. Bankanın kendi yayımladığı
yapısal tablo olduğu için güveni `html_table` ile AYNI (1.000) — yalnızca PDF
paketli olması güveni düşürmez.

⚠️ TEK BATCH BLOĞU. Bkz. 0011'in docstring'i: `product_rates`'e birden fazla
ayrı `batch_alter_table` bloğuyla dokunmak `naming_convention` aktifken her
seferinde bir kat daha kısıt öneki ekliyor (ölçüldü). Bu göç `rate_type_valid`
gibi zaten temiz olan başka bir kısıtı YENİDEN AÇMIYOR, yalnızca
`rate_source_valid`'i (0011'de temiz adla kurulmuştu) düşürüp genişletiyor.
"""

from __future__ import annotations

from alembic import op

from app.db.base import NAMING_CONVENTION

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

_ESKI_RATE_SOURCES = (
    "'html_table', 'payment_plan_derived', 'calculator_api', "
    "'calculator_playwright', 'text', 'js_default', 'none', 'seed_manual'"
)
_YENI_RATE_SOURCES = (
    "'html_table', 'payment_plan_derived', 'calculator_api', "
    "'calculator_playwright', 'text', 'js_default', 'none', 'seed_manual', 'pdf_table'"
)


def upgrade() -> None:
    """`rate_source_valid` kısıtına `pdf_table` değerini ekler."""
    with op.batch_alter_table("product_rates", naming_convention=NAMING_CONVENTION) as batch:
        batch.drop_constraint("ck_product_rates_rate_source_valid", type_="check")
        batch.create_check_constraint("rate_source_valid", f"rate_source IN ({_YENI_RATE_SOURCES})")


def downgrade() -> None:
    """`pdf_table` değerini kısıttan kaldırır."""
    with op.batch_alter_table("product_rates", naming_convention=NAMING_CONVENTION) as batch:
        batch.drop_constraint("ck_product_rates_rate_source_valid", type_="check")
        batch.create_check_constraint("rate_source_valid", f"rate_source IN ({_ESKI_RATE_SOURCES})")
