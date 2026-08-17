"""Kampanya ve istatistik uçlarının testleri."""

from __future__ import annotations

from datetime import date

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Bank, Campaign


@pytest.fixture
def ornek_kampanyalar(seeded_session: Session) -> None:
    """Farklı durum ve tarih kesinliklerini kapsayan örnek veri."""
    emlak = seeded_session.scalar(select(Bank).where(Bank.code == "emlak_katilim"))
    hayat = seeded_session.scalar(select(Bank).where(Bank.code == "hayat_finans"))
    assert emlak is not None and hayat is not None

    seeded_session.add_all(
        [
            Campaign(
                bank_id=emlak.id,
                external_slug="akaryakit-kampanyasi",
                title="Akaryakıt Kampanyası",
                description="Akaryakıt harcamalarına hediye",
                source_url="https://ornek/akaryakit",
                segment="bireysel",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 31),
                date_precision="exact",
                date_evidence_text="01.01.2026 - 31.12.2026",
                date_evidence_source="body",
                status="active",
            ),
            Campaign(
                bank_id=emlak.id,
                external_slug="market-kampanyasi",
                title="Market Kampanyası",
                description="Market alışverişlerinde taksit",
                source_url="https://ornek/market",
                segment="bireysel",
                end_date=date(2026, 12, 31),
                date_precision="partial",
                status="active",
            ),
            Campaign(
                bank_id=hayat.id,
                external_slug="katilma-hesabi",
                title="Katılma Hesabı Fırsatı",
                source_url="https://ornek/katilma",
                start_date=date(2026, 1, 1),
                end_date=date(2026, 3, 31),
                date_precision="exact",
                date_evidence_text="01.01.2026 - 31.12.2026",
                date_evidence_source="body",
                status="expired",
            ),
            Campaign(
                bank_id=hayat.id,
                external_slug="tarihsiz-kampanya",
                title="Tarihsiz Kampanya",
                source_url="https://ornek/tarihsiz",
                date_precision="unknown",
                status="unknown",
            ),
            Campaign(
                bank_id=hayat.id,
                external_slug="gelecek-kampanya",
                title="Gelecek Kampanya",
                source_url="https://ornek/gelecek",
                start_date=date(2026, 12, 1),
                end_date=date(2026, 12, 31),
                date_precision="exact",
                date_evidence_text="01.01.2026 - 31.12.2026",
                date_evidence_source="body",
                status="upcoming",
            ),
        ]
    )
    seeded_session.commit()


class TestKampanyaListesi:
    def test_sayfali_yanit_semasi(self, api_client: httpx.Client, ornek_kampanyalar: None) -> None:
        veri = api_client.get("/api/v1/campaigns").json()

        assert set(veri) == {"items", "total", "page", "page_size", "total_pages"}
        assert veri["total"] == 5
        assert veri["page"] == 1
        assert veri["page_size"] == 25
        assert veri["total_pages"] == 1

    def test_sayfalama(self, api_client: httpx.Client, ornek_kampanyalar: None) -> None:
        veri = api_client.get("/api/v1/campaigns?page_size=2&page=2").json()

        assert len(veri["items"]) == 2
        assert veri["page"] == 2
        assert veri["total_pages"] == 3

    def test_banka_filtresi(self, api_client: httpx.Client, ornek_kampanyalar: None) -> None:
        veri = api_client.get("/api/v1/campaigns?bank=emlak_katilim").json()

        assert veri["total"] == 2
        assert all(i["bank_code"] == "emlak_katilim" for i in veri["items"])

    def test_coklu_banka_filtresi(self, api_client: httpx.Client, ornek_kampanyalar: None) -> None:
        veri = api_client.get("/api/v1/campaigns?bank=emlak_katilim&bank=hayat_finans").json()
        assert veri["total"] == 5

    def test_durum_filtresi(self, api_client: httpx.Client, ornek_kampanyalar: None) -> None:
        veri = api_client.get("/api/v1/campaigns?status=expired").json()

        assert veri["total"] == 1
        assert veri["items"][0]["title"] == "Katılma Hesabı Fırsatı"

    def test_unknown_durumu_expired_den_ayridir(
        self, api_client: httpx.Client, ornek_kampanyalar: None
    ) -> None:
        """⚠️ Tarihi olmayan kampanya "süresi dolmuş" DEĞİLDİR."""
        unknown = api_client.get("/api/v1/campaigns?status=unknown").json()
        expired = api_client.get("/api/v1/campaigns?status=expired").json()

        assert unknown["total"] == 1
        assert unknown["items"][0]["title"] == "Tarihsiz Kampanya"
        assert unknown["items"][0]["start_date"] is None
        assert unknown["items"][0]["end_date"] is None
        # İki küme kesişmiyor.
        assert {i["id"] for i in unknown["items"]}.isdisjoint({i["id"] for i in expired["items"]})

    def test_arama(self, api_client: httpx.Client, ornek_kampanyalar: None) -> None:
        veri = api_client.get("/api/v1/campaigns?q=market").json()

        assert veri["total"] == 1
        assert veri["items"][0]["external_slug"] == "market-kampanyasi"

    def test_siralama(self, api_client: httpx.Client, ornek_kampanyalar: None) -> None:
        veri = api_client.get("/api/v1/campaigns?sort=title&order=desc").json()
        basliklar = [i["title"] for i in veri["items"]]
        assert basliklar == sorted(basliklar, reverse=True)

    def test_tarih_siralamasinda_bos_degerler_sonda(
        self, api_client: httpx.Client, ornek_kampanyalar: None
    ) -> None:
        """Tarihi bilinmeyen kampanyalar listenin başında görünmemeli."""
        veri = api_client.get("/api/v1/campaigns?sort=start_date&order=asc").json()
        tarihler = [i["start_date"] for i in veri["items"]]

        dolu = [t for t in tarihler if t is not None]
        assert tarihler[: len(dolu)] == dolu

    def test_gecersiz_durum_degeri_422(self, api_client: httpx.Client) -> None:
        yanit = api_client.get("/api/v1/campaigns?status=gecersiz")

        assert yanit.status_code == 422
        assert yanit.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_page_size_ust_siniri(self, api_client: httpx.Client) -> None:
        assert api_client.get("/api/v1/campaigns?page_size=101").status_code == 422


