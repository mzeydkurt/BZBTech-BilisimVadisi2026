"""Ürün sıralama servisi (SPRINT2.5 §8.3).

⚠️ `rate_type` ZORUNLUDUR. Finansman maliyeti ile katılma getirisi aynı
sütunda durur ama biri gider biri gelirdir; karıştıkları anda "en iyi banka"
sonucu tesadüfe döner.

⚠️ Ölçütün alanı boş olan ürün SIRALANMAZ. `without_data` grubunda nedeniyle
döner. NULL'u sıfır sayıp "en düşük kâr payı" ilan etmek yanlıştır.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.vocab import RATE_TYPE_COMPARABLE_FIELD
from app.db.models.bank import Bank
from app.db.models.campaign import Campaign
from app.db.models.campaign_category import CampaignCategory
from app.db.models.campaign_metric import CampaignMetric
from app.db.models.product import Product, ProductRate
from app.db.models.source_document import SourceDocument
from app.schemas.compare import (
    CAMPAIGN_CRITERIA,
    CRITERIA,
    CampaignRankingResponse,
    ProductRankingResponse,
    RankedCampaign,
    RankedProduct,
    RankingWeights,
)

_YUZDE = Decimal("100")

# Ölçütün insan okuyabilir adı; `winner_reason` bundan üretilir.
_OLCUT_ADI: dict[str, str] = {
    "en_dusuk_kar_payi": "en düşük kâr payı oranı",
    "en_dusuk_masraf": "en düşük tahsis ücreti",
    "en_dusuk_toplam_maliyet": "en düşük yıllık toplam maliyet",
    "en_yuksek_getiri": "en yüksek katılma hesabı getirisi",
    "en_yuksek_paylasim_orani": "en yüksek katılımcı payı",
    "en_uzun_vade": "en uzun vade",
    "en_avantajli": "ağırlıklı toplam skor",
}

_ALAN_BIRIMI: dict[str, str] = {
    "profit_rate_pct": "%",
    "allocation_fee_pct": "%",
    "annual_cost_pct": "%",
    "investor_share_pct": "%",
    "term_months": " ay",
}


class RankingError(ValueError):
    """Sıralama isteği geçersiz olduğunda yükseltilir."""


def _dogrula(rate_type: str, criterion: str) -> tuple[str, bool]:
    """İstenen ölçütün oran türüyle bağdaştığını doğrular.

    Returns:
        (sıralanacak alan, azalan mı) ikilisi.

    Raises:
        RankingError: Oran türü ya da ölçüt geçersizse, veya ölçüt bu oran
            türünde anlamsızsa.

    """
    # ⚠️ `RATE_TYPES` (depolama sözlüğü) değil `RATE_TYPE_COMPARABLE_FIELD`
    # (sıralamaya girebilen alt küme) ile doğrulanır. `interest_free_benevolent_loan`
    # (karz-ı hasen/eğitim finansmanı) `RATE_TYPES`'ta vardır ama bilinçli olarak
    # burada YOKTUR — vade farksız ürünler hiçbir ölçütte sıralamaya giremez.
    if rate_type not in RATE_TYPE_COMPARABLE_FIELD:
        raise RankingError(
            f"Geçersiz rate_type: {rate_type!r}. Geçerli değerler: "
            f"{', '.join(RATE_TYPE_COMPARABLE_FIELD)}"
        )
    if criterion not in CRITERIA:
        raise RankingError(
            f"Geçersiz criterion: {criterion!r}. Geçerli değerler: {', '.join(CRITERIA)}"
        )

    alan, azalan, gerekli_tur = CRITERIA[criterion]
    if gerekli_tur is not None and gerekli_tur != rate_type:
        raise RankingError(
            f"{criterion!r} ölçütü yalnızca {gerekli_tur!r} oranlarında anlamlıdır; "
            f"{rate_type!r} istendi. Farklı oran türleri aynı sıralamaya giremez."
        )
    return alan, azalan


def _normalize(
    deger: Decimal, en_dusuk: Decimal, en_yuksek: Decimal, *, yuksek_iyi: bool
) -> Decimal:
    """Değeri 0-100 aralığına taşır.

    Tek satır varsa aralık sıfırdır; o satıra tam puan verilir — göreli
    sıralamada tek aday zaten birincidir.
    """
    if en_yuksek == en_dusuk:
        return _YUZDE
    oran = (deger - en_dusuk) / (en_yuksek - en_dusuk) * _YUZDE
    return oran if yuksek_iyi else _YUZDE - oran


def _agirlikli_skor(
    satirlar: list[RankedProduct], agirliklar: RankingWeights
) -> dict[int, Decimal]:
    """Çok ölçütlü ağırlıklı skoru hesaplar.

    ⚠️ Bir bileşenin verisi yoksa o bileşen ağırlığıyla birlikte paydadan da
    düşer. Aksi hâlde masraf verisi olmayan ürün, masrafı sıfırmış gibi
    davranıp haksız avantaj kazanır.
    """
    bilesenler: tuple[tuple[str, Decimal, bool], ...] = (
        ("profit_rate_pct", agirliklar.rate_weight, False),
        ("allocation_fee_pct", agirliklar.fee_weight, False),
        ("term_months", agirliklar.term_weight, True),
    )

    skorlar: dict[int, Decimal] = {}
    paydalar: dict[int, Decimal] = {}

    for alan, agirlik, yuksek_iyi in bilesenler:
        if agirlik <= 0:
            continue
        degerli = [(s, getattr(s, alan)) for s in satirlar if getattr(s, alan) is not None]
        if not degerli:
            continue

        sayilar = [Decimal(str(d)) for _, d in degerli]
        alt, ust = min(sayilar), max(sayilar)
        for satir, ham in degerli:
            puan = _normalize(Decimal(str(ham)), alt, ust, yuksek_iyi=yuksek_iyi)
            skorlar[satir.product_id] = skorlar.get(satir.product_id, Decimal(0)) + puan * agirlik
            paydalar[satir.product_id] = paydalar.get(satir.product_id, Decimal(0)) + agirlik

    return {
        pid: (toplam / paydalar[pid]).quantize(Decimal("0.01"))
        for pid, toplam in skorlar.items()
        if paydalar.get(pid, Decimal(0)) > 0
    }


def rank_products(
    session: Session,
    *,
    rate_type: str,
    criterion: str,
    product_type: str | None = None,
    bank_codes: list[str] | None = None,
    term_months: int | None = None,
    term_days: int | None = None,
    currency: str = "TRY",
    amount_try: Decimal | None = None,
    weights: RankingWeights | None = None,
    limit: int = 20,
) -> ProductRankingResponse:
    """Ürünleri tek bir açık ölçüte göre sıralar.

    Args:
        session: Veritabanı oturumu.
        rate_type: ZORUNLU oran türü.
        criterion: `CRITERIA` içinden bir ölçüt.
        product_type: Ürün türü süzgeci.
        bank_codes: Yalnızca bu banka kodları.
        term_months: Vade süzgeci (ay).
        term_days: Vade süzgeci (gün); oranın gün aralığına düşmesi aranır.
        currency: Para birimi süzgeci.
        amount_try: Tutar; oranın bandına düşmesi aranır.
        weights: `en_avantajli` ölçütünün ağırlıkları.
        limit: Döndürülecek sıralı satır sayısı.

    Returns:
        Sıralı liste ve ayrıca sıralanamayan "veri yok" grubu.

    Raises:
        RankingError: Ölçüt oran türüyle bağdaşmıyorsa.

    """
    alan, azalan = _dogrula(rate_type, criterion)
    agirliklar = weights or RankingWeights()

    stmt = (
        select(ProductRate, Product, Bank)
        .join(Product, ProductRate.product_id == Product.id)
        .join(Bank, Product.bank_id == Bank.id)
        .where(ProductRate.rate_type == rate_type, ProductRate.currency == currency)
    )
    if product_type:
        stmt = stmt.where(Product.product_type == product_type)
    if bank_codes:
        stmt = stmt.where(Bank.code.in_(bank_codes))
    if term_months is not None:
        stmt = stmt.where(ProductRate.term_months == term_months)
    if term_days is not None:
        stmt = stmt.where(
            (ProductRate.term_days_min.is_(None)) | (ProductRate.term_days_min <= term_days),
            (ProductRate.term_days_max.is_(None)) | (ProductRate.term_days_max >= term_days),
        )
    if amount_try is not None:
        stmt = stmt.where(
            (ProductRate.amount_min.is_(None)) | (ProductRate.amount_min <= amount_try),
            (ProductRate.amount_max.is_(None)) | (ProductRate.amount_max >= amount_try),
        )

    kaynaklar: dict[int, str] = {}
    satirlar: list[RankedProduct] = []
    for oran, urun, banka in session.execute(stmt).all():
        if urun.source_document_id and urun.source_document_id not in kaynaklar:
            belge = session.get(SourceDocument, urun.source_document_id)
            if belge:
                kaynaklar[urun.source_document_id] = belge.url
        satirlar.append(
            RankedProduct(
                product_id=urun.id,
                product_name=urun.name,
                bank_code=banka.code,
                bank_name=banka.name,
                product_type=urun.product_type,
                rate_type=oran.rate_type,
                profit_rate_pct=oran.profit_rate_pct,
                allocation_fee_pct=oran.allocation_fee_pct,
                annual_cost_pct=oran.annual_cost_pct,
                investor_share_pct=oran.investor_share_pct,
                bank_share_pct=oran.bank_share_pct,
                term_months=oran.term_months,
                term_label=oran.term_label,
                currency=oran.currency,
                evidence_text=oran.evidence_text,
                source_url=kaynaklar.get(urun.source_document_id or -1),
            )
        )

    if criterion == "en_avantajli":
        skorlar = _agirlikli_skor(satirlar, agirliklar)
        for s in satirlar:
            s.score = skorlar.get(s.product_id)
        sirali = [s for s in satirlar if s.score is not None]
        veri_yok = [s for s in satirlar if s.score is None]
        for s in veri_yok:
            s.missing_reason = "Ağırlıklı skorun hiçbir bileşeninde veri yok"
        sirali.sort(key=lambda s: s.score or Decimal(0), reverse=True)
    else:
        sirali = [s for s in satirlar if getattr(s, alan) is not None]
        veri_yok = [s for s in satirlar if getattr(s, alan) is None]
        for s in veri_yok:
            s.missing_reason = f"{alan} alanı bu üründe yayımlanmamış"
        sirali.sort(key=lambda s: Decimal(str(getattr(s, alan))), reverse=azalan)

    for i, s in enumerate(sirali, start=1):
        s.rank = i
    sirali = sirali[:limit]

    kazanan = sirali[0] if sirali else None
    gerekce: str | None = None
    if kazanan is not None:
        if criterion == "en_avantajli":
            gerekce = (
                f"{kazanan.bank_name} — ağırlıklı skor {kazanan.score} "
                f"(oran %{agirliklar.rate_weight}, masraf %{agirliklar.fee_weight}, "
                f"vade %{agirliklar.term_weight} ağırlıkla)"
            )
        else:
            deger = getattr(kazanan, alan)
            birim = _ALAN_BIRIMI.get(alan, "")
            onek = "%" if birim == "%" else ""
            sonek = birim if birim != "%" else ""
            gerekce = f"{kazanan.bank_name} — {_OLCUT_ADI[criterion]}: {onek}{deger}{sonek}"

    return ProductRankingResponse(
        rate_type=rate_type,
        criterion=criterion,
        sort_field=alan,
        descending=azalan,
        winner=kazanan,
        winner_reason=gerekce,
        ranked=sirali,
        without_data=veri_yok,
        note=(
            f"{len(sirali)} ürün sıralandı, {len(veri_yok)} ürün ölçütün alanı boş "
            f"olduğu için sıralamaya alınmadı. Oranlar bankaların kendi yayımladığı "
            f"tablolardan okundu; her satırın kanıt metni ve kaynak sayfası yanıttadır."
        ),
    )


# ── Kampanya sıralama (§5.7) ──────────────────────────────

_KAMPANYA_OLCUT_ADI: dict[str, str] = {
    "en_yuksek_odul": "en yüksek ödül miktarı",
    "en_dusuk_kar_payi": "en düşük kâr payı oranı",
    "en_uzun_vade": "en uzun vade",
    "en_yuksek_taksit": "en yüksek taksit sayısı",
    "en_yuksek_iade_orani": "en yüksek nakit iade oranı",
    "en_yuksek_indirim": "en yüksek indirim oranı",
}


def rank_campaigns(
    session: Session,
    *,
    criterion: str,
    bank_codes: list[str] | None = None,
    product_type: str | None = None,
    only_active: bool = True,
    limit: int = 20,
) -> CampaignRankingResponse:
    """Kampanyaları tek bir açık ölçüte göre sıralar (§5.7).

    ⚠️ Ödül tutarı ÜRÜNDE DEĞİL KAMPANYADADIR: bir bankanın "Taşıt
    Finansmanı" ürününün ödülü olmaz, o ürünü konu alan kampanyanın olur.
    Bu yüzden "En Yüksek Ödül Miktarı" ölçütü ürün sıralamasında değil
    burada karşılanır.

    ⚠️ Ölçütün alanı boş olan kampanya SIRALANMAZ; `without_data` grubunda
    nedeniyle döner. NULL'u sıfır saymak "ödülsüz kampanya" ile "ödülü
    yayımlanmamış kampanya"yı aynı kefeye koyar.

    Args:
        session: Veritabanı oturumu.
        criterion: `CAMPAIGN_CRITERIA` içinden bir ölçüt.
        bank_codes: Yalnızca bu banka kodları.
        product_type: Kampanya türü süzgeci (`campaign_categories`).
        only_active: Yalnızca yürürlükteki kampanyalar.
        limit: Döndürülecek sıralı satır sayısı.

    Returns:
        Sıralı liste ve sıralanamayan "veri yok" grubu.

    Raises:
        RankingError: Ölçüt tanımsızsa.

    """
    if criterion not in CAMPAIGN_CRITERIA:
        raise RankingError(
            f"Geçersiz criterion: {criterion!r}. Geçerli değerler: {', '.join(CAMPAIGN_CRITERIA)}"
        )
    alan, azalan = CAMPAIGN_CRITERIA[criterion]

    stmt = (
        select(Campaign, CampaignMetric, Bank)
        .join(Bank, Bank.id == Campaign.bank_id)
        .outerjoin(CampaignMetric, CampaignMetric.campaign_id == Campaign.id)
        .where(Campaign.parent_campaign_id.is_(None))
    )
    if only_active:
        stmt = stmt.where(Campaign.status == "active")
    if bank_codes:
        stmt = stmt.where(Bank.code.in_(bank_codes))
    if product_type:
        stmt = stmt.where(
            Campaign.id.in_(
                select(CampaignCategory.campaign_id).where(
                    CampaignCategory.axis == "product_type",
                    CampaignCategory.value == product_type,
                )
            )
        )

    satirlar: list[RankedCampaign] = []
    for kampanya, olcum, banka in session.execute(stmt).all():
        satirlar.append(
            RankedCampaign(
                campaign_id=kampanya.id,
                title=kampanya.title,
                bank_code=banka.code,
                bank_name=banka.name,
                status=kampanya.status,
                reward_amount_try=getattr(olcum, "reward_amount_try", None),
                reward_type=getattr(olcum, "reward_type", None),
                profit_rate_pct=getattr(olcum, "profit_rate_pct", None),
                term_months_max=getattr(olcum, "term_months_max", None),
                installment_count=getattr(olcum, "installment_count", None),
                cashback_pct=getattr(olcum, "cashback_pct", None),
                discount_pct=getattr(olcum, "discount_pct", None),
                min_spend_try=getattr(olcum, "min_spend_try", None),
                has_no_fee=getattr(olcum, "has_no_fee", None),
                end_date=kampanya.end_date,
                source_url=kampanya.source_url,
            )
        )

    sirali = [s for s in satirlar if getattr(s, alan) is not None]
    veri_yok = [s for s in satirlar if getattr(s, alan) is None]
    for s in veri_yok:
        s.missing_reason = f"{alan} bu kampanyanın metninden çıkarılamadı"
    sirali.sort(key=lambda s: Decimal(str(getattr(s, alan))), reverse=azalan)

    for i, s in enumerate(sirali, start=1):
        s.rank = i
    sirali = sirali[:limit]

    kazanan = sirali[0] if sirali else None
    gerekce = (
        f"{kazanan.bank_name} — {_KAMPANYA_OLCUT_ADI[criterion]}: {getattr(kazanan, alan)}"
        if kazanan
        else None
    )

    return CampaignRankingResponse(
        criterion=criterion,
        sort_field=alan,
        descending=azalan,
        winner=kazanan,
        winner_reason=gerekce,
        ranked=sirali,
        without_data=veri_yok[:limit],
        note=(
            f"{len(sirali)} kampanya sıralandı, {len(veri_yok)} kampanyada ölçütün "
            f"alanı metinden çıkarılamadı. Değerler kampanya metinlerinden "
            f"kanıtla çıkarılmıştır."
        ),
    )
