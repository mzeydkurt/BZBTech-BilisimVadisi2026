"""Ürün / finansman boru hattı: yazma, idempotency ve varyant ağacı.

⚠️ Ağa çıkmaz: `make_transport` ile sahte taşıyıcı verilir.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Product, ProductRate
from app.scrapers.base import BaseScraper
from app.scrapers.fetcher import Fetcher
from app.scrapers.models import DiscoveredUrl, RawProduct, RawProductRate
from app.scrapers.products import ProductRunner, band_key, product_external_key

URUN_URL = "https://x.example/urunler/konut-finansmani"

# Gerçek sayfaların yapısını taklit eden asgari HTML: bir oran tablosu ve
# varyant taşıyan bir hesaplayıcı formu.
URUN_HTML = """<!DOCTYPE html>
<html><body>
  <h1>Konut Finansmanı</h1>
  <p>Konut sahibi olmanız için 120 aya kadar vade ve 5.000.000 TL'ye kadar
     finansman imkânı sunulmaktadır. Ekspertiz değerinin en fazla %90'ı
     tutarında finansman kullanılabilir.</p>

  <form>
    <select name="finansmanTipi">
      <option value="1">Sigortalı</option>
      <option value="2">Sigortasız</option>
    </select>
    <input type="range" name="tutar" min="50000" max="5000000" />
    <select name="vade">
      <option value="12">12</option>
      <option value="36">36</option>
      <option value="120">120</option>
    </select>
  </form>

  <table>
    <caption>Sigortalı Konut Finansmanı</caption>
    <thead><tr><th>Vade</th><th>Kâr Payı Oranı</th><th>Tahsis Ücreti</th></tr></thead>
    <tbody>
      <tr><td>12 ay</td><td>%2,05</td><td>%0,50</td></tr>
      <tr><td>36 ay</td><td>%2,45</td><td>%0,50</td></tr>
    </tbody>
  </table>

  <p>Buradaki hesaplamalar bilgilendirme amaçlıdır, bağlayıcı değildir.</p>
</body></html>
"""


class _UrunScraper(BaseScraper):
    """Whitelist'ten tek ürün sayfası okuyan sahte banka."""

    bank_code = "emlak_katilim"

    def discover(self) -> list[DiscoveredUrl]:
        return []

    def parse_detail(self, html: str, url: str, hint: DiscoveredUrl) -> None:
        return None

    def discover_products(self) -> list[DiscoveredUrl]:
        return [
            DiscoveredUrl(
                url=URUN_URL,
                doc_type="product",
                category_hint="konut_finansmani",
                segment_hint="bireysel",
                discovery_method="whitelist",
            )
        ]

    def parse_products(self, html: str, url: str, hint: DiscoveredUrl) -> list[RawProduct]:
        from app.processing.cleaner import clean_html, extract_title
        from app.scrapers.calculator_inventory import (
            find_legal_notice,
            parse_form_controls,
            variant_candidates,
        )
        from app.scrapers.products import limits_from_page, rates_from_tables

        title = extract_title(html) or "Ürün"
        body = clean_html(html, bank_code=self.bank_code, title=title)
        limitler, kaynak = limits_from_page(html, body)
        form = parse_form_controls(html)

        ana = RawProduct(
            external_key=product_external_key("konut-finansmani", None),
            name=title,
            source_url=url,
            product_type=hint.category_hint,
            segment=hint.segment_hint,
            limits_source=kaynak,
            has_calculator=bool(form.input_fields),
            calculator_url=url,
            non_binding_notice=find_legal_notice(html),
            rates=rates_from_tables(html),
            **limitler,  # type: ignore[arg-type]
        )
        urunler = [ana]
        for aday in variant_candidates(form):
            urunler.append(
                RawProduct(
                    external_key=product_external_key(
                        "konut-finansmani", aday.variant_key or aday.label
                    ),
                    name=f"{title} — {aday.label}",
                    source_url=url,
                    parent_external_key=ana.external_key,
                    variant_key=aday.variant_key,
                    variant_label=aday.label,
                    variant_dimension=aday.variant_dimension,
                    variant_source="dropdown_option",
                    limits_source=kaynak,
                )
            )
        return urunler


