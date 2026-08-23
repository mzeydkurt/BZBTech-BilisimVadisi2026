"""Ürün açıklama çıkarımı, probe örnekleri ve annüite tutarlılık testleri."""

from __future__ import annotations

from decimal import Decimal

from app.processing.limits import derive_rate_from_payment_plan
from app.processing.product_description import extract_product_description
from app.services.bddk_limits_service import allocation_fee_cap_pct
from app.services.calculator_probe_service import probe_samples_for_product
from app.services.simulator_service import _annuite_taksit


def test_aciklama_boilerplate_elenir() -> None:
    metin = (
        "İnternet Şubesi\n\n"
        "Konut finansmanı ile hayalinizdeki eve ulaşın. "
        "Esnek vade seçenekleri ve avantajlı kâr oranlarıyla başvurabilirsiniz.\n\n"
        "Çerez politikası ve KVKK aydınlatma metni için tıklayın."
    )
    aciklama = extract_product_description(metin, title="Konut Finansmanı")
    assert aciklama is not None
    assert "hayalinizdeki" in aciklama
    assert "çerez" not in aciklama.casefold()
    assert "kvkk" not in aciklama.casefold()


def test_aciklama_yetersizse_none() -> None:
    assert extract_product_description("Menü | Hesaplar | Kartlar") is None


def test_probe_ornekleri_bddk_hizali() -> None:
    ihtiyac = probe_samples_for_product("ihtiyac_finansmani")
    assert ihtiyac[0].amount == Decimal("10000") and ihtiyac[0].term_months == 36
    assert ihtiyac[-1].amount == Decimal("1000000") and ihtiyac[-1].term_months == 12

    tasit = probe_samples_for_product("tasit_finansmani")
    assert any(o.amount == Decimal("400000") and o.term_months == 48 for o in tasit)


def test_annuite_ters_cozum_albaraka() -> None:
    """Gold: 150k / 23 × 9169.06 → ~%3,0495 aylık."""
    ana = Decimal("150000")
    taksit = Decimal("9169.06")
    vade = 23
    toplam = taksit * vade
    oran = derive_rate_from_payment_plan(ana, toplam, vade)
    assert oran is not None
    assert abs(oran - Decimal("3.0495")) < Decimal("0.01")


def test_annuite_tutarlilik_esigi() -> None:
    """Yayımlanan oran + taksit tutarlıysa sapma küçük kalır."""
    ana = Decimal("500000")
    aylik_oran = Decimal("0.0305")
    vade = 36
    taksit = _annuite_taksit(ana, aylik_oran, vade)
    geri = derive_rate_from_payment_plan(ana, taksit * vade, vade)
    assert geri is not None
    assert abs(geri - Decimal("3.05")) < Decimal("0.02")


def test_tahsis_tavani() -> None:
    assert allocation_fee_cap_pct() == Decimal("0.5")


def test_ihtiyac_simulasyon_bddk_reddi(seeded_session) -> None:
    """1M TL ihtiyaç + 36 ay → BDDK 12 ay tavanı; teklif üretilmez."""
    from app.schemas.simulator import FinancingSimulationRequest
    from app.services.simulator_service import calculate_financing_simulation

    sonuc = calculate_financing_simulation(
        seeded_session,
        FinancingSimulationRequest(
            amount_try=Decimal("1000000"),
            term_months=36,
            product_type="ihtiyac_finansmani",
        ),
    )
    assert sonuc.offers == []
    assert "BDDK" in sonuc.method_note
    assert "12" in sonuc.method_note
