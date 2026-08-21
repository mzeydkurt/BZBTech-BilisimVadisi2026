"""Finansmanlar (KAPI 6) ve Katılım Hesabı (KAPI 7) sekmelerinin API uçları."""

from __future__ import annotations

from decimal import Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.bank import Bank
from app.db.models.product import Product, ProductRate


def _urun_ekle(
    session: Session,
    *,
    banka_kodu: str,
    ad: str,
    urun_turu: str,
    variant_key: str | None = None,
    availability_status: str = "unknown",
) -> Product:
    banka = session.scalar(select(Bank).where(Bank.code == banka_kodu))
    assert banka is not None, f"seed'de banka yok: {banka_kodu}"

    urun = Product(
        bank_id=banka.id,
        external_key=f"{banka_kodu}:{ad}:{variant_key or 'base'}",
        name=ad,
        product_type=urun_turu,
        variant_key=variant_key,
        availability_status=availability_status,
    )
    session.add(urun)
    session.flush()
    return urun


class TestFinansmanlarUcu:
    def test_katilma_hesabi_sizmaz(self, seeded_session: Session, api_client: httpx.Client) -> None:
        _urun_ekle(
            seeded_session,
            banka_kodu="albaraka",
            ad="Konut Finansmanı",
            urun_turu="konut_finansmani",
        )
        _urun_ekle(
            seeded_session, banka_kodu="albaraka", ad="Katılma Hesabı", urun_turu="katilma_hesabi"
        )

        veri = api_client.get("/api/v1/financing").json()
        adlar = {u["name"] for u in veri["financing"]}

        assert "Konut Finansmanı" in adlar
        assert "Katılma Hesabı" not in adlar

    def test_oransiz_urun_no_data_listesine_girer(
        self, seeded_session: Session, api_client: httpx.Client
    ) -> None:
        _urun_ekle(
            seeded_session,
            banka_kodu="ziraat_katilim",
            ad="Gayrimenkul Finansmanı",
            urun_turu="gayrimenkul_finansmani",
        )

        veri = api_client.get("/api/v1/financing").json()

        assert any("Gayrimenkul Finansmanı" in item for item in veri["no_data_products"])
        assert veri["coverage_note"]

    def test_karz_i_hasen_kar_paysiz_isaretlenir(
        self, seeded_session: Session, api_client: httpx.Client
    ) -> None:
        urun = _urun_ekle(
            seeded_session,
            banka_kodu="dunya_katilim",
            ad="Enerya Karz-ı Hasen",
            urun_turu="karz_i_hasen",
        )
        seeded_session.add(
            ProductRate(
                product_id=urun.id,
                rate_type="interest_free_benevolent_loan",
                rate_source="html_table",
                evidence_text="vade farksız, kâr payı alınmaz",
            )
        )
        seeded_session.flush()

        veri = api_client.get("/api/v1/financing?product_type=karz_i_hasen").json()

        assert len(veri["financing"]) == 1
        urun_ciktisi = veri["financing"][0]
        assert urun_ciktisi["rates"][0]["rate_type"] == "interest_free_benevolent_loan"
        assert urun_ciktisi["rates"][0]["profit_rate_pct"] is None

    def test_gecersiz_urun_turu_422(self, api_client: httpx.Client) -> None:
        yanit = api_client.get("/api/v1/financing?product_type=uydurma_tur")
        assert yanit.status_code == 422

    def test_banka_bulunamadi_404(self, api_client: httpx.Client) -> None:
        yanit = api_client.get("/api/v1/financing?bank_code=olmayan_banka")
        assert yanit.status_code == 404


