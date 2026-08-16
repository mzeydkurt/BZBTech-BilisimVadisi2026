"""Varlık kartları ve gömmeler — arama katmanının hazırlığı.

KART NEDİR: Bir kampanyanın/ürünün dağınık alanlarından üretilmiş, tek parça
ve kendi kendine yeten metin özeti. Çıkarım sonrası üretilir, SPRINT 5'te
gömme (embedding) hesaplamasının girdisi olur.

⚠️ `card_hash` NEDEN VAR: Kaynak veri değişmediyse gömme yeniden hesaplanmaz.
Gömme hesaplamak pahalıdır; kartın özeti değişmediği sürece eski vektör
geçerlidir. Aynı mantık `embeddings.source_hash` ile eşleştirilir.

⚠️ `embeddings` tablosu bu sprintte OLUŞTURULUR ama DOLDURULMAZ. Şemayı şimdi
kurmak, SPRINT 5'te ikinci bir Alembic başının (multiple heads) doğmasını
engeller.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

from sqlalchemy import (
    CheckConstraint,
    Index,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.vocab import ENTITY_TYPES
from app.db.base import Base, UtcDateTime, in_check, utc_now

# Gömme vektörünün varsayılan boyutu (BAAI/bge-m3). Modele göre değişir,
# bu yüzden satır bazında saklanır.
DEFAULT_EMBEDDING_DIM: Final[int] = 1024


class EntityCard(Base):
    """Bir varlığın metin kartı — gömmenin ve sohbet yanıtının girdisi."""

    __tablename__ = "entity_cards"
    __table_args__ = (
        # Bir varlığın tek bir güncel kartı olur; yeniden üretim satırı günceller.
        UniqueConstraint("entity_type", "entity_id", name="uq_entity_cards_entity_type_entity_id"),
        CheckConstraint(in_check("entity_type", ENTITY_TYPES), name="entity_type_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    # ⚠️ Çok biçimli (polymorphic) referans: foreign key YOK. Kart beş farklı
    # tabloya bakabildiği için tek bir FK tanımlanamaz; tutarlılık kart üretimi
    # sırasında sağlanır ve kaynak kaybolursa kart yeniden üretilir.
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)

    card_text: Mapped[str] = mapped_column(Text, nullable=False)
    # Kartın içerik özeti: değişmediyse gömme yeniden hesaplanmaz.
    card_hash: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utc_now)


class Embedding(Base):
    """Bir kart parçasının vektör gösterimi.

    ⚠️ SPRINT 3A'da şema kurulur, satır YAZILMAZ. Doldurma SPRINT 5'tedir.
    """

    __tablename__ = "embeddings"
    __table_args__ = (
        UniqueConstraint(
            "entity_type",
            "entity_id",
            "chunk_index",
            name="uq_embeddings_entity_type_entity_id_chunk_index",
        ),
        CheckConstraint(in_check("entity_type", ENTITY_TYPES), name="entity_type_valid"),
        CheckConstraint("dim > 0", name="dim_positive"),
        Index("ix_embeddings_model_name_entity_type", "model_name", "entity_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    # Uzun kartlar parçalanır; her parça ayrı vektördür.
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)

    # ⚠️ Vektör BAYT olarak saklanır (float dizisi paketlenmiş hâlde).
    # PostgreSQL'e geçişte pgvector'e taşınabilir; SQLite'ta yerel vektör tipi
    # bulunmadığı için taşınabilir olan biçim budur.
    embedding: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    dim: Mapped[int] = mapped_column(Integer, nullable=False)
    # Model adı satırda saklanır: model değişince eski vektörler geçersizdir
    # ama SİLİNMEZ, karşılaştırma için durur.
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    # Kaynak kartın özeti — `entity_cards.card_hash` ile eşleşir.
    source_hash: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utc_now)
