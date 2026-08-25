"""Hesaplayıcı probe'unun içsel tutarlılık kapıları.

Canlı veritabanından ÖLÇÜLEN gerçek satırlarla sabitlenir. İki sessiz hata:
bayat okuma (sayfa güncellenmeden okunuyor) ve yıllık maliyet oranının aylık
alana yazılması. İkisi de hata fırlatmıyor, yetkili görünen yanlış sayı
üretiyordu.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.calculator_probe_service import (
    AYLIK_ORAN_TAVANI,
    probe_orani_guvenilir_mi,
)


def _kontrol(oran, vade, taksit=None, toplam=None):
    return probe_orani_guvenilir_mi(
        profit_rate_pct=None if oran is None else Decimal(str(oran)),
        term_months=vade,
        monthly_installment=None if taksit is None else Decimal(str(taksit)),
        total_repayment=None if toplam is None else Decimal(str(toplam)),
    )


# ── G1: bayat okuma (gerçek satırlar) ────────────────────────────────────


@pytest.mark.parametrize(
    ("oran", "vade", "taksit", "toplam", "ima"),
    [
        # Albaraka: aynı taksit/toplam 36 VE 48 ay probe'unda; plan 23 ay ima ediyor.
        (64.49, 48, 10283.74, 236526.84, 23),
        (64.49, 36, 10283.74, 236526.84, 23),
        (82.44, 120, 9169.06, 210888.82, 23),
        (71.17, 120, 4895.74, 293744.08, 60),
        # Dünya Katılım: 12 aylık sonuç 24 ve 36 ay probe'larına yazılmış.
        (3.39, 24, 21816.71, 261800.49, 12),
        (3.39, 36, 1090.84, 13089.99, 12),
    ],
)
def test_bayat_okuma_reddedilir(oran, vade, taksit, toplam, ima) -> None:
    """⚠️ Makul GÖRÜNEN oran da reddedilir (3.39): başka bir vadenin
    sonucundan türetildiği için yine yanlış veridir."""
    tamam, neden = _kontrol(oran, vade, taksit, toplam)
    assert not tamam
    assert neden is not None
    assert f"{ima} ay ima ediyor" in neden


@pytest.mark.parametrize(
    ("oran", "vade", "taksit", "toplam"),
    [
        (3.39, 12, 21816.71, 261800.49),
        (3.39, 48, 10086.71, 484161.55),
        (2.99, 84, 48972.57, 4113695.84),
        (3.62, 36, 29085.14, 1047064.52),
        (4.25, 18, 44.54, 801.91),
        (3.99, 36, 6189.33, 222815.33),
    ],
)
def test_tutarli_okuma_gecer(oran, vade, taksit, toplam) -> None:
    """Planın ima ettiği vade probe ile örtüşüyor — meşru satır kaybedilmez."""
    tamam, neden = _kontrol(oran, vade, taksit, toplam)
    assert tamam, neden


# ── G2: aylık oran olamayan değerler ─────────────────────────────────────


def test_ayristirma_hatasi_reddedilir() -> None:
    """%5000: Türkiye Finans / Vakıf Katılım konut, 120 ay, 1.000.000₺.
    Oran kolonuna taksit tutarı yazılmış; plan verisi yok."""
    tamam, neden = _kontrol(5000, 120)
    assert not tamam
    assert "aylık oran olamaz" in str(neden)


def test_yillik_maliyet_orani_reddedilir() -> None:
    """Plan verisi olmadan gelen %62.1 (Kuveyt Türk konut) aylık oran değil."""
    tamam, neden = _kontrol(62.1, 36)
    assert not tamam
    assert "aylık oran olamaz" in str(neden)


@pytest.mark.parametrize("oran", [0, 0.89, 3.05, 6.1, 9.0, 19.99])
def test_guvenilir_kaynaklarin_araligi_korunur(oran) -> None:
    """Ölçülen tavan %9.0 (pdf_table); kapı meşru hiçbir oranı düşürmez."""
    tamam, neden = _kontrol(oran, 36)
    assert tamam, neden


def test_negatif_oran_reddedilir() -> None:
    tamam, neden = _kontrol(-1, 36)
    assert not tamam
    assert "negatif" in str(neden)


def test_oran_yoksa_yazilmaz() -> None:
    tamam, neden = _kontrol(None, 36)
    assert not tamam
    assert neden == "oran yok"


def test_tavan_belgelenen_degismezin_altinda() -> None:
    """`derive_rate_from_payment_plan`: "Aylık oran hiçbir gerçek üründe
    %100'ü aşmaz". Tavan bu değişmezin içinde kalmalı."""
    assert Decimal("100") > AYLIK_ORAN_TAVANI
    assert Decimal("9") < AYLIK_ORAN_TAVANI
