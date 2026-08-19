"""Sıralama, sohbet ve istatistik API uçları testleri.

⚠️ `api_client` fixture'ı kullanılır; testler geliştiricinin gerçek
veritabanına dokunmaz.
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.bank import Bank
from app.db.models.product import Product, ProductRate


@pytest.fixture
def siralanabilir_oturum(seeded_session: Session) -> Session:
    """İki bankada finansman oranı bulunan oturum."""
    for kod, ad, oran, vade in (
        ("albaraka", "Ucuz Taşıt", Decimal("3.05"), 36),
        ("kuveyt_turk", "Pahalı Taşıt", Decimal("4.20"), 36),
    ):
        banka = seeded_session.scalar(select(Bank).where(Bank.code == kod))
        assert banka is not None
        urun = Product(
            bank_id=banka.id,
            external_key=f"{kod}:{ad}",
            name=ad,
            product_type="tasit_finansmani",
        )
        seeded_session.add(urun)
        seeded_session.flush()
        seeded_session.add(
            ProductRate(
                product_id=urun.id,
                band_key=ad,
                rate_type="financing_rate",
                profit_rate_pct=oran,
                term_months=vade,
                currency="TRY",
                evidence_text=f"{ad} | {vade} ay | %{oran}",
            )
        )
    seeded_session.flush()
    return seeded_session


class TestSiralamaUcu:
    def test_siralama_kazananı_ve_gerekcesini_doner(
        self, api_client: httpx.Client, siralanabilir_oturum: Session
    ) -> None:
        yanit = api_client.post(
            "/api/v1/products/compare",
            json={"rate_type": "financing_rate", "criterion": "en_dusuk_kar_payi"},
        )

        assert yanit.status_code == 200
        veri = yanit.json()
        assert veri["winner"]["bank_code"] == "albaraka"
        assert veri["winner_reason"]

    def test_rate_type_zorunludur(
        self, api_client: httpx.Client, siralanabilir_oturum: Session
    ) -> None:
        """⚠️ Varsayılan oran türü YOK; verilmezse istek reddedilir."""
        yanit = api_client.post("/api/v1/products/compare", json={"criterion": "en_dusuk_kar_payi"})

        assert yanit.status_code == 422

    def test_bagdasmayan_olcut_422_doner(
        self, api_client: httpx.Client, siralanabilir_oturum: Session
    ) -> None:
        yanit = api_client.post(
            "/api/v1/products/compare",
            json={"rate_type": "financing_rate", "criterion": "en_yuksek_getiri"},
        )

        assert yanit.status_code == 422
        # Hatalar tek biçimli zarfla döner: {"error": {"code","message","detail"}}
        assert "participation_yield" in yanit.json()["error"]["message"]

    def test_yanit_veri_yok_grubunu_tasir(
        self, api_client: httpx.Client, siralanabilir_oturum: Session
    ) -> None:
        yanit = api_client.post(
            "/api/v1/products/compare",
            json={"rate_type": "financing_rate", "criterion": "en_dusuk_masraf"},
        )

        assert "without_data" in yanit.json()


class TestSohbetUcu:
    def test_yasakli_terim_uyarisi_doner(self, api_client: httpx.Client) -> None:
        yanit = api_client.post(
            "/api/v1/chat",
            json={"query": "En düşük faiz oranı hangi katılım bankasında var?"},
        )

        assert yanit.status_code == 200
        uyari = yanit.json()["forbidden_terms_warning"]
        assert uyari is not None
        assert "kâr payı" in uyari

    def test_uyari_metninde_emoji_yoktur(self, api_client: httpx.Client) -> None:
        """⚠️ Arayüze giden metinde emoji kullanılmaz (CLAUDE.md)."""
        yanit = api_client.post("/api/v1/chat", json={"query": "faiz oranı nedir"})

        uyari = yanit.json()["forbidden_terms_warning"] or ""
        assert not any(ord(k) > 0x2100 for k in uyari), f"emoji bulundu: {uyari!r}"


def test_istatistik_ucu_alanlari(api_client: httpx.Client) -> None:
    yanit = api_client.get("/api/v1/stats")

    assert yanit.status_code == 200
    veri = yanit.json()
    assert {"radar_scores", "sector_distribution", "products_total"} <= veri.keys()
