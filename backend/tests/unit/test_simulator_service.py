"""Finansman simülatörü, katılma getirisi ve BDDK denetçisi testleri.

⚠️ Bu testlerin asıl işi UYDURMA VERİYİ YAKALAMAKTIR. Önceki sürüm oranı
olmayan bankaya %3,85, getirisi olmayan bankaya %42,5 brüt ve %85 pay
yazıyordu; 10 bankaya birbirinin aynısı 10 sahte teklif dönüyordu.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.stopaj import stopaj_orani
from app.db.models.bank import Bank
from app.db.models.product import Product, ProductRate
from app.schemas.simulator import (
    BDDKLimitCheckRequest,
    FinancingSimulationRequest,
    ParticipationYieldRequest,
)
from app.services.simulator_service import (
    _annuite_taksit,
    calculate_financing_simulation,
    calculate_participation_yield,
    check_bddk_limits,
)


def _oran_ekle(session: Session, banka_kodu: str, ad: str, **alanlar: object) -> None:
    banka = session.scalar(select(Bank).where(Bank.code == banka_kodu))
    assert banka is not None
    urun = Product(
        bank_id=banka.id,
        external_key=f"{banka_kodu}:{ad}",
        name=ad,
        product_type=str(alanlar.pop("product_type", "tasit_finansmani")),
    )
    session.add(urun)
    session.flush()
    session.add(
        ProductRate(
            product_id=urun.id,
            band_key=ad,
            rate_type=str(alanlar.pop("rate_type", "financing_rate")),
            currency=str(alanlar.pop("currency", "TRY")),
            evidence_text=f"{ad} kanıt",
            **alanlar,  # type: ignore[arg-type]
        )
    )
    session.flush()


# ── Annüite ───────────────────────────────────────────────


def test_annuite_taksidi_decimal_doner() -> None:
    """⚠️ Para hesabı `float` ile yapılmaz (CLAUDE.md)."""
    taksit = _annuite_taksit(Decimal("500000"), Decimal("0.0305"), 36)

    assert isinstance(taksit, Decimal)
    assert taksit == taksit.quantize(Decimal("0.01"))


def test_sifir_oranda_anapara_esit_bolunur() -> None:
    assert _annuite_taksit(Decimal("120000"), Decimal("0"), 12) == Decimal("10000.00")


# ── Uydurma veri denetimi ─────────────────────────────────


class TestVeriUydurmaz:
    """Oranı olmayan banka teklif ÜRETMEZ, ayrı grupta bildirilir."""

    def test_orani_olmayan_banka_teklif_listesine_girmez(self, seeded_session: Session) -> None:
        _oran_ekle(
            seeded_session,
            "albaraka",
            "Taşıt",
            profit_rate_pct=Decimal("3.05"),
            term_months=36,
        )

        sonuc = calculate_financing_simulation(
            seeded_session,
            FinancingSimulationRequest(
                amount_try=Decimal("500000"), term_months=36, product_type="tasit_finansmani"
            ),
        )

        assert [t.bank_code for t in sonuc.offers] == ["albaraka"]
        assert len(sonuc.banks_without_data) == 9

    def test_eksik_banka_nedeniyle_birlikte_bildirilir(self, seeded_session: Session) -> None:
        """Sessizce düşürmek "bu banka pahalı" gibi okunur."""
        sonuc = calculate_financing_simulation(
            seeded_session,
            FinancingSimulationRequest(amount_try=Decimal("100000"), term_months=12),
        )

        assert sonuc.offers == []
        assert all(b.reason for b in sonuc.banks_without_data)

    def test_getirisi_olmayan_banka_teklif_uretmez(self, seeded_session: Session) -> None:
        _oran_ekle(
            seeded_session,
            "turkiye_finans",
            "Katılma",
            rate_type="participation_yield",
            profit_rate_pct=Decimal("31.21"),
            term_months=12,
            product_type="birikim_katilma_hesabi",
        )

        sonuc = calculate_participation_yield(
            seeded_session,
            ParticipationYieldRequest(deposit_try=Decimal("100000"), term_days=365),
        )

        assert [t.bank_code for t in sonuc.offers] == ["turkiye_finans"]
        assert len(sonuc.banks_without_data) == 9

    def test_teklifler_birbirinin_ayni_degildir(self, seeded_session: Session) -> None:
        """⚠️ Eski sürümde 10 bankanın 10'u da aynı sayıyı dönüyordu."""
        _oran_ekle(seeded_session, "albaraka", "A", profit_rate_pct=Decimal("3.05"), term_months=36)
        _oran_ekle(
            seeded_session, "kuveyt_turk", "B", profit_rate_pct=Decimal("4.20"), term_months=36
        )

        sonuc = calculate_financing_simulation(
            seeded_session,
            FinancingSimulationRequest(amount_try=Decimal("500000"), term_months=36),
        )

        taksitler = {t.monthly_payment_try for t in sonuc.offers}
        assert len(taksitler) == 2


