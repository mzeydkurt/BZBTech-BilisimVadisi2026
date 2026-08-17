"""Kampanya çıkarımları — AÇIKLANABİLİRLİK / KANIT KATMANI.

Çıkarılan her alan için kaynak metindeki kanıtı ve karakter aralığını saklar.
Böylece "bu oran nereden geldi?" sorusu kaynak metinden gösterilerek yanıtlanır.

PART 1'de tablo OLUŞTURULUR ama DOLDURULMAZ; doldurma mantığı PART 3'te gelir.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Final

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UtcDateTime, utc_now

if TYPE_CHECKING:
    from app.db.models.campaign import Campaign

# Değerin hangi yöntemle çıkarıldığı. Birleştirmede öncelik: table > rule > llm.
EXTRACTION_METHODS: Final[tuple[str, ...]] = ("table", "rule", "llm", "hybrid")


class CampaignExtraction(Base):
    """Tek bir alanın çıkarım kaydı: değer + kanıt + güven skoru."""

    __tablename__ = "campaign_extractions"
    __table_args__ = (
        CheckConstraint(
            "extraction_method IN ('table', 'rule', 'llm', 'hybrid')",
            name="extraction_method_valid",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Hangi alan çıkarıldı (ör. "profit_rate_pct", "end_date")
    field_name: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    # Kaynak metindeki ham ifade (ör. "%2,05")
    value_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Normalize edilmiş değer (ör. "2.05") — metin olarak saklanır, tip alana göre değişir.
    value_normalized: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Kanıt ─────────────────────────────────────────────
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_char_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence_char_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence_source_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Ofsetlerin ait olduğu belge. Bu bağ olmadan `clean_text` yenilendiğinde
    # eski ofsetlerin geçersizleştiği anlaşılamaz ve doğrulama sessizce yanılır.
    source_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="SET NULL"), nullable=True
    )

    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    extraction_method: Mapped[str] = mapped_column(Text, nullable=False, default="rule")

    # ── Model kimliği (PART 3'te LLM çıkarımları için) ────
    model_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_validated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    validation_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ⚠️ REDDEDİLEN ÇIKARIM SİLİNMEZ. Halüsinasyon guard'ı bir alanı
    # reddettiğinde kayıt bu alan doldurularak saklanır: "modelin ürettiği ama
    # kaynakta doğrulanamayan" değerlerin oranı ancak böyle raporlanabilir.
    # Silinirse sistem kusursuz görünür ve guard'ın işe yaradığı kanıtlanamaz.
    rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    extracted_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utc_now)

    campaign: Mapped[Campaign] = relationship(back_populates="extractions")
