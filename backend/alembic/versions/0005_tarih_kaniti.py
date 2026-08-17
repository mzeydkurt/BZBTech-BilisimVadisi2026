"""Tarih kanıtı kolonları ve çıkarımların belge bağı.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-17

NEDEN
-----
Kampanya tarihi artık tek ortak yoldan (`app/processing/dates.py::
find_period_in_sources`) belirleniyor ve bulgunun DAYANAĞI kayıt altına
alınıyor. Ölçüldü: 20 Ziraat kampanyasının bitiş tarihi komşu kampanya
kartından sızmıştı ve Albaraka #290 `2020-01-01` değerini `exact` güveniyle
taşıyordu — kanıtı ise sayfanın menü metniydi.

Üç değişiklik:

1. `campaigns.date_evidence_text` / `date_evidence_source`
   Arayüzde "bu tarih nereden geldi?" sorusu JOIN yapılmadan yanıtlanır.
   ⚠️ Karakter ofseti BU TABLOYA yazılmaz: `clean_text` yeniden
   üretilebiliyor ve ofset bayatlıyor; kanıt metni bayatlamaz.

2. `ck_campaigns_exact_requires_evidence`
   Kanıtsız `exact` iddiasını veritabanı düzeyinde yasaklar.

3. `campaign_extractions.source_document_id`
   Ofsetin hangi metne ait olduğunu bağlar; olmadan `yeniden-isle`
   sonrası ofsetlerin geçersizleştiği anlaşılamaz.

Tümü nullable ve geriye uyumludur; eski kod kırılmadan uygulanabilir.
`downgrade` tam güvenlidir — yalnızca türetilmiş kanıt alanları kaybolur,
asıl kanıt `campaign_extractions.evidence_text` içinde durmaya devam eder.

⚠️ MEVCUT SATIRLAR DÜZELTİLİR, İSTİSNA TANINMAZ.
SQLite'ta `batch_alter_table` tabloyu yeniden kurup satırları kopyalar ve
CHECK kısıtı TÜM satırlara uygulanır. Deponun bugünkü verisinde 244 kayıt
`date_precision='exact'` taşıyor ama hiçbirinin kanıt metni yok (kanıt alanı
bu göçle geliyor). Bu yüzden göç, kısıtı eklemeden ÖNCE o satırları
`inferred`'a düşürür.

Bu bir veri kaybı değil, yanlış iddianın geri alınmasıdır: o kayıtların
tarihi yerinde kalır, yalnızca "kaynakta birebir gördüm" iddiası düşer.
Kanıtlı `exact` değerler kampanyalar yeniden kazındığında geri gelir
(bkz. planın 5. fazı).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.db.base import NAMING_CONVENTION

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Kanıt kolonlarını ve belge bağını ekler."""
    # ⚠️ SIRA ÖNEMLİ: kısıt eklenmeden önce mevcut kanıtsız `exact` iddiaları
    # geri alınır. SQLite batch modu tabloyu yeniden kurup satırları kopyalar;
    # kısıt TÜM satırlara uygulanır ve bu adım olmadan göç çöker.
    op.execute(
        "UPDATE campaigns SET date_precision = 'inferred' WHERE date_precision = 'exact'"
    )

    with op.batch_alter_table("campaigns", naming_convention=NAMING_CONVENTION) as batch:
        batch.add_column(sa.Column("date_evidence_text", sa.Text(), nullable=True))
        batch.add_column(sa.Column("date_evidence_source", sa.Text(), nullable=True))
        batch.create_check_constraint(
            "date_evidence_source_valid",
            "date_evidence_source IS NULL "
            "OR date_evidence_source IN ('structured', 'conditions', 'body')",
        )
        batch.create_check_constraint(
            "exact_requires_evidence",
            "date_precision <> 'exact' OR date_evidence_text IS NOT NULL",
        )

    with op.batch_alter_table("campaign_extractions", naming_convention=NAMING_CONVENTION) as batch:
        batch.add_column(sa.Column("source_document_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_campaign_extractions_source_document_id_source_documents",
            "source_documents",
            ["source_document_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    """Kanıt kolonlarını kaldırır. Veri kaybı türetilmiş alanlarla sınırlıdır."""
    with op.batch_alter_table("campaign_extractions", naming_convention=NAMING_CONVENTION) as batch:
        batch.drop_constraint(
            "fk_campaign_extractions_source_document_id_source_documents",
            type_="foreignkey",
        )
        batch.drop_column("source_document_id")

    with op.batch_alter_table("campaigns", naming_convention=NAMING_CONVENTION) as batch:
        batch.drop_constraint("ck_campaigns_exact_requires_evidence", type_="check")
        batch.drop_constraint("ck_campaigns_date_evidence_source_valid", type_="check")
        batch.drop_column("date_evidence_source")
        batch.drop_column("date_evidence_text")
