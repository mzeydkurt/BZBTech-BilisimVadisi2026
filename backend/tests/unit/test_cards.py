"""KAPI A9 — varlık kartı testleri.

⚠️ EN KRİTİK TEST `test_dogrulanmamis_alan_karta_girmez`. Kart, sistemin
kullanıcıya gösterdiği en özet biçimdir; guard'ın elediği bir değerin
buraya sızması halüsinasyonu en görünür yere koymak olurdu.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.ai.cards import (
    MIN_CARD_CONFIDENCE,
    NON_BINDING_NOTICE,
    build_bank_card,
    build_campaign_card,
    build_glossary_card,
    build_product_card,
    card_hash,
)
from app.db.models import (
    Bank,
    Campaign,
    CampaignCategory,
    CampaignExtraction,
    GlossaryTerm,
    Product,
    SourceDocument,
)


def _cikarim(
    campaign_id: int,
    alan: str,
    deger: str,
    *,
    birim: str = "pct",
    guven: str = "0.900",
    dogrulandi: bool = True,
    red: str | None = None,
) -> CampaignExtraction:
    """Test için çıkarım satırı."""
    return CampaignExtraction(
        campaign_id=campaign_id,
        field_name=alan,
        value_normalized=deger,
        unit=birim,
        confidence=Decimal(guven),
        extraction_method="rule",
        is_validated=dogrulandi,
        rejected_reason=red,
    )


@pytest.fixture
def kampanya(db_session: Session) -> Campaign:
    """Kaynak belgesiyle birlikte test kampanyası."""
    from datetime import date

    bank = Bank(code="kart_bank", name="Kart Katılım", website="https://ornek.test")
    db_session.add(bank)
    db_session.flush()
    belge = SourceDocument(
        bank_id=bank.id,
        url="https://ornek.test/k",
        url_hash="k",
        doc_type="campaign",
        clean_text="metin",
    )
    db_session.add(belge)
    db_session.flush()
    kayit = Campaign(
        bank_id=bank.id,
        source_document_id=belge.id,
        external_slug="k",
        title="Market Alışverişlerinde Taksit",
        source_url="https://ornek.test/k",
        description="Market alışverişlerinde taksit fırsatı.",
        status="active",
        date_precision="exact",
        date_evidence_text="01.01.2026 - 31.12.2026",
        date_evidence_source="body",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 12, 31),
    )
    db_session.add(kayit)
    db_session.flush()
    return kayit


class TestKampanyaKarti:
    """Kart yalnızca doğrulanmış alanları içerir."""

    def test_dogrulanmis_alan_karta_girer(self, db_session: Session, kampanya: Campaign) -> None:
        db_session.add(_cikarim(kampanya.id, "profit_rate_pct", "2.0500"))
        db_session.flush()

        kart = build_campaign_card(db_session, kampanya)
        assert "Kâr payı oranı %2,05" in kart

    def test_dogrulanmamis_alan_karta_girmez(self, db_session: Session, kampanya: Campaign) -> None:
        """⚠️ KAPI A9 geçiş koşulu."""
        db_session.add(_cikarim(kampanya.id, "profit_rate_pct", "9.9900", dogrulandi=False))
        db_session.flush()

        assert "9,99" not in build_campaign_card(db_session, kampanya)

    def test_reddedilen_alan_karta_girmez(self, db_session: Session, kampanya: Campaign) -> None:
        db_session.add(_cikarim(kampanya.id, "profit_rate_pct", "1.2300", red="evidence_not_found"))
        db_session.flush()

        assert "1,23" not in build_campaign_card(db_session, kampanya)

    def test_dusuk_guvenli_alan_karta_girmez(self, db_session: Session, kampanya: Campaign) -> None:
        """Çoklu eşleşmede güven 0.60'a düşer; belirsiz değer gösterilmez."""
        assert Decimal("0.60") == MIN_CARD_CONFIDENCE
        db_session.add(_cikarim(kampanya.id, "profit_rate_pct", "7.7700", guven="0.500"))
        db_session.flush()

        assert "7,77" not in build_campaign_card(db_session, kampanya)

    def test_banka_ve_baslik_kartta(self, db_session: Session, kampanya: Campaign) -> None:
        kart = build_campaign_card(db_session, kampanya)
        assert "Kart Katılım" in kart
        assert "Market Alışverişlerinde Taksit" in kart

    def test_tarih_dogal_dile_cevrilir(self, db_session: Session, kampanya: Campaign) -> None:
        kart = build_campaign_card(db_session, kampanya)
        assert "1 Ağustos 2026" in kart
        assert "31 Aralık 2026" in kart

    def test_tarihsizlik_gizlenmez(self, db_session: Session, kampanya: Campaign) -> None:
        """⚠️ "Süresi dolmuş" ile "tarihi bilinmiyor" ayrı şeylerdir."""
        kampanya.start_date = None
        kampanya.end_date = None
        db_session.flush()

        kart = build_campaign_card(db_session, kampanya)
        assert "belirtilmemiş" in kart

    def test_etiketler_okunur_hale_gelir(self, db_session: Session, kampanya: Campaign) -> None:
        db_session.add(
            CampaignCategory(
                campaign_id=kampanya.id,
                axis="sector",
                value="market_gida",
                confidence=Decimal("0.900"),
                source="keyword",
            )
        )
        db_session.flush()

        kart = build_campaign_card(db_session, kampanya)
        assert "market gida" in kart

    def test_ozet_kartta_yer_alir(self, db_session: Session, kampanya: Campaign) -> None:
        kampanya.summary_ai = "Doğrulanmış özet metni."
        db_session.flush()
        assert "Doğrulanmış özet metni." in build_campaign_card(db_session, kampanya)

    def test_katilim_terminolojisi_kullanilir(
        self, db_session: Session, kampanya: Campaign
    ) -> None:
        """⚠️ Kartta "faiz"/"kredi" geçmez (CLAUDE.md)."""
        db_session.add(_cikarim(kampanya.id, "profit_rate_pct", "2.0500"))
        db_session.flush()

        kart = build_campaign_card(db_session, kampanya).casefold()
        assert "faiz" not in kart
        assert "mevduat" not in kart


