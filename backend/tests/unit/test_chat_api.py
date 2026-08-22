"""Kanıtlı arama uç noktası — yanıt sözleşmesi ve boş/hata ayrımı.

⚠️ AĞA ÇIKMAZ. `conftest.py` `LLM_PROVIDER=mock` sabitliyor ve ağ koruması
gerçek isteği düşürüyor; yanıt metni `MockProvider`'dan gelir.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Bank, Campaign, CampaignCategory, CampaignMetric, EntityCard
from app.retrieval.corpus import invalidate_corpus


@pytest.fixture(autouse=True)
def _govdeyi_temizle() -> None:
    """⚠️ Gövde önbelleği testler arasında sızmamalı.

    Parmak izi denetimi bunu zaten yakalıyor ama testler aynı sayıları
    üretebilir; açık düşürme ölçümü kesinleştirir.
    """
    invalidate_corpus()


def _kampanya_ekle(
    session: Session,
    *,
    bank_code: str,
    campaign_id: int,
    title: str,
    card_text: str,
    sector: str | None = None,
    product_type: str | None = None,
    profit_rate: str | None = None,
    reward: str | None = None,
    status: str = "active",
) -> Campaign:
    """Aranabilir tek bir kampanya kurar (kampanya + kart + etiket + metrik)."""
    banka = session.scalar(select(Bank).where(Bank.code == bank_code))
    assert banka is not None
    kampanya = Campaign(
        id=campaign_id,
        bank_id=banka.id,
        external_slug=f"slug-{campaign_id}",
        title=title,
        source_url=f"https://example.test/{campaign_id}",
        status=status,
        # ⚠️ `date_precision='exact'` kanıt metni olmadan geçersizdir —
        # veritabanı düzeyinde CHECK ile zorlanıyor (CLAUDE.md).
        date_precision="exact",
        date_evidence_text="Kampanya Dönemi: 01.01.2026 - 31.12.2026",
        date_evidence_source="structured",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
    )
    session.add(kampanya)
    session.flush()

    session.add(
        EntityCard(
            entity_type="campaign",
            entity_id=campaign_id,
            card_text=card_text,
            card_hash=f"hash-{campaign_id}",
        )
    )
    for eksen, deger in (("sector", sector), ("product_type", product_type)):
        if not deger:
            continue
        session.add(
            CampaignCategory(
                campaign_id=campaign_id,
                axis=eksen,
                value=deger,
                source="keyword",
                confidence=Decimal("0.700"),
                evidence="test",
            )
        )
    if profit_rate or reward:
        session.add(
            CampaignMetric(
                campaign_id=campaign_id,
                profit_rate_pct=Decimal(profit_rate) if profit_rate else None,
                reward_amount_try=Decimal(reward) if reward else None,
            )
        )
    session.commit()
    return kampanya


@pytest.fixture
def dolu_oturum(seeded_session: Session) -> Session:
    """Üç bankadan dört aranabilir kampanya."""
    _kampanya_ekle(
        seeded_session,
        bank_code="kuveyt_turk",
        campaign_id=101,
        title="Market Alışverişlerinde Hediye Çeki",
        card_text="Kuveyt Türk — market alışverişinde 250 TL hediye çeki kazanın.",
        sector="market_gida",
        reward="250",
    )
    _kampanya_ekle(
        seeded_session,
        bank_code="albaraka",
        campaign_id=102,
        title="Akaryakıt İndirimi",
        card_text="Albaraka Türk — akaryakıt alışverişlerinde indirim.",
        sector="akaryakit",
    )
    _kampanya_ekle(
        seeded_session,
        bank_code="kuveyt_turk",
        campaign_id=103,
        title="Avantajlı Finansman",
        card_text="Kuveyt Türk — kâr payı oranı %1,50 ile finansman.",
        product_type="finansman",
        profit_rate="1.50",
    )
    _kampanya_ekle(
        seeded_session,
        bank_code="albaraka",
        campaign_id=104,
        title="Standart Finansman",
        card_text="Albaraka Türk — kâr payı oranı %4,20 ile finansman.",
        product_type="finansman",
        profit_rate="4.20",
    )
    return seeded_session


class TestYanitSozlesmesi:
    def test_anladigim_ciplari_kanitla_doner(
        self, api_client: httpx.Client, dolu_oturum: Session
    ) -> None:
        """Sistemin soruyu nasıl anladığı yanıtta görünmeli."""
        veri = api_client.post(
            "/api/v1/chat", json={"query": "Kuveyt Türk'te market kampanyası"}
        ).json()

        turler = {cip["kind"] for cip in veri["understood"]}
        assert "bank" in turler
        assert "sector" in turler
        for cip in veri["understood"]:
            assert cip["evidence"].strip(), "kanıtsız süzgeç arayüzde gösterilemez"

    def test_erisim_seridi_dolu_doner(self, api_client: httpx.Client, dolu_oturum: Session) -> None:
        veri = api_client.post("/api/v1/chat", json={"query": "market kampanyası"}).json()

        rapor = veri["retrieval"]
        assert rapor["corpus_size"] == 4
        assert rapor["returned"] >= 1
        assert rapor["elapsed_ms"] >= 0
        # Gömme üretilmemiş; durum sessizce gizlenmemeli.
        assert rapor["semantic_used"] is False
        assert rapor["semantic_note"]

    def test_sonuclar_kanit_metni_ve_kaynak_tasir(
        self, api_client: httpx.Client, dolu_oturum: Session
    ) -> None:
        veri = api_client.post("/api/v1/chat", json={"query": "market kampanyası"}).json()

        assert veri["results"], "sonuç bekleniyordu"
        ilk = veri["results"][0]
        assert ilk["card_text"].strip()
        assert ilk["source_url"].startswith("https://")
        # ⚠️ Durum backend'de hesaplanır; arayüz yeniden hesaplamaz.
        assert ilk["status"] in {"active", "expired", "upcoming", "unknown"}


class TestSertSuzgec:
    def test_sayisal_esik_uygulanir(self, api_client: httpx.Client, dolu_oturum: Session) -> None:
        """⚠️ %4,20'lik kampanya, metni ne kadar benzerse benzesin dönmemeli."""
        veri = api_client.post(
            "/api/v1/chat",
            json={"query": "kâr payı oranı %2'nin altında olan finansman"},
        ).json()

        kimlikler = {sonuc["campaign_id"] for sonuc in veri["results"]}
        assert 103 in kimlikler
        assert 104 not in kimlikler

    def test_banka_suzgeci_sorgu_metnini_ezer(
        self, api_client: httpx.Client, dolu_oturum: Session
    ) -> None:
        """⚠️ Metinde bir banka, açılır listede başka banka varsa SON EYLEM kazanır.

        İkisini birleştirmek daima boş sonuç verirdi.
        """
        veri = api_client.post(
            "/api/v1/chat",
            json={"query": "Kuveyt Türk kampanyaları", "bank_code": "albaraka"},
        ).json()

        kodlar = {sonuc["bank_code"] for sonuc in veri["results"]}
        assert kodlar == {"albaraka"}