# ── Oran seçimi ───────────────────────────────────────────


class TestOranSecimi:
    """⚠️ Rastgele oran (`id DESC`) seçilmez; ürün türü ve vade eşleşir."""

    def test_baska_urun_turunun_orani_kullanilmaz(self, seeded_session: Session) -> None:
        _oran_ekle(
            seeded_session,
            "albaraka",
            "Konut",
            profit_rate_pct=Decimal("2.10"),
            term_months=120,
            product_type="konut_finansmani",
        )

        sonuc = calculate_financing_simulation(
            seeded_session,
            FinancingSimulationRequest(
                amount_try=Decimal("500000"), term_months=36, product_type="tasit_finansmani"
            ),
        )

        assert sonuc.offers == []

    def test_tam_vade_eslesmesi_isaretlenir(self, seeded_session: Session) -> None:
        _oran_ekle(
            seeded_session, "albaraka", "Taşıt", profit_rate_pct=Decimal("3.05"), term_months=36
        )

        sonuc = calculate_financing_simulation(
            seeded_session,
            FinancingSimulationRequest(amount_try=Decimal("500000"), term_months=36),
        )

        assert sonuc.offers[0].is_exact_term_match is True

    def test_yaklasik_vade_isaretlenir(self, seeded_session: Session) -> None:
        """Farklı vadenin oranı kullanıldıysa kullanıcı bunu görmeli."""
        _oran_ekle(
            seeded_session, "albaraka", "Taşıt", profit_rate_pct=Decimal("3.05"), term_months=12
        )

        sonuc = calculate_financing_simulation(
            seeded_session,
            FinancingSimulationRequest(amount_try=Decimal("500000"), term_months=36),
        )

        assert sonuc.offers[0].is_exact_term_match is False
        assert sonuc.offers[0].rate_term_months == 12

    def test_tutar_bandi_disindaki_oran_kullanilmaz(self, seeded_session: Session) -> None:
        _oran_ekle(
            seeded_session,
            "albaraka",
            "Taşıt",
            profit_rate_pct=Decimal("3.05"),
            term_months=36,
            amount_min=Decimal("1000000"),
            amount_max=Decimal("2000000"),
        )

        sonuc = calculate_financing_simulation(
            seeded_session,
            FinancingSimulationRequest(amount_try=Decimal("50000"), term_months=36),
        )

        assert sonuc.offers == []

    def test_hesaplayici_nokta_ornegi_kapali_bant_degildir(self, seeded_session: Session) -> None:
        """150.000 TL hesaplayıcı örneği 400.000 TL talebini 'oran yok' yapmaz."""
        _oran_ekle(
            seeded_session,
            "albaraka",
            "Taşıt",
            profit_rate_pct=Decimal("3.21"),
            term_months=48,
            amount_min=Decimal("150000"),
            amount_max=Decimal("150000"),
        )

        sonuc = calculate_financing_simulation(
            seeded_session,
            FinancingSimulationRequest(
                amount_try=Decimal("400000"), term_months=48, product_type="tasit_finansmani"
            ),
        )

        assert [t.bank_code for t in sonuc.offers] == ["albaraka"]
        assert sonuc.offers[0].profit_rate_pct == Decimal("3.21")

    def test_urun_tavanini_asan_tutar_elensin(self, seeded_session: Session) -> None:
        banka = seeded_session.scalar(select(Bank).where(Bank.code == "albaraka"))
        assert banka is not None
        urun = Product(
            bank_id=banka.id,
            external_key="albaraka:tavanli-tasit",
            name="Taşıt",
            product_type="tasit_finansmani",
            amount_max=Decimal("400000"),
        )
        seeded_session.add(urun)
        seeded_session.flush()
        seeded_session.add(
            ProductRate(
                product_id=urun.id,
                band_key="tavanli",
                rate_type="financing_rate",
                currency="TRY",
                evidence_text="kanıt",
                profit_rate_pct=Decimal("3.21"),
                term_months=48,
                amount_min=Decimal("150000"),
                amount_max=Decimal("150000"),
            )
        )
        seeded_session.flush()

        sonuc = calculate_financing_simulation(
            seeded_session,
            FinancingSimulationRequest(
                amount_try=Decimal("500000"), term_months=48, product_type="tasit_finansmani"
            ),
        )

        assert "albaraka" not in {t.bank_code for t in sonuc.offers}

    def test_sahte_sifir_oran_vadesiz_satir_teklif_uretmez(self, seeded_session: Session) -> None:
        """Emlak 'text' %0 (vade yok) gerçek hesaplayıcı oranını gizlemesin."""
        _oran_ekle(
            seeded_session,
            "emlak_katilim",
            "Konut",
            profit_rate_pct=Decimal("0"),
            term_months=None,
            product_type="konut_finansmani",
            rate_source="text",
        )
        _oran_ekle(
            seeded_session,
            "emlak_katilim",
            "Konut2",
            profit_rate_pct=Decimal("3.39"),
            term_months=120,
            product_type="konut_finansmani",
            amount_min=Decimal("1000000"),
            amount_max=Decimal("1000000"),
        )

        sonuc = calculate_financing_simulation(
            seeded_session,
            FinancingSimulationRequest(
                amount_try=Decimal("400000"), term_months=120, product_type="konut_finansmani"
            ),
        )

        assert [t.bank_code for t in sonuc.offers] == ["emlak_katilim"]
        assert sonuc.offers[0].profit_rate_pct == Decimal("3.39")


