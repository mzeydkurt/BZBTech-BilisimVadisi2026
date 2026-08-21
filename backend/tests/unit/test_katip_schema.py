"""KATİP KAPI 1 — şema genişlemeleri.

`purchase_order`/`brand`/`model`/`availability_status` (products) ve
`data_source` (product_rates) kolonları ile genişletilen `rate_type`/
`rate_source` sözlükleri. Buradaki kısıtların amacı SPRINT 2'dekiyle aynı:
yanlış veriyi hata vererek reddetmek, sessizce kabul etmemek.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Bank, Product, ProductRate


@pytest.fixture
def banka(db_session: Session) -> Bank:
    bank = Bank(code="ornek_katilim", name="Örnek Katılım", website="https://ornek.com.tr")
    db_session.add(bank)
    db_session.flush()
    return bank


@pytest.fixture
def urun(db_session: Session, banka: Bank) -> Product:
    product = Product(bank_id=banka.id, name="Konut Finansmanı", product_type="konut_finansmani")
    db_session.add(product)
    db_session.flush()
    return product


class TestUrunMevcudiyeti:
    """`products.availability_status` — "ürün yok" ile "veri henüz toplanmadı" ayrımı."""

    def test_varsayilan_unknown(self, db_session: Session, urun: Product) -> None:
        db_session.refresh(urun)
        assert urun.availability_status == "unknown"

    def test_not_offered_kaydedilebilir(self, db_session: Session, banka: Bank) -> None:
        """TKBB'de ara ödemeli katılma hesabı sunmayan 4 banka için kullanılır."""
        db_session.add(
            Product(
                bank_id=banka.id,
                name="Ara Ödemeli Katılma Hesabı",
                product_type="ara_donem_kar_odemeli",
                availability_status="not_offered",
            )
        )
        db_session.flush()

        kayit = db_session.query(Product).filter_by(name="Ara Ödemeli Katılma Hesabı").one()
        assert kayit.availability_status == "not_offered"

    def test_gecersiz_deger_reddedilir(self, db_session: Session, banka: Bank) -> None:
        db_session.add(Product(bank_id=banka.id, name="X", availability_status="belki"))
        with pytest.raises(IntegrityError):
            db_session.flush()


class TestAlimSirasiVeMarkaModel:
    """`purchase_order` (ilk/sonraki alım) ve `brand`/`model` (Togg gibi)."""

    def test_alim_sirasi_saklanir(self, db_session: Session, banka: Bank, urun: Product) -> None:
        for sira, etiket in (("ilk_alim", "İlk Konut Alımı"), ("sonraki_alim", "İkinci Alım")):
            db_session.add(
                Product(
                    bank_id=banka.id,
                    parent_product_id=urun.id,
                    name=f"Konut Finansmanı — {etiket}",
                    product_type="konut_finansmani",
                    purchase_order=sira,
                    variant_dimension="alim_sirasi",
                    variant_source="table_column",
                )
            )
        db_session.flush()
        db_session.refresh(urun)

        assert {v.purchase_order for v in urun.variants} == {"ilk_alim", "sonraki_alim"}

    def test_marka_model_saklanir(self, db_session: Session, banka: Bank) -> None:
        """Togg T10X gibi model bazlı finansman."""
        db_session.add(
            Product(
                bank_id=banka.id,
                name="Togg Finansmanı — T10X",
                product_type="marka_ozel_finansman",
                brand="Togg",
                model="T10X",
                variant_dimension="marka_model",
                variant_source="table_row",
            )
        )
        db_session.flush()

        kayit = db_session.query(Product).filter_by(model="T10X").one()
        assert kayit.brand == "Togg"


