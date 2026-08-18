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
    rate_competitiveness: float = Field(ge=0, le=100, description="Kâr Payı Oranı Rekabetçiliği (0-100)")
    campaign_volume: float = Field(ge=0, le=100, description="Kampanya Hacmi (0-100)")
    reward_generosity: float = Field(ge=0, le=100, description="Ödül & İade Cömertliği (0-100)")
    term_flexibility: float = Field(ge=0, le=100, description="Vade Esnekliği (0-100)")
    transparency_index: float = Field(ge=0, le=100, description="Veri Şeffaflığı ve Güven İndeksi (0-100)")


class SectorCount(BaseModel):
    """Sektör başına kampanya sayısı."""

    sector: str
    count: int


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
    ai_coverage_pct: float = Field(default=0.0, description="AI/Kural çıkarım kapsama oranı (%)")
    green_campaigns_count: int = Field(default=0, description="Yeşil / Sürdürülebilir finansman kampanya sayısı")
    campaigns_by_bank: list[BankCampaignCount]
    campaigns_by_category: list[CategoryCount]
    sector_distribution: list[SectorCount] = Field(default_factory=list)
    radar_scores: list[RadarScore] = Field(default_factory=list)
    last_scrape_at: datetime | None = Field(
        default=None, description="Son tamamlanan kazımanın zamanı (Türkiye saati)"
    )
