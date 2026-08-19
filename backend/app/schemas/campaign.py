"""Kampanya yanıt şemaları."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.bank import BankBase


class CampaignCategoryOut(BaseModel):
    """Kampanyanın tek bir eksendeki tek bir etiketi.

    Her etiket KANITIYLA döner: hangi kaynaktan (`source`) ve hangi metinden
    (`evidence`) çıkarıldığı arayüzde gösterilebilir. Kaynaksız etiket
    bankacılıkta kabul edilemez.
    """

    model_config = ConfigDict(from_attributes=True)

    axis: str = Field(description="product_type | sector | audience | benefit")
    value: str = Field(description="Kontrollü sözlükten bir değer")
    confidence: Decimal = Field(description="0-1 arası; 1.00 bankanın kendi verisi")
    source: str = Field(description="url | bank_category | merchant | keyword | llm")
    evidence: str | None = Field(default=None, description="Etiketin dayandığı metin")


class CampaignListItem(BaseModel):
    """Tablo görünümünde kullanılan kampanya özeti."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    bank_code: str
    bank_name: str
    external_slug: str
    title: str
    category: str | None = Field(
        default=None, description="Nihai (çıkarılmış) sınıflandırma; sonraki sprintte dolar"
    )
    bank_category: str | None = Field(
        default=None, description="Bankanın KENDİ kategori etiketi, ham hâliyle"
    )
    categories: list[CampaignCategoryOut] = Field(
        default_factory=list,
        description="Dört eksenli taksonomi etiketleri, kanıtlarıyla",
    )
    segment: str | None = None
    target_customer: str | None = None
    start_date: date | None = Field(
        default=None, description="Bilinmiyorsa null — tarih UYDURULMAZ"
    )
    end_date: date | None = None
    date_precision: str = Field(description="exact | partial | inferred | unknown")
    date_evidence_text: str | None = Field(
        default=None, description="Tarihin kaynaktaki dayanağı; yoksa null"
    )
    date_evidence_source: str | None = Field(
        default=None, description="structured | conditions | body"
    )
    status: str = Field(description="active | upcoming | expired | unknown — BACKEND'de hesaplanır")
    source_url: str
    parent_campaign_id: int | None = Field(
        default=None, description="Dolu ise bu kayıt bir ALT kampanyadır"
    )
    sub_campaign_count: int = Field(default=0, description="Bu kampanyanın alt kampanya sayısı")


class SourceDocumentSummary(BaseModel):
    """Kampanyanın çıkarıldığı ham dokümanın özeti (izlenebilirlik)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    url: str
    canonical_url: str | None = None
    doc_type: str
    http_status: int | None = None
    fetched_at: datetime
    scraper_name: str | None = None
    scraper_version: str | None = None
    raw_html_sha256: str | None = None


class LinkedProduct(BaseModel):
    """Kampanyaya bağlanmış ürün.

    ⚠️ `confidence` bağın ne kadar sağlam olduğunu söyler: ürün adı BAŞLIKTA
    geçiyorsa 0,90; yalnızca gövde metninde geçiyorsa 0,60. Düşük güvenli bağ
    "kampanya bu ürüne aittir" demez, "metinde bu ürün anılıyor" der. Arayüz
    ikisini aynı ağırlıkta göstermemelidir.
    """

    model_config = ConfigDict(from_attributes=True)

    product_id: int
    product_name: str
    product_type: str | None = None
    variant_label: str | None = None
    match_method: str = Field(description="title | slug | body")
    confidence: Decimal
    evidence: str | None = None


class CampaignDetail(CampaignListItem):
    """Kampanya detay yanıtı."""

    description: str | None = None
    conditions_text: str | None = None
    exclusions_text: str | None = None
    participation_method: str | None = None
    participation_channel: str | None = None
    sms_keyword: str | None = None
    sms_number: str | None = None
    coupon_code: str | None = None
    is_archived: bool = False
    first_seen_at: datetime
    last_seen_at: datetime
    bank: BankBase
    source_document: SourceDocumentSummary | None = None
    sub_campaigns: list[CampaignListItem] = Field(
        default_factory=list, description="Aynı sayfada yayımlanan alt kampanyalar"
    )
    products: list[LinkedProduct] = Field(
        default_factory=list,
        description="Kampanyanın konu aldığı ürünler; kanıtı ve güveniyle",
    )