class TestBosSonucHataDegildir:
    def test_bos_sonuc_200_doner(self, api_client: httpx.Client, dolu_oturum: Session) -> None:
        """⚠️ 4xx döndürmek arayüzde `ErrorState` tetikler; "veri yok" ile karışır."""
        yanit = api_client.post("/api/v1/chat", json={"query": "Adil Katılım kampanyaları"})

        assert yanit.status_code == 200
        assert yanit.json()["results"] == []

    def test_bos_sonucta_gevsetme_onerisi_doner(
        self, api_client: httpx.Client, dolu_oturum: Session
    ) -> None:
        """Kullanıcı hangi süzgeci kaldırınca ne çıkacağını görmeli."""
        veri = api_client.post(
            "/api/v1/chat", json={"query": "Albaraka'da market kampanyası"}
        ).json()

        assert veri["results"] == []
        assert veri["relaxation_hints"]
        assert all(oneri["hit_count"] > 0 for oneri in veri["relaxation_hints"])

    def test_kart_yokken_model_cagrilmaz(
        self, api_client: httpx.Client, dolu_oturum: Session
    ) -> None:
        veri = api_client.post("/api/v1/chat", json={"query": "Adil Katılım kampanyaları"}).json()

        assert veri["answer"]["source"] == "refusal"


