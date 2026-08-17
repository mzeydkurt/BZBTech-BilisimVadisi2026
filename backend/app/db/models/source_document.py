"""Kaynak doküman modeli — HAM VERİ KATMANI.

KURAL: Ham HTML asla silinmez. Analizde doğrulandı — Hayat Finans'ta biten
kampanyalar 404'e düşüyor, Emlak Katılım'da arşiv yok. Kaybedilen veri geri gelmez.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Final

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UtcDateTime, utc_now

if TYPE_CHECKING:
    from app.db.models.bank import Bank
    from app.db.models.campaign import Campaign

# Doküman türü
DOC_TYPES: Final[tuple[str, ...]] = ("campaign", "product", "rate_table", "listing", "other")

# URL'in nasıl keşfedildiği — veri kaynağının izlenebilirliği için tutulur.
DISCOVERY_METHODS: Final[tuple[str, ...]] = (
    "sitemap",
    "listing",
    # Bankanın arşiv/geçmiş kampanya listesi. Ziraat ve Vakıf bu değeri
    # üretiyordu ama sözlükte yoktu; CHECK olmadığı için sessizce yazılıyordu.
    "archive",
    "playwright",
    "manual",
    "whitelist",
)


class SourceDocument(Base):
    """Çekilen her HTTP yanıtının kaydı (ham HTML dosya yolu ve özetleri dahil).

    Başarısız çekimler de (404, robots ile engellenmiş, soft-404) kaydedilir:
    veri setinin neden eksik olduğu sonradan kanıtlanabilir olmalıdır.
    """

    __tablename__ = "source_documents"
    __table_args__ = (
        CheckConstraint(
            "doc_type IN ('campaign', 'product', 'rate_table', 'listing', 'other')",
            name="doc_type_valid",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    bank_id: Mapped[int] = mapped_column(
        ForeignKey("banks.id", ondelete="CASCADE"), nullable=False, index=True
    )

    url: Mapped[str] = mapped_column(Text, nullable=False)
    # Yönlendirme sonrası nihai adres (cross-host redirect'ten sonra).
    canonical_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # URL'in sha256 özeti — uzun URL'lerde indeksleme maliyetini düşürür.
    url_hash: Mapped[str] = mapped_column(Text, nullable=False, index=True)

    doc_type: Mapped[str] = mapped_column(Text, nullable=False, default="campaign")
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utc_now)
    content_type: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Ham HTML arşivi: RAW_HTML_DIR altındaki göreli dosya yolu.
    raw_html_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_html_sha256: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Boilerplate temizliği sonrası metin.
    clean_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # İçerik bazlı deduplikasyon ve soft-404 tespiti için kullanılır.
    clean_text_sha256: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)

    scraper_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    scraper_version: Mapped[str | None] = mapped_column(Text, nullable=True)

    # robots.txt izni: False ise istek yapılmadı, kayıt belgeleme amaçlı tutuldu.
    robots_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # HTTP 200 döndüren ama aslında "sayfa yok" olan yanıtlar.
    is_soft_404: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    discovery_method: Mapped[str] = mapped_column(Text, nullable=False, default="listing")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utc_now)

    bank: Mapped[Bank] = relationship(back_populates="source_documents")
    campaigns: Mapped[list[Campaign]] = relationship(back_populates="source_document")
