"""Dışa aktar → doğrula → sıfırla → yeniden bağla turu.

⚠️ Bu turun kanıtladığı şey tek cümleyle: 880 satırlık elle etiketleme işi
`campaign_id` değiştiğinde KAYBOLMUYOR.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Bank, Campaign, CampaignExtraction, GoldAnnotation
from scripts.export_dataset import disa_aktar
from scripts.reanchor_gold import yeniden_bagla
from scripts.reset_campaign_data import sifirla
from scripts.verify_export import damga_bas, dogrula, dogrulanmis_mi


def _kampanya(bank_id: int, slug: str, baslik: str) -> Campaign:
    """Test kampanyası üretir."""
    return Campaign(
        bank_id=bank_id,
        external_slug=slug,
        title=baslik,
        source_url=f"https://x.example/{slug}",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 31),
        date_precision="exact",
        date_evidence_text="01.08.2026 - 31.08.2026",
        date_evidence_source="body",
        status="active",
    )


@pytest.fixture
def veri(seeded_session: Session) -> Session:
    """Üç kampanya, beş gold etiketi ve bir çıkarım."""
    bank = seeded_session.scalar(select(Bank).where(Bank.code == "emlak_katilim"))
    assert bank is not None

    kampanyalar = [
        _kampanya(bank.id, "kampanya-a", "Kampanya A"),
        _kampanya(bank.id, "kampanya-b", "Kampanya B"),
        _kampanya(bank.id, "kampanya-c", "Kampanya C"),
    ]
    seeded_session.add_all(kampanyalar)
    seeded_session.flush()

    for i, kampanya in enumerate(kampanyalar[:2]):
        for alan in ("start_date", "end_date", "profit_rate_pct")[: 3 - i]:
            seeded_session.add(
                GoldAnnotation(
                    campaign_key=f"emlak_katilim:{kampanya.external_slug}",
                    campaign_id=kampanya.id,
                    field_name=alan,
                    gold_value="2.05" if alan == "profit_rate_pct" else "2026-08-01",
                    unit="pct" if alan == "profit_rate_pct" else "date",
                    evidence_text="%2,05 kâr payı oranı",
                    annotator="zeyd",
                    method="blind",
                )
            )

    seeded_session.add(
        CampaignExtraction(
            campaign_id=kampanyalar[0].id,
            field_name="profit_rate_pct",
            value_raw="%2,05",
            value_normalized="2.05",
            unit="pct",
            confidence=Decimal("0.900"),
            extraction_method="rule",
        )
    )
    seeded_session.commit()
    return seeded_session


class TestDisaAktarma:
    def test_gold_campaign_key_ile_aktarilir(self, veri: Session, tmp_path: Path) -> None:
        """⚠️ `campaign_id` aktarılmaz; kimlik kararlı anahtardır."""
        disa_aktar(veri, hedef=tmp_path)

        satirlar = [
            json.loads(s)
            for s in (tmp_path / "gold_annotations.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        assert satirlar
        assert all("campaign_key" in s for s in satirlar)
        assert all("campaign_id" not in s for s in satirlar)
        # Yedek eşleştirme çıpaları taşınır.
        assert all(s.get("source_url") for s in satirlar)

    def test_decimal_dize_olarak_serilesir(self, veri: Session, tmp_path: Path) -> None:
        """⚠️ float'a düşerse oranlar sessizce bozulur."""
        disa_aktar(veri, hedef=tmp_path)

        satirlar = [
            json.loads(s)
            for s in (tmp_path / "campaign_extractions.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        guvenler = [s["confidence"] for s in satirlar if s["confidence"] is not None]
        assert guvenler
        assert all(isinstance(g, str) for g in guvenler)

    def test_manifest_sayilari_ve_ozetleri_tasir(self, veri: Session, tmp_path: Path) -> None:
        manifest = disa_aktar(veri, hedef=tmp_path)

        assert manifest["satir_sayilari"]["campaigns"] == 3
        assert manifest["dosya_ozetleri"]["campaigns.jsonl"]
        assert manifest["verified_at"] is None


class TestDogrulama:
    def test_temiz_aktarma_damgalanir(self, veri: Session, tmp_path: Path) -> None:
        disa_aktar(veri, hedef=tmp_path)

        assert dogrula(tmp_path) == []
        assert not dogrulanmis_mi(tmp_path)
        damga_bas(tmp_path)
        assert dogrulanmis_mi(tmp_path)

    def test_bozulmus_dosya_yakalanir(self, veri: Session, tmp_path: Path) -> None:
        disa_aktar(veri, hedef=tmp_path)
        (tmp_path / "campaigns.jsonl").write_text("{}\n", encoding="utf-8")

        bulgular = dogrula(tmp_path)
        assert bulgular
        assert any("satır sayısı" in b or "özeti" in b for b in bulgular)

    def test_manifest_yoksa_bulgu_verir(self, tmp_path: Path) -> None:
        assert dogrula(tmp_path)


class TestSifirlama:
    def test_dogrulanmamis_aktarma_ile_silme_reddedilir(
        self, veri: Session, tmp_path: Path
    ) -> None:
        """En kritik güvenlik kilidi."""
        disa_aktar(veri, hedef=tmp_path)

        with pytest.raises(PermissionError):
            sifirla(veri, export_dizini=tmp_path)

        assert veri.scalar(select(func.count()).select_from(Campaign)) == 3

    def test_kuru_calistirma_silmez(self, veri: Session, tmp_path: Path) -> None:
        disa_aktar(veri, hedef=tmp_path)
        damga_bas(tmp_path)

        ozeti = sifirla(veri, export_dizini=tmp_path, kuru=True)

        assert ozeti.silinen["campaigns"] == 3
        assert veri.scalar(select(func.count()).select_from(Campaign)) == 3

    def test_kampanyalar_silinir_gold_kalir(self, veri: Session, tmp_path: Path) -> None:
        """⚠️ Gold etiketleri SİLİNMEZ; `campaign_id` NULL'a düşer."""
        disa_aktar(veri, hedef=tmp_path)
        damga_bas(tmp_path)

        sifirla(veri, export_dizini=tmp_path)

        assert veri.scalar(select(func.count()).select_from(Campaign)) == 0
        assert veri.scalar(select(func.count()).select_from(GoldAnnotation)) == 5
        assert veri.scalar(select(func.count()).select_from(CampaignExtraction)) == 0


class TestYenidenBaglama:
    def test_yeniden_kazima_sonrasi_tam_eslesme(self, veri: Session, tmp_path: Path) -> None:
        """Tur testi: id'ler değişse de etiketler doğru kampanyaya bağlanır."""
        disa_aktar(veri, hedef=tmp_path)
        damga_bas(tmp_path)
        sifirla(veri, export_dizini=tmp_path)

        # "Yeniden kazıma": aynı sluglar, YENİ id'ler.
        bank = veri.scalar(select(Bank).where(Bank.code == "emlak_katilim"))
        assert bank is not None
        veri.add_all(
            [
                _kampanya(bank.id, "kampanya-a", "Kampanya A"),
                _kampanya(bank.id, "kampanya-b", "Kampanya B"),
                _kampanya(bank.id, "kampanya-c", "Kampanya C"),
            ]
        )
        veri.commit()

        ozeti = yeniden_bagla(veri)

        assert ozeti.toplam == 5
        assert ozeti.oksuz == 0
        assert ozeti.oran == Decimal("1.0000")
        assert ozeti.eslesen_slug == 5

        # Asıl kanıt: her etiket, anahtarındaki slug'a sahip kampanyaya bağlı.
        slug_by_id = {k.id: k.external_slug for k in veri.scalars(select(Campaign))}
        for etiket in veri.scalars(select(GoldAnnotation)):
            assert etiket.campaign_id is not None
            beklenen_slug = etiket.campaign_key.split(":", 1)[1]
            assert slug_by_id[etiket.campaign_id] == beklenen_slug
            assert etiket.reanchor_method == "slug"

    def test_eslesmeyen_etiket_silinmez(self, veri: Session, tmp_path: Path) -> None:
        disa_aktar(veri, hedef=tmp_path)
        damga_bas(tmp_path)
        sifirla(veri, export_dizini=tmp_path)

        # Hiç kampanya geri gelmedi.
        ozeti = yeniden_bagla(veri)

        assert ozeti.oksuz == 5
        assert veri.scalar(select(func.count()).select_from(GoldAnnotation)) == 5
        assert all(e.campaign_id is None for e in veri.scalars(select(GoldAnnotation)))


class TestGoldSilme:
    """Gold silme AÇIK bayrak gerektirir; kazara silinmemeli."""

    def test_varsayilan_olarak_gold_korunur(self, veri: Session, tmp_path: Path) -> None:
        disa_aktar(veri, hedef=tmp_path)
        damga_bas(tmp_path)

        sifirla(veri, export_dizini=tmp_path)

        assert veri.scalar(select(func.count()).select_from(GoldAnnotation)) == 5

    def test_gold_sil_bayragiyla_silinir(self, veri: Session, tmp_path: Path) -> None:
        """⚠️ Yalnızca doğrulanmış dışa aktarma varken; dosyada kararlı
        anahtarla duruyor ve geri yüklenebilir."""
        disa_aktar(veri, hedef=tmp_path)
        damga_bas(tmp_path)

        ozeti = sifirla(veri, export_dizini=tmp_path, gold_sil=True)

        assert ozeti.silinen["gold_annotations"] == 5
        assert veri.scalar(select(func.count()).select_from(GoldAnnotation)) == 0

    def test_dogrulanmamis_aktarmada_gold_silinmez(self, veri: Session, tmp_path: Path) -> None:
        disa_aktar(veri, hedef=tmp_path)

        with pytest.raises(PermissionError):
            sifirla(veri, export_dizini=tmp_path, gold_sil=True)

        assert veri.scalar(select(func.count()).select_from(GoldAnnotation)) == 5