class TestSifirIleNullAyrimi:
    """`profit_rate_pct=0` ile `NULL` KARIŞTIRILAMAZ (KAPI 1.3 — Togg %0,00 örneği).

    ⚠️ Bu ayrım bug'a çok müsait: bir ORM/serileştirme katmanı `0`'ı "boş"
    sanıp `None`'a düşürürse, "banka bu modele özel sıfır kâr paylı finansman
    sunuyor" bilgisi sessizce "veri yok"a dönüşür — ikisi anlamca taban tabana
    zıttır (bkz. `app/db/models/product.py` KAPI 1.3 yorumu).
    """

    def test_sifir_oran_null_degildir(self, db_session: Session, urun: Product) -> None:
        db_session.add(
            ProductRate(
                product_id=urun.id,
                term_months=12,
                profit_rate_pct=Decimal("0.0000"),
                rate_source="html_table",
                evidence_text=(
                    "Togg T10F V2, 12 ay, kredi tutarı 1.000.000 TL: aylık kâr oranı %0,00"
                ),
            )
        )
        db_session.flush()
        db_session.expire_all()

        kayit = db_session.query(ProductRate).filter_by(term_months=12).one()
        assert kayit.profit_rate_pct is not None
        assert kayit.profit_rate_pct == Decimal("0.0000")

    def test_veri_yoksa_gercekten_null_kalir(self, db_session: Session, urun: Product) -> None:
        db_session.add(ProductRate(product_id=urun.id, term_months=48, rate_source="html_table"))
        db_session.flush()
        db_session.expire_all()

        kayit = db_session.query(ProductRate).filter_by(term_months=48).one()
        assert kayit.profit_rate_pct is None


class TestVadeFarksizFinansman:
    """`rate_type='interest_free_benevolent_loan'` — karz-ı hasen / eğitim finansmanı."""

    def test_kaydedilebilir(self, db_session: Session, urun: Product) -> None:
        db_session.add(
            ProductRate(
                product_id=urun.id,
                rate_type="interest_free_benevolent_loan",
                rate_source="html_table",
                evidence_text="vade farksız, kâr payı alınmaz",
            )
        )
        db_session.flush()

        kayit = db_session.query(ProductRate).one()
        assert kayit.rate_type == "interest_free_benevolent_loan"
        assert kayit.profit_rate_pct is None

    def test_siralamaya_giremez(self, db_session: Session, urun: Product) -> None:
        """`rank_products` bu türü reddeder — vade farksız ürün finansman değildir."""
        from app.services.comparison_service import RankingError, rank_products

        db_session.add(
            ProductRate(
                product_id=urun.id,
                rate_type="interest_free_benevolent_loan",
                rate_source="html_table",
            )
        )
        db_session.flush()

        with pytest.raises(RankingError):
            rank_products(
                db_session,
                rate_type="interest_free_benevolent_loan",
                criterion="en_uzun_vade",
            )


class TestVeriKaynagi:
    """`product_rates.data_source` — banka sitesi mi TKBB Veri Peteği mi."""

    def test_varsayilan_bank_site(self, db_session: Session, urun: Product) -> None:
        oran = ProductRate(product_id=urun.id, rate_source="html_table")
        db_session.add(oran)
        db_session.flush()

        assert oran.data_source == "bank_site"

    def test_tkbb_kaynagi_saklanir(self, db_session: Session, urun: Product) -> None:
        db_session.add(
            ProductRate(
                product_id=urun.id,
                rate_type="participation_yield",
                rate_source="seed_manual",
                data_source="tkbb_veripetegi",
                currency="TRY",
                profit_rate_pct=Decimal("31.35"),
            )
        )
        db_session.flush()

        kayit = db_session.query(ProductRate).one()
        assert kayit.data_source == "tkbb_veripetegi"
        assert kayit.rate_source == "seed_manual"

    def test_gecersiz_kaynak_reddedilir(self, db_session: Session, urun: Product) -> None:
        db_session.add(ProductRate(product_id=urun.id, data_source="baska_bir_yer"))
        with pytest.raises(IntegrityError):
            db_session.flush()

    def test_seed_manual_gecerli_rate_source(self, db_session: Session, urun: Product) -> None:
        """Otomasyonun çalışmadığı ortamda elle girilen veri — tahmin değil."""
        db_session.add(ProductRate(product_id=urun.id, rate_source="seed_manual"))
        db_session.flush()

        kayit = db_session.query(ProductRate).one()
        assert kayit.confidence == Decimal("1.000")
