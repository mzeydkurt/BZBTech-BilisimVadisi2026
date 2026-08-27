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

from app.core.financing_taxes import financing_tax_rates
from app.core.stopaj import STOPAJ_DAYANAK, stopaj_orani
from app.db.models.bank import Bank
from app.db.models.product import Product, ProductRate
from app.db.models.source_document import SourceDocument
from app.schemas.simulator import (
    BankFinancingOffer,
    BankYieldOffer,
    FinancingSimulationRequest,
    FinancingSimulationResponse,
    InstallmentRow,
    MissingDataBank,
    ParticipationYieldRequest,
    ParticipationYieldResponse,
)
from app.services.bddk_limits_service import check_bddk_limits

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
        aylik_oran: Aylık efektif oran (vergiler dahil), ONDALIK olarak (%4,407 → 0.04407).
        vade: Vade (ay).

    Returns:
        Kuruşa yuvarlanmış aylık taksit.

    """
    if aylik_oran <= 0:
        return _kurusla(anapara / Decimal(vade))

    carpan = (Decimal(1) + aylik_oran) ** vade
    return _kurusla(anapara * aylik_oran * carpan / (carpan - Decimal(1)))


def _odeme_plani(
    anapara: Decimal,
    aylik_oran: Decimal,
    bsmv_orani: Decimal,
    kkdf_orani: Decimal,
    vade: int,
    taksit: Decimal,
) -> list[InstallmentRow]:
    """Eşit taksitli amortisman tablosunu BSMV ve KKDF vergileriyle üretir.

    Her ay:
    - kâr payı = kalan × r
    - bsmv = kâr payı × bsmv_orani
    - kkdf = kâr payı × kkdf_orani
    - anapara = taksit − (kâr payı + bsmv + kkdf)
    Son ayda yuvarlama farkı anaparaya yedirilerek bakiye sıfırlanır.
    """
    kalan = anapara
    satirlar: list[InstallmentRow] = []
    for ay in range(1, vade + 1):
        kar = _kurusla(kalan * aylik_oran) if aylik_oran > 0 else Decimal("0.00")
        bsmv = _kurusla(kar * bsmv_orani) if bsmv_orani > 0 else Decimal("0.00")
        kkdf = _kurusla(kar * kkdf_orani) if kkdf_orani > 0 else Decimal("0.00")
        faiz_ve_vergi = kar + bsmv + kkdf

        if ay == vade:
            anapara_payi = kalan
            odeme = _kurusla(anapara_payi + faiz_ve_vergi)
            kalan = Decimal("0.00")
        else:
            anapara_payi = _kurusla(taksit - faiz_ve_vergi)
            if anapara_payi > kalan:
                anapara_payi = kalan
            odeme = taksit
            kalan = _kurusla(kalan - anapara_payi)

        satirlar.append(
            InstallmentRow(
                month=ay,
                installment=odeme,
                profit_share=kar,
                bsmv=bsmv,
                kkdf=kkdf,
                principal=anapara_payi,
                remaining_balance=kalan,
            )
        )
    return satirlar


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

    # ⚠️ BAĞLAYICI ORAN ÖNCE GELİR — ama tek aday oysa eleme YAPILMAZ.
    # Ölçüldü: Türkiye Finans taşıt simülasyonunda hesaplayıcıdan gelen
    # `%0,50` (bağlayıcı değil) bankanın yayımladığı `%4,02` tablosunu
    # eziyor ve "En uygun" rozetini alıyordu. Sert süzgeç ise 13 banka ×
    # ürün kombinasyonunu (Kuveyt Türk konut dahil) listeden tamamen
    # düşürürdü; tercih sırası hem doğruyu seçer hem kapsamı korur.
    def _sec(aday: list[ProductRate]) -> ProductRate:
        baglayici = [o for o in aday if _baglayici(o)]
        return _lehte(baglayici or aday)

    tam = [o for o in oranlar if o.term_months == istenen_ay]
    if tam:
        return _sec(tam), True

    vadeli = [o for o in oranlar if o.term_months is not None]
    if not vadeli:
        return None, False

    # Bağlayıcı satırların vadesi varsa en yakınlık onlar üzerinden ölçülür:
    # aksi hâlde bağlayıcı olmayan bir satır sırf vadesi yakın diye seçilir.
    havuz = [o for o in vadeli if _baglayici(o)] or vadeli
    en_yakin_fark = min(abs((o.term_months or 0) - istenen_ay) for o in havuz)
    adaylar = [o for o in havuz if abs((o.term_months or 0) - istenen_ay) == en_yakin_fark]
    return _lehte(adaylar), False


def _baglayici(oran: ProductRate) -> bool:
    """Oran bankanın taahhüdü mü?

    ⚠️ `None` BAĞLAYICI SAYILIR. Kolon `nullable=False, default=True`; kalıcı
    satırda asla None olmaz, ama henüz yazılmamış nesnede Python tarafı
    varsayılanı uygulanmadığı için None görünür. `bool(None)` demek, kaydedilmemiş
    her oranı bağlayıcı değil saymak olurdu.
    """
    return oran.is_binding is not False


def _tl(deger: Decimal) -> str:
    """Tutarı Türkçe binlik ayracıyla biçimler (1234567 -> 1.234.567).

    ⚠️ Biçimleme SAYIYA uygulanır, cümleye değil: `f"...".replace(",", ".")`
    cümledeki virgülleri de noktaya çeviriyordu.
    """
    return f"{deger:,.0f}".replace(",", ".")


def _oran_baglami(oran: ProductRate, req: FinancingSimulationRequest) -> str | None:
    """Oran istenenden farklı bir tutar/vade için yayımlandıysa açıklar.

    ⚠️ `is_exact_term_match` bir bayraktır; 1 aylık sapmayla 36 aylık sapmayı
    ayırt etmez. Ölçüldü: Emlak Katılım ihtiyaç finansmanında 30.000 ₺ / 12 ay
    için yayımlanmış %1,69 kampanya oranı, 400.000 ₺ / 48 ay isteğine
    uygulanıyordu. Teklif elenmiyor — sapma SÖYLENİYOR.
    """
    parcalar: list[str] = []

    if oran.term_months is not None and oran.term_months != req.term_months:
        parcalar.append(f"{oran.term_months} ay vade")

    if oran.amount_min is not None or oran.amount_max is not None:
        alt, ust = oran.amount_min, oran.amount_max
        if alt is not None and ust is not None and alt != ust:
            kapsiyor = alt <= req.amount_try <= ust
            if not kapsiyor:
                parcalar.append(f"{_tl(alt)}–{_tl(ust)} ₺ tutar bandı")
        elif alt is not None and alt == ust:
            # Hesaplayıcı/ödeme planı örneği: kapalı bant değil, tek örnek tutar.
            if alt != req.amount_try:
                parcalar.append(f"{_tl(alt)} ₺ örnek tutar")

    if not parcalar:
        return None

    return (
        f"Bu oran {' ve '.join(parcalar)} için yayımlandı; "
        f"siz {_tl(req.amount_try)} ₺ / {req.term_months} ay istediniz."
    )


def calculate_financing_simulation(
    session: Session, req: FinancingSimulationRequest
) -> FinancingSimulationResponse:
    """Bankaların yayımlanmış oranlarıyla finansman taksitlerini karşılaştırır.

    Yalnızca istenen ürün türünde `financing_rate` yayımlamış bankalar teklif
    üretir. Oranı olmayan banka `banks_without_data` içinde bildirilir.

    İhtiyaç finansmanında BDDK vade tavanı aşılırsa teklif üretilmez; neden
    `banks_without_data` ve `method_note` içinde bildirilir.
    """
    from app.services.bddk_limits_service import (
        family_for_product_type,
        max_term_for_ihtiyac_amount,
    )

    bddk_vade_notu: str | None = None
    aile = family_for_product_type(req.product_type)
    if aile == "ihtiyac":
        azami_vade, bant, _ = max_term_for_ihtiyac_amount(req.amount_try)
        if req.term_months > azami_vade:
            return FinancingSimulationResponse(
                amount_try=req.amount_try,
                term_months=req.term_months,
                product_type=req.product_type,
                best_bank_code=None,
                offers=[],
                banks_without_data=[],
                method_note=(
                    f"BDDK ihtiyaç vade tavanı aşıldı: {bant} için azami "
                    f"{azami_vade} ay. İstenen vade {req.term_months} ay — "
                    "teklif üretilmedi."
                ),
            )
        bddk_vade_notu = f"BDDK azami vade ({bant}): {azami_vade} ay."

    bankalar = list(session.scalars(select(Bank).order_by(Bank.code)))
    if req.bank_codes:
        istenen = set(req.bank_codes)
        bankalar = [b for b in bankalar if b.code in istenen]
    teklifler: list[BankFinancingOffer] = []
    eksikler: list[MissingDataBank] = []
    tahsis_dahil = False

    for banka in bankalar:
        from app.services.calculator_probe_service import is_zero_rate_promotional
        from app.services.product_rate_current import rate_covers_amount, select_current_rates

        satirlar = list(
            session.scalars(
                select(ProductRate)
                .join(Product, ProductRate.product_id == Product.id)
                .where(
                    Product.bank_id == banka.id,
                    Product.is_active.is_(True),
                    Product.product_type == req.product_type,
                    ProductRate.rate_type == "financing_rate",
                    # ⚠️ %0 finansman GERÇEKTİR (Albaraka Togg kampanyası:
                    # "T10F V2 | 12 | 1.000.000 | 0,00%"). Elenirse bankanın
                    # en iyi teklifi listeden düşer.
                    ProductRate.profit_rate_pct.is_not(None),
                )
            )
        )
        # Aynı bandın eski kazıma tarihleri DB'de kalır; teklifte yalnızca güncel.
        satirlar = select_current_rates(satirlar)
        urun_by_id = {
            u.id: u
            for u in session.scalars(
                select(Product).where(Product.id.in_({o.product_id for o in satirlar} or {0}))
            )
        }

        uygun: list[ProductRate] = []
        for o in satirlar:
            urun = urun_by_id.get(o.product_id)
            if urun is None:
                continue
            if (
                o.profit_rate_pct is not None
                and o.profit_rate_pct <= Decimal("0.05")
                and not is_zero_rate_promotional(
                    product_name=urun.name,
                    description=urun.description,
                    evidence_text=o.evidence_text,
                    product_type=urun.product_type,
                    rate_type=o.rate_type,
                )
            ):
                continue
            if rate_covers_amount(
                req.amount_try,
                rate_min=o.amount_min,
                rate_max=o.amount_max,
                product_min=urun.amount_min,
                product_max=urun.amount_max,
            ):
                uygun.append(o)

        oran, tam_eslesme = _en_yakin_vade(uygun, req.term_months, dusuk_iyi=True)
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

        urun = urun_by_id.get(oran.product_id) or session.get(Product, oran.product_id)
        tax_cfg = financing_tax_rates(req.product_type)
        aylik_oran = oran.profit_rate_pct / _YUZDE
        efektif_aylik_oran = aylik_oran * tax_cfg.total_tax_multiplier

        aylik = _annuite_taksit(req.amount_try, efektif_aylik_oran, req.term_months)
        plan = _odeme_plani(
            req.amount_try,
            aylik_oran,
            tax_cfg.bsmv_rate,
            tax_cfg.kkdf_rate,
            req.term_months,
            aylik,
        )
        toplam_odeme = _kurusla(sum((s.installment for s in plan), Decimal(0)))
        toplam_kar = _kurusla(sum((s.profit_share for s in plan), Decimal(0)))
        toplam_bsmv = _kurusla(sum((s.bsmv for s in plan), Decimal(0)))
        toplam_kkdf = _kurusla(sum((s.kkdf for s in plan), Decimal(0)))

        tahsis: Decimal | None = None
        if oran.allocation_fee_pct is not None:
            tahsis = _kurusla(req.amount_try * oran.allocation_fee_pct / _YUZDE)
            tahsis_dahil = True
        toplam_maliyet = _kurusla(toplam_odeme + (tahsis or Decimal(0)))

        teklifler.append(
            BankFinancingOffer(
                bank_code=banka.code,
                bank_name=banka.name,
                product_id=oran.product_id,
                product_name=urun.name if urun else "",
                profit_rate_pct=oran.profit_rate_pct,
                rate_term_months=oran.term_months,
                is_exact_term_match=tam_eslesme,
                term_gap_months=(
                    None
                    if tam_eslesme or oran.term_months is None
                    else abs(oran.term_months - req.term_months)
                ),
                rate_amount_min=oran.amount_min,
                rate_amount_max=oran.amount_max,
                rate_context_note=_oran_baglami(oran, req),
                bsmv_rate_pct=tax_cfg.bsmv_pct,
                kkdf_rate_pct=tax_cfg.kkdf_pct,
                monthly_payment_try=aylik,
                total_profit_try=toplam_kar,
                total_bsmv_try=toplam_bsmv,
                total_kkdf_try=toplam_kkdf,
                total_payment_try=toplam_odeme,
                allocation_fee_try=tahsis,
                total_cost_try=toplam_maliyet,
                annual_cost_pct=oran.annual_cost_pct,
                installments=plan,
                is_binding=_baglayici(oran),
                binding_note=(
                    None
                    if _baglayici(oran)
                    else (
                        "Bu oran bankanın taahhüdü değildir; hesaplayıcı sorgusundan "
                        "okunmuştur. Kesin teklif için bankaya başvurun."
                    )
                ),
                source_url=_kaynak_url(session, urun) if urun else None,
                evidence_text=oran.evidence_text,
            )
        )

    en_iyi: str | None = None
    if teklifler:
        teklifler.sort(key=lambda t: t.total_cost_try)
        # ⚠️ "En uygun" rozeti BAĞLAYICI tekliflere ayrılır. Bağlayıcı olmayan
        # teklif listede kalır ama bankanın taahhüdü olmayan bir sayıyla
        # kazanan ilan edilmez. Hiç bağlayıcı teklif yoksa en ucuz seçilir.
        kazanan = next((t for t in teklifler if t.is_binding), teklifler[0])
        kazanan.is_best_offer = True
        en_iyi = kazanan.bank_code

    tax_info = financing_tax_rates(req.product_type)
    tax_desc = (
        "Vergisiz (Konut mevzuatı gereği BSMV ve KKDF'den muaftır)."
        if tax_info.is_tax_exempt
        else (
            f"Vergiler dahil: %{tax_info.bsmv_pct:g} BSMV + %{tax_info.kkdf_pct:g} KKDF "
            "kâr payı üzerine eklenmiştir."
        )
    )

    if tahsis_dahil:
        method = (
            f"Eşit taksitli (annüite) plan; {tax_desc} "
            "Aylık oran, bankanın yayımladığı aylık kâr payı oranıdır. "
            "Tahsis ücreti (allocation_fee_pct × tutar) toplam maliyete "
            "dahil edilmiştir; annual_cost_pct bankanın yayımladığı yıllık "
            "toplam maliyet oranıdır. Sigorta gibi ek maliyetler bu hesaba "
            "dahil değildir."
        )
    else:
        method = (
            f"Eşit taksitli (annüite) plan; {tax_desc} "
            "Aylık oran, bankanın yayımladığı aylık kâr payı oranıdır. "
            "Tahsis ücretleri bankadan bankaya azami olarak finansman tutarının "
            "binde beşi yani %0.50'si olarak tahsil edilmektedir; bankalar arası "
            "farklılıklar gösterebileceğinden hesaplamaya dahil edilmemiştir; "
            "sigorta gibi ek maliyetler de dahil değildir."
        )
    if bddk_vade_notu:
        method = f"{method} {bddk_vade_notu}"

    return FinancingSimulationResponse(
        amount_try=req.amount_try,
        term_months=req.term_months,
        product_type=req.product_type,
        best_bank_code=en_iyi,
        offers=teklifler,
        banks_without_data=eksikler,
        method_note=method,
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
    if req.bank_codes:
        istenen = set(req.bank_codes)
        bankalar = [b for b in bankalar if b.code in istenen]
    teklifler: list[BankYieldOffer] = []
    eksikler: list[MissingDataBank] = []

    stopaj_pct = stopaj_orani(req.currency, req.term_days)
    donem = Decimal(req.term_days) / _YIL_GUN

    for banka in bankalar:
        from app.services.product_rate_current import select_current_rates

        satirlar = list(
            session.scalars(
                select(ProductRate)
                .join(Product, ProductRate.product_id == Product.id)
                .where(
                    Product.bank_id == banka.id,
                    Product.is_active.is_(True),
                    ProductRate.rate_type == "participation_yield",
                    ProductRate.currency == req.currency,
                    ProductRate.profit_rate_pct.is_not(None),
                    ProductRate.profit_rate_pct > 0,
                )
            )
        )
        satirlar = select_current_rates(satirlar)
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

        katilimci_payi = oran.investor_share_pct
        banka_payi = oran.bank_share_pct

        if katilimci_payi is None:
            paylasim_satirlari = list(
                session.scalars(
                    select(ProductRate)
                    .join(Product, ProductRate.product_id == Product.id)
                    .where(
                        Product.bank_id == banka.id,
                        Product.is_active.is_(True),
                        ProductRate.rate_type == "profit_sharing_ratio",
                        ProductRate.currency == req.currency,
                        ProductRate.investor_share_pct.is_not(None),
                    )
                )
            )
            paylasim_satirlari = select_current_rates(paylasim_satirlari)
            paylasim_satirlari = [
                p
                for p in paylasim_satirlari
                if (p.amount_min is None or req.deposit_try >= p.amount_min)
                and (p.amount_max is None or req.deposit_try <= p.amount_max)
            ]
            if paylasim_satirlari:
                ayni_varyant = [p for p in paylasim_satirlari if p.variant == oran.variant]
                adaylar = ayni_varyant if ayni_varyant else paylasim_satirlari

                eslesen = None
                if oran.term_months is not None:
                    tam_vade = [p for p in adaylar if p.term_months == oran.term_months]
                    if tam_vade:
                        eslesen = tam_vade[0]
                    else:
                        vadeli = [p for p in adaylar if p.term_months is not None]
                        if vadeli:
                            eslesen = min(
                                vadeli,
                                key=lambda p: abs((p.term_months or 0) - (oran.term_months or 0)),
                            )
                if eslesen is None and adaylar:
                    eslesen = adaylar[0]

                if eslesen is not None:
                    katilimci_payi = eslesen.investor_share_pct
                    banka_payi = eslesen.bank_share_pct or (
                        Decimal("100") - eslesen.investor_share_pct
                        if eslesen.investor_share_pct is not None
                        else None
                    )

        teklifler.append(
            BankYieldOffer(
                bank_code=banka.code,
                bank_name=banka.name,
                product_id=oran.product_id,
                product_name=urun.name if urun else "",
                annual_yield_gross_pct=oran.profit_rate_pct,
                rate_term_label=oran.term_label,
                is_exact_term_match=tam_eslesme,
                investor_share_pct=katilimci_payi,
                bank_share_pct=banka_payi,
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


# check_bddk_limits: `bddk_limits_service` üzerinden yeniden dışa aktarılır
# (yukarıdaki import). Koda gömülü LTV matrisi YOKTUR.
__all__ = [
    "calculate_financing_simulation",
    "calculate_participation_yield",
    "check_bddk_limits",
]
