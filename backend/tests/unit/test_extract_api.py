"""KAPI A9 — `POST /api/v1/extract` ve ablasyon kip filtresi testleri.

⚠️ EN KRİTİK TEST `test_sartname_ornegi_dogru_cozulur`. Şartname §10.2'nin
örnek metnini kural katmanının doğru çözmesi, sprintin gösterilebilir
çıktısıdır: gerçek model olmadan da sistem çalışıyor.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.ai.evaluation import MODE_METHODS, evaluate
from app.schemas.extract import MAX_TEXT_CHARS

# Şartname §10.2'deki örnek metin.
SARTNAME_METNI = (
    "Yeni ev sahibi olmak isteyen müşterilerimize özel %1,89 kâr payı oranı "
    "ile 120 aya kadar konut finansmanı fırsatı sunulmaktadır. Kampanya "
    "kapsamında 50.000 TL'ye kadar dosya masrafı alınmamaktadır. "
    "Kampanya 31 Aralık 2026 tarihine kadar geçerlidir."
)


class TestExtractUcu:
    """Canlı çıkarım ucunun davranışı."""

    def test_sartname_ornegi_dogru_cozulur(self, api_client: TestClient) -> None:
        """⚠️ KAPI A9 geçiş koşulu: kural katmanı örneği çözmeli."""
        yanit = api_client.post(
            "/api/v1/extract", json={"text": SARTNAME_METNI, "mode": "rule_only"}
        )
        assert yanit.status_code == 200
        alanlar = yanit.json()["fields"]

        assert alanlar["profit_rate_pct"]["value"] == "1.89"
        assert alanlar["term_months_max"]["value"] == "120"
        assert alanlar["end_date"]["value"] == "2026-12-31"

    def test_her_alan_kanitiyla_doner(self, api_client: TestClient) -> None:
        """⚠️ Kanıtsız değer "bu nereden çıktı?" sorusunu yanıtlayamaz."""
        veri = api_client.post(
            "/api/v1/extract", json={"text": SARTNAME_METNI, "mode": "rule_only"}
        ).json()

        for ad, alan in veri["fields"].items():
            assert alan["evidence"], f"{ad} kanıtsız döndü"
            assert alan["method"] in {"table", "rule", "llm"}

    def test_kanit_araligi_kaynaktan_dilimlenebilir(self, api_client: TestClient) -> None:
        """`evidence_span` verildiyse metnin o aralığı kanıta eşit olmalı."""
        veri = api_client.post(
            "/api/v1/extract", json={"text": SARTNAME_METNI, "mode": "rule_only"}
        ).json()

        for ad, alan in veri["fields"].items():
            aralik = alan["evidence_span"]
            if aralik is None:
                continue
            bas, son = aralik
            assert SARTNAME_METNI[bas:son] == alan["evidence"], f"{ad} ofseti kaymış"

    def test_model_kimligi_doner(self, api_client: TestClient) -> None:
        veri = api_client.post("/api/v1/extract", json={"text": SARTNAME_METNI}).json()
        assert veri["model"]["local"] is True
        assert veri["model"]["name"].startswith("mock")
        assert veri["latency_ms"] >= 0

    def test_uzun_metin_reddedilir(self, api_client: TestClient) -> None:
        """⚠️ Sınırsız girdi bağlam penceresini aşar ve SESSİZCE kırpılır."""
        yanit = api_client.post("/api/v1/extract", json={"text": "a" * (MAX_TEXT_CHARS + 1)})
        assert yanit.status_code == 422

    def test_bos_metin_reddedilir(self, api_client: TestClient) -> None:
        assert api_client.post("/api/v1/extract", json={"text": ""}).status_code == 422

    def test_tanimsiz_kip_reddedilir(self, api_client: TestClient) -> None:
        yanit = api_client.post("/api/v1/extract", json={"text": SARTNAME_METNI, "mode": "sihirli"})
        assert yanit.status_code == 422

    def test_bilgi_yoksa_alan_uretilmez(self, api_client: TestClient) -> None:
        """⚠️ Şartname 7: bilgi yokken bilgi uydurulmamalı."""
        veri = api_client.post(
            "/api/v1/extract",
            json={
                "text": "Bu kampanyada kâr payı oranı bulunmamaktadır. "
                "Detaylı bilgi için şubelerimize başvurabilirsiniz.",
                "mode": "rule_only",
            },
        ).json()
        assert "profit_rate_pct" not in veri["fields"]

    def test_hybrid_kipinde_ozet_alani_doner(self, api_client: TestClient) -> None:
        """MockProvider boş özet ürettiği için `summary` None kalmalı."""
        veri = api_client.post(
            "/api/v1/extract", json={"text": SARTNAME_METNI, "mode": "hybrid"}
        ).json()
        assert veri["summary"] is None
        assert veri["mode"] == "hybrid"

    def test_veritabanina_kampanya_yazilmaz(
        self, api_client: TestClient, db_session: Session
    ) -> None:
        """⚠️ Demo ucu gerçek veri setini KİRLETMEZ."""
        from sqlalchemy import func, select

        from app.db.models import Campaign

        once = db_session.scalar(select(func.count()).select_from(Campaign))
        api_client.post("/api/v1/extract", json={"text": SARTNAME_METNI})
        assert db_session.scalar(select(func.count()).select_from(Campaign)) == once


class TestAblasyonKipFiltresi:
    """⚠️ `mode` yalnızca etiket DEĞİL; hangi katmanların ölçüldüğünü belirler."""

    def test_kip_katman_eslemesi(self) -> None:
        assert MODE_METHODS["rule_only"] == ("table", "rule")
        assert MODE_METHODS["llm_only"] == ("llm",)
        assert set(MODE_METHODS["hybrid"]) == {"table", "rule", "llm"}

    def test_tanimsiz_kip_reddedilir(self, db_session: Session) -> None:
        with pytest.raises(ValueError, match="Tanımsız kip"):
            evaluate(db_session, mode="sihirli_kip")

    def test_llm_only_kural_kayitlarini_saymaz(self, db_session: Session) -> None:
        """Aynı veritabanında kural kaydı varken `llm_only` onu görmemeli."""
        from decimal import Decimal

        from app.db.models import (
            Bank,
            Campaign,
            CampaignExtraction,
            GoldAnnotation,
            SourceDocument,
        )

        bank = Bank(code="abl_bank", name="Abl", website="https://a.test")
        db_session.add(bank)
        db_session.flush()
        belge = SourceDocument(
            bank_id=bank.id, url="https://a.test/1", url_hash="a1", clean_text="metin"
        )
        db_session.add(belge)
        db_session.flush()
        kampanya = Campaign(
            bank_id=bank.id,
            source_document_id=belge.id,
            external_slug="a1",
            title="Test",
            source_url="https://a.test/1",
            status="unknown",
            date_precision="unknown",
        )
        db_session.add(kampanya)
        db_session.flush()

        db_session.add(
            GoldAnnotation(
                campaign_key=f"emlak_katilim:test-{kampanya.id}",
                campaign_id=kampanya.id,
                field_name="profit_rate_pct",
                gold_value="2.05",
                unit="pct",
                annotator="test",
                method="blind",
            )
        )
        db_session.add(
            CampaignExtraction(
                campaign_id=kampanya.id,
                field_name="profit_rate_pct",
                value_normalized="2.05",
                unit="pct",
                confidence=Decimal("0.900"),
                extraction_method="rule",
                is_validated=True,
            )
        )
        db_session.flush()

        # Kural kaydı `rule_only`de sayılır...
        assert evaluate(db_session, mode="rule_only").overall.tp == 1
        # ...ama `llm_only`de görünmez: kaçırma sayılır.
        llm_sonuc = evaluate(db_session, mode="llm_only")
        assert llm_sonuc.overall.tp == 0
        assert llm_sonuc.overall.fn == 1
