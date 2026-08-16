"""Gold set — insanın elle yazdığı CEVAP ANAHTARI.

Sistemin çıktısı buna karşı ölçülür. Sistem kendi cevap anahtarını üretemez;
üretirse her zaman %100 alır ve ölçüm anlamsızlaşır.

⚠️ `gold_value IS NULL` "ETİKETLENMEDİ" DEĞİL, "BU ALAN METİNDE YOK" DEMEKTİR.
Ayrım kritik: kaynakta bilgi olmadığı hâlde sistemin değer üretmesi
halüsinasyondur (yanlış pozitif) ve ayrı raporlanır. Etiketlenmemiş alan ise
gold set'e hiç satır olarak girmez.

⚠️ `method` alanı YANLILIK KONTROLÜNÜN TEMELİDİR. Ön-doldurmalı (`assisted`)
etiketlemede etiketleyici sistemin cevabını görür ve ona meyleder; bu F1'i
sahte şişirir. Kör (`blind`) alt küme ayrı ölçülür ve iki F1 arasındaki fark
0,05'i aşarsa ana metrik olarak kör alt küme raporlanır.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.vocab import ANNOTATION_METHODS
from app.db.base import Base, UtcDateTime, in_check, utc_now

if TYPE_CHECKING:
    from app.db.models.campaign import Campaign


class GoldAnnotation(Base):
    """Bir kampanyanın tek bir alanı için insan etiketi."""

    __tablename__ = "gold_annotations"
    __table_args__ = (
        # Aynı etiketleyici aynı alanı iki kez etiketlemez; düzeltme mevcut
        # satırı günceller. Öz-tutarlılık ölçümü ayrı `annotator` adıyla yapılır.
        UniqueConstraint(
            "campaign_id",
            "field_name",
            "annotator",
            name="uq_gold_annotations_campaign_id_field_name",
        ),
        CheckConstraint(in_check("method", ANNOTATION_METHODS), name="method_valid"),
        Index("ix_gold_annotations_method_is_difficult", "method", "is_difficult"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True
    )

    field_name: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    # ⚠️ NULL = "bu alan metinde YOK". Boş dize ya da 0 ile karıştırılmaz:
    # 0 "değer sıfır" demektir (ör. "vade farksız" -> kâr payı oranı 0).
    gold_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Değerin okunduğu cümle, kaynaktan BİREBİR. Yazılamıyorsa alan NULL'dur.
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    annotator: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    # Zor vaka alt kümesi ayrı F1 ile raporlanır: kolay kayıtlarla ortalanınca
    # sistemin gerçek zayıf noktaları görünmez olur.
    is_difficult: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utc_now)

    campaign: Mapped[Campaign] = relationship()
