"""Kampanya ↔ ürün bağı.

NEDEN AYRI TABLO: Bir kampanya birden çok ürünü konu alabilir ("Taksitlio
kampanyası" hem `Alışveriş Finansmanı` hem `Taksitlio Alışveriş Finansmanı`
ürününü anıyor) ve bir ürün birçok kampanyada geçer. `campaigns` üzerinde tek
bir `product_id` sütunu bu ilişkiyi taşıyamaz.

⚠️ BAĞ, ÜRÜN TÜRÜNDEN KURULMAZ. "Bu kampanyanın türü taşıt finansmanı, o
hâlde bankanın taşıt finansmanı ürününe bağlansın" demek, ürünün oran
tablosunu her taşıt kampanyasına kopyalamak olurdu. Kampanyanın kendi oranı
varsa ürününkiyle çelişir; yoksa sahip olmadığımız bir bilgi iddia edilmiş
olur. Bağ yalnızca kampanya metninde ürünün ADI GEÇTİĞİNDE kurulur.

⚠️ HER BAĞ KANITIYLA SAKLANIR. `match_method` bağın hangi sinyalden geldiğini,
`evidence` metnin hangi parçasının eşleştiğini söyler. Kanıtsız bağ,
"bu kampanya bu ürüne ait" iddiasını denetlenemez kılar.

Ölçüldü (19 Ağustos 2026, 602 kampanya):

    finansman kampanyası   13/16  (%81) eşleşti
    diğer (kart, alışveriş) 115/586 (%20) eşleşti

Finansman tarafındaki kapsama yüksek; diğer tarafta ürün adının metinde
geçmesi çoğu zaman geçerken anılmasıdır — bu yüzden `body` yöntemiyle kurulan
bağın güveni düşük tutulur ve tüketen taraf eşiğe göre süzer.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.vocab import CAMPAIGN_PRODUCT_MATCH_METHODS
from app.db.base import Base, TimestampMixin, in_check

if TYPE_CHECKING:
    from app.db.models.campaign import Campaign
    from app.db.models.product import Product


class CampaignProduct(TimestampMixin, Base):
    """Bir kampanyanın konu aldığı ürün."""

    __tablename__ = "campaign_products"
    __table_args__ = (
        UniqueConstraint("campaign_id", "product_id", name="uq_campaign_products_pair"),
        CheckConstraint(
            in_check("match_method", CAMPAIGN_PRODUCT_MATCH_METHODS),
            name="campaign_product_match_method_valid",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="campaign_product_confidence_range",
        ),
        Index("ix_campaign_products_campaign_id", "campaign_id"),
        Index("ix_campaign_products_product_id", "product_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )

    # Bağın hangi sinyalden kurulduğu: `title` > `slug` > `body`.
    match_method: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)

    # ⚠️ Metnin eşleşen parçası. Olmadan bağ denetlenemez.
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)

    campaign: Mapped[Campaign] = relationship(back_populates="product_links")
    product: Mapped[Product] = relationship()