class TestToplama:
    def test_uc_deger_tum_kayitlar_uzerinden(
        self, api_client: httpx.Client, dolu_oturum: Session
    ) -> None:
        veri = api_client.post(
            "/api/v1/chat", json={"query": "Hangi bankada en düşük kâr payı oranı var?"}
        ).json()

        assert veri["intent"] == "aggregate"
        toplama = veri["aggregate"]
        assert toplama["kind"] == "extremum"
        assert Decimal(str(toplama["value"])) == Decimal("1.50")
        assert toplama["winner_campaign_id"] == 103

    def test_veri_olmayan_kayit_sayisi_gizlenmez(
        self, api_client: httpx.Client, dolu_oturum: Session
    ) -> None:
        """⚠️ "%1,50 en düşük" cümlesi kaç kayıt üzerinden söylendiği bilinmeden değersiz."""
        veri = api_client.post(
            "/api/v1/chat", json={"query": "Hangi bankada en düşük kâr payı oranı var?"}
        ).json()

        toplama = veri["aggregate"]
        assert toplama["with_value"] == 2
        assert toplama["without_value"] == 2
        assert "hesaba katılmadı" in veri["answer"]["text"]

    def test_toplamada_model_cagrilmaz(
        self, api_client: httpx.Client, dolu_oturum: Session
    ) -> None:
        veri = api_client.post(
            "/api/v1/chat", json={"query": "Kaç tane market kampanyası var?"}
        ).json()

        assert veri["answer"]["source"] == "computed"
        assert veri["answer"]["model_name"] is None

    def test_sayma_banka_dokumu_verir(self, api_client: httpx.Client, dolu_oturum: Session) -> None:
        veri = api_client.post(
            "/api/v1/chat", json={"query": "Albaraka'da kaç kampanya var?"}
        ).json()

        assert veri["aggregate"]["by_bank"] == {"Albaraka Türk": 2}


class TestTerminoloji:
    def test_yasakli_terim_sorguyu_durdurmaz(
        self, api_client: httpx.Client, dolu_oturum: Session
    ) -> None:
        """⚠️ "faiz" yazmak bir hata değil alışkanlıktır; sorgu çalışmalı."""
        veri = api_client.post(
            "/api/v1/chat", json={"query": "En düşük faiz oranı hangi bankada?"}
        ).json()

        assert veri["forbidden_terms_warning"] is not None
        assert "kâr payı" in veri["forbidden_terms_warning"]
        assert veri["aggregate"] is not None

    def test_uyari_metninde_emoji_yoktur(
        self, api_client: httpx.Client, dolu_oturum: Session
    ) -> None:
        """⚠️ Arayüze giden metinde emoji kullanılmaz (CLAUDE.md)."""
        uyari = (
            api_client.post("/api/v1/chat", json={"query": "faiz oranı nedir"}).json()[
                "forbidden_terms_warning"
            ]
            or ""
        )
        assert not any(ord(karakter) > 0x2100 for karakter in uyari), f"emoji: {uyari!r}"


class TestGovdeOnbellegi:
    def test_veri_degisince_govde_tazelenir(
        self, api_client: httpx.Client, dolu_oturum: Session
    ) -> None:
        """⚠️ Önbellek koşulsuz tutulursa yeni kampanya ARANAMAZ hâle gelir."""
        ilk = api_client.post("/api/v1/chat", json={"query": "market"}).json()
        assert ilk["retrieval"]["corpus_size"] == 4

        _kampanya_ekle(
            dolu_oturum,
            bank_code="vakif_katilim",
            campaign_id=105,
            title="Yeni Market Kampanyası",
            card_text="Vakıf Katılım — market alışverişlerinde indirim.",
            sector="market_gida",
        )

        ikinci = api_client.post("/api/v1/chat", json={"query": "market"}).json()
        assert ikinci["retrieval"]["corpus_size"] == 5
