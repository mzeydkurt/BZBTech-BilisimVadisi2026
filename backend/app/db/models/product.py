"""Ürün, ürün varyantı ve ürün oranı modelleri.

Terminoloji: "finansman" kullanılır, konvansiyonel karşılığı KULLANILMAZ.

⚠️ TASARIM KARARI — HER VARYANT KENDİ SATIRIDIR (SPRINT 2).
"Sıfır araç taşıt finansmanı" ile "2. el araç taşıt finansmanı" ayrı iki
`products` kaydıdır ve `parent_product_id` ile bağlıdır. Sebep: her varyantın
KENDİ oran tablosu, KENDİ tutar/vade limiti ve KENDİ hesaplayıcı girdisi var.
Tek satırda tutulup varyant bir metin alanına sıkıştırılırsa, "en düşük kâr
payı oranı" karşılaştırması bir bankanın sigortalı oranını başka bankanın
sigortasız oranıyla kıyaslar ve sessizce yanlış sonuç üretir.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
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

from app.core.vocab import (
    ACCOUNT_TIERS,
    AVAILABILITY_STATUSES,
    COLLATERAL_TYPES,
    CURRENCIES,
    CUSTOMER_TYPES,
    DATA_SOURCES,
    LIMIT_EXTRACTION_METHODS,
    LIMIT_SOURCES,
    RATE_SOURCES,
    RATE_TYPES,
    VARIANT_DIMENSIONS,
    VARIANT_SOURCES,
)
from app.db.base import Base, TimestampMixin, UtcDateTime, in_check

if TYPE_CHECKING:
    from app.db.models.bank import Bank
    from app.db.models.calculator import CalculatorProbe
    from app.db.models.source_document import SourceDocument


class Product(TimestampMixin, Base):
    """Bankanın sürekli sunduğu finansal ürün veya onun bir varyantı."""

    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint(
            in_check("variant_dimension", VARIANT_DIMENSIONS),
            name="variant_dimension_valid",
        ),
        CheckConstraint(in_check("variant_source", VARIANT_SOURCES), name="variant_source_valid"),
        CheckConstraint(in_check("limits_source", LIMIT_SOURCES), name="limits_source_valid"),
        CheckConstraint(
            in_check("collateral_type", COLLATERAL_TYPES), name="collateral_type_valid"
        ),
        CheckConstraint(
            in_check("availability_status", AVAILABILITY_STATUSES),
            name="availability_status_valid",
        ),
        # Tutar ve vade aralıkları tersine dönmüş olamaz; bozuk ayrıştırma
        # (ör. "50.000" ile "5.000"in karışması) burada yakalanır.
        CheckConstraint(
            "amount_min IS NULL OR amount_max IS NULL OR amount_min <= amount_max",
            name="amount_range_valid",
        ),
        CheckConstraint(
            "term_months_min IS NULL OR term_months_max IS NULL "
            "OR term_months_min <= term_months_max",
            name="term_range_valid",
        ),
        # Upsert anahtarı. Olmadan ürün kazıması her çalıştırmada satır
        # çoğaltır; `variant_key` NULL olabildiği için mevcut kolonlarla
        # bileşik anahtar kurulamıyor (SQLite'ta NULL != NULL).
        UniqueConstraint("bank_id", "external_key", name="uq_products_bank_id_external_key"),
        Index("ix_products_bank_id_product_type", "bank_id", "product_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    bank_id: Mapped[int] = mapped_column(
        ForeignKey("banks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # "{url-slug}#{variant_key|variant_label|base}" — deterministik, izlenebilir.
    external_key: Mapped[str] = mapped_column(Text, nullable=False)

    name: Mapped[str] = mapped_column(Text, nullable=False)
    # Ör. konut_finansmani, tasit_finansmani, katilma_hesabi, kart
    product_type: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    segment: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    source_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="SET NULL"), nullable=True
    )

    # ── Varyant boyutu ────────────────────────────────────
    # Ana ürün (varyantı olmayan ya da varyantların çatısı) için NULL kalır.
    parent_product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Kanonik anahtar — karşılaştırma bunun üzerinden yapılır (VARIANT_VOCAB).
    variant_key: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    # ⚠️ Kaynaktaki insan okunur etiket BİREBİR yazılır ("Sıfır Km Araç").
    # Kanonikleştirme `variant_key`'de yapılır; ham etiket değiştirilmez.
    variant_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    variant_dimension: Mapped[str | None] = mapped_column(Text, nullable=True)
    variant_source: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Limitler ──────────────────────────────────────────
    amount_min: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    amount_max: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    term_months_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    term_months_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Bankanın izin verdiği ayrık vade seçenekleri: [3, 6, 12, 24, 36].
    # Aralık (min/max) yetmez — bazı bankalar yalnızca belirli vadeleri sunuyor.
    allowed_terms: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    # Kredi/değer oranı üst sınırı (loan-to-value). Konut finansmanında
    # gayrimenkul değerinin en fazla yüzde kaçının finanse edilebileceği.
    ltv_max_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    collateral_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    currency: Mapped[str] = mapped_column(Text, nullable=False, default="TRY")

    # ── Hesaplayıcı ve kanıt ──────────────────────────────
    has_calculator: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    calculator_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    limits_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Limitin çıkarıldığı ham metin/attribute — kaynak gösterimi için.
    limits_evidence: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Bankanın yayımladığı değer bağlayıcı mı, yoksa "örnek/bilgilendirme
    # amaçlıdır" kaydı mı düşülmüş? Hesaplayıcıdan gelen değerler bağlayıcı
    # değildir ve arayüzde rozetle gösterilir.
    is_binding: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    non_binding_notice: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── KATİP: alım sırası, marka/model, mevcudiyet ────────
    # "ilk_alim" | "sonraki_alim" | NULL — konut finansmanında iki ayrı LTV
    # matrisi olduğunda (Standart / İkinci Alım) `product_limits` kesişimini
    # ayırt eder. `variant_dimension="alim_sirasi"` ile birlikte kullanılır.
    purchase_order: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Marka/model bazlı finansman (ör. Togg T10X). `variant_dimension="marka_model"`.
    brand: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ⚠️ "Ürün yok" (`not_offered`) ile "veri henüz toplanmadı" (`unknown`)
    # AYRI durumlardır — bkz. `app/core/vocab.py::AVAILABILITY_STATUSES`.
    # Yalnızca TKBB kaynaklı katılma hesabı ürünlerinde `not_offered`
    # kullanılır; scrape edilen finansman verisinde `unknown` kalabilir.
    availability_status: Mapped[str] = mapped_column(Text, nullable=False, default="unknown")

    # ── İzleme ────────────────────────────────────────────
    # ⚠️ Ürün sayfadan KALKINCA satır SİLİNMEZ, `is_active=False` olur.
    # Silmek, o ürünün hiç var olmadığı izlenimi yaratır ve geçmiş
    # karşılaştırmaları geçersiz kılar.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    first_seen_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    bank: Mapped[Bank] = relationship(back_populates="products")
    source_document: Mapped[SourceDocument | None] = relationship()
    rates: Mapped[list[ProductRate]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    limits: Mapped[list[ProductLimit]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    parent: Mapped[Product | None] = relationship(
        back_populates="variants", remote_side="Product.id"
    )
    variants: Mapped[list[Product]] = relationship(
        back_populates="parent", cascade="all, delete-orphan"
    )
    probes: Mapped[list[CalculatorProbe]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )

    def __init__(self, **kwargs: Any) -> None:
        """Verilmediyse `external_key`'i addan ve varyanttan türetir.

        Üretimde anahtar sayfa adresinden kurulur
        (`scrapers/products.py::product_external_key`); bu varsayılan yalnızca
        elle kurulan nesneler içindir.
        """
        if not kwargs.get("external_key"):
            from app.utils.slugify import slugify

            varyant = kwargs.get("variant_key") or kwargs.get("variant_label")
            ad = slugify(str(kwargs.get("name") or "urun"))
            kwargs["external_key"] = f"{ad}#{slugify(str(varyant)) if varyant else 'base'}"
        super().__init__(**kwargs)


def _band_key_from_kwargs(kwargs: dict[str, Any]) -> str:
    """Bant boyutlarından deterministik anahtar üretir.

    Sıra sabittir; değişirse aynı oran farklı anahtar üretir ve upsert
    satır çoğaltır. Üretim yolu `scrapers/products.py::band_key`.
    """
    alanlar = (
        "term_months",
        "term_days_min",
        "term_days_max",
        "variant",
        "amount_min",
        "amount_max",
        "ltv_band_min_pct",
        "ltv_band_max_pct",
        "energy_class",
        "vehicle_age_min",
        "vehicle_age_max",
        "currency",
        "account_tier",
        "customer_type",
        "rate_type",
    )
    return "|".join("" if kwargs.get(a) is None else str(kwargs[a]) for a in alanlar)


class ProductRate(Base):
    """Bir ürünün belirli bir bant ve vadedeki kâr payı oranı satırı.

    Kaynak: bankaların ürün sayfalarındaki HTML oran tabloları
    (ör. Vade | Kâr Payı Oranı | Tahsis Ücreti | Aylık/Yıllık Toplam Maliyet).

    Oran tek bir vadeye değil, bir BANDA bağlı olabilir: tutar bandı, LTV bandı,
    enerji sınıfı, araç yaşı. Bu boyutlar ayrı satırlar olarak tutulur.
    """

    __tablename__ = "product_rates"
    __table_args__ = (
        CheckConstraint(in_check("rate_source", RATE_SOURCES), name="rate_source_valid"),
        CheckConstraint(in_check("rate_type", RATE_TYPES), name="rate_type_valid"),
        CheckConstraint(in_check("currency", CURRENCIES), name="rate_currency_valid"),
        CheckConstraint(in_check("account_tier", ACCOUNT_TIERS), name="account_tier_valid"),
        CheckConstraint(in_check("customer_type", CUSTOMER_TYPES), name="customer_type_valid"),
        CheckConstraint(in_check("data_source", DATA_SOURCES), name="data_source_valid"),
        # ⚠️ Bölüşüm oranının iki ucu 100'ü aşamaz. "90/10" toplamı 100 olmalı
        # ama bazı bankalar masrafı ayırıp "89.1/10.9" yazıyor; tam eşitlik
        # ZORLANMAZ, yalnızca üst sınır denetlenir.
        CheckConstraint(
            "investor_share_pct IS NULL OR (investor_share_pct >= 0 AND investor_share_pct <= 100)",
            name="investor_share_range_valid",
        ),
        CheckConstraint(
            "term_days_min IS NULL OR term_days_max IS NULL OR term_days_min <= term_days_max",
            name="term_days_range_valid",
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range_valid"),
        CheckConstraint(
            "amount_min IS NULL OR amount_max IS NULL OR amount_min <= amount_max",
            name="rate_amount_range_valid",
        ),
        CheckConstraint(
            "vehicle_age_min IS NULL OR vehicle_age_max IS NULL "
            "OR vehicle_age_min <= vehicle_age_max",
            name="vehicle_age_range_valid",
        ),
        # `effective_date` anahtara dahildir: banka oranı güncelleyince yeni
        # satır açılır, eski satır korunur ve oran zaman serisi oluşur.
        UniqueConstraint(
            "product_id",
            "rate_source",
            "effective_date",
            "band_key",
            name="uq_product_rates_product_id_rate_source_effective_date_band_key",
        ),
        Index("ix_product_rates_product_id_term_months", "product_id", "term_months"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Bant boyutlarının NULL-güvenli kodlaması; bkz. `scrapers/products.py`.
    band_key: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # ⭐ ORAN TÜRÜ — VARSAYILANI YOK, HER SATIRDA DOLU.
    #
    # ⚠️ "Kâr payı" üç ayrı büyüklüğü anlatıyor ve aynı kolona yazılırlarsa
    # karşılaştırma sessizce yanlış sonuç verir. Ayrıntı `core/vocab.py`:
    #   financing_rate       → finansman maliyeti      (%4,15)
    #   participation_yield  → katılma hesabı getirisi (%31,22)
    #   profit_sharing_ratio → bölüşüm oranı           (90/10)
    #
    # Sunucu tarafı varsayılanı `financing_rate`: göç sırasında mevcut 253
    # satır finansman oranıdır. YENİ kayıtlarda açıkça verilmelidir.
    rate_type: Mapped[str] = mapped_column(Text, nullable=False, default="financing_rate")

    term_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # ⚠️ Vade her zaman AY değil: Kuveyt Türk katılma hesabında "2-6 Gün" gibi
    # kısa vadeler var. Aya yuvarlamak 2 günlük hesabı 0 ay yapardı.
    term_days_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    term_days_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Kaynaktaki vade ifadesi BİREBİR: "1 Yıldan Uzun (366-999 Gün)".
    term_label: Mapped[str | None] = mapped_column(Text, nullable=True)

    profit_rate_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    # ⚠️ Bölüşüm oranının İKİ ucu da saklanır. Yalnızca müşteri payını tutmak
    # "90/10" ile "90/8 + %2 masraf" ayrımını kaybettirir.
    investor_share_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    bank_share_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    allocation_fee_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    monthly_cost_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    annual_cost_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)

    # Aynı sayfada birden fazla tablo olabilir (ör. sigortalı / sigortasız).
    variant: Mapped[str | None] = mapped_column(Text, nullable=True)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # ── Bant boyutu ───────────────────────────────────────
    amount_min: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    amount_max: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    ltv_band_min_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    ltv_band_max_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    # A | B | diger — konut finansmanında enerji sınıfı oranı değiştiriyor.
    energy_class: Mapped[str | None] = mapped_column(Text, nullable=True)
    vehicle_age_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vehicle_age_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # ⚠️ XAU/XAG'de `amount_min/max` GRAM cinsindendir, TL değil.
    currency: Mapped[str] = mapped_column(Text, nullable=False, default="TRY")
    # Katılma hesabında paylaşım oranı bakiye kademesine göre değişiyor.
    account_tier: Mapped[str | None] = mapped_column(Text, nullable=True)
    customer_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ⚠️ Brüt/net ayrımı: stopaj öncesi oran ile sonrası aynı sayı değildir.
    # Bilinmiyorsa NULL kalır — varsayım yapılmaz.
    is_gross: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # ── Kaynak ve güven (ZORUNLU) ─────────────────────────
    # ⚠️ NOT NULL: kaynağı bilinmeyen oran karşılaştırmaya giremez.
    # Güven sıralaması ve karşılaştırılabilirlik `app/core/vocab.py`'de.
    rate_source: Mapped[str] = mapped_column(Text, nullable=False, default="html_table")
    # KATİP: bankanın kendi sitesi mi (`bank_site`, varsayılan — geriye dönük
    # veri bozulmaz) yoksa TKBB Veri Peteği'nin resmi API'si mi (`tkbb_veripetegi`).
    data_source: Mapped[str] = mapped_column(Text, nullable=False, default="bank_site")
    confidence: Mapped[Decimal] = mapped_column(
        Numeric(4, 3), nullable=False, default=Decimal("1.000")
    )
    source_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="SET NULL"), nullable=True
    )
    # ⚠️ False = hesaplayıcıdan ya da ödeme planından TÜRETİLMİŞ; bankanın
    # ilan ettiği bir taahhüt değildir. Karşılaştırmada ayrı işaretlenir.
    is_binding: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Oranın okunduğu ham metin parçası — jüriye ve kullanıcıya kanıt.
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    product: Mapped[Product] = relationship(back_populates="rates")
    source_document: Mapped[SourceDocument | None] = relationship()

    def __init__(self, **kwargs: Any) -> None:
        """Güven katsayısını verilmediyse oran kaynağından türetir.

        `rate_source` ile `confidence`'ın elle ayrı ayrı yazılması, ikisinin
        birbirinden kopmasına yol açıyordu (ör. `js_default` bir orana 1.0
        güven verilmesi). Varsayılan tek yerden, `RATE_SOURCE_CONFIDENCE`
        tablosundan gelir; gerekirse çağıran açıkça geçersiz kılabilir.
        """
        from app.core.vocab import rate_confidence

        if "confidence" not in kwargs and "rate_source" in kwargs:
            kwargs["confidence"] = rate_confidence(kwargs["rate_source"])
        if not kwargs.get("band_key"):
            kwargs["band_key"] = _band_key_from_kwargs(kwargs)
        super().__init__(**kwargs)


class ProductLimit(Base):
    """Tutar bandı × ayrım boyutu → finansman oranı ve azami vade matrisi.

    ⚠️ NEDEN AYRI TABLO. Bankaların çoğu finansman KÂR PAYI ORANINI
    yayımlamıyor (sektör normu; oran başvuruda veriliyor). Ama neredeyse
    hepsi şunu yayımlıyor: "konut değeri şu banttaysa değerin %X'i kadar,
    en fazla Y ay vadeyle finanse edilir."

    Bu, oran olmayan yerde karşılaştırmayı mümkün kılan tek veridir
    (şartname 5.7 — "En Uzun Vade", finansman oranı).

    ⚠️ `product_rates`'E YAZILAMAZ. Oran tablosunda `profit_rate_pct=NULL`
    olan satırlar birikirse "oran" tablosu oran içermeyen satırlarla dolar ve
    sıralama sorguları bunları elemek zorunda kalır. Ölçüldü: LTV matrisi
    oran tablosuna yazıldığında 253 satırın 105'i oransız kalıyordu.
    """

    __tablename__ = "product_limits"
    __table_args__ = (
        CheckConstraint(
            in_check("extraction_method", LIMIT_EXTRACTION_METHODS),
            name="limit_extraction_method_valid",
        ),
        CheckConstraint(in_check("currency", CURRENCIES), name="limit_currency_valid"),
        CheckConstraint(
            "asset_value_min IS NULL OR asset_value_max IS NULL "
            "OR asset_value_min <= asset_value_max",
            name="asset_value_range_valid",
        ),
        CheckConstraint(
            "financing_ratio_pct IS NULL "
            "OR (financing_ratio_pct >= 0 AND financing_ratio_pct <= 100)",
            name="financing_ratio_range_valid",
        ),
        CheckConstraint(
            "vehicle_age_min IS NULL OR vehicle_age_max IS NULL "
            "OR vehicle_age_min <= vehicle_age_max",
            name="limit_vehicle_age_range_valid",
        ),
        # ⚠️ Bant sınırları NULL olabildiği için (üst uç açık: "20 Milyon
        # Üzeri") doğrudan bileşik anahtar kullanılamaz; `band_key` NULL
        # güvenli kodlamadır — `product_rates` ile aynı desen.
        UniqueConstraint(
            "product_id",
            "band_key",
            "extraction_method",
            name="uq_product_limits_product_id_band_key_extraction_method",
        ),
        Index("ix_product_limits_product_id", "product_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    band_key: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # ── Varlık değeri bandı ───────────────────────────────
    # "Değer <= 5 Milyon TL" · "5 Milyon - 7 Milyon TL" · "20 Milyon Üzeri"
    asset_value_min: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    asset_value_max: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)

    # Varlık değerinin yüzde kaçı finanse edilir ("Değer x %70").
    financing_ratio_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    term_months_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    term_months_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amount_max: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)

    # ── Ayrım boyutları — hangisi geçerliyse dolar ────────
    # ⚠️ Enerji sınıfı kaynaktaki BİREBİR etikettir ("A-B", "A -B", "DİĞER").
    # Bankalar aynı sınıfı farklı yazıyor; normalize etmek kaynağı bozar.
    energy_class: Mapped[str | None] = mapped_column(Text, nullable=True)
    vehicle_age_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vehicle_age_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(Text, nullable=False, default="TRY")

    # ── Kaynak ────────────────────────────────────────────
    source_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Tablo satırının birebir metni — "Değer <= 5 Milyon TL | A-B | Değer x 90%"
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_method: Mapped[str] = mapped_column(Text, nullable=False, default="html_table")
    source_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="SET NULL"), nullable=True
    )
    fetched_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    product: Mapped[Product] = relationship(back_populates="limits")
    source_document: Mapped[SourceDocument | None] = relationship()