# ── Katılma getirisi ──────────────────────────────────────


class TestKatilmaGetirisi:
    def test_getiri_katilimci_payiyla_carpilmaz(self, seeded_session: Session) -> None:
        """⚠️ Yayımlanan getiriye katılımcı payı ZATEN dahildir.

        Ayrıca çarpılırsa pay iki kez düşülür ve getiri olduğundan düşük çıkar.
        """
        _oran_ekle(
            seeded_session,
            "turkiye_finans",
            "Katılma",
            rate_type="participation_yield",
            profit_rate_pct=Decimal("40"),
            term_months=12,
            product_type="birikim_katilma_hesabi",
        )

        sonuc = calculate_participation_yield(
            seeded_session,
            ParticipationYieldRequest(deposit_try=Decimal("100000"), term_days=365),
        )

        # 100.000 × %40 × 365/365 = 40.000 brüt
        assert sonuc.offers[0].gross_profit_try == Decimal("40000.00")

    def test_stopaj_vadeye_gore_uygulanir(self, seeded_session: Session) -> None:
        """1 yıllık TL hesapta stopaj %15; sabit %7,5 değil."""
        _oran_ekle(
            seeded_session,
            "turkiye_finans",
            "Katılma",
            rate_type="participation_yield",
            profit_rate_pct=Decimal("40"),
            term_months=12,
            product_type="birikim_katilma_hesabi",
        )

        sonuc = calculate_participation_yield(
            seeded_session,
            ParticipationYieldRequest(deposit_try=Decimal("100000"), term_days=365),
        )

        teklif = sonuc.offers[0]
        assert teklif.withholding_pct == Decimal("15.0")
        assert teklif.withholding_try == Decimal("6000.00")
        assert teklif.net_profit_try == Decimal("34000.00")

    def test_stopaj_dayanagi_yanitta_bildirilir(self, seeded_session: Session) -> None:
        """Sayı gökten inmemeli; mevzuat dayanağı yanıtta olmalı."""
        sonuc = calculate_participation_yield(
            seeded_session,
            ParticipationYieldRequest(deposit_try=Decimal("100000"), term_days=365),
        )

        assert "Gelir Vergisi" in sonuc.withholding_note

    def test_baska_para_biriminin_orani_kullanilmaz(self, seeded_session: Session) -> None:
        """⚠️ Altın hesabının %0,04'ü TL karşılaştırmasına giremez."""
        _oran_ekle(
            seeded_session,
            "turkiye_finans",
            "Altın",
            rate_type="participation_yield",
            profit_rate_pct=Decimal("0.04"),
            term_months=12,
            currency="XAU",
            product_type="birikim_katilma_hesabi",
        )

        sonuc = calculate_participation_yield(
            seeded_session,
            ParticipationYieldRequest(deposit_try=Decimal("100000"), term_days=365, currency="TRY"),
        )

        assert sonuc.offers == []