def _scraper(tmp_path: Path, transport: httpx.MockTransport) -> _UrunScraper:
    """Sahte taşıyıcıya bağlı, hız sınırı kapalı ürün scraper'ı."""
    settings = Settings(
        raw_html_dir=str(tmp_path / "raw_html"),
        scraper_request_delay_seconds=0.0,
        scraper_max_retries=2,
        airgap_mode=False,
    )
    client = httpx.Client(transport=transport, follow_redirects=True)
    fetcher = Fetcher("emlak_katilim", settings=settings, client=client)
    return _UrunScraper(fetcher=fetcher, settings=settings)


@pytest.fixture
def kosucu(tmp_path: Path, make_transport: Any) -> _UrunScraper:
    """Sahte taşıyıcıya bağlı ürün scraper'ı."""
    return _scraper(tmp_path, make_transport({URUN_URL: (200, URUN_HTML)}))


def _kosur(session: Session, scraper: _UrunScraper, *, dry_run: bool = False) -> Any:
    try:
        return ProductRunner(scraper).run(session, dry_run=dry_run)
    finally:
        scraper.close()


class TestYazma:
    def test_urun_ve_varyantlar_yazilir(
        self, seeded_session: Session, kosucu: _UrunScraper
    ) -> None:
        sonuc = _kosur(seeded_session, kosucu)

        assert sonuc.status == "success"
        urunler = list(seeded_session.scalars(select(Product)))
        assert len(urunler) == 3  # ana + sigortalı + sigortasız

        ana = next(u for u in urunler if u.parent_product_id is None)
        assert ana.product_type == "konut_finansmani"
        assert {u.variant_label for u in urunler if u.parent_product_id} == {
            "Sigortalı",
            "Sigortasız",
        }

    def test_oranlar_html_table_kaynagiyla_yazilir(
        self, seeded_session: Session, kosucu: _UrunScraper
    ) -> None:
        _kosur(seeded_session, kosucu)

        oranlar = list(seeded_session.scalars(select(ProductRate)))
        assert len(oranlar) == 2
        assert {o.rate_source for o in oranlar} == {"html_table"}
        # Güven `rate_source`'tan türetilir, elle yazılmaz.
        assert all(o.confidence == Decimal("1.000") for o in oranlar)

    def test_para_ve_oran_decimal_kalir(
        self, seeded_session: Session, kosucu: _UrunScraper
    ) -> None:
        """⚠️ float sızıntısı finansal değerlerde yuvarlama hatası üretir."""
        _kosur(seeded_session, kosucu)

        oran = seeded_session.scalar(select(ProductRate).where(ProductRate.term_months == 12))
        assert oran is not None
        assert isinstance(oran.profit_rate_pct, Decimal)

        ana = seeded_session.scalar(select(Product).where(Product.parent_product_id.is_(None)))
        assert ana is not None
        if ana.amount_max is not None:
            assert isinstance(ana.amount_max, Decimal)

    def test_limitler_form_niteliklerinden_okunur(
        self, seeded_session: Session, kosucu: _UrunScraper
    ) -> None:
        """Slider min/max ürün limitidir; hesaplayıcıya istek atılmaz."""
        _kosur(seeded_session, kosucu)

        ana = seeded_session.scalar(select(Product).where(Product.parent_product_id.is_(None)))
        assert ana is not None
        # Slider min/max doğrudan üründen okundu.
        assert ana.amount_min == Decimal("50000")
        assert ana.amount_max == Decimal("5000000")
        # Vade seçicisi izinli vadeleri verdi.
        assert ana.allowed_terms == [12, 36, 120]
        assert ana.has_calculator is True
        # Form nitelikleri bankanın yayımladığı yapısal limittir.
        assert ana.is_binding is True

    def test_limits_source_en_zayif_kaynagi_bildirir(
        self, seeded_session: Session, kosucu: _UrunScraper
    ) -> None:
        """⚠️ Dürüstlük kuralı: tutar formdan gelse de LTV metinden geldiyse
        alan `text` raporlanır. "En güçlü" yazmak veriyi olduğundan sağlam
        gösterirdi."""
        _kosur(seeded_session, kosucu)

        ana = seeded_session.scalar(select(Product).where(Product.parent_product_id.is_(None)))
        assert ana is not None
        assert ana.ltv_max_pct == Decimal("90")
        assert ana.limits_source == "text"

    def test_yasal_uyari_birebir_saklanir(
        self, seeded_session: Session, kosucu: _UrunScraper
    ) -> None:
        _kosur(seeded_session, kosucu)

        ana = seeded_session.scalar(select(Product).where(Product.parent_product_id.is_(None)))
        assert ana is not None
        assert ana.non_binding_notice
        assert "bağlayıcı değildir" in ana.non_binding_notice


