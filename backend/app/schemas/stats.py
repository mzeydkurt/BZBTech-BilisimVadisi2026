"""Gösterge paneli istatistik şemaları."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class BankCampaignCount(BaseModel):
    """Banka başına kampanya sayısı."""

    bank_code: str
    bank_name: str
    count: int


class CategoryCount(BaseModel):
    """Kategori başına kampanya sayısı.

    `category` PART 1'de daima null'dur (sitelerde kategori etiketi yok);
    bu satır "sınıflandırılmamış" anlamına gelir.
    """

    category: str | None = None
    count: int


class RadarScore(BaseModel):
    """Banka rekabet radarı skoru (5 eksen)."""

    bank_code: str
    bank_name: str
    rate_competitiveness: float | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Kâr payı oranı rekabetçiliği; en düşük finansman oranından. Oran yoksa null",
    )
    campaign_volume: float = Field(ge=0, le=100, description="Kampanya hacmi (0-100)")
    reward_generosity: float | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Ödül cömertliği; ödül tutarlarının ortancasından. Ölçüm yoksa null",
    )
    term_flexibility: float | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Vade esnekliği; yayımlanan azami vadeden. Vade yoksa null",
    )
    transparency_index: float | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Ürünlerinin yüzde kaçının yayımlanmış oranı/limiti var. Ürün yoksa null",
    )
    measured_axes: int = Field(
        ge=0, le=5, description="Kaç eksenin gerçek ölçümü var (null olmayan eksen sayısı)"
    )


class SectorCount(BaseModel):
    """Sektör başına kampanya sayısı."""

    sector: str
    count: int


class TaxonomyCount(BaseModel):
    """Taksonomi eksen değeri başına kampanya sayısı."""

    value: str
    count: int


class BankCoverage(BaseModel):
    """Banka bazında aktif / toplam kampanya kapsaması."""

    bank_code: str
    bank_name: str
    active: int
    total: int


class StatsResponse(BaseModel):
    """Genel bakış sayfasının beslendiği istatistikler."""

    total_banks: int = Field(description="BDDK listesindeki tüm bankalar")
    banks_with_data: int = Field(description="En az bir kampanyası bulunan banka sayısı")
    total_campaigns: int
    active_campaigns: int
    upcoming_campaigns: int
    expired_campaigns: int
    unknown_status_campaigns: int = Field(
        description="Tarihi bulunamayan kampanyalar — 'süresi dolmuş' DEĞİLDİR"
    )
    products_total: int = Field(default=0, description="Yapısal ürün sayısı")
    rates_total: int = Field(default=0, description="Yapısal oran satırı sayısı")
    limits_total: int = Field(default=0, description="Yapısal limit satırı sayısı")
    ai_coverage_pct: float = Field(
        default=0.0,
        description="Sınıflandırma kapsamı: en az bir taksonomi etiketi olan kök kampanya oranı (%)",
    )
    green_campaigns_count: int = Field(
        default=0, description="Yeşil / Sürdürülebilir finansman kampanya sayısı"
    )
    ending_soon_count: int = Field(
        default=0,
        description="Aktif ve bitiş tarihi ≤14 gün içinde olan kök kampanya sayısı",
    )
    campaigns_by_bank: list[BankCampaignCount]
    campaigns_by_category: list[CategoryCount]
    sector_distribution: list[SectorCount] = Field(default_factory=list)
    audience_distribution: list[TaxonomyCount] = Field(default_factory=list)
    benefit_distribution: list[TaxonomyCount] = Field(default_factory=list)
    active_by_bank: list[BankCoverage] = Field(default_factory=list)
    radar_scores: list[RadarScore] = Field(default_factory=list)
    last_scrape_at: datetime | None = Field(
        default=None, description="Son tamamlanan kazımanın zamanı (Türkiye saati)"
    )