@pytest.mark.parametrize(
    ("para", "gun", "beklenen"),
    [
        ("TRY", 30, Decimal("17.5")),
        ("TRY", 180, Decimal("17.5")),
        ("TRY", 365, Decimal("15.0")),
        ("TRY", 400, Decimal("10.0")),
        ("USD", 30, Decimal("25.0")),
        ("EUR", 365, Decimal("25.0")),
        ("XAU", 180, Decimal("15.0")),
    ],
)
def test_stopaj_kademeleri(para: str, gun: int, beklenen: Decimal) -> None:
    """Oranlar üç bankanın canlı sayfasından doğrulandı (docs/stopaj_oranlari.md)."""
    assert stopaj_orani(para, gun) == beklenen


# ── BDDK ──────────────────────────────────────────────────


def test_bddk_tasit_bandi() -> None:
    sonuc = check_bddk_limits(
        BDDKLimitCheckRequest(asset_type="tasit", asset_value_try=Decimal("600000"))
    )

    assert sonuc.max_financing_ratio_pct == Decimal("50")
    assert sonuc.max_allowed_term_months == 36
    assert sonuc.max_financing_amount_try == Decimal("300000.00")


def test_bddk_tasit_ust_sinirda_finansman_yok() -> None:
    sonuc = check_bddk_limits(
        BDDKLimitCheckRequest(asset_type="tasit", asset_value_try=Decimal("2500000"))
    )

    assert sonuc.is_financing_allowed is False
    assert sonuc.max_financing_amount_try == Decimal("0.00")


class TestKonutLTV:
    """⚠️ Konut LTV'si enerji sınıfına TEK BAŞINA bağlı değildir.

    Eski kod A sınıfına değer bandına bakmadan %90 veriyordu: 25 milyonluk
    bir konutta 22,5 milyon TL finansman vaat ediyordu, gerçek sınır 10
    milyon. Matris dört bankanın yayımladığı tablodan doğrulandı.
    """

    @pytest.mark.parametrize(
        ("deger", "sinif", "oran"),
        [
            (Decimal("2000000"), "A", Decimal("90")),
            (Decimal("2000000"), "C", Decimal("80")),
            (Decimal("2000000"), "D", Decimal("70")),
            (Decimal("6000000"), "A", Decimal("80")),
            (Decimal("9000000"), "B", Decimal("70")),
            (Decimal("15000000"), "A", Decimal("50")),
            (Decimal("25000000"), "A", Decimal("40")),
            (Decimal("25000000"), "D", Decimal("20")),
        ],
    )
    def test_deger_bandi_ve_sinif_birlikte_belirler(
        self, deger: Decimal, sinif: str, oran: Decimal
    ) -> None:
        sonuc = check_bddk_limits(
            BDDKLimitCheckRequest(asset_type="konut", asset_value_try=deger, energy_class=sinif)
        )

        assert sonuc.max_financing_ratio_pct == oran

    def test_pahali_konutta_eski_kural_iki_kat_comert_olurdu(self) -> None:
        sonuc = check_bddk_limits(
            BDDKLimitCheckRequest(
                asset_type="konut", asset_value_try=Decimal("25000000"), energy_class="A"
            )
        )

        assert sonuc.max_financing_amount_try == Decimal("10000000.00")
        assert sonuc.value_band_label == "20 milyon TL üzeri"

    def test_bilinmeyen_sinif_en_dusuk_bandi_alir(self) -> None:
        """Sınıf bilinmiyorsa banka lehine değil, TÜKETİCİ lehine varsayım yapılmaz."""
        sonuc = check_bddk_limits(
            BDDKLimitCheckRequest(
                asset_type="konut", asset_value_try=Decimal("2000000"), energy_class=None
            )
        )

        assert sonuc.max_financing_ratio_pct == Decimal("70")


