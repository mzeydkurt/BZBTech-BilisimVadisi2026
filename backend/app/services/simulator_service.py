"""Finansman simülatörü, katılma hesabı getirisi ve BDDK limit denetimi.

⚠️ TEMEL KURAL: veri olmayan yerde veri UYDURULMAZ. Oranı bulunmayan banka
teklif listesine girmez; `banks_without_data` içinde nedeniyle bildirilir.
Varsayılan oran, varsayılan getiri, varsayılan paylaşım oranı YOKTUR.

⚠️ Para ve oran hesapları `Decimal` ile yapılır (CLAUDE.md). Annüite üssü
`Decimal.__pow__` ile alınır; `float` dönüşümü yuvarlama hatası biriktirir.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.stopaj import STOPAJ_DAYANAK, stopaj_orani
from app.db.models.bank import Bank
from app.db.models.product import Product, ProductRate
from app.db.models.source_document import SourceDocument
from app.schemas.simulator import (
    BankFinancingOffer,
    BankYieldOffer,
    BDDKLimitCheckRequest,
    BDDKLimitCheckResponse,
    FinancingSimulationRequest,
    FinancingSimulationResponse,
    MissingDataBank,
    ParticipationYieldRequest,
    ParticipationYieldResponse,
)

_KURUS = Decimal("0.01")
_YUZDE = Decimal("100")
_YIL_GUN = Decimal("365")


def _kurusla(deger: Decimal) -> Decimal:
    """Tutarı kuruşa yuvarlar."""
    return deger.quantize(_KURUS, rounding=ROUND_HALF_UP)


def _annuite_taksit(anapara: Decimal, aylik_oran: Decimal, vade: int) -> Decimal:
    """Eşit taksitli (annüite) ödeme planında aylık taksiti hesaplar.

    Taksit = P · r · (1+r)^n / ((1+r)^n − 1)

    Args:
        anapara: Finansman tutarı.
        aylik_oran: Aylık kâr payı oranı, ONDALIK olarak (%3,05 → 0.0305).
        vade: Vade (ay).

    Returns:
        Kuruşa yuvarlanmış aylık taksit.

    """
    if aylik_oran <= 0:
        return _kurusla(anapara / Decimal(vade))

    carpan = (Decimal(1) + aylik_oran) ** vade
    return _kurusla(anapara * aylik_oran * carpan / (carpan - Decimal(1)))


def _kaynak_url(session: Session, urun: Product) -> str | None:
    """Ürünün oranının okunduğu banka sayfasını döndürür."""
    if urun.source_document_id is None:
        return None
    belge = session.get(SourceDocument, urun.source_document_id)
    return belge.url if belge else None


def _en_yakin_vade(
    oranlar: list[ProductRate], istenen_ay: int, *, dusuk_iyi: bool
) -> tuple[ProductRate | None, bool]:
    """İstenen vadeye en yakın, müşteri lehine oranı seçer.

    ⚠️ Rastgele bir oran (`id DESC`) seçilmez: 12 ay için yayımlanmış oranı
    36 aylık simülasyonda kullanmak tekliflerin sırasını değiştirir. Tam
    eşleşme yoksa en yakın vade kullanılır ve bu durum yanıtta işaretlenir.

    ⚠️ "Müşteri lehine" yön oran türüne göre TERS çevrilir. Finansmanda düşük
    oran iyidir (az öder); katılma hesabında YÜKSEK oran iyidir (çok kazanır).
    Tek yön kullanılırsa bankanın en kötü getirisi teklif diye sunulur.

    Args:
        oranlar: Adaylar.
        istenen_ay: İstenen vade (ay).
        dusuk_iyi: Finansmanda True, getiride False.

    Returns:
        (seçilen oran, tam eşleşme mi) ikilisi.

    """
    if not oranlar:
        return None, False

    uc = Decimal("999999") if dusuk_iyi else Decimal("-1")

    def _lehte(aday: list[ProductRate]) -> ProductRate:
        secici = min if dusuk_iyi else max
        return secici(
            aday, key=lambda o: o.profit_rate_pct if o.profit_rate_pct is not None else uc
        )

    tam = [o for o in oranlar if o.term_months == istenen_ay]
    if tam:
        return _lehte(tam), True

    vadeli = [o for o in oranlar if o.term_months is not None]
    if not vadeli:
        return None, False

    en_yakin_fark = min(abs((o.term_months or 0) - istenen_ay) for o in vadeli)
    adaylar = [o for o in vadeli if abs((o.term_months or 0) - istenen_ay) == en_yakin_fark]
    return _lehte(adaylar), False


def calculate_financing_simulation(
    session: Session, req: FinancingSimulationRequest
) -> FinancingSimulationResponse:
    """Bankaların yayımlanmış oranlarıyla finansman taksitlerini karşılaştırır.

    Yalnızca istenen ürün türünde `financing_rate` yayımlamış bankalar teklif
    üretir. Oranı olmayan banka `banks_without_data` içinde bildirilir.
    """
    bankalar = list(session.scalars(select(Bank).order_by(Bank.code)))
    teklifler: list[BankFinancingOffer] = []
    eksikler: list[MissingDataBank] = []

    for banka in bankalar:
        satirlar = list(
            session.scalars(
                select(ProductRate)
                .join(Product, ProductRate.product_id == Product.id)
                .where(
                    Product.bank_id == banka.id,
                    Product.product_type == req.product_type,
                    ProductRate.rate_type == "financing_rate",
                    # ⚠️ %0 finansman GERÇEKTİR (Albaraka Togg kampanyası:
                    # "T10F V2 | 12 | 1.000.000 | 0,00%"). Elenirse bankanın
                    # en iyi teklifi listeden düşer.
                    ProductRate.profit_rate_pct.is_not(None),
                )
            )
        )

        # Tutar bandı yayımlanmışsa istenen tutar bandın dışındaysa oran geçersizdir.
        satirlar = [
            o
            for o in satirlar
            if (o.amount_min is None or req.amount_try >= o.amount_min)
            and (o.amount_max is None or req.amount_try <= o.amount_max)
        ]

        oran, tam_eslesme = _en_yakin_vade(satirlar, req.term_months, dusuk_iyi=True)
        if oran is None or oran.profit_rate_pct is None:
            eksikler.append(
                MissingDataBank(
                    bank_code=banka.code,
                    bank_name=banka.name,
                    reason=(
                        f"{req.product_type} için yayımlanmış kâr payı oranı bulunamadı"
                        if not satirlar
                        else "Yayımlanmış oranlar istenen tutar/vade bandını kapsamıyor"
                    ),
                )
            )
            continue

        urun = session.get(Product, oran.product_id)
        aylik = _annuite_taksit(req.amount_try, oran.profit_rate_pct / _YUZDE, req.term_months)
        toplam = _kurusla(aylik * Decimal(req.term_months))

        teklifler.append(
            BankFinancingOffer(
                bank_code=banka.code,
                bank_name=banka.name,
                product_id=oran.product_id,
                product_name=urun.name if urun else "",
                profit_rate_pct=oran.profit_rate_pct,
                rate_term_months=oran.term_months,
                is_exact_term_match=tam_eslesme,
                monthly_payment_try=aylik,
                total_profit_try=_kurusla(toplam - req.amount_try),
                total_payment_try=toplam,
                source_url=_kaynak_url(session, urun) if urun else None,
                evidence_text=oran.evidence_text,
            )
        )

    en_iyi: str | None = None
    if teklifler:
        kazanan = min(teklifler, key=lambda t: t.total_payment_try)
        kazanan.is_best_offer = True
        en_iyi = kazanan.bank_code
        teklifler.sort(key=lambda t: t.total_payment_try)

    return FinancingSimulationResponse(
        amount_try=req.amount_try,
        term_months=req.term_months,
        product_type=req.product_type,
        best_bank_code=en_iyi,
        offers=teklifler,
        banks_without_data=eksikler,
        method_note=(
            "Eşit taksitli (annüite) plan; taksit = P·r·(1+r)^n/((1+r)^n−1). "
            "Oranlar bankaların kendi yayımladığı tablolardan okundu; tahsis "
            "ücreti ve sigorta gibi ek maliyetler bu hesaba dahil değildir."
        ),
    )


def calculate_participation_yield(
    session: Session, req: ParticipationYieldRequest
) -> ParticipationYieldResponse:
    """Katılma hesabı brüt/net getirisini bankaların yayımladığı oranlarla hesaplar.

    ⚠️ Kullanılan oran bankanın yayımladığı GERÇEKLEŞMİŞ getiridir; katılımcı
    payı bu orana zaten dahildir. Ayrıca paylaşım oranıyla çarpılmaz.
    """
    istenen_ay = max(1, round(req.term_days / 30))
    bankalar = list(session.scalars(select(Bank).order_by(Bank.code)))
    teklifler: list[BankYieldOffer] = []
    eksikler: list[MissingDataBank] = []

    stopaj_pct = stopaj_orani(req.currency, req.term_days)
    donem = Decimal(req.term_days) / _YIL_GUN

    for banka in bankalar:
        satirlar = list(
            session.scalars(
                select(ProductRate)
                .join(Product, ProductRate.product_id == Product.id)
                .where(
                    Product.bank_id == banka.id,
                    ProductRate.rate_type == "participation_yield",
                    ProductRate.currency == req.currency,
                    ProductRate.profit_rate_pct.is_not(None),
                    ProductRate.profit_rate_pct > 0,
                )
            )
        )
        satirlar = [
            o
            for o in satirlar
            if (o.amount_min is None or req.deposit_try >= o.amount_min)
            and (o.amount_max is None or req.deposit_try <= o.amount_max)
        ]

        oran, tam_eslesme = _en_yakin_vade(satirlar, istenen_ay, dusuk_iyi=False)
        if oran is None or oran.profit_rate_pct is None:
            eksikler.append(
                MissingDataBank(
                    bank_code=banka.code,
                    bank_name=banka.name,
                    reason=(
                        f"{req.currency} katılma hesabı için yayımlanmış getiri oranı bulunamadı"
                    ),
                )
            )
            continue

        urun = session.get(Product, oran.product_id)
        brut = _kurusla(req.deposit_try * oran.profit_rate_pct / _YUZDE * donem)
        kesinti = _kurusla(brut * stopaj_pct / _YUZDE)

        teklifler.append(
            BankYieldOffer(
                bank_code=banka.code,
                bank_name=banka.name,
                product_id=oran.product_id,
                product_name=urun.name if urun else "",
                annual_yield_gross_pct=oran.profit_rate_pct,
                rate_term_label=oran.term_label,
                is_exact_term_match=tam_eslesme,
                investor_share_pct=oran.investor_share_pct,
                bank_share_pct=oran.bank_share_pct,
                gross_profit_try=brut,
                withholding_pct=stopaj_pct,
                withholding_try=kesinti,
                net_profit_try=_kurusla(brut - kesinti),
                source_url=_kaynak_url(session, urun) if urun else None,
                evidence_text=oran.evidence_text,
            )
        )

    en_iyi: str | None = None
    if teklifler:
        kazanan = max(teklifler, key=lambda t: t.net_profit_try)
        kazanan.is_best_yield = True
        en_iyi = kazanan.bank_code
        teklifler.sort(key=lambda t: t.net_profit_try, reverse=True)

    return ParticipationYieldResponse(
        deposit_try=req.deposit_try,
        term_days=req.term_days,
        currency=req.currency,
        best_yield_bank_code=en_iyi,
        offers=teklifler,
        banks_without_data=eksikler,
        withholding_note=f"%{stopaj_pct} stopaj uygulandı. Dayanak: {STOPAJ_DAYANAK}",
        method_note=(
            "Brüt kâr = tutar × yıllık getiri × (vade gün / 365). Kullanılan "
            "oran bankanın yayımladığı gerçekleşmiş getiridir; katılımcı payı "
            "bu orana zaten dahildir. Geçmiş getiri gelecek getiriyi taahhüt "
            "etmez — katılma hesabında kâr payı önceden garanti edilemez."
        ),
    )


# ── BDDK limit denetimi ───────────────────────────────────
#
# ⚠️ Konut LTV'si TEK BAŞINA enerji sınıfına bağlı DEĞİLDİR; konut değeri
# bandıyla birlikte belirlenir. "A sınıfı → %90" kuralı 25 milyonluk bir
# konutta bankayı gerçekte verdiğinin iki katı cömert gösterir. Aşağıdaki
# matris Albaraka, Türkiye Finans, Vakıf Katılım ve Emlak Katılım'ın
# yayımladığı tablolardan doğrulandı (bkz. `product_limits`).

_KONUT_LTV: tuple[tuple[Decimal | None, str, dict[str, Decimal]], ...] = (
    (
        Decimal("5000000"),
        "5 milyon TL ve altı",
        {"A-B": Decimal("90"), "C": Decimal("80"), "DIGER": Decimal("70")},
    ),
    (
        Decimal("7000000"),
        "5–7 milyon TL",
        {"A-B": Decimal("80"), "C": Decimal("70"), "DIGER": Decimal("60")},
    ),
    (
        Decimal("10000000"),
        "7–10 milyon TL",
        {"A-B": Decimal("70"), "C": Decimal("60"), "DIGER": Decimal("50")},
    ),
    (
        Decimal("20000000"),
        "10–20 milyon TL",
        {"A-B": Decimal("50"), "C": Decimal("40"), "DIGER": Decimal("30")},
    ),
    (
        None,
        "20 milyon TL üzeri",
        {"A-B": Decimal("40"), "C": Decimal("30"), "DIGER": Decimal("20")},
    ),
)

# Taşıt: kasko/satış değeri bandına göre oran ve azami vade.
_TASIT_BANTLARI: tuple[tuple[Decimal | None, Decimal, int | None], ...] = (
    (Decimal("400000"), Decimal("70"), 48),
    (Decimal("800000"), Decimal("50"), 36),
    (Decimal("1200000"), Decimal("30"), 24),
    (Decimal("2000000"), Decimal("20"), 12),
    (None, Decimal("0"), None),  # 2 milyon üzeri: finansman kullandırılmaz
)

_TASIT_DAYANAK = "BDDK 21.02.2022 tarihli 10099 sayılı Taşıt Kredileri Kararı"
_KONUT_DAYANAK = "BDDK 24.08.2023 tarihli 10631 sayılı Konut Kredileri LTV Kararı"


def _enerji_sinifi(ham: str | None) -> str:
    """Serbest metinli enerji sınıfını matris anahtarına çevirir."""
    if not ham:
        return "DIGER"
    temiz = ham.strip().upper().replace("İ", "I")
    if temiz.startswith("A") or temiz.startswith("B"):
        return "A-B"
    if temiz.startswith("C"):
        return "C"
    return "DIGER"


def check_bddk_limits(req: BDDKLimitCheckRequest) -> BDDKLimitCheckResponse:
    """BDDK azami finansman oranı ve vadesini denetler."""
    deger = req.asset_value_try

    if req.asset_type == "tasit":
        for ust, oran, vade in _TASIT_BANTLARI:
            if ust is None or deger <= ust:
                bant = f"{ust:,.0f} TL ve altı".replace(",", ".") if ust else "2 milyon TL üzeri"
                azami = _kurusla(deger * oran / _YUZDE)
                return BDDKLimitCheckResponse(
                    asset_type="tasit",
                    asset_value_try=deger,
                    value_band_label=bant,
                    max_financing_ratio_pct=oran,
                    max_financing_amount_try=azami,
                    max_allowed_term_months=vade,
                    is_financing_allowed=oran > 0,
                    legal_reference=_TASIT_DAYANAK,
                )

    sinif = _enerji_sinifi(req.energy_class)
    for ust, etiket, oranlar in _KONUT_LTV:
        if ust is None or deger <= ust:
            oran = oranlar[sinif]
            return BDDKLimitCheckResponse(
                asset_type="konut",
                asset_value_try=deger,
                energy_class=sinif,
                value_band_label=etiket,
                max_financing_ratio_pct=oran,
                max_financing_amount_try=_kurusla(deger * oran / _YUZDE),
                max_allowed_term_months=120,
                is_financing_allowed=oran > 0,
                legal_reference=_KONUT_DAYANAK,
            )

    raise AssertionError("limit bandı bulunamadı")  # pragma: no cover