class TestIdempotency:
    def test_ikinci_calistirma_satir_cogaltmaz(
        self, seeded_session: Session, tmp_path: Path, make_transport: Any
    ) -> None:
        """⚠️ `products`'ta unique kısıt olmadan tablo sessizce şişiyordu."""
        for _ in range(2):
            _kosur(seeded_session, _scraper(tmp_path, make_transport({URUN_URL: (200, URUN_HTML)})))

        assert seeded_session.scalar(select(func.count()).select_from(Product)) == 3
        assert seeded_session.scalar(select(func.count()).select_from(ProductRate)) == 2


class TestKuruCalistirma:
    def test_kuru_calistirmada_hicbir_satir_yazilmaz(
        self, seeded_session: Session, kosucu: _UrunScraper
    ) -> None:
        _kosur(seeded_session, kosucu, dry_run=True)

        assert seeded_session.scalar(select(func.count()).select_from(Product)) == 0
        assert seeded_session.scalar(select(func.count()).select_from(ProductRate)) == 0


class TestOksuzVaryant:
    def test_ana_urunsuz_varyant_yazilmaz(
        self, seeded_session: Session, kosucu: _UrunScraper
    ) -> None:
        """Ana ürünü olmayan "sigortalı" satırı tek başına anlamsızdır."""
        from app.db.models import Bank
        from app.scrapers.models import ProductRunResult

        bank = seeded_session.scalar(select(Bank).where(Bank.code == "emlak_katilim"))
        assert bank is not None
        from app.db.models import SourceDocument

        belge = SourceDocument(
            bank_id=bank.id, url=URUN_URL, url_hash="b" * 64, doc_type="product", http_status=200
        )
        seeded_session.add(belge)
        seeded_session.flush()

        oksuz = RawProduct(
            external_key="yok#sigortali",
            name="Öksüz Varyant",
            source_url=URUN_URL,
            parent_external_key="hic-olmayan",
        )
        sonuc = ProductRunResult(bank_code="emlak_katilim")
        runner = ProductRunner(kosucu)
        try:
            runner._upsert_products(seeded_session, bank, [oksuz], belge, sonuc, dry_run=False)
        finally:
            kosucu.close()

        assert seeded_session.scalar(select(func.count()).select_from(Product)) == 0
        assert sonuc.errors_count == 1


class TestBandKey:
    def test_ayni_bant_ayni_anahtari_uretir(self) -> None:
        a = RawProductRate(rate_source="html_table", term_months=36, variant="sigortali")
        b = RawProductRate(rate_source="html_table", term_months=36, variant="sigortali")
        assert band_key(a) == band_key(b)

    def test_farkli_bant_farkli_anahtar_uretir(self) -> None:
        a = RawProductRate(rate_source="html_table", term_months=36, variant="sigortali")
        b = RawProductRate(rate_source="html_table", term_months=36, variant="sigortasiz")
        assert band_key(a) != band_key(b)

    def test_null_alanlar_anahtari_bozmaz(self) -> None:
        bos = RawProductRate(rate_source="text")
        assert band_key(bos) == "|" * (len(band_key(bos).split("|")) - 1)


class TestExternalKey:
    def test_varyantsiz_urun_base_eki_alir(self) -> None:
        assert product_external_key("konut-finansmani", None) == "konut-finansmani#base"

    def test_varyant_anahtari_slug_edilir(self) -> None:
        assert product_external_key("arac", "Sigortalı") == "arac#sigortali"


def test_kaydedilmis_html_ile_ag_erisimi_olmaz(kosucu: _UrunScraper) -> None:
    """conftest'teki autouse engel gerçek taşıyıcıyı düşürüyor."""
    with pytest.raises(RuntimeError):
        httpx.Client().get("https://gercek-adres.example")