class TestMusteriLehineSecim:
    """⚠️ "Müşteri lehine" yön oran türüne göre TERS çevrilir."""

    def test_getiride_en_yuksek_oran_secilir(self, seeded_session: Session) -> None:
        """Aynı vadede iki getiri varsa müşteri YÜKSEĞİNİ ister."""
        banka = seeded_session.scalar(select(Bank).where(Bank.code == "turkiye_finans"))
        assert banka is not None
        urun = Product(
            bank_id=banka.id,
            external_key="tf:katilma",
            name="Katılma",
            product_type="birikim_katilma_hesabi",
        )
        seeded_session.add(urun)
        seeded_session.flush()
        for i, oran in enumerate((Decimal("28.14"), Decimal("31.21"))):
            seeded_session.add(
                ProductRate(
                    product_id=urun.id,
                    band_key=f"b{i}",
                    rate_type="participation_yield",
                    profit_rate_pct=oran,
                    term_months=12,
                    currency="TRY",
                    evidence_text=f"1 Yıl | %{oran}",
                )
            )
        seeded_session.flush()

        sonuc = calculate_participation_yield(
            seeded_session,
            ParticipationYieldRequest(deposit_try=Decimal("100000"), term_days=365),
        )

        assert sonuc.offers[0].annual_yield_gross_pct == Decimal("31.21")

    def test_finansmanda_en_dusuk_oran_secilir(self, seeded_session: Session) -> None:
        banka = seeded_session.scalar(select(Bank).where(Bank.code == "albaraka"))
        assert banka is not None
        urun = Product(
            bank_id=banka.id,
            external_key="alb:tasit",
            name="Taşıt",
            product_type="tasit_finansmani",
        )
        seeded_session.add(urun)
        seeded_session.flush()
        for i, oran in enumerate((Decimal("4.20"), Decimal("3.05"))):
            seeded_session.add(
                ProductRate(
                    product_id=urun.id,
                    band_key=f"b{i}",
                    rate_type="financing_rate",
                    profit_rate_pct=oran,
                    term_months=36,
                    currency="TRY",
                    evidence_text=f"36 ay | %{oran}",
                )
            )
        seeded_session.flush()

        sonuc = calculate_financing_simulation(
            seeded_session,
            FinancingSimulationRequest(amount_try=Decimal("500000"), term_months=36),
        )

        assert sonuc.offers[0].profit_rate_pct == Decimal("3.05")

    def test_sifir_oranli_gercek_kampanya_elenmez(self, seeded_session: Session) -> None:
        """⚠️ %0 finansman GERÇEKTİR (Albaraka Togg kampanyası).

        Elenirse bankanın en iyi teklifi listeden düşer ve kullanıcı
        gerçekte var olan sıfır maliyetli seçeneği hiç görmez.
        """
        _oran_ekle(seeded_session, "albaraka", "Togg", profit_rate_pct=Decimal("0"), term_months=12)

        sonuc = calculate_financing_simulation(
            seeded_session,
            FinancingSimulationRequest(amount_try=Decimal("120000"), term_months=12),
        )

        assert [t.bank_code for t in sonuc.offers] == ["albaraka"]
        assert sonuc.offers[0].monthly_payment_try == Decimal("10000.00")
        assert sonuc.offers[0].total_profit_try == Decimal("0.00")


# ── Ödeme planı ve tahsis ─────────────────────────────────


