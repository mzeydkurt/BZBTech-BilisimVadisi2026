"""Finansman simülatörü, katılma hesabı getiri ve BDDK limit denetim servisleri."""

from __future__ import annotations

from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.bank import Bank
from app.db.models.product import Product, ProductLimit, ProductRate
from app.schemas.simulator import (
    BDDKLimitCheckRequest,
    BDDKLimitCheckResponse,
    BankFinancingOffer,
    BankYieldOffer,
    FinancingSimulationRequest,
    FinancingSimulationResponse,
    ParticipationYieldRequest,
    ParticipationYieldResponse,
)


def calculate_financing_simulation(
    session: Session, req: FinancingSimulationRequest
) -> FinancingSimulationResponse:
    """Tutar ve vadeye göre 10 katılım bankasının finansman taksit tekliflerini hesaplar.

    Formül (Annüite Taksit):
    Taksit = P * (r * (1+r)^n) / ((1+r)^n - 1)
    P: Anapara (TL), r: Aylık Oran (% / 100), n: Vade (Ay)
    """
    bankalar = list(session.scalars(select(Bank).order_by(Bank.code)))
    offers: list[BankFinancingOffer] = []

    tutar_float = float(req.amount_try)
    vade = req.term_months

    for banka in bankalar:
        # Bankaya ait ilgili ürünün en güncel oranını çek
        rate_obj = session.scalar(
            select(ProductRate)
            .join(Product, ProductRate.product_id == Product.id)
            .where(
                Product.bank_id == banka.id,
                ProductRate.rate_type == "financing_rate",
                ProductRate.profit_rate_pct.is_not(None),
            )
            .order_by(ProductRate.id.desc())
        )

        # Varsayılan veya veritabanından alınan aylık oran (%)
        oran_pct = float(rate_obj.profit_rate_pct) if rate_obj and rate_obj.profit_rate_pct is not None else 3.85

        r = oran_pct / 100.0
        if r > 0:
            aylik_taksit = tutar_float * (r * ((1 + r) ** vade)) / (((1 + r) ** vade) - 1)
        else:
            aylik_taksit = tutar_float / vade

        toplam_geri_odeme = aylik_taksit * vade
        toplam_kar_payi = toplam_geri_odeme - tutar_float

        offers.append(
            BankFinancingOffer(
                bank_code=banka.code,
                bank_name=banka.name,
                profit_rate_pct=round(oran_pct, 2),
                monthly_payment_try=round(aylik_taksit, 2),
                total_profit_try=round(toplam_kar_payi, 2),
                total_payment_try=round(toplam_geri_odeme, 2),
                is_best_offer=False,
            )
        )

    # En düşük maliyetli teklifi seç
    if offers:
        best_offer = min(offers, key=lambda x: x.total_payment_try)
        best_offer.is_best_offer = True
        best_code = best_offer.bank_code
    else:
        best_code = None

    return FinancingSimulationResponse(
        amount_try=tutar_float,
        term_months=vade,
        product_type=req.product_type,
        best_bank_code=best_code,
        offers=offers,
    )


def calculate_participation_yield(
    session: Session, req: ParticipationYieldRequest
) -> ParticipationYieldResponse:
    """Katılma hesabı kâr paylaşımı getirisini hesaplar."""
    bankalar = list(session.scalars(select(Bank).order_by(Bank.code)))
    offers: list[BankYieldOffer] = []
    yatirim_float = float(req.deposit_try)
    gun = req.term_days

    for banka in bankalar:
        # Bankanın kâr paylaşım oranını çek
        rate_obj = session.scalar(
            select(ProductRate)
            .join(Product, ProductRate.product_id == Product.id)
            .where(
                Product.bank_id == banka.id,
                ProductRate.rate_type == "profit_sharing_ratio",
                ProductRate.investor_share_pct.is_not(None),
            )
            .order_by(ProductRate.id.desc())
        )

        musteri_payi = float(rate_obj.investor_share_pct) if rate_obj and rate_obj.investor_share_pct is not None else 85.0
        banka_payi = 100.0 - musteri_payi

        # Tahmini yıllık brüt getiri
        yillik_brut_pct = 42.5
        brut_kar = yatirim_float * (yillik_brut_pct / 100.0) * (gun / 365.0) * (musteri_payi / 100.0)
        net_kar = brut_kar * 0.925  # %7.5 stopaj kesintisi

        offers.append(
            BankYieldOffer(
                bank_code=banka.code,
                bank_name=banka.name,
                investor_share_pct=round(musteri_payi, 1),
                bank_share_pct=round(banka_payi, 1),
                annual_yield_gross_pct=yillik_brut_pct,
                estimated_gross_profit_try=round(brut_kar, 2),
                estimated_net_profit_try=round(net_kar, 2),
                is_best_yield=False,
            )
        )

    if offers:
        best_yield = max(offers, key=lambda x: x.estimated_net_profit_try)
        best_yield.is_best_yield = True
        best_code = best_yield.bank_code
    else:
        best_code = None

    return ParticipationYieldResponse(
        deposit_try=yatirim_float,
        term_days=gun,
        currency=req.currency,
        best_yield_bank_code=best_code,
        offers=offers,
    )


def check_bddk_limits(req: BDDKLimitCheckRequest) -> BDDKLimitCheckResponse:
    """BDDK mevzuat üst sınırlarına göre azami finansman ve vade hesabı yapar."""
    deger = float(req.asset_value_try)

    if req.asset_type == "tasit":
        if deger <= 400_000:
            oran = 70.0
            vade = 48
        elif deger <= 800_000:
            oran = 50.0
            vade = 36
        elif deger <= 1_200_000:
            oran = 30.0
            vade = 24
        elif deger <= 2_000_000:
            oran = 20.0
            vade = 12
        else:
            oran = 0.0
            vade = 0
        dayanak = "BDDK 21.02.2022 tarihli 10099 sayılı Taşıt Kredileri Kararı"
    else:
        # Konut LTV hesabı
        enerji = (req.energy_class or "A").upper()
        if enerji == "A":
            oran = 90.0
        elif enerji == "B":
            oran = 85.0
        else:
            oran = 80.0
        vade = 120
        dayanak = "BDDK 24.08.2023 tarihli 10631 sayılı Konut Kredileri LTV Kararı"

    azami_tutar = deger * (oran / 100.0)

    return BDDKLimitCheckResponse(
        asset_type=req.asset_type,
        asset_value_try=deger,
        max_financing_ratio_pct=oran,
        max_financing_amount_try=round(azami_tutar, 2),
        max_allowed_term_months=vade,
        legal_reference=dayanak,
    )
