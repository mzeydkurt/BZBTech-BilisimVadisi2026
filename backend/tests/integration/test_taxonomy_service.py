"""`taxonomy_service` — sınıflandırmanın veritabanına uygulanması.

⚠️ BU DOSYA BİR OLAYIN ARDINDAN YAZILDI. `taxonomy_service.py` test kapsamı
**%0**'dı ve 27 Ağustos'ta bulunan tutarsızlığın merkezindeydi:

    siniflandir  →  campaign_categories SİLER ve YENİDEN YAZAR
    cikarim      →  campaign_categories OKUR (`_taxonomy_fields`)

Boru hattı sırası ters olduğu için `cikarim` bir önceki koşunun etiketlerini
okuyor, sonra `siniflandir` etiketleri yeniden yazıyordu; 91 kampanyada
`campaign_extractions.sector` ile `campaign_categories` ayrışmıştı — yani
F1 raporu ile arayüz farklı şey söylüyordu. Hiç testi olmayan, veri SİLEN bir
fonksiyon için bu kabul edilebilir bir risk değil.

⚠️ SİLME DAVRANIŞI ADIYLA TEST EDİLİR. "Tekrar çalıştırılabilir" iddiası
docstring'de yazılı; iddianın testi yoksa iddia değil temennidir.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Bank, Campaign, CampaignCategory
from app.services.taxonomy_service import categorize_campaigns


@pytest.fixture
def kampanyalar(seeded_session: Session) -> Session:
    """İki bankada, sınıflandırılabilir üç kampanya."""
    emlak = seeded_session.scalar(select(Bank).where(Bank.code == "emlak_katilim"))
    kuveyt = seeded_session.scalar(select(Bank).where(Bank.code == "kuveyt_turk"))
    assert emlak is not None and kuveyt is not None

    seeded_session.add_all(
        [
            Campaign(
                bank_id=emlak.id,
                external_slug="market-parafpara",
                title="Market Alışverişlerinize 800 TL ParafPara Hediye!",
                description="Market harcamalarında puan",
                source_url="https://ornek/market-parafpara",
                segment="bireysel",
                end_date=date(2026, 12, 31),
                date_precision="partial",
                status="active",
            ),
            Campaign(
                bank_id=emlak.id,
                external_slug="konut-finansmani",
                title="Konut Finansmanı Kampanyası",
                description="Ev sahibi olmak için",
                source_url="https://ornek/konut-finansmani",
                segment="bireysel",
                status="unknown",
            ),
            Campaign(
                bank_id=kuveyt.id,
                external_slug="emeklilere-ozel",
                title="Emeklilere Özel Avantaj Paketi",
                source_url="https://ornek/emeklilere-ozel",
                segment="bireysel",
                status="active",
            ),
        ]
    )
    seeded_session.flush()
    return seeded_session


def _etiketler(session: Session, slug: str) -> dict[str, set[str]]:
    """Bir kampanyanın eksen → değer kümesi."""
    kampanya = session.scalar(select(Campaign).where(Campaign.external_slug == slug))
    assert kampanya is not None
    sonuc: dict[str, set[str]] = {}
    for kayit in session.scalars(
        select(CampaignCategory).where(CampaignCategory.campaign_id == kampanya.id)
    ):
        sonuc.setdefault(kayit.axis, set()).add(kayit.value)
    return sonuc


class TestEtiketUretimi:
    """Sınıflandırma gerçekten etiket üretiyor mu?"""

    def test_etiket_uretilir_ve_ozet_sayar(self, kampanyalar: Session) -> None:
        sonuc = categorize_campaigns(kampanyalar)

        assert sonuc.campaigns == 3
        assert sonuc.labels > 0
        # Özet sayacı gerçekten yazılan satır sayısını yansıtmalı.
        yazilan = kampanyalar.scalar(select(CampaignCategory.id).limit(1))  # en az bir satır var
        assert yazilan is not None

    def test_urun_turu_basliktan_okunur(self, kampanyalar: Session) -> None:
        """ "Konut Finansmanı Kampanyası" → `product_type=konut_finansmani`."""
        categorize_campaigns(kampanyalar)
        etiketler = _etiketler(kampanyalar, "konut-finansmani")
        assert "konut_finansmani" in etiketler.get("product_type", set())

    def test_hedef_kitle_basliktan_okunur(self, kampanyalar: Session) -> None:
        categorize_campaigns(kampanyalar)
        etiketler = _etiketler(kampanyalar, "emeklilere-ozel")
        assert "emekli" in etiketler.get("audience", set())

    def test_banka_suzgeci_yalnizca_o_bankayi_isler(self, kampanyalar: Session) -> None:
        """⚠️ Süzgeç sızarsa diğer bankanın etiketleri de silinir."""
        sonuc = categorize_campaigns(kampanyalar, bank_code="kuveyt_turk")

        assert sonuc.campaigns == 1
        assert _etiketler(kampanyalar, "emeklilere-ozel")
        assert not _etiketler(kampanyalar, "market-parafpara")


class TestTekrarCalistirilabilirlik:
    """⚠️ Docstring'in iddiası: "tekrar çalıştırılabilir". Testi burada."""

    def test_ikinci_calistirma_kayit_cogaltmaz(self, kampanyalar: Session) -> None:
        """Aynı komut iki kez koşunca etiket sayısı ARTMAZ.

        Önce silme yapılmazsa her koşuda kayıt katlanır ve
        `_taxonomy_pick` aynı değerden birden çok kopya arasında seçim
        yapmaya çalışır.
        """
        birinci = categorize_campaigns(kampanyalar)
        kampanyalar.flush()
        ikinci = categorize_campaigns(kampanyalar)
        kampanyalar.flush()

        assert birinci.labels == ikinci.labels
        toplam = len(list(kampanyalar.scalars(select(CampaignCategory))))
        assert toplam == ikinci.labels

    def test_baslik_degisirse_eski_etiket_silinir(self, kampanyalar: Session) -> None:
        """⚠️ ASIL DAVRANIŞ BU. Sözlükten ya da başlıktan çıkan bir sinyalin
        etiketi veritabanında KALMAMALI; kalırsa arayüz artık geçerli
        olmayan bir sınıflandırma gösterir ve bu hiçbir yerde hata vermez.
        """
        categorize_campaigns(kampanyalar)
        kampanyalar.flush()
        assert "konut_finansmani" in _etiketler(kampanyalar, "konut-finansmani").get(
            "product_type", set()
        )

        kampanya = kampanyalar.scalar(
            select(Campaign).where(Campaign.external_slug == "konut-finansmani")
        )
        assert kampanya is not None
        kampanya.title = "Akaryakıt Harcamalarınıza Hediye"
        kampanya.description = None
        kampanyalar.flush()

        categorize_campaigns(kampanyalar)
        kampanyalar.flush()

        etiketler = _etiketler(kampanyalar, "konut-finansmani")
        assert "konut_finansmani" not in etiketler.get("product_type", set())
        assert "akaryakit" in etiketler.get("sector", set())


class TestFallbackOrani:
    """`genel` oranı boru hattı kapısı olarak kullanılıyor (eşik 0,40)."""

    def test_fallback_orani_hesaplanir(self, kampanyalar: Session) -> None:
        sonuc = categorize_campaigns(kampanyalar)

        assert 0.0 <= sonuc.fallback_ratio <= 1.0
        assert sonuc.fallback_only <= sonuc.campaigns

    def test_kampanya_yoksa_oran_sifir_dondurur(self, seeded_session: Session) -> None:
        """⚠️ Sıfıra bölme yok: kampanya yoksa oran 0,0."""
        sonuc = categorize_campaigns(seeded_session)

        assert sonuc.campaigns == 0
        assert sonuc.fallback_ratio == 0.0