class TestBosSonucHataDegildir:
    """⚠️ Bu ayrım kritiktir: boş sonuç 200, hata 4xx/5xx."""

    def test_eslesme_yoksa_200_ve_bos_liste(
        self, api_client: httpx.Client, ornek_kampanyalar: None
    ) -> None:
        yanit = api_client.get("/api/v1/campaigns?q=kesinlikle-olmayan-bir-metin")

        assert yanit.status_code == 200
        veri = yanit.json()
        assert veri["items"] == []
        assert veri["total"] == 0
        assert "error" not in veri

    def test_veri_yokken_bile_200(self, api_client: httpx.Client) -> None:
        """Hiç kampanya yokken de liste ucu başarıyla döner."""
        yanit = api_client.get("/api/v1/campaigns")
        assert yanit.status_code == 200
        assert yanit.json()["total"] == 0


class TestKampanyaDetayi:
    def test_detay_banka_ve_kaynak_ile_doner(
        self, api_client: httpx.Client, ornek_kampanyalar: None
    ) -> None:
        liste = api_client.get("/api/v1/campaigns?q=akaryakıt").json()
        kampanya_id = liste["items"][0]["id"]

        veri = api_client.get(f"/api/v1/campaigns/{kampanya_id}").json()

        assert veri["title"] == "Akaryakıt Kampanyası"
        assert veri["bank"]["code"] == "emlak_katilim"
        assert veri["date_precision"] == "exact"
        assert "conditions_text" in veri

    def test_olmayan_kampanya_404(self, api_client: httpx.Client) -> None:
        yanit = api_client.get("/api/v1/campaigns/999999")

        assert yanit.status_code == 404
        assert yanit.json()["error"]["code"] == "NOT_FOUND"


class TestSaglik:
    def test_health(self, api_client: httpx.Client) -> None:
        veri = api_client.get("/api/v1/health").json()

        assert veri["status"] == "ok"
        assert veri["db_ok"] is True
        assert veri["campaign_count"] == 0
        assert veri["version"]


class TestIstatistikler:
    def test_sayimlar(self, api_client: httpx.Client, ornek_kampanyalar: None) -> None:
        veri = api_client.get("/api/v1/stats").json()

        assert veri["total_banks"] == 10
        assert veri["banks_with_data"] == 2
        assert veri["total_campaigns"] == 5
        assert veri["active_campaigns"] == 2
        assert veri["upcoming_campaigns"] == 1
        assert veri["expired_campaigns"] == 1
        assert veri["unknown_status_campaigns"] == 1

    def test_toplamlar_tutarli(self, api_client: httpx.Client, ornek_kampanyalar: None) -> None:
        veri = api_client.get("/api/v1/stats").json()
        parcalar = (
            veri["active_campaigns"]
            + veri["upcoming_campaigns"]
            + veri["expired_campaigns"]
            + veri["unknown_status_campaigns"]
        )
        assert parcalar == veri["total_campaigns"]

    def test_kampanyasiz_bankalar_dagilimda_sifirla_yer_alir(
        self, api_client: httpx.Client, ornek_kampanyalar: None
    ) -> None:
        veri = api_client.get("/api/v1/stats").json()
        dagilim = {b["bank_code"]: b["count"] for b in veri["campaigns_by_bank"]}

        assert len(dagilim) == 10
        assert dagilim["adil_katilim"] == 0
        assert dagilim["emlak_katilim"] == 2

    def test_kategori_dagilimi_part1_de_null(
        self, api_client: httpx.Client, ornek_kampanyalar: None
    ) -> None:
        """PART 1'de kategori sınıflandırması yok; tüm kayıtlar null grubunda."""
        veri = api_client.get("/api/v1/stats").json()
        assert veri["campaigns_by_category"] == [{"category": None, "count": 5}]
