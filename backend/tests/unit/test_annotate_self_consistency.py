"""Öz-tutarlılık turu iş akışı testleri.

⚠️ Kılavuz §4 "ilk 15 kaydı ertesi gün farklı bir adla yeniden etiketle" diyor
ama `/annotate/next` etiketlenmiş kampanyayı ETİKETLEYİCİYE BAKMADAN atlıyordu:
`Zeyd-tur2` adıyla gelen kişi örneklemin başına dönemiyor, birinci turun
bittiği yerden devam ediyordu. Belge bir akış tarif ediyor, kod başka bir şey
yapıyordu; bu testler ikisini bir arada tutar.
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.vocab import OTO_KANIT_NOTU
from app.db.models.bank import Bank
from app.db.models.campaign import Campaign
from app.db.models.gold_annotation import GoldAnnotation


@pytest.fixture
def etiketli_oturum(seeded_session: Session, tmp_path, monkeypatch) -> Session:  # type: ignore[no-untyped-def]
    """İki kampanyalı örneklem; ilki `Zeyd` tarafından etiketlenmiş."""
    from app.api.v1 import annotate

    banka = seeded_session.scalar(select(Bank).where(Bank.code == "ziraat_katilim"))
    assert banka is not None

    kampanyalar = []
    for slug in ("ilk-kampanya", "ikinci-kampanya"):
        kampanya = Campaign(
            bank_id=banka.id,
            external_slug=slug,
            title=slug,
            source_url=f"https://ornek.com.tr/{slug}",
        )
        seeded_session.add(kampanya)
        kampanyalar.append(kampanya)
    seeded_session.flush()

    ornek = tmp_path / "gold_sample.jsonl"
    satirlar = [
        f'{{"campaign_id": {k.id}, "campaign_key": "ziraat_katilim:{k.external_slug}",'
        f' "method": "blind"}}'
        for k in kampanyalar
    ]
    ornek.write_text("\n".join(satirlar) + "\n", encoding="utf-8")
    monkeypatch.setattr(annotate, "SAMPLE_PATH", ornek)

    # İlk kampanya birinci turda etiketlendi.
    seeded_session.add(
        GoldAnnotation(
            campaign_key="ziraat_katilim:ilk-kampanya",
            campaign_id=kampanyalar[0].id,
            field_name="cashback_pct",
            gold_value="10",
            evidence_text="%10 nakit iade",
            annotator="Zeyd",
            method="blind",
        )
    )
    seeded_session.flush()
    return seeded_session


def _ilk_kampanya_id(session: Session) -> int:
    kampanya = session.scalar(select(Campaign).where(Campaign.external_slug == "ilk-kampanya"))
    assert kampanya is not None
    return kampanya.id


class TestIkinciTur:
    def test_ikinci_tur_ornegin_basina_doner(
        self, api_client: httpx.Client, etiketli_oturum: Session
    ) -> None:
        """⚠️ `Zeyd-tur2` ilk kaydı GÖRMELİ; birinci turun kaydı onu atlamamalı."""
        yanit = api_client.get("/api/v1/annotate/next?annotator=Zeyd-tur2")

        assert yanit.status_code == 200
        assert yanit.json()["campaign_id"] == _ilk_kampanya_id(etiketli_oturum)

    def test_ilk_tur_kaldigi_yerden_devam_eder(
        self, api_client: httpx.Client, etiketli_oturum: Session
    ) -> None:
        """`Zeyd` kendi etiketlediğini tekrar görmez."""
        yanit = api_client.get("/api/v1/annotate/next?annotator=Zeyd")

        assert yanit.status_code == 200
        assert yanit.json()["campaign_id"] != _ilk_kampanya_id(etiketli_oturum)

    def test_ad_verilmezse_eski_davranis_korunur(
        self, api_client: httpx.Client, etiketli_oturum: Session
    ) -> None:
        """Parametresiz çağrı herkesin etiketlediğini atlar — geriye uyum."""
        yanit = api_client.get("/api/v1/annotate/next")

        assert yanit.status_code == 200
        assert yanit.json()["campaign_id"] != _ilk_kampanya_id(etiketli_oturum)

    def test_ikinci_tur_birinci_turu_ezmez(
        self, api_client: httpx.Client, etiketli_oturum: Session
    ) -> None:
        """⚠️ İki tur AYNI alanda ayrı satır tutmalı; yoksa uyum ölçülemez."""
        cid = _ilk_kampanya_id(etiketli_oturum)

        api_client.post(
            f"/api/v1/annotate/{cid}",
            json={
                "annotator": "Zeyd-tur2",
                "method": "blind",
                "is_difficult": False,
                "fields": {"cashback_pct": {"value": "15", "evidence": "%15 nakit iade"}},
            },
        )

        satirlar = etiketli_oturum.scalars(
            select(GoldAnnotation).where(
                GoldAnnotation.campaign_id == cid,
                GoldAnnotation.field_name == "cashback_pct",
            )
        ).all()
        degerler = {s.annotator: s.gold_value for s in satirlar}
        assert degerler == {"Zeyd": "10", "Zeyd-tur2": "15"}


class TestOtoKanitIsareti:
    """⚠️ `oto-kanit` işareti insan doğrulaması OLMADIĞINI söyler."""

    def test_kanit_degismediyse_isaret_korunur(
        self, api_client: httpx.Client, etiketli_oturum: Session
    ) -> None:
        """Kampanyayı yeniden kaydetmek işareti sessizce silmemeli.

        Silinirse `gold-durum` otomatik bağlamayı insan seçimi sayar ve rapor
        sahip olmadığımız bir titizliği iddia eder.
        """
        cid = _ilk_kampanya_id(etiketli_oturum)
        etiket = etiketli_oturum.scalar(
            select(GoldAnnotation).where(GoldAnnotation.campaign_id == cid)
        )
        assert etiket is not None
        etiket.note = OTO_KANIT_NOTU
        etiketli_oturum.flush()

        api_client.post(
            f"/api/v1/annotate/{cid}",
            json={
                "annotator": "Zeyd",
                "method": "blind",
                "is_difficult": False,
                "fields": {"cashback_pct": {"value": "10", "evidence": "%10 nakit iade"}},
            },
        )

        etiketli_oturum.refresh(etiket)
        assert etiket.note == OTO_KANIT_NOTU

    def test_kanit_degistiyse_isaret_silinir(
        self, api_client: httpx.Client, etiketli_oturum: Session
    ) -> None:
        """İnsan kanıtı elle değiştirdiyse artık insan doğrulamasıdır."""
        cid = _ilk_kampanya_id(etiketli_oturum)
        etiket = etiketli_oturum.scalar(
            select(GoldAnnotation).where(GoldAnnotation.campaign_id == cid)
        )
        assert etiket is not None
        etiket.note = OTO_KANIT_NOTU
        etiketli_oturum.flush()

        api_client.post(
            f"/api/v1/annotate/{cid}",
            json={
                "annotator": "Zeyd",
                "method": "blind",
                "is_difficult": False,
                "fields": {
                    "cashback_pct": {"value": "10", "evidence": "kampanyada %10 nakit iade var"}
                },
            },
        )

        etiketli_oturum.refresh(etiket)
        assert etiket.note != OTO_KANIT_NOTU


class TestIkinciTurKorlugu:
    """⚠️ İkinci tur BİRİNCİ TURUN cevaplarını GÖRMEMELİ.

    Arayüzün "düzeltme akışı" `existing` alanını forma dolduruyor. Bu alan
    etiketleyiciye göre süzülmezse ikinci tur körlüğünü kaybeder: kişi kendi
    kararını görüp onaylar ve uyum sahte biçimde %100 çıkar.

    Ölçüldü: Zeyd2 turunda 704 alanın 704'ü hem DEĞER hem KANIT METNİ olarak
    birebir aynıydı. Kanıt fareyle elle seçiliyor; 704 seçimin aynı karakterde
    başlayıp bitmesi mümkün değil — form ön-dolu geliyordu.
    """

    def test_baska_turun_etiketi_geri_yuklenmez(
        self, api_client: httpx.Client, etiketli_oturum: Session
    ) -> None:
        cid = _ilk_kampanya_id(etiketli_oturum)

        yanit = api_client.get(f"/api/v1/annotate/{cid}?annotator=Zeyd-tur2")

        assert yanit.status_code == 200
        assert yanit.json()["existing"] == []

    def test_kendi_etiketi_geri_yuklenir(
        self, api_client: httpx.Client, etiketli_oturum: Session
    ) -> None:
        """Düzeltme akışı KENDİ turu için çalışmaya devam etmeli."""
        cid = _ilk_kampanya_id(etiketli_oturum)

        veri = api_client.get(f"/api/v1/annotate/{cid}?annotator=Zeyd").json()

        assert [k["field_name"] for k in veri["existing"]] == ["cashback_pct"]

    def test_ad_verilmezse_hepsi_doner(
        self, api_client: httpx.Client, etiketli_oturum: Session
    ) -> None:
        """Parametresiz çağrı geriye uyumlu kalır."""
        cid = _ilk_kampanya_id(etiketli_oturum)

        assert api_client.get(f"/api/v1/annotate/{cid}").json()["existing"]

    def test_sonraki_kayit_da_suzulur(
        self, api_client: httpx.Client, etiketli_oturum: Session
    ) -> None:
        """`/next` de aynı süzgeci uygulamalı; iki uç ayrışmamalı."""
        veri = api_client.get("/api/v1/annotate/next?annotator=Zeyd-tur2").json()

        assert veri["campaign_id"] == _ilk_kampanya_id(etiketli_oturum)
        assert veri["existing"] == []
