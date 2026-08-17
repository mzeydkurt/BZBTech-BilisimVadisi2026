"""Scraper katmanının veri taşıyıcıları.

Bu dataclass'lar ORM modellerinden BAĞIMSIZDIR: scraper'lar veritabanı
nesneleri değil, saf veri üretir. Kalıcılık `BaseScraper.run()` içinde tek
noktadan yapılır; böylece ayrıştırma mantığı veritabanı olmadan test edilebilir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class DiscoveredUrl:
    """Keşif aşamasında bulunan bir adres ve o adres hakkında bilinenler.

    `*_hint` alanları keşif bağlamından gelir: örneğin Emlak Katılım'da
    /tr/bireysel/kampanyalar listesinden çıkan her adres bireysel segmenttedir.
    Bu bilgi detay sayfasında bulunmadığı için keşifte taşınır.
    """

    url: str
    doc_type: str  # campaign | product | listing | rate_table
    category_hint: str | None = None
    segment_hint: str | None = None  # bireysel | kurumsal | kobi | ticari | tarim
    discovery_method: str = "listing"


@dataclass
class RawCampaign:
    """Detay sayfasından çıkarılmış, henüz veritabanına yazılmamış kampanya."""

    external_slug: str
    title: str
    source_url: str
    # None → kök kampanya. Dolu ise kök kampanyanın slug'ı; ayrımı SCRAPER
    # verir, taban sınıf yorumlamaz.
    parent_slug: str | None = None
    block_index: int | None = None
    slug_source: str | None = None  # href | anchor | index
    description: str | None = None
    conditions_text: str | None = None
    exclusions_text: str | None = None
    category: str | None = None
    # Bankanın kendi kategori etiketi, ham hâliyle. Keşiften taşınır ve
    # sınıflandırmada güveni 1.00 olan kanıt olarak kullanılır.
    bank_category: str | None = None
    segment: str | None = None
    target_customer: str | None = None
    # ⚠️ Tarih alanlarına scraper yazmaz; `BaseScraper._apply_period()` doldurur.
    # Alt sınıfın yazacağı tek şey `structured_period_text()`tir.
    start_date: date | None = None
    end_date: date | None = None
    date_precision: str = "unknown"
    date_evidence_text: str | None = None
    date_evidence_source: str | None = None  # structured | conditions | body
    participation_method: str | None = None
    participation_channel: str | None = None
    sms_keyword: str | None = None
    sms_number: str | None = None
    coupon_code: str | None = None
    is_archived: bool = False


@dataclass
class RawProductRate:
    """Bir üründen çıkarılmış tek oran satırı.

    `rate_source` ZORUNLUDUR: güven değeri `ProductRate.__init__` içinde
    bundan türetilir, elle yazılmaz.
    """

    rate_source: str
    term_months: int | None = None
    profit_rate_pct: Decimal | None = None
    allocation_fee_pct: Decimal | None = None
    monthly_cost_pct: Decimal | None = None
    annual_cost_pct: Decimal | None = None
    variant: str | None = None
    effective_date: date | None = None
    amount_min: Decimal | None = None
    amount_max: Decimal | None = None
    ltv_band_min_pct: Decimal | None = None
    ltv_band_max_pct: Decimal | None = None
    energy_class: str | None = None
    vehicle_age_min: int | None = None
    vehicle_age_max: int | None = None
    evidence_text: str | None = None


@dataclass
class RawProduct:
    """Ürün sayfasından çıkarılmış, henüz veritabanına yazılmamış ürün.

    Bir sayfada birden çok ürün olabiliyor (ör. Dünya Katılım'ın finansman
    sayfasında üç ayrı finansman), bu yüzden `parse_products()` liste döndürür.
    """

    external_key: str
    name: str
    source_url: str
    product_type: str | None = None
    segment: str | None = None
    description: str | None = None

    # ⚠️ Varyant ağacı KEY ile kurulur, id ile değil: scraper veritabanı
    # kimliklerini bilmez. Bağlamayı `ProductRunner` yapar.
    parent_external_key: str | None = None
    variant_key: str | None = None
    variant_label: str | None = None
    variant_dimension: str | None = None
    variant_source: str | None = None

    amount_min: Decimal | None = None
    amount_max: Decimal | None = None
    term_months_min: int | None = None
    term_months_max: int | None = None
    allowed_terms: list[int] | None = None
    ltv_max_pct: Decimal | None = None
    collateral_type: str | None = None
    limits_source: str = "none"
    limits_evidence: str | None = None

    has_calculator: bool = False
    calculator_url: str | None = None
    # Yalnızca hesaplayıcı SORGULANARAK elde edilen değerler bağlayıcı değildir.
    # Form nitelikleri bankanın yayımladığı yapısal limittir; True kalır.
    is_binding: bool = True
    non_binding_notice: str | None = None

    rates: list[RawProductRate] = field(default_factory=list)


@dataclass
class ProductRunResult:
    """Bir ürün kazıma çalıştırmasının özeti."""

    bank_code: str
    status: str = "running"
    urls_discovered: int = 0
    urls_fetched: int = 0
    products_new: int = 0
    products_updated: int = 0
    rates_new: int = 0
    errors_count: int = 0
    errors: list[str] = field(default_factory=list)

    def add_error(self, message: str) -> None:
        """Hata kaydeder; çalıştırma durmaz, sayaç artar."""
        self.errors_count += 1
        if len(self.errors) < 50:
            self.errors.append(message)


@dataclass
class FetchResult:
    """Tek bir HTTP çekiminin sonucu.

    Başarısız çekimler de döndürülür (istisna fırlatılmaz): tek bir URL'in
    hatası tüm çalıştırmayı durdurmamalıdır (§12). Hata bilgisi `error`
    alanında taşınır ve `source_documents` kaydına yazılır.
    """

    url: str
    final_url: str | None = None
    status_code: int | None = None
    html: str | None = None
    content_type: str | None = None
    raw_html_path: str | None = None
    raw_html_sha256: str | None = None
    robots_allowed: bool = True
    is_soft_404: bool = False
    error: str | None = None

    # ⚠️ Ham gövde, METNE ÇEVRİLMEDEN. Sitemap'ler için ZORUNLU: Hayat Finans,
    # T.O.M. Bank ve Dünya Katılım `sitemap.xml` adresinde gzip kodlanmış bayt
    # döndürüyor ama ne uzantı ne de `Content-Type` bunu belli ediyor. `html`
    # alanı (metin) okunursa gzip baytları bozuk karakterlere dönüşür ve
    # ayrıştırıcı SIFIR adres bulur — hata vermeden.
    content: bytes | None = None

    @property
    def is_success(self) -> bool:
        """İçerik ayrıştırmaya uygun mu?"""
        return (
            self.robots_allowed
            and not self.is_soft_404
            and self.error is None
            and self.status_code is not None
            and 200 <= self.status_code < 300
            and bool(self.html)
        )


@dataclass
class ScrapeRunResult:
    """Bir kazıma çalıştırmasının özeti."""

    bank_code: str
    status: str = "running"
    run_id: int | None = None
    urls_discovered: int = 0
    urls_fetched: int = 0
    campaigns_new: int = 0
    campaigns_updated: int = 0
    # Dönem denetimini geçemediği için yazılmayan kampanyalar. Hata değildir;
    # "kaçırdık" ile "bilerek almadık" karışmasın diye ayrı sayılır.
    campaigns_skipped: int = 0
    errors_count: int = 0
    errors: list[str] = field(default_factory=list)

    def add_error(self, message: str) -> None:
        """Hata kaydeder; çalıştırma durmaz, sayaç artar."""
        self.errors_count += 1
        # Log dosyasının şişmemesi için ilk 50 hata metni saklanır.
        if len(self.errors) < 50:
            self.errors.append(message)