class TestKatilimHesabiUcu:
    def test_birikim_katilma_hesabi_gercek_veride_kullanilan_tur(
        self, seeded_session: Session, api_client: httpx.Client
    ) -> None:
        """⚠️ Regresyon: SPRINT 2-4'ün scraper'ları katılma hesabı ürünlerini
        `katilma_hesabi` değil `birikim_katilma_hesabi` ile etiketliyor —
        bu tip kapsamdan eksik kalırsa sekme gerçek veriyle boş görünür
        (ölçüldü, bkz. `app/core/vocab.py::KATILIM_HESABI_TIPLERI` yorumu).
        """
        urun = _urun_ekle(
            seeded_session,
            banka_kodu="ziraat_katilim",
            ad="Katılma Hesabı",
            urun_turu="birikim_katilma_hesabi",
        )
        seeded_session.add(
            ProductRate(
                product_id=urun.id,
                rate_type="profit_sharing_ratio",
                rate_source="html_table",
                term_months=1,
                currency="TRY",
                investor_share_pct=Decimal("90.000"),
            )
        )
        seeded_session.flush()

        veri = api_client.get("/api/v1/katilim-hesabi?rate_type=profit_sharing_ratio").json()
        kodlar = {r["bank_code"] for r in veri["rows"]}

        assert "ziraat_katilim" in kodlar

    def test_pivot_satirlari_dogru_kurulur(
        self, seeded_session: Session, api_client: httpx.Client
    ) -> None:
        urun = _urun_ekle(
            seeded_session, banka_kodu="albaraka", ad="Katılma Hesabı", urun_turu="katilma_hesabi"
        )
        seeded_session.add_all(
            [
                ProductRate(
                    product_id=urun.id,
                    rate_type="participation_yield",
                    rate_source="html_table",
                    term_months=1,
                    currency="TRY",
                    profit_rate_pct=Decimal("31.35"),
                ),
                ProductRate(
                    product_id=urun.id,
                    rate_type="participation_yield",
                    rate_source="html_table",
                    term_months=12,
                    currency="TRY",
                    profit_rate_pct=Decimal("40.86"),
                ),
            ]
        )
        seeded_session.flush()

        veri = api_client.get("/api/v1/katilim-hesabi").json()
        satir = next(r for r in veri["rows"] if r["bank_code"] == "albaraka")

        assert Decimal(satir["values"]["aylik|TRY"]) == Decimal("31.35")
        assert Decimal(satir["values"]["yillik|TRY"]) == Decimal("40.86")
        assert satir["data_source"] == "bank_site"
        assert satir["cross_check"] is None

    def test_ara_odemeli_yalnizca_isaretli_bankalarda(
        self, seeded_session: Session, api_client: httpx.Client
    ) -> None:
        urun = _urun_ekle(
            seeded_session,
            banka_kodu="albaraka",
            ad="Ara Ödemeli Katılma Hesabı",
            urun_turu="ara_donem_kar_odemeli",
            variant_key="ara_odemeli",
        )
        seeded_session.add(
            ProductRate(
                product_id=urun.id,
                rate_type="participation_yield",
                rate_source="seed_manual",
                data_source="tkbb_veripetegi",
                term_months=1,
                currency="TRY",
                profit_rate_pct=Decimal("34.36"),
            )
        )
        # Sunmayan banka: `availability_status='not_offered'`, oran satırı yok.
        _urun_ekle(
            seeded_session,
            banka_kodu="dunya_katilim",
            ad="Ara Ödemeli Katılma Hesabı",
            urun_turu="ara_donem_kar_odemeli",
            variant_key="ara_odemeli",
            availability_status="not_offered",
        )
        seeded_session.flush()

        veri = api_client.get("/api/v1/katilim-hesabi?variant=ara_odemeli").json()

        kodlar = {r["bank_code"] for r in veri["rows"]}
        assert "albaraka" in kodlar
        assert "dunya_katilim" not in kodlar
        assert "Dünya Katılım" in veri["not_offered_banks"]

    def test_cross_check_iki_kaynak_da_varsa_dolar(
        self, seeded_session: Session, api_client: httpx.Client
    ) -> None:
        urun = _urun_ekle(
            seeded_session,
            banka_kodu="vakif_katilim",
            ad="Katılma Hesabı",
            urun_turu="katilma_hesabi",
        )
        seeded_session.add_all(
            [
                ProductRate(
                    product_id=urun.id,
                    rate_type="participation_yield",
                    rate_source="html_table",
                    data_source="bank_site",
                    term_months=1,
                    currency="TRY",
                    profit_rate_pct=Decimal("31.20"),
                ),
                ProductRate(
                    product_id=urun.id,
                    rate_type="participation_yield",
                    rate_source="seed_manual",
                    data_source="tkbb_veripetegi",
                    term_months=1,
                    currency="TRY",
                    profit_rate_pct=Decimal("31.50"),
                ),
            ]
        )
        seeded_session.flush()

        veri = api_client.get("/api/v1/katilim-hesabi").json()
        satir = next(r for r in veri["rows"] if r["bank_code"] == "vakif_katilim")

        assert satir["data_source"] == "tkbb_veripetegi"
        assert satir["cross_check"] is not None
        assert satir["cross_check"]["match"] == "yakin"

    def test_gecersiz_rate_type_422(self, api_client: httpx.Client) -> None:
        yanit = api_client.get("/api/v1/katilim-hesabi?rate_type=financing_rate")
        assert yanit.status_code == 422

    def test_anomali_notu_evidence_textten_gelir(
        self, seeded_session: Session, api_client: httpx.Client
    ) -> None:
        urun = _urun_ekle(
            seeded_session,
            banka_kodu="vakif_katilim",
            ad="Ara Ödemeli Katılma Hesabı",
            urun_turu="ara_donem_kar_odemeli",
            variant_key="ara_odemeli",
        )
        seeded_session.add(
            ProductRate(
                product_id=urun.id,
                rate_type="participation_yield",
                rate_source="seed_manual",
                data_source="tkbb_veripetegi",
                term_months=6,
                currency="TRY",
                profit_rate_pct=Decimal("25.39"),
                evidence_text=(
                    "TKBB kaynağında tekdüze artan örüntüyü bozan anomali — "
                    "banka kendi sitesinden çapraz doğrulanmalı"
                ),
            )
        )
        seeded_session.flush()

        veri = api_client.get("/api/v1/katilim-hesabi?variant=ara_odemeli").json()

        assert len(veri["data_quality_notes"]) == 1
        assert "anomali" in veri["data_quality_notes"][0].lower()
