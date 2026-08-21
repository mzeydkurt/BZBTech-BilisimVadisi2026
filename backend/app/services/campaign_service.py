"""Kampanya iş mantığı: durum hesabı, filtreleme ve sayfalama.

⚠️ `compute_status` TEK DOĞRULUK KAYNAĞIDIR. Kampanya durumu YALNIZCA burada
hesaplanır; frontend bu hesabı asla tekrar etmez. Aksi hâlde iki taraf farklı
sonuç üretir ve kullanıcıya çelişkili bilgi gösterilir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Final
from zoneinfo import ZoneInfo

from sqlalchemy import Select, func, nulls_last, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.exceptions import NotFoundError
from app.db.models import Bank, Campaign, CampaignCategory, CampaignProduct

# Kampanya tarihleri Türkiye yerel takvimine göre değerlendirilir: bir kampanya
# "31.12.2026'ya kadar" ise Türkiye'de 31 Aralık boyunca geçerlidir.
ISTANBUL_TZ: Final[ZoneInfo] = ZoneInfo("Europe/Istanbul")


def today_tr() -> date:
    """Türkiye saatine göre bugünün tarihini döndürür."""
    return datetime.now(ISTANBUL_TZ).date()


def compute_status(
    start_date: date | None,
    end_date: date | None,
    today: date | None = None,
) -> str:
    """Kampanya durumunu tarihlerden hesaplar.

    Kurallar:
        bitiş < bugün                 -> "expired"
        başlangıç > bugün             -> "upcoming"
        başlangıç <= bugün <= bitiş   -> "active"
        tarih bilgisi yok             -> "unknown"

    `unknown` ile `expired` bilinçli olarak AYRI tutulur: tarihi bulunmayan bir
    kampanyayı "süresi dolmuş" göstermek yanlış bilgi olurdu. Türkiye Finans'ın
    hiçbir kampanyasında yapısal tarih alanı bulunmuyor.

    Args:
        start_date: Kampanya başlangıcı (bilinmiyorsa None).
        end_date: Kampanya bitişi (bilinmiyorsa None).
        today: Karşılaştırma tarihi; verilmezse Türkiye saatiyle bugün.

    Returns:
        "active", "upcoming", "expired" veya "unknown".
    """
    reference = today if today is not None else today_tr()

    if start_date is None and end_date is None:
        return "unknown"

    if end_date is not None and end_date < reference:
        return "expired"

    if start_date is not None and start_date > reference:
        return "upcoming"

    # Buraya gelindiğinde kampanya süresi devam ediyor demektir:
    # bitiş yoksa veya bugünden sonraysa ve başlangıç yoksa veya geçmişteyse.
    return "active"


# ── Filtreleme ve sayfalama ───────────────────────────────

# Sıralanabilir kolonlar. Serbest metin kabul edilmez: kullanıcı girdisinin
# doğrudan ORDER BY'a geçmesi engellenir.
SORTABLE_FIELDS: Final[tuple[str, ...]] = ("title", "start_date", "end_date", "bank")

DEFAULT_PAGE_SIZE: Final[int] = 25
MAX_PAGE_SIZE: Final[int] = 100


@dataclass
class CampaignFilters:
    """`GET /campaigns` sorgu parametreleri."""

    banks: list[str] = field(default_factory=list)
    category: str | None = None
    segment: str | None = None
    target_customer: str | None = None
    status: str | None = None
    # Taksonomi süzgeci: `sector=market_gida` gibi. Eksen adı → değer.
    # Birden fazla eksen verilirse hepsini birden sağlayan kampanyalar döner.
    sector: str | None = None
    product_type: str | None = None
    audience: str | None = None
    benefit: str | None = None
    q: str | None = None
    start_after: date | None = None
    end_before: date | None = None
    sort: str = "title"
    order: str = "asc"
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE
    # Alt kampanyalar varsayılan olarak listelenmez: bir banka üç finansmanı
    # tek sayfada, öteki üç ayrı sayfada yayımlıyor. Kök sayımı olmadan
    # bankalar arası karşılaştırma yanlış olur.
    include_children: bool = False
    # KATİP KAPI 5 — kullanıcının isteği: "kampanyanın tarihi kesin olarak
    # dolmuşsa dashboard'da göstermesin, tarihi belirsizse göstersin."
    # `unknown` ile `expired` AYRI durumlardır (bkz. `compute_status`); bu
    # bayrak yalnızca `expired`'ı etkiler, tarihi bilinmeyen kampanyalar bu
    # bayraktan bağımsız her zaman görünür kalır. `comparison_service.rank_campaigns`'daki
    # `only_active: bool = True` deseninin aynısı — sadece ismi ve mantığı
    # tersine çevrilmiş (burada "veri kaybı yok, sadece görünürlük" ilkesi
    # gereği varsayılan dışlama gizli, açık `status` isteğiyle bypass edilebilir).
    include_expired: bool = False


def _apply_filters(
    statement: Select[tuple[Campaign]], filters: CampaignFilters
) -> Select[tuple[Campaign]]:
    """Sorguya filtreleri uygular."""
    if not filters.include_children:
        statement = statement.where(Campaign.parent_campaign_id.is_(None))
    if filters.banks:
        statement = statement.where(Bank.code.in_(filters.banks))
    if filters.category:
        statement = statement.where(Campaign.category == filters.category)
    if filters.segment:
        statement = statement.where(Campaign.segment == filters.segment)
    if filters.target_customer:
        statement = statement.where(Campaign.target_customer == filters.target_customer)
    if filters.status:
        # Açık bir durum isteği (ör. `status=expired`) bu bayraktan bağımsız
        # her zaman çalışır — kullanıcı "kesin olarak dolmuşları görmek
        # istemiyorum" derken, jüri demosunda "sistem süresi dolmuşu biliyor
        # ama filtreliyor" göstermek için `status=expired` isteğini
        # engellemek istemez.
        statement = statement.where(Campaign.status == filters.status)
    elif not filters.include_expired:
        statement = statement.where(Campaign.status != "expired")
    if filters.q:
        # LIKE tabanlı basit arama. Türkçe büyük/küçük harf katlaması ve kök
        # bulma FTS5 ile PART 2'de gelecek (§9).
        pattern = f"%{filters.q.strip()}%"
        statement = statement.where(
            or_(Campaign.title.ilike(pattern), Campaign.description.ilike(pattern))
        )
    if filters.start_after:
        statement = statement.where(Campaign.start_date >= filters.start_after)
    if filters.end_before:
        statement = statement.where(Campaign.end_date <= filters.end_before)

    # Taksonomi süzgeçleri. Her eksen AYRI bir alt sorgudur: bir kampanya
    # hem `sector=market_gida` hem `benefit=taksit` etiketini taşıyabilir ve
    # ikisi de aranıyorsa İKİSİNİ BİRDEN sağlaması gerekir. Tek JOIN ile
    # yazılsaydı aynı satırda iki farklı etiket aranır ve sonuç daima boş
    # dönerdi.
    for eksen, deger in (
        ("sector", filters.sector),
        ("product_type", filters.product_type),
        ("audience", filters.audience),
        ("benefit", filters.benefit),
    ):
        if not deger:
            continue
        statement = statement.where(
            select(CampaignCategory.id)
            .where(
                CampaignCategory.campaign_id == Campaign.id,
                CampaignCategory.axis == eksen,
                CampaignCategory.value == deger,
            )
            .exists()
        )

    return statement


def _apply_sort(
    statement: Select[tuple[Campaign]], filters: CampaignFilters
) -> Select[tuple[Campaign]]:
    """Sorguya sıralamayı uygular.

    Tarih kolonlarında NULL değerler SONA alınır: tarihi bilinmeyen kampanyaların
    listenin başında görünmesi kullanıcıyı yanıltırdı.
    """
    sort_field = filters.sort if filters.sort in SORTABLE_FIELDS else "title"
    descending = filters.order.lower() == "desc"

    column = {
        "title": Campaign.title,
        "start_date": Campaign.start_date,
        "end_date": Campaign.end_date,
        "bank": Bank.name,
    }[sort_field]

    ordering = column.desc() if descending else column.asc()
    if sort_field in ("start_date", "end_date"):
        ordering = nulls_last(ordering)

    # İkincil sıralama kararlılığı sağlar: aynı değerli satırlar sayfalar
    # arasında yer değiştirmez.
    return statement.order_by(ordering, Campaign.id.asc())


def list_campaigns(session: Session, filters: CampaignFilters) -> tuple[list[Campaign], int]:
    """Filtreli ve sayfalı kampanya listesi döndürür.

    Args:
        session: Veritabanı oturumu.
        filters: Sorgu parametreleri.

    Returns:
        (kampanyalar, filtreye_uyan_toplam) ikilisi.
    """
    page = max(1, filters.page)
    page_size = min(max(1, filters.page_size), MAX_PAGE_SIZE)

    base = select(Campaign).join(Bank, Campaign.bank_id == Bank.id)
    base = _apply_filters(base, filters)

    count_statement = select(func.count()).select_from(base.subquery())
    total = session.scalar(count_statement) or 0

    statement = _apply_sort(base, filters).options(
        joinedload(Campaign.bank),
        # Taksonomi etiketleri listede de gösteriliyor; N+1 sorgu olmasın.
        selectinload(Campaign.categories),
        selectinload(Campaign.sub_campaigns).joinedload(Campaign.bank),
    )
    statement = statement.offset((page - 1) * page_size).limit(page_size)

    campaigns = list(session.scalars(statement).unique().all())
    return campaigns, total


def get_campaign(session: Session, campaign_id: int) -> Campaign:
    """Tek bir kampanyayı banka ve kaynak dokümanıyla birlikte döndürür.

    Args:
        session: Veritabanı oturumu.
        campaign_id: Kampanya kimliği.

    Returns:
        Kampanya kaydı.

    Raises:
        NotFoundError: Kampanya bulunamazsa.
    """
    campaign = session.scalar(
        select(Campaign)
        .where(Campaign.id == campaign_id)
        .options(
            joinedload(Campaign.bank),
            joinedload(Campaign.source_document),
            selectinload(Campaign.categories),
            selectinload(Campaign.sub_campaigns).joinedload(Campaign.bank),
            # Bağlı ürünler detayda gösteriliyor; N+1 sorgu olmasın.
            selectinload(Campaign.product_links).joinedload(CampaignProduct.product),
        )
    )
    if campaign is None:
        raise NotFoundError(f"Kampanya bulunamadı: {campaign_id}")
    return campaign