class TestOdemePlaniVeTahsis:
    def test_taksit_tablosu_vade_kadar_satir_uretir(self, seeded_session: Session) -> None:
        _oran_ekle(
            seeded_session, "albaraka", "Taşıt", profit_rate_pct=Decimal("3.05"), term_months=12
        )

        sonuc = calculate_financing_simulation(
            seeded_session,
            FinancingSimulationRequest(amount_try=Decimal("120000"), term_months=12),
        )

        teklif = sonuc.offers[0]
        assert len(teklif.installments) == 12
        assert teklif.installments[0].month == 1
        assert teklif.installments[-1].remaining_balance == Decimal("0.00")
        assert teklif.installments[-1].principal > 0
        # Anapara payları toplamı finansman tutarına eşit olmalı
        anapara_toplam = sum((s.principal for s in teklif.installments), Decimal(0))
        assert anapara_toplam == Decimal("120000.00")

    def test_tahsis_ucreti_toplam_maliyete_eklenir(self, seeded_session: Session) -> None:
        _oran_ekle(
            seeded_session,
            "albaraka",
            "Taşıt",
            profit_rate_pct=Decimal("0"),
            allocation_fee_pct=Decimal("0.50"),
            annual_cost_pct=Decimal("12.00"),
            term_months=12,
        )

        sonuc = calculate_financing_simulation(
            seeded_session,
            FinancingSimulationRequest(amount_try=Decimal("100000"), term_months=12),
        )

        teklif = sonuc.offers[0]
        assert teklif.allocation_fee_try == Decimal("500.00")
        assert teklif.total_payment_try == Decimal("100000.00")
        assert teklif.total_cost_try == Decimal("100500.00")
        assert teklif.annual_cost_pct == Decimal("12.00")
        assert "tahsis" in sonuc.method_note.lower()
        assert "sigorta" in sonuc.method_note.lower()

    def test_banka_alt_kumesi_suzulur(self, seeded_session: Session) -> None:
        _oran_ekle(seeded_session, "albaraka", "A", profit_rate_pct=Decimal("3.05"), term_months=36)
        _oran_ekle(
            seeded_session, "kuveyt_turk", "B", profit_rate_pct=Decimal("4.20"), term_months=36
        )

        sonuc = calculate_financing_simulation(
            seeded_session,
            FinancingSimulationRequest(
                amount_try=Decimal("500000"),
                term_months=36,
                bank_codes=["albaraka"],
            ),
        )

        assert [t.bank_code for t in sonuc.offers] == ["albaraka"]
        assert "kuveyt_turk" not in {b.bank_code for b in sonuc.banks_without_data}

    def test_dunya_katilim_tasit_finansmani_bsmv_kkdf_ile_tam_uyusur(
        self, seeded_session: Session
    ) -> None:
        """400.000 TL, 48 ay, %3.39 oranında taksit 20.173,41 TL ve toplam geri ödeme 968.323,48 TL çıkmalı."""
        _oran_ekle(
            seeded_session,
            "dunya_katilim",
            "Araç Binek 2.El",
            profit_rate_pct=Decimal("3.39"),
            term_months=48,
            product_type="tasit_finansmani",
        )

        sonuc = calculate_financing_simulation(
            seeded_session,
            FinancingSimulationRequest(
                amount_try=Decimal("400000"),
                term_months=48,
                product_type="tasit_finansmani",
                bank_codes=["dunya_katilim"],
            ),
        )

        assert len(sonuc.offers) == 1
        teklif = sonuc.offers[0]
        assert teklif.monthly_payment_try == Decimal("20173.41")
        assert teklif.total_payment_try == Decimal("968323.48")
        assert teklif.bsmv_rate_pct == Decimal("15.00")
        assert teklif.kkdf_rate_pct == Decimal("15.00")
        assert len(teklif.installments) == 48

        # 1. Ay doğrulama
        ay1 = teklif.installments[0]
        assert ay1.month == 1
        assert ay1.installment == Decimal("20173.41")
        assert ay1.profit_share == Decimal("13560.00")
        assert ay1.bsmv == Decimal("2034.00")
        assert ay1.kkdf == Decimal("2034.00")
        assert ay1.principal == Decimal("2545.41")
        assert ay1.remaining_balance == Decimal("397454.59")

    def test_konut_finansmani_vergisiz_muaf_hesaplanir(
        self, seeded_session: Session
    ) -> None:
        """Konut finansmanında BSMV ve KKDF %0 olmalı."""
        _oran_ekle(
            seeded_session,
            "dunya_katilim",
            "Konut Finansmanı",
            profit_rate_pct=Decimal("2.99"),
            term_months=60,
            product_type="konut_finansmani",
        )

        sonuc = calculate_financing_simulation(
            seeded_session,
            FinancingSimulationRequest(
                amount_try=Decimal("1000000"),
                term_months=60,
                product_type="konut_finansmani",
                bank_codes=["dunya_katilim"],
            ),
        )

        assert len(sonuc.offers) == 1
        teklif = sonuc.offers[0]
        assert teklif.bsmv_rate_pct == Decimal("0.00")
        assert teklif.kkdf_rate_pct == Decimal("0.00")
        assert teklif.total_bsmv_try == Decimal("0.00")
        assert teklif.total_kkdf_try == Decimal("0.00")
        assert teklif.monthly_payment_try == Decimal("36055.58")
        assert teklif.installments[0].bsmv == Decimal("0.00")
        assert teklif.installments[0].kkdf == Decimal("0.00")
