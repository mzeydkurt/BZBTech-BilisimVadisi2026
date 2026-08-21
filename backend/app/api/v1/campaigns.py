"""Kampanya uçları."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Path, Query

from app.api.deps import DbSession
from app.db.models import Campaign
from app.schemas.campaign import (
    CampaignCategoryOut,
    CampaignDetail,
    CampaignListItem,
    LinkedProduct,
)
from app.schemas.common import Page
from app.schemas.compare import CampaignRankingRequest, CampaignRankingResponse
from app.services.campaign_service import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    CampaignFilters,
    get_campaign,
    list_campaigns,
)
from app.services.comparison_service import RankingError, rank_campaigns

router = APIRouter(prefix="/campaigns", tags=["kampanyalar"])


def _to_list_item(campaign: Campaign) -> CampaignListItem:
    """ORM kaydını liste şemasına dönüştürür."""
    return CampaignListItem(
        id=campaign.id,
        bank_code=campaign.bank.code,
        bank_name=campaign.bank.name,
        external_slug=campaign.external_slug,
        title=campaign.title,
        category=campaign.category,
        bank_category=campaign.bank_category,
        categories=[CampaignCategoryOut.model_validate(c) for c in campaign.categories],
        segment=campaign.segment,
        target_customer=campaign.target_customer,
        start_date=campaign.start_date,
        end_date=campaign.end_date,
        date_precision=campaign.date_precision,
        date_evidence_text=campaign.date_evidence_text,
        date_evidence_source=campaign.date_evidence_source,
        status=campaign.status,
        source_url=campaign.source_url,
        parent_campaign_id=campaign.parent_campaign_id,
        sub_campaign_count=len(campaign.sub_campaigns),
    )


@router.get("", response_model=Page[CampaignListItem], summary="Kampanya listesi")
def read_campaigns(
    session: DbSession,
    bank: Annotated[
        list[str] | None, Query(description="Banka kodu (birden fazla verilebilir)")
    ] = None,
    category: Annotated[str | None, Query()] = None,
    segment: Annotated[str | None, Query()] = None,
    target_customer: Annotated[str | None, Query()] = None,
    status: Annotated[Literal["active", "upcoming", "expired", "unknown"] | None, Query()] = None,
    sector: Annotated[str | None, Query(description="Taksonomi: harcama sektörü")] = None,
    product_type: Annotated[str | None, Query(description="Taksonomi: ürün türü")] = None,
    audience: Annotated[str | None, Query(description="Taksonomi: hedef kitle")] = None,
    benefit: Annotated[str | None, Query(description="Taksonomi: fayda türü")] = None,
    q: Annotated[str | None, Query(description="Başlık ve açıklamada arama")] = None,
    start_after: Annotated[date | None, Query()] = None,
    end_before: Annotated[date | None, Query()] = None,
    sort: Annotated[Literal["title", "start_date", "end_date", "bank"], Query()] = "title",
    order: Annotated[Literal["asc", "desc"], Query()] = "asc",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    include_children: Annotated[
        bool, Query(description="Alt kampanyaları da listele (varsayılan: yalnızca kökler)")
    ] = False,
    include_expired: Annotated[
        bool,
        Query(
            description=(
                "Süresi kesin olarak dolmuş kampanyaları da listele "
                "(varsayılan: gizli — tarihi belirsiz olanlar bundan etkilenmez)"
            )
        ),
    ] = False,
) -> Page[CampaignListItem]:
    """Filtrelenmiş ve sayfalanmış kampanya listesi döndürür.

    ⚠️ Filtreye uyan kayıt yoksa bu bir HATA DEĞİLDİR: HTTP 200 ve boş `items`
    döner. Arayüz bu durumu "sonuç yok" olarak gösterir; "veri alınamadı"
    mesajı yalnızca 4xx/5xx yanıtlarında gösterilmelidir.
    """
    filters = CampaignFilters(
        banks=bank or [],
        category=category,
        segment=segment,
        target_customer=target_customer,
        status=status,
        sector=sector,
        product_type=product_type,
        audience=audience,
        benefit=benefit,
        q=q,
        start_after=start_after,
        end_before=end_before,
        sort=sort,
        order=order,
        page=page,
        page_size=page_size,
        include_children=include_children,
        include_expired=include_expired,
    )

    campaigns, total = list_campaigns(session, filters)
    items = [_to_list_item(campaign) for campaign in campaigns]
    return Page.create(items=items, total=total, page=page, page_size=page_size)


@router.post("/compare", response_model=CampaignRankingResponse, summary="Kampanya sıralama")
def compare_campaigns(req: CampaignRankingRequest, session: DbSession) -> CampaignRankingResponse:
    """Kampanyaları tek bir açık ölçüte göre sıralar (şartname §5.7).

    ⚠️ Yol `/{campaign_id}`'DEN ÖNCE tanımlıdır; sonra gelirse "compare"
    bir kampanya kimliği sanılır ve 422 döner.

    ⚠️ "En Yüksek Ödül Miktarı" ölçütü burada karşılanır, ürün sıralamasında
    değil: ödül tutarı üründe değil KAMPANYADA bulunur.
    """
    try:
        return rank_campaigns(
            session,
            criterion=req.criterion,
            bank_codes=req.bank_codes,
            product_type=req.product_type,
            only_active=req.only_active,
            limit=req.limit,
        )
    except RankingError as hata:
        raise HTTPException(status_code=422, detail=str(hata)) from hata


@router.get("/{campaign_id}", response_model=CampaignDetail, summary="Kampanya detayı")
def read_campaign(
    session: DbSession,
    campaign_id: int = Path(description="Kampanya kimliği"),
) -> CampaignDetail:
    """Kampanya detayını banka ve kaynak doküman özetiyle birlikte döndürür.

    Kaynak doküman bilgisi izlenebilirlik içindir: verinin hangi adresten,
    ne zaman ve hangi scraper sürümüyle alındığı görülebilir.
    """
    campaign = get_campaign(session, campaign_id)

    return CampaignDetail(
        **_to_list_item(campaign).model_dump(),
        description=campaign.description,
        conditions_text=campaign.conditions_text,
        exclusions_text=campaign.exclusions_text,
        participation_method=campaign.participation_method,
        participation_channel=campaign.participation_channel,
        sms_keyword=campaign.sms_keyword,
        sms_number=campaign.sms_number,
        coupon_code=campaign.coupon_code,
        is_archived=campaign.is_archived,
        first_seen_at=campaign.first_seen_at,
        last_seen_at=campaign.last_seen_at,
        bank=campaign.bank,  # type: ignore[arg-type]
        source_document=campaign.source_document,  # type: ignore[arg-type]
        sub_campaigns=[_to_list_item(alt) for alt in campaign.sub_campaigns],
        products=[
            LinkedProduct(
                product_id=bag.product_id,
                product_name=bag.product.name,
                product_type=bag.product.product_type,
                variant_label=bag.product.variant_label,
                match_method=bag.match_method,
                confidence=bag.confidence,
                evidence=bag.evidence,
            )
            for bag in campaign.product_links
        ],
    )
