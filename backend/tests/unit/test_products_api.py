"""Ürün ve oran API uçları testleri (SPRINT 2.5 KAPI F5).

⚠️ Testler `api_client` fixture'ı üzerinden çalışır; geliştiricinin gerçek
veritabanına DOKUNMAZ. Router'lar `app.db.session.get_db`'yi doğrudan
kullandığı sürece fixture'ın bağımlılık değiştirmesi etkisiz kalıyordu ve
testler sessizce canlı veriyi okuyordu.
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.bank import Bank
from app.db.models.product import Product, ProductRate


def _urun_ekle(
    session: Session,
    *,
    banka_kodu: str,
    ad: str,
    urun_turu: str = "tasit_finansmani",
    oranlar: list[dict[str, object]] | None = None,
) -> Product:
    """Test için ürün ve oranlarını ekler."""
    banka = session.scalar(select(Bank).where(Bank.code == banka_kodu))
    assert banka is not None, f"seed'de banka yok: {banka_kodu}"

    urun = Product(
        bank_id=banka.id,
        external_key=f"{banka_kodu}:{ad}",
        name=ad,
        product_type=urun_turu,
    )
    session.add(urun)
    session.flush()

    for i, o in enumerate(oranlar or []):
        session.add(
            ProductRate(
                product_id=urun.id,
                band_key=f"{ad}-{i}",
                rate_type=str(o.get("rate_type", "financing_rate")),
                profit_rate_pct=o.get("profit_rate_pct"),
                allocation_fee_pct=o.get("allocation_fee_pct"),
                investor_share_pct=o.get("investor_share_pct"),
                bank_share_pct=o.get("bank_share_pct"),
                term_months=o.get("term_months"),
                currency=str(o.get("currency", "TRY")),
                evidence_text=str(o.get("evidence_text", f"{ad} kanıt {i}")),
            )
        )
    session.flush()
    return urun


@pytest.fixture
def urunlu_oturum(seeded_session: Session) -> Session:
    """İki bankada oranlı ürün bulunan oturum."""
    _urun_ekle(
        seeded_session,
        banka_kodu="albaraka",
        ad="Taşıt Finansmanı",
        oranlar=[
            {
                "profit_rate_pct": Decimal("3.05"),
                "term_months": 36,
                "allocation_fee_pct": Decimal("0.50"),
            },
        ],
    )
    _urun_ekle(
        seeded_session,
        banka_kodu="kuveyt_turk",
        ad="Araç Finansmanı",
        oranlar=[
            {
                "profit_rate_pct": Decimal("3.48"),
                "term_months": 36,
                "allocation_fee_pct": Decimal("0.25"),
            },
        ],
    )
    _urun_ekle(
        seeded_session,
        banka_kodu="turkiye_finans",
        ad="Katılma Hesabı",
        urun_turu="birikim_katilma_hesabi",
        oranlar=[
            {
                "rate_type": "participation_yield",
                "profit_rate_pct": Decimal("31.21"),
                "term_months": 12,
            },
        ],
    )
    return seeded_session


def test_urun_listesi_doner(api_client: httpx.Client, urunlu_oturum: Session) -> None:
    yanit = api_client.get("/api/v1/products")

    assert yanit.status_code == 200
    assert len(yanit.json()) == 3


def test_oran_turu_suzgeci_yalnizca_o_turu_birakir(
    api_client: httpx.Client, urunlu_oturum: Session
) -> None:
    """Süzgeç hem ÜRÜNÜ hem ORANLARI süzmeli."""
    yanit = api_client.get("/api/v1/products?rate_type=participation_yield")

    veri = yanit.json()
    assert len(veri) == 1
    assert veri[0]["name"] == "Katılma Hesabı"
    assert {o["rate_type"] for o in veri[0]["rates"]} == {"participation_yield"}


def test_gecersiz_oran_turu_422_doner(api_client: httpx.Client, urunlu_oturum: Session) -> None:
    """⚠️ Sözlükte olmayan tür sessizce boş liste döndürmemeli.

    Boş liste "bu türde ürün yok" gibi okunur; yazım hatası fark edilmez.
    """
    yanit = api_client.get("/api/v1/products?rate_type=faiz_orani")

    assert yanit.status_code == 422


def test_urun_detayi_oranlari_ve_limitleri_verir(
    api_client: httpx.Client, urunlu_oturum: Session
) -> None:
    urun = urunlu_oturum.scalar(select(Product).where(Product.name == "Taşıt Finansmanı"))
    assert urun is not None

    yanit = api_client.get(f"/api/v1/products/{urun.id}")

    assert yanit.status_code == 200
    veri = yanit.json()
    assert veri["name"] == "Taşıt Finansmanı"
    assert veri["bank_code"] == "albaraka"
    assert len(veri["rates"]) == 1
    assert "limits" in veri and "variants" in veri


def test_urun_detayi_kanit_metnini_tasir(api_client: httpx.Client, urunlu_oturum: Session) -> None:
    """⚠️ Kanıt olmadan arayüz "bu oran nereden geldi" sorusunu yanıtlayamaz."""
    urun = urunlu_oturum.scalar(select(Product).where(Product.name == "Taşıt Finansmanı"))
    assert urun is not None

    veri = api_client.get(f"/api/v1/products/{urun.id}").json()

    assert veri["rates"][0]["evidence_text"]


def test_olmayan_urun_404_doner(api_client: httpx.Client, urunlu_oturum: Session) -> None:
    assert api_client.get("/api/v1/products/999999").status_code == 404


def test_olmayan_banka_404_doner(api_client: httpx.Client, urunlu_oturum: Session) -> None:
    assert api_client.get("/api/v1/products?bank_code=yok_boyle_banka").status_code == 404