class TestKartHash:
    """Değişmeyen kart yeniden üretilmez."""

    def test_ayni_metin_ayni_ozet(self) -> None:
        assert card_hash("aynı metin") == card_hash("aynı metin")

    def test_farkli_metin_farkli_ozet(self) -> None:
        assert card_hash("metin A") != card_hash("metin B")

    def test_kart_kararli(self, db_session: Session, kampanya: Campaign) -> None:
        """Aynı veriden iki kez üretilen kart aynı olmalı."""
        ilk = build_campaign_card(db_session, kampanya)
        ikinci = build_campaign_card(db_session, kampanya)
        assert card_hash(ilk) == card_hash(ikinci)


class TestDigerKartlar:
    """Banka, sözlük ve ürün kartları."""

    def test_banka_karti(self, db_session: Session, kampanya: Campaign) -> None:
        banka = db_session.get(Bank, kampanya.bank_id)
        assert banka is not None
        kart = build_bank_card(db_session, banka)
        assert "Kart Katılım" in kart
        assert "1 kampanyası" in kart

    def test_kampanyasiz_banka_gizlenmez(self, db_session: Session) -> None:
        """⚠️ "Veri yok" bilgisi de bir bulgudur (CLAUDE.md)."""
        banka = Bank(code="bos_banka", name="Boş Katılım", website="https://bos.test")
        db_session.add(banka)
        db_session.flush()

        assert "bulunamadı" in build_bank_card(db_session, banka)

    def test_yasakli_terim_karti_uyari_icerir(self) -> None:
        terim = GlossaryTerm(
            term="kâr payı",
            definition="Katılım bankacılığında getiri.",
            conventional_equivalent="faiz",
            is_forbidden_conventional=False,
        )
        assert "faiz" in build_glossary_card(terim)

    def test_baglayici_olmayan_urun_isaretlenir(self, db_session: Session) -> None:
        """⚠️ Hesaplayıcı kaynaklı değer bankanın beyanı değildir (§10.3)."""
        banka = Bank(code="urun_banka", name="Ürün Katılım", website="https://u.test")
        db_session.add(banka)
        db_session.flush()
        urun = Product(
            bank_id=banka.id,
            name="İhtiyaç Finansmanı",
            product_type="ihtiyac_finansmani",
            is_binding=False,
        )
        db_session.add(urun)
        db_session.flush()

        assert NON_BINDING_NOTICE in build_product_card(db_session, urun)

    def test_baglayici_urunde_ibare_yok(self, db_session: Session) -> None:
        banka = Bank(code="urun_banka2", name="Ürün2", website="https://u2.test")
        db_session.add(banka)
        db_session.flush()
        urun = Product(bank_id=banka.id, name="Konut Finansmanı", is_binding=True)
        db_session.add(urun)
        db_session.flush()

        assert NON_BINDING_NOTICE not in build_product_card(db_session, urun)
