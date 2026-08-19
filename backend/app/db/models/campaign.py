"""Kampanya modeli — İŞLENMİŞ VERİ KATMANI."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Final

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UtcDateTime, utc_now

if TYPE_CHECKING:
    from app.db.models.bank import Bank
    from app.db.models.campaign_category import CampaignCategory
    from app.db.models.campaign_extraction import CampaignExtraction
    from app.db.models.campaign_metric import CampaignMetric
    from app.db.models.campaign_product import CampaignProduct
    from app.db.models.source_document import SourceDocument

# Kampanya durumu. `unknown`, tarih verisi hiç bulunmayan kampanyalar içindir ve
# `expired`'dan AYRI tutulur: tarihi olmayan kampanyayı "süresi dolmuş" göstermek
# yanlış bilgi olur (Türkiye Finans'ta hiçbir kampanyada tarih yok).
CAMPAIGN_STATUSES: Final[tuple[str, ...]] = ("active", "upcoming", "expired", "unknown")

# Tarih çıkarımının güvenilirliği:
#   exact    — başlangıç ve bitiş açıkça yazılı
#   partial  — yalnızca biri yazılı (ör. "31.12.2026 tarihine kadar")
#   inferred — eksik bilgi çıkarsandı (ör. başlangıçtaki yıl bitişten devralındı)
#   unknown  — tarih bulunamadı
DATE_PRECISIONS: Final[tuple[str, ...]] = ("exact", "partial", "inferred", "unknown")

# Müşteri segmenti
SEGMENTS: Final[tuple[str, ...]] = ("bireysel", "kurumsal", "kobi", "ticari", "tarim")

# Kampanyaya katılım yöntemi
PARTICIPATION_METHODS: Final[tuple[str, ...]] = ("sms", "kod", "otomatik", "basvuru", "yok")


class Campaign(TimestampMixin, Base):
    """Bir bankanın tek bir kampanyası.

    Tarih alanlarının nullable olması ZORUNLUDUR: bankaların çoğunda yapısal
    tarih alanı yok, bazılarında hiç tarih yok. NOT NULL yapılırsa veri kaybedilir.
    """

    __tablename__ = "campaigns"
    __table_args__ = (
        # Aynı bankada aynı slug tek kayıt olur — upsert anahtarı budur.
        UniqueConstraint("bank_id", "external_slug", name="uq_campaigns_bank_id_external_slug"),
        CheckConstraint(
            "status IN ('active', 'upcoming', 'expired', 'unknown')",
            name="status_valid",
        ),
        CheckConstraint(
            "date_precision IN ('exact', 'partial', 'inferred', 'unknown')",
            name="date_precision_valid",
        ),
        CheckConstraint(
            "date_evidence_source IS NULL "
            "OR date_evidence_source IN ('structured', 'conditions', 'body')",
            name="date_evidence_source_valid",
        ),
        # Kanıtsız `exact` yasağı: "kaynakta birebir gördüm" iddiası kanıt
        # metni olmadan geçersizdir (Albaraka #290: 2020-01-01, exact, kanıt yok).
        CheckConstraint(
            "date_precision <> 'exact' OR date_evidence_text IS NOT NULL",
            name="exact_requires_evidence",
        ),
        CheckConstraint(
            "slug_source IS NULL OR slug_source IN ('href', 'anchor', 'index')",
            name="slug_source_valid",
        ),
        CheckConstraint(
            "parent_campaign_id IS NULL OR parent_campaign_id <> id",
            name="parent_not_self",
        ),
        Index("ix_campaigns_bank_id_status", "bank_id", "status"),
        Index("ix_campaigns_end_date", "end_date"),
        Index("ix_campaigns_parent_campaign_id", "parent_campaign_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    bank_id: Mapped[int] = mapped_column(
        ForeignKey("banks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Kampanyanın çıkarıldığı ham doküman — kaynak gösterimi için zorunlu bağ.
    source_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="SET NULL"), nullable=True
    )

    # Bir sayfada birden çok kampanya olabiliyor. Alt kampanya ayrı satırdır;
    # kanıt/arama katmanının tamamı tamsayı bir campaign_id bekliyor.
    parent_campaign_id: Mapped[int | None] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=True
    )
    # Sayfadaki sıra (yalnızca alt kampanyalarda dolu).
    block_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Alt slug'ın kaynağı: href > anchor > index. `index` kırılgandır, ölçülür.
    slug_source: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Bankanın URL'inde geçen slug. Başlıktan TÜRETİLMEZ, href'ten birebir alınır.
    # Alt kampanyada biçim: `{kök slug}#{alt}`.
    external_slug: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # PART 3'te LLM ile doldurulacak; PART 1'de daima NULL.
    summary_ai: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Nihai (çıkarılmış) sınıflandırma. Sonraki sprintte doldurulacak.
    category: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    category_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)

    # ⚠️ Bankanın KENDİ kategori etiketi, ham hâliyle ("Giyim ve Aksesuar").
    # Çıkarım değil kaynak veridir; taksonomide güveni 1.00'dır. `category`
    # ile karıştırılmaz: biri bankanın dediği, öteki bizim çıkardığımızdır.
    bank_category: Mapped[str | None] = mapped_column(Text, nullable=True)

    segment: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    target_customer: Mapped[str | None] = mapped_column(Text, nullable=True)

    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_precision: Mapped[str] = mapped_column(Text, nullable=False, default="unknown")

    # Tarihin kaynaktaki dayanağı; arayüzde JOIN yapılmadan gösterilir.
    # ⚠️ Karakter ofseti buraya yazılmaz: `clean_text` yeniden üretilebildiği
    # için ofset bayatlar, kanıt metni bayatlamaz. Ofset `campaign_extractions`'ta.
    date_evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    date_evidence_source: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Backend'de hesaplanır — tek doğruluk kaynağı burasıdır, frontend hesaplamaz.
    status: Mapped[str] = mapped_column(Text, nullable=False, default="unknown", index=True)

    participation_channel: Mapped[str | None] = mapped_column(Text, nullable=True)
    participation_method: Mapped[str | None] = mapped_column(Text, nullable=True)
    sms_keyword: Mapped[str | None] = mapped_column(Text, nullable=True)
    sms_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    coupon_code: Mapped[str | None] = mapped_column(Text, nullable=True)

    conditions_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    exclusions_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    source_url: Mapped[str] = mapped_column(Text, nullable=False)

    first_seen_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utc_now)
    last_seen_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utc_now)
    # Bankanın arşiv/geçmiş kampanya bölümünden gelen kayıtlar.
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    parent: Mapped[Campaign | None] = relationship(
        back_populates="sub_campaigns",
        remote_side="Campaign.id",
    )
    sub_campaigns: Mapped[list[Campaign]] = relationship(
        back_populates="parent",
        cascade="all, delete-orphan",
    )

    bank: Mapped[Bank] = relationship(back_populates="campaigns", lazy="joined")
    source_document: Mapped[SourceDocument | None] = relationship(back_populates="campaigns")
    metric: Mapped[CampaignMetric | None] = relationship(
        back_populates="campaign", cascade="all, delete-orphan", uselist=False
    )
    extractions: Mapped[list[CampaignExtraction]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )
    # Çok eksenli taksonomi etiketleri
    # Kampanyanın konu aldığı ürünler; `campaign_products` üzerinden.
    product_links: Mapped[list[CampaignProduct]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )

    categories: Mapped[list[CampaignCategory]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )
