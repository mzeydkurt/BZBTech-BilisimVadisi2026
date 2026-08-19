"""Ürün / finansman kazımasının orkestrasyonu.

`BaseScraper.run()` kampanyaları yazar; bu modül aynı `Fetcher`'ı, robots
denetimini, ham HTML arşivini ve `source_documents` kaydını yeniden kullanarak
ÜRÜN tarafını yazar. Ayrı bir scraper hiyerarşisi kurulmaz.

VERİ KAYNAĞI HİYERARŞİSİ (güçlüden zayıfa):

    1. html_table    statik HTML oran tablosu        güven 1.000
    2. html_attr     hesaplayıcı FORM ENVANTERİ      (oran değil, varyant+limit)
    3. text          serbest metinden limit çıkarımı güven 0.750

⚠️ Hesaplayıcı SORGULANMAZ. Form envanteri, bankanın yayımladığı yapısal
limittir (dropdown = varyant, slider min/max = tutar, vade seçici = izinli
vadeler) ve hesaplayıcıya tek istek atmadan elde edilir; bu yüzden
`is_binding=True` kalır. Sorgulama yapılırsa `is_binding=False` olur.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.core.vocab import VARIANT_VOCAB
from app.db.base import utc_now
from app.db.models import Bank, Product, ProductLimit, ProductRate, ScrapeRun, SourceDocument
from app.logging_config import get_logger
from app.processing.cleaner import clean_html, extract_title
from app.processing.limits import derive_rate_from_payment_plan, extract_limits_from_text
from app.processing.rate_tables import (
    parse_ltv_matrices,
    parse_payment_plan,
    parse_rate_tables,
    parse_vehicle_limit_matrices,
)
from app.scrapers.base import BaseScraper
from app.scrapers.calculator_inventory import allowed_terms, amount_bounds, parse_form_controls
from app.scrapers.models import (
    DiscoveredUrl,
    FetchResult,
    ProductRunResult,
    RawProduct,
    RawProductLimit,
    RawProductRate,
)
from app.utils.hashing import canonicalize_url, sha256_text, url_hash
from app.utils.slugify import slugify

logger = get_logger(__name__)

# Site geneli seçici eşiği: iki sayfanın seçenek kümesi bu oranda
# örtüşüyorsa küme ürüne değil siteye aittir. Birebir eşitlik (1.0)
# yetersiz kaldı — bankalar aynı seçeneği sayfadan sayfaya bir harf
# farkla yazabiliyor ("Katılma Hesap" / "Katılma Hesabı"). Türkiye
# Finans'ın dört seçeneğinin ikisi bu yüzden farklı yazılıyor ve
# örtüşme tam 0.5 çıkıyor — eşik buna göre belirlendi.
_SELECTOR_OVERLAP: float = 0.5

# Bant boyutlarının kodlanma sırası. Sıra SABİT olmalı: değişirse aynı oran
# farklı `band_key` üretir ve upsert satır çoğaltır.
# ⚠️ SPRINT 2.5: Katılma hesabı oranları para birimine, kademeye ve müşteri
# tipine göre farklılaşıyor; bunlar bant boyutuna eklendi.
_BAND_FIELDS: tuple[str, ...] = (
    "term_months",
    "term_days_min",
    "term_days_max",
    "variant",
    "amount_min",
    "amount_max",
    "ltv_band_min_pct",
    "ltv_band_max_pct",
    "energy_class",
    "vehicle_age_min",
    "vehicle_age_max",
    "currency",
    "account_tier",
    "customer_type",
    "rate_type",
)


def band_key(rate: RawProductRate) -> str:
    """Bant boyutlarını NULL-güvenli, deterministik tek dizeye kodlar.

    `product_rates` tekilliği bu anahtara dayanır. Bant kolonlarının çoğu NULL
    olabildiği ve SQLite'ta `NULL != NULL` olduğu için doğrudan bileşik anahtar
    kullanılamıyor.

    Args:
        rate: Kodlanacak oran satırı.

    Returns:
        Ör. `"t36|v-sigortali|a-|a-|l-|l-|e-|y-|y-"`.
    """
    parcalar: list[str] = []
    for alan in _BAND_FIELDS:
        deger = getattr(rate, alan)
        parcalar.append("" if deger is None else str(deger))
    return "|".join(parcalar)


_LIMIT_BAND_FIELDS: tuple[str, ...] = (
    "asset_value_min",
    "asset_value_max",
    "energy_class",
    "vehicle_age_min",
    "vehicle_age_max",
    "currency",
)


def limit_band_key(limit: RawProductLimit) -> str:
    """Limit bant boyutlarını NULL-güvenli, deterministik tek dizeye kodlar."""
    parcalar: list[str] = []
    for alan in _LIMIT_BAND_FIELDS:
        deger = getattr(limit, alan)
        parcalar.append("" if deger is None else str(deger))
    return "|".join(parcalar)


class ProductRunner:
    """Bir bankanın ürün sayfalarını gezip `products`/`product_rates` yazar.

    Hata sözleşmesi `BaseScraper.run()` ile aynıdır: tek bir adresin hatası
    çalıştırmayı durdurmaz, sayılır ve çalıştırma `partial` kapanır.
    """

    def __init__(self, scraper: BaseScraper) -> None:
        """
        Args:
            scraper: Ürün kancalarını sağlayan banka scraper'ı.
        """
        self.scraper = scraper

    def run(self, session: Session, *, dry_run: bool = False) -> ProductRunResult:
        """Ürün kazımasını baştan sona yürütür.

        Args:
            session: Veritabanı oturumu.
            dry_run: True ise hiçbir şey yazılmaz.

        Returns:
            Çalıştırma özeti.

        Raises:
            NotFoundError: Banka kaydı yoksa.
        """
        kod = self.scraper.bank_code
        result = ProductRunResult(bank_code=kod)

        bank = session.scalar(select(Bank).where(Bank.code == kod))
        if bank is None:
            raise NotFoundError(f"Banka kaydı bulunamadı: {kod}. Önce seed çalıştırın.")

        run_row: ScrapeRun | None = None
        if not dry_run:
            run_row = ScrapeRun(
                bank_id=bank.id,
                status="running",
                scraper_version=f"{self.scraper.version}-products",
            )
            session.add(run_row)
            session.flush()

        logger.info("urun_kazimasi_basladi", banka=kod, dry_run=dry_run)

        try:
            hedefler = self.scraper.discover_products()
        except Exception as exc:
            result.add_error(f"discover_products() hatası: {type(exc).__name__}: {exc}")
            result.status = "failed"
            self._close(session, run_row, result, dry_run=dry_run)
            return result

        result.urls_discovered = len(hedefler)
        if self.scraper.limit is not None:
            hedefler = hedefler[: self.scraper.limit]

        # ⚠️ İKİ FAZLI. Önce TÜM sayfalar çekilip ayrıştırılır, sonra yazılır.
        # Sebep `_site_geneli_secicileri_ele()` — bir dropdown'ın site geneli
        # seçici mi yoksa ürün varyantı mı olduğu ancak DİĞER sayfalara
        # bakılarak anlaşılıyor. Tek geçişte yazmak bunu imkânsız kılardı.
        sayfalar: list[tuple[DiscoveredUrl, SourceDocument, list[RawProduct]]] = []
        for hint in hedefler:
            try:
                cikti = self._process_url(session, bank, hint, result, dry_run=dry_run)
            except Exception as exc:
                # Tek adresin hatası çalıştırmayı durdurmaz.
                result.add_error(f"{hint.url}: {type(exc).__name__}: {exc}")
                logger.warning("urun_sayfasi_hatali", url=hint.url, banka=kod, hata=str(exc))
                continue
            if cikti is not None:
                sayfalar.append(cikti)

        self._site_geneli_secicileri_ele(sayfalar, bank_code=kod)

        for hint, document, raws in sayfalar:
            try:
                self._upsert_products(session, bank, raws, document, result, dry_run=dry_run)
            except Exception as exc:
                result.add_error(f"{hint.url}: {type(exc).__name__}: {exc}")
                logger.warning("urun_yazma_hatali", url=hint.url, banka=kod, hata=str(exc))

        result.status = "partial" if result.errors_count else "success"
        self._close(session, run_row, result, dry_run=dry_run)
        return result

    @staticmethod
    def _site_geneli_secicileri_ele(
        sayfalar: list[tuple[DiscoveredUrl, SourceDocument, list[RawProduct]]],
        *,
        bank_code: str,
    ) -> None:
        """Site geneli hesaplayıcı seçicilerinden doğan sahte varyantları siler.

        ⚠️ GERÇEK VERİDE ÖLÇÜLDÜ (Dünya Katılım, 17 Ağustos 2026). Sitenin
        ortak finansman hesaplayıcısı her ürün sayfasında aynı dropdown'ı
        gösteriyor: taşıt finansmanı sayfasında `konut-yeni`, `arsa`,
        `tuketici-ihtiyac-finansmani` seçenekleri var. Bunlar o ürünün
        varyantı DEĞİL, sitenin ürün seçicisi. Filtresiz çalıştırmada 31
        üründen 24'ü sahte varyanttı ve `products ≥ 60` eşiği yapay olarak
        geçilebiliyordu.

        AYIRT EDİCİ İMZA: aynı seçenek kümesi BİRDEN ÇOK farklı ürün
        sayfasında görülüyorsa o küme ürüne ait olamaz. Gerçek varyant
        (konut finansmanında `sifir_konut`/`ikinci_el_konut`) yalnızca kendi
        sayfasında bulunur.

        ⚠️ Ana ürün SİLİNMEZ, yalnızca varyantları düşer: sayfa gerçek bir
        ürünü anlatıyor, hatalı olan yalnızca varyant çıkarımı.

        Args:
            sayfalar: (hint, belge, ham ürünler) üçlüleri; yerinde değiştirilir.
            bank_code: Log için banka kodu.
        """
        # Her sayfanın varyant etiket kümesi.
        #
        # ⚠️ BİREBİR EŞİTLİK YETMİYOR. Türkiye Finans aynı hesap seçicisini
        # iki sayfada da gösteriyor ama etiketleri bir harf farklı yazıyor:
        # "Katılma Hesap" / "Katılma Hesabı", "E-Katılma Hesap" /
        # "E-Katılma Hesabı". Kümeler eşit olmadığı için eleme çalışmıyor ve
        # 8 sahte varyant yazılıyordu. ÖRTÜŞME oranına bakılır.
        kumeler: list[frozenset[str]] = []
        for _, _, raws in sayfalar:
            etiketler = frozenset(
                (r.variant_label or "").casefold() for r in raws if _dropdown_varyanti(r)
            )
            if etiketler:
                kumeler.append(etiketler)

        site_geneli: set[frozenset[str]] = set()
        for i, kume in enumerate(kumeler):
            for j, digeri in enumerate(kumeler):
                if i == j:
                    continue
                ortak = len(kume & digeri)
                if ortak and ortak / min(len(kume), len(digeri)) >= _SELECTOR_OVERLAP:
                    site_geneli.add(kume)
                    break

        # ⚠️ VADE EKSENİ DE AYNI SORUNU YAŞIYOR. Ziraat'in ortak
        # hesaplayıcısı sunucu HTML'inde ve vade seçicisi 1-60 listeliyor;
        # `limits_from_page` bunu her ürüne `term_months_max=60` olarak
        # yazıyordu. Birleşik liste HİÇBİR ürünün gerçek sınırı değil:
        # taşıt gerçekte 48 ay, konut 120 ay. Aynı vade kümesi birden çok
        # üründe görülüyorsa o sınır ürüne ait değildir ve YAZILMAZ —
        # `scripts/apply_inventory.py` seçenek etiketinden gerçek sınırı
        # okuyup dolduruyor.
        vade_imzalari: dict[tuple[int | None, int | None], int] = {}
        for _, _, raws in sayfalar:
            for kok in (r for r in raws if r.parent_external_key is None):
                if kok.term_months_min is None and kok.term_months_max is None:
                    continue
                anahtar = (kok.term_months_min, kok.term_months_max)
                vade_imzalari[anahtar] = vade_imzalari.get(anahtar, 0) + 1
        ortak_vade = {imza for imza, adet in vade_imzalari.items() if adet > 1}

        if not site_geneli and not ortak_vade:
            return

        for _, _, raws in sayfalar:
            for kok in (r for r in raws if r.parent_external_key is None):
                if (kok.term_months_min, kok.term_months_max) in ortak_vade:
                    logger.info(
                        "site_geneli_vade_elendi",
                        banka=bank_code,
                        urun=kok.external_key,
                        vade=f"{kok.term_months_min}-{kok.term_months_max}",
                    )
                    kok.term_months_min = None
                    kok.term_months_max = None
                    kok.allowed_terms = None

            # ⚠️ `site_geneli` kümeleri CASEFOLD edilmiş; burada da aynı
            # dönüşüm uygulanmazsa üyelik denetimi hiç tutmaz ve eleme
            # sessizce devre dışı kalır (24 sahte varyant geri gelmişti).
            etiketler = frozenset(
                (r.variant_label or "").casefold() for r in raws if _dropdown_varyanti(r)
            )
            if etiketler not in site_geneli:
                continue
            atilan = [r for r in raws if _dropdown_varyanti(r)]
            raws[:] = [r for r in raws if not _dropdown_varyanti(r)]
            logger.info(
                "site_geneli_secici_elendi",
                banka=bank_code,
                atilan_varyant=len(atilan),
                secenekler=sorted(etiketler)[:6],
            )

    def _process_url(
        self,
        session: Session,
        bank: Bank,
        hint: DiscoveredUrl,
        result: ProductRunResult,
        *,
        dry_run: bool,
    ) -> tuple[DiscoveredUrl, SourceDocument, list[RawProduct]] | None:
        """Tek ürün sayfasını çeker ve ayrıştırır.

        ⚠️ YAZMAZ. Yazma `run()` içinde, site geneli seçici elemesinden SONRA
        yapılır.

        Returns:
            (hint, belge, ham ürünler) veya sayfa kullanılamazsa None.
        """
        fetch = self.scraper.fetcher.fetch(hint.url)
        result.urls_fetched += 1

        title = extract_title(fetch.html, ignore_headings=self.scraper.brand_headings)
        clean_text = (
            clean_html(fetch.html, bank_code=self.scraper.bank_code, title=title)
            if fetch.html
            else ""
        )

        document = self._build_document(bank, hint, fetch, clean_text)
        if not dry_run:
            session.add(document)
            session.flush()

        if not fetch.is_success:
            if fetch.robots_allowed is False:
                logger.info("robots_atlandi", url=hint.url)
                return None
            if fetch.is_soft_404:
                logger.info("soft_404_atlandi", url=hint.url)
                return None
            result.add_error(f"{hint.url}: {fetch.error or 'başarısız çekim'}")
            return None

        assert fetch.html is not None
        raws = self.scraper.parse_products(fetch.html, fetch.final_url or hint.url, hint)
        if not raws:
            logger.info("urun_cikarilamadi", url=hint.url, banka=self.scraper.bank_code)
            return None

        return hint, document, raws

    def _upsert_products(
        self,
        session: Session,
        bank: Bank,
        raws: list[RawProduct],
        document: SourceDocument,
        result: ProductRunResult,
        *,
        dry_run: bool,
    ) -> None:
        """Ana ürünleri ve varyantlarını iki geçişte yazar.

        ⚠️ Ebeveyni bulunamayan varyant YAZILMAZ ve hata sayılır: ana ürünü
        olmayan "sigortalı" satırı tek başına anlamsızdır ve karşılaştırmaya
        girerse yanlış sonuç üretir.
        """
        kokler = [r for r in raws if r.parent_external_key is None]
        varyantlar = [r for r in raws if r.parent_external_key is not None]

        key_to_id: dict[str, int] = {}
        for raw in kokler:
            urun = self._upsert_product(
                session, bank, raw, document, result, parent_id=None, dry_run=dry_run
            )
            if urun is not None:
                key_to_id[raw.external_key] = urun.id
                self._write_rates(session, urun.id, raw.rates, document, result, dry_run=dry_run)
                self._write_limits(session, urun.id, raw.limits, document, result, dry_run=dry_run)

        for raw in varyantlar:
            anahtar = raw.parent_external_key or ""
            parent_id = key_to_id.get(anahtar)
            if parent_id is None and not dry_run:
                parent_id = session.scalar(
                    select(Product.id).where(
                        Product.bank_id == bank.id, Product.external_key == anahtar
                    )
                )
            if parent_id is None:
                # ⚠️ KURU ÇALIŞTIRMADA BU HATA DEĞİL. Ana ürün yazılmadığı için
                # id'si de yok; her varyant zorunlu olarak "ebeveynsiz" görünür.
                # Hata sayılırsa `--kuru` çıktısı gerçekte başarılı olacak bir
                # çalıştırmayı `partial` gösterir ve whitelist hatası ile
                # ayırt edilemez hâle gelir.
                if dry_run:
                    logger.debug(
                        "varyant_kuru_calistirmada_atlandi",
                        banka=bank.code,
                        varyant=raw.external_key,
                    )
                    continue
                result.add_error(f"{raw.external_key}: ana ürün bulunamadı ({anahtar})")
                logger.warning(
                    "varyant_ana_urunsuz",
                    banka=bank.code,
                    varyant=raw.external_key,
                    ana_urun=anahtar,
                )
                continue

            urun = self._upsert_product(
                session, bank, raw, document, result, parent_id=parent_id, dry_run=dry_run
            )
            if urun is not None:
                self._write_rates(session, urun.id, raw.rates, document, result, dry_run=dry_run)
                self._write_limits(session, urun.id, raw.limits, document, result, dry_run=dry_run)

    def _upsert_product(
        self,
        session: Session,
        bank: Bank,
        raw: RawProduct,
        document: SourceDocument,
        result: ProductRunResult,
        *,
        parent_id: int | None,
        dry_run: bool,
    ) -> Product | None:
        """Ürünü ekler veya günceller (`bank_id` + `external_key` tekildir).

        ⚠️ ASLA `delete` kullanılmaz: `Product.variants` ilişkisi
        `cascade="all, delete-orphan"` taşıyor, ana ürünün silinmesi tüm
        varyantları götürür. Artık sunulmayan varyant silinmez, `updated_at`
        eskir ve raporda görünür.
        """
        mevcut = session.scalar(
            select(Product).where(
                Product.bank_id == bank.id, Product.external_key == raw.external_key
            )
        )

        if mevcut is None:
            result.products_new += 1
            if dry_run:
                return None
            urun = Product(
                bank_id=bank.id,
                external_key=raw.external_key,
                source_document_id=document.id,
                parent_product_id=parent_id,
                name=raw.name,
                product_type=raw.product_type,
                segment=raw.segment,
                description=raw.description,
                variant_key=raw.variant_key,
                variant_label=raw.variant_label,
                variant_dimension=raw.variant_dimension,
                variant_source=raw.variant_source,
                amount_min=raw.amount_min,
                amount_max=raw.amount_max,
                term_months_min=raw.term_months_min,
                term_months_max=raw.term_months_max,
                allowed_terms=raw.allowed_terms,
                ltv_max_pct=raw.ltv_max_pct,
                collateral_type=raw.collateral_type,
                limits_source=raw.limits_source,
                limits_evidence=raw.limits_evidence,
                has_calculator=raw.has_calculator,
                calculator_url=raw.calculator_url,
                is_binding=raw.is_binding,
                non_binding_notice=raw.non_binding_notice,
            )
            session.add(urun)
            session.flush()
            return urun

        result.products_updated += 1
        if dry_run:
            return None

        mevcut.source_document_id = document.id
        mevcut.parent_product_id = parent_id
        mevcut.name = raw.name
        mevcut.product_type = raw.product_type
        mevcut.segment = raw.segment
        mevcut.description = raw.description
        mevcut.variant_key = raw.variant_key
        mevcut.variant_label = raw.variant_label
        mevcut.variant_dimension = raw.variant_dimension
        mevcut.variant_source = raw.variant_source
        mevcut.amount_min = raw.amount_min
        mevcut.amount_max = raw.amount_max
        mevcut.term_months_min = raw.term_months_min
        mevcut.term_months_max = raw.term_months_max
        mevcut.allowed_terms = raw.allowed_terms
        mevcut.ltv_max_pct = raw.ltv_max_pct
        mevcut.collateral_type = raw.collateral_type
        mevcut.limits_source = raw.limits_source
        mevcut.limits_evidence = raw.limits_evidence
        mevcut.has_calculator = raw.has_calculator
        mevcut.calculator_url = raw.calculator_url
        mevcut.is_binding = raw.is_binding
        mevcut.non_binding_notice = raw.non_binding_notice
        return mevcut

    def _write_rates(
        self,
        session: Session,
        product_id: int,
        raws: list[RawProductRate],
        document: SourceDocument,
        result: ProductRunResult,
        *,
        dry_run: bool,
    ) -> None:
        """Oran satırlarını yazar; aynı bant aynı gün ikinci kez eklenmez."""
        if dry_run or not raws:
            return

        bugun = document.fetched_at.date() if document.fetched_at else utc_now().date()

        # ⚠️ PARTİ İÇİ TEKİLLEŞTİRME ZORUNLU. Aşağıdaki `SELECT` yalnızca
        # VERİTABANINDAKİ satırları görüyor; aynı çağrıda `session.add()` ile
        # eklenmiş ama henüz flush edilmemiş satırları görmüyor. Bir sayfada
        # aynı bandı üreten iki tablo satırı olduğunda (Vakıf Katılım'ın konut
        # oran tablosunda ölçüldü) UNIQUE ihlali flush anında patlıyor,
        # oturum "rolled back" durumuna düşüyor ve o noktadan sonraki HER
        # işlem `PendingRollbackError` veriyordu — tek bir yinelenen satır
        # bütün bankanın çalıştırmasını düşürüyordu.
        yazilanlar: set[tuple[str, object, str]] = set()

        for raw in raws:
            gecerlilik = raw.effective_date or bugun
            anahtar = band_key(raw)

            kimlik = (raw.rate_source, gecerlilik, anahtar)
            if kimlik in yazilanlar:
                logger.info(
                    "yinelenen_oran_bandi_atlandi",
                    banka=self.scraper.bank_code,
                    urun=product_id,
                    band_key=anahtar,
                    kanit=(raw.evidence_text or "")[:80],
                )
                continue
            yazilanlar.add(kimlik)

            var_mi = session.scalar(
                select(ProductRate.id).where(
                    ProductRate.product_id == product_id,
                    ProductRate.rate_source == raw.rate_source,
                    ProductRate.effective_date == gecerlilik,
                    ProductRate.band_key == anahtar,
                )
            )
            if var_mi is not None:
                continue

            # ⚠️ `confidence` elle verilmez: `ProductRate.__init__` onu
            # `rate_source`'tan türetiyor (bkz. `RATE_SOURCE_CONFIDENCE`).
            session.add(
                ProductRate(
                    product_id=product_id,
                    band_key=anahtar,
                    rate_source=raw.rate_source,
                    rate_type=raw.rate_type,
                    effective_date=gecerlilik,
                    term_months=raw.term_months,
                    term_days_min=raw.term_days_min,
                    term_days_max=raw.term_days_max,
                    term_label=raw.term_label,
                    profit_rate_pct=raw.profit_rate_pct,
                    investor_share_pct=raw.investor_share_pct,
                    bank_share_pct=raw.bank_share_pct,
                    allocation_fee_pct=raw.allocation_fee_pct,
                    monthly_cost_pct=raw.monthly_cost_pct,
                    annual_cost_pct=raw.annual_cost_pct,
                    variant=raw.variant,
                    amount_min=raw.amount_min,
                    amount_max=raw.amount_max,
                    ltv_band_min_pct=raw.ltv_band_min_pct,
                    ltv_band_max_pct=raw.ltv_band_max_pct,
                    energy_class=raw.energy_class,
                    vehicle_age_min=raw.vehicle_age_min,
                    vehicle_age_max=raw.vehicle_age_max,
                    currency=raw.currency,
                    account_tier=raw.account_tier,
                    customer_type=raw.customer_type,
                    is_gross=raw.is_gross,
                    source_document_id=document.id,
                    evidence_text=raw.evidence_text,
                )
            )
            result.rates_new += 1

        session.flush()

    def _write_limits(
        self,
        session: Session,
        product_id: int,
        raws: list[RawProductLimit],
        document: SourceDocument,
        result: ProductRunResult,
        *,
        dry_run: bool,
    ) -> None:
        """Limit matrisi satırlarını product_limits tablosuna yazar."""
        if dry_run or not raws:
            return

        yazilanlar: set[tuple[str, str]] = set()

        for raw in raws:
            anahtar = limit_band_key(raw)
            kimlik = (raw.extraction_method, anahtar)
            if kimlik in yazilanlar:
                continue
            yazilanlar.add(kimlik)

            var_mi = session.scalar(
                select(ProductLimit.id).where(
                    ProductLimit.product_id == product_id,
                    ProductLimit.extraction_method == raw.extraction_method,
                    ProductLimit.band_key == anahtar,
                )
            )
            if var_mi is not None:
                continue

            session.add(
                ProductLimit(
                    product_id=product_id,
                    band_key=anahtar,
                    asset_value_min=raw.asset_value_min,
                    asset_value_max=raw.asset_value_max,
                    financing_ratio_pct=raw.financing_ratio_pct,
                    term_months_min=raw.term_months_min,
                    term_months_max=raw.term_months_max,
                    amount_max=raw.amount_max,
                    energy_class=raw.energy_class,
                    vehicle_age_min=raw.vehicle_age_min,
                    vehicle_age_max=raw.vehicle_age_max,
                    currency=raw.currency,
                    source_url=raw.source_url or document.url,
                    evidence_text=raw.evidence_text,
                    extraction_method=raw.extraction_method,
                    source_document_id=document.id,
                    fetched_at=document.fetched_at,
                )
            )
            result.limits_new += 1

        session.flush()

    def _build_document(
        self,
        bank: Bank,
        hint: DiscoveredUrl,
        fetch: FetchResult,
        clean_text: str,
    ) -> SourceDocument:
        """Ürün sayfası için `source_documents` kaydı üretir."""
        return SourceDocument(
            bank_id=bank.id,
            url=hint.url,
            canonical_url=canonicalize_url(fetch.final_url) if fetch.final_url else None,
            url_hash=url_hash(hint.url),
            doc_type=hint.doc_type,
            http_status=fetch.status_code,
            fetched_at=utc_now(),
            content_type=fetch.content_type,
            raw_html_path=fetch.raw_html_path,
            raw_html_sha256=fetch.raw_html_sha256,
            clean_text=clean_text or None,
            clean_text_sha256=sha256_text(clean_text) if clean_text else None,
            scraper_name=self.scraper.bank_code,
            scraper_version=f"{self.scraper.version}-products",
            robots_allowed=fetch.robots_allowed,
            is_soft_404=fetch.is_soft_404,
            discovery_method=hint.discovery_method,
        )

    @staticmethod
    def _close(
        session: Session,
        run_row: ScrapeRun | None,
        result: ProductRunResult,
        *,
        dry_run: bool,
    ) -> None:
        """Çalıştırma kaydını kapatır ve sayaçları yazar."""
        logger.info(
            "urun_kazimasi_bitti",
            banka=result.bank_code,
            durum=result.status,
            kesfedilen=result.urls_discovered,
            cekilen=result.urls_fetched,
            yeni_urun=result.products_new,
            guncellenen_urun=result.products_updated,
            yeni_oran=result.rates_new,
            yeni_limit=result.limits_new,
            hata=result.errors_count,
        )
        if dry_run or run_row is None:
            return

        run_row.status = result.status
        run_row.urls_discovered = result.urls_discovered
        run_row.urls_fetched = result.urls_fetched
        run_row.campaigns_new = result.products_new
        run_row.campaigns_updated = result.products_updated
        run_row.errors_count = result.errors_count
        run_row.error_log = "\n".join(result.errors) or None
        run_row.finished_at = utc_now()
        session.commit()


def rates_from_payment_plan(html: str | None) -> list[RawProductRate]:
    """Ödeme planından kâr payı oranını geri hesaplar (§7.5).

    ⚠️ ALBARAKA ORANI YAZMIYOR, PLANI YAZIYOR. Konut finansmanı sayfasında
    23 satırlık taksit tablosu var; oran annüite denkleminden çözülür.

    ⚠️ KAYNAK `payment_plan_derived` (güven 0.950), `html_table` DEĞİL:
    bankanın ilan ettiği bir sayı değil, bizim türettiğimiz bir değer. Bir
    kademe düşük güven bu farkı kayıt altına alır.

    ⚠️ SAYFANIN "YILLIK MALİYET ORANI" DEĞERİ AYRI BİR BÜYÜKLÜKTÜR ve buraya
    yazılmaz. Albaraka %82,39 yazıyor; o değer ücretler düşüldükten sonra net
    ele geçen tutar üzerinden bileşik yıllık maliyet (aynı planla %82,73
    doğrulandı). Buradaki oran ücretsiz, aylık kâr payıdır.

    Args:
        html: Ürün sayfasının HTML'i.

    Returns:
        Tek elemanlı liste; plan yoksa ya da oran çözülemezse boş liste.
    """
    plan = parse_payment_plan(html)
    if plan is None:
        return []

    # ⚠️ GERİ ÖDEME TOPLAMI ÜCRET İÇEREBİLİR. Albaraka'nın arsa finansmanı
    # planında "Taksit Tutarı" toplamı 293.744,08 TL, oysa ana para +
    # kâr payı = 249.033,88 TL; aradaki 44.710,20 TL ücret ve vergi.
    # Toplam üzerinden hesaplanan oran KÂR PAYI DEĞİL maliyet olur ve
    # bankayı olduğundan pahalı gösterir. Kâr payı kolonu varsa esas alınır.
    geri_odeme: Decimal | None
    if plan.principal is not None and plan.total_profit is not None:
        geri_odeme = plan.principal + plan.total_profit
    else:
        geri_odeme = plan.total_repayment

    oran = derive_rate_from_payment_plan(plan.principal, geri_odeme, plan.term_months)
    if oran is None:
        return []

    return [
        RawProductRate(
            rate_source="payment_plan_derived",
            term_months=plan.term_months,
            profit_rate_pct=oran,
            amount_min=plan.principal,
            amount_max=plan.principal,
            evidence_text=plan.evidence_text,
        )
    ]


def limits_from_ltv_matrices(html: str | None) -> list[RawProductLimit]:
    """Konut ve taşıt limit matrislerini RawProductLimit listesine çevirir.

    ⚠️ SPRINT 2.5: Bu satırlar kâr payı değil TEMİNAT/KREDİ ORANI taşıyor.
    Oran tablosuna (product_rates) yazılmak yerine product_limits tablosuna aktarılır.

    Args:
        html: Ürün sayfasının HTML'i.

    Returns:
        Her matris hücresi için bir limit satırı; matris yoksa boş liste.
    """
    bulunan: list[RawProductLimit] = []
    for matris in parse_ltv_matrices(html):
        for hucre in matris.cells:
            bulunan.append(
                RawProductLimit(
                    extraction_method="html_table",
                    financing_ratio_pct=hucre.ltv_max_pct,
                    energy_class=hucre.energy_class,
                    asset_value_min=hucre.amount_min,
                    asset_value_max=hucre.amount_max,
                    evidence_text=hucre.evidence_text,
                )
            )

    for v_lim in parse_vehicle_limit_matrices(html):
        bulunan.append(
            RawProductLimit(
                extraction_method="html_table",
                financing_ratio_pct=v_lim.financing_ratio_pct,
                term_months_max=v_lim.term_months_max,
                asset_value_min=v_lim.asset_value_min,
                asset_value_max=v_lim.asset_value_max,
                vehicle_age_min=v_lim.vehicle_age_min,
                vehicle_age_max=v_lim.vehicle_age_max,
                evidence_text=v_lim.evidence_text,
            )
        )
    return bulunan


def rates_from_tables(
    html: str | None,
    *,
    variant: str | None = None,
) -> list[RawProductRate]:
    """Statik HTML oran tablolarını `RawProductRate` listesine çevirir.

    En güvenilir kaynak budur (`html_table`, güven 1.000): bankanın kendi
    yayımladığı yapısal tablo.

    Args:
        html: Ürün sayfasının HTML'i.
        variant: Tabloda varyant belirtilmemişse kullanılacak varsayılan.

    Returns:
        Çıkarılan oran satırları; tablo yoksa boş liste.
    """
    bulunan: list[RawProductRate] = []
    for tablo in parse_rate_tables(html):
        for satir in tablo.rows:
            bulunan.append(
                RawProductRate(
                    rate_source="html_table",
                    rate_type=getattr(satir, "rate_type", "financing_rate"),
                    term_months=satir.term_months,
                    term_days_min=getattr(satir, "term_days_min", None),
                    term_days_max=getattr(satir, "term_days_max", None),
                    term_label=getattr(satir, "term_label", None),
                    profit_rate_pct=satir.profit_rate_pct,
                    investor_share_pct=getattr(satir, "investor_share_pct", None),
                    bank_share_pct=getattr(satir, "bank_share_pct", None),
                    allocation_fee_pct=satir.allocation_fee_pct,
                    monthly_cost_pct=satir.monthly_cost_pct,
                    annual_cost_pct=satir.annual_cost_pct,
                    variant=tablo.variant_key or tablo.variant_label or variant,
                    amount_min=getattr(satir, "amount_min", None),
                    amount_max=getattr(satir, "amount_max", None),
                    currency=getattr(satir, "currency", "TRY"),
                    account_tier=getattr(satir, "account_tier", None),
                    customer_type=getattr(satir, "customer_type", None),
                    is_gross=getattr(satir, "is_gross", None),
                    evidence_text=satir.evidence_text,
                )
            )
    return bulunan


def limits_from_page(html: str, text: str) -> tuple[dict[str, object], str]:
    """Sayfadan limit ve varyant bilgisini çıkarır.

    Öncelik: hesaplayıcı FORM ENVANTERİ (`html_attr`) > serbest metin (`text`).
    Form nitelikleri bankanın yayımladığı yapısal limittir; metinden çıkarım
    yalnızca formun vermediği alanları doldurur.

    Args:
        html: Sayfanın HTML'i.
        text: Sayfanın temizlenmiş metni.

    Returns:
        (limit alanları, en zayıf kaynak adı). Kaynak, doldurulan alanlar
        arasındaki EN ZAYIF olanıdır — veriyi olduğundan sağlam göstermemek için.
    """
    form = parse_form_controls(html)
    tutar_min, tutar_max = amount_bounds(form.input_fields)
    vadeler = allowed_terms(form.input_fields)

    metinden = extract_limits_from_text(text)

    alanlar: dict[str, object] = {}
    kaynaklar: list[str] = []

    def _ata(ad: str, form_degeri: object, metin_degeri: object) -> None:
        if form_degeri is not None:
            alanlar[ad] = form_degeri
            kaynaklar.append("html_attr")
        elif metin_degeri is not None:
            alanlar[ad] = metin_degeri
            kaynaklar.append("text")

    # ⚠️ SIFIR TAVAN LİMİT DEĞİLDİR. Kuveyt Türk'ün "Yuvam TL Katılma
    # Hesabı" sayfasında `amount_max=0` yazılıyordu; sıfır bir üst sınır
    # değil, ayrıştırma artığıdır.
    _ata("amount_min", tutar_min, metinden.amount_min)
    _ata("amount_max", _sifirsiz(tutar_max), _sifirsiz(metinden.amount_max))
    _ata("allowed_terms", vadeler, metinden.allowed_terms)
    _ata(
        "term_months_min",
        min(vadeler) if vadeler else None,
        metinden.term_months_min,
    )
    _ata(
        "term_months_max",
        max(vadeler) if vadeler else None,
        metinden.term_months_max,
    )
    _ata("ltv_max_pct", None, metinden.ltv_max_pct)

    if not kaynaklar:
        return alanlar, "none"
    # En zayıf kaynak kazanır (dürüstlük ilkesi).
    return alanlar, "text" if "text" in kaynaklar else "html_attr"


def product_external_key(url_slug: str, variant: str | None) -> str:
    """Ürün upsert anahtarını üretir.

    Args:
        url_slug: Sayfa adresinden okunan slug.
        variant: Varyant anahtarı veya etiketi; yoksa None.

    Returns:
        `"{url_slug}#{variant|base}"`.
    """
    parca = slugify(variant) if variant else None
    return f"{url_slug}#{parca or 'base'}"


def run_products(bank_code: str, *, dry_run: bool = False) -> ProductRunResult:
    """Tek bankanın ürün kazımasını çalıştırır (CLI girişi).

    Args:
        bank_code: Banka kodu.
        dry_run: True ise yazma yapılmaz.

    Returns:
        Çalıştırma özeti.
    """
    from app.db.session import SessionLocal
    from app.scrapers.registry import get_scraper

    scraper = get_scraper(bank_code)
    try:
        with SessionLocal() as session:
            return ProductRunner(scraper).run(session, dry_run=dry_run)
    finally:
        scraper.close()


__all__ = [
    "ProductRunner",
    "band_key",
    "limits_from_page",
    "product_external_key",
    "rates_from_tables",
    "run_products",
]


def _sifirsiz(deger: object) -> object:
    """Sıfır tutarı `None`a çevirir.

    Sıfır bir üst sınır değildir; ayrıştırma artığı ya da hesaplayıcı
    yer tutucusudur ("Ödenecek Toplam Tutar 0 TL").
    """
    return None if deger is not None and deger == 0 else deger


def _dropdown_varyanti(raw: RawProduct) -> bool:
    """Varyant bir HESAPLAYICI DROPDOWN'ından mı geldi?

    ⚠️ Site geneli seçici elemesi YALNIZCA dropdown varyantlarına uygulanır.
    Oran tablosundan gelen varyant (`separate_page`) o sayfanın KENDİ
    verisidir; birden çok sayfada aynı adla görünmesi ("Sigortalı" /
    "Sigortasız" hem taşıtta hem konutta var) onu sahte yapmaz.

    Ölçüldü: ayrım yapılmadığında Türkiye Finans'ın konut ve ihtiyaç
    finansmanı oranlarının tamamı — 54 satır — sessizce siliniyordu; ana
    ürün bölünmede boşaltılmış, alt ürünler ise "site geneli" diye atılmıştı.
    """
    return bool(raw.parent_external_key) and raw.variant_source == "dropdown_option"


def split_rate_variants(ana: RawProduct) -> list[RawProduct]:
    """Oran tablosu varyantlarını AYRI ÜRÜN satırlarına böler.

    ⚠️ Varyant, ORAN SATIRINDA taşınıyordu ama ÜRÜN satırında değil. Türkiye
    Finans taşıt sayfasında dört tablo var — {Sigortalı, Sigortasız} ×
    {0 km, 2. El} — ve dördünün oranı tek "Taşıt Finansmanı" ürününe
    yığılıyordu. Ürün kataloğunda tek satır görünüyor, hangi oranın hangi
    koşula ait olduğu kaybolıyordu; sigortasız oran (%4,27) ile sigortalı
    oran (%3,67) aynı ürünün altında yan yana duruyordu.

    ⚠️ TEK VARYANT BÖLÜNMEZ. Bir sayfada yalnızca bir varyant varsa alt ürün
    üretmek katalogda anlamsız bir kırılım yaratır; oranlar ana üründe kalır.

    ⚠️ Varyantsız oranlar ANA ÜRÜNDE kalır. Tablodan gelmeyen (ödeme planından
    türetilmiş) satırların varyantı yoktur; alt ürüne taşınırlarsa hangi
    koşula ait oldukları hakkında sahip olmadığımız bir bilgi iddia edilmiş
    olur.

    Args:
        ana: Sayfanın ana ürünü; oranları `rates` alanında.

    Returns:
        Ana ürün ve (varsa) varyant alt ürünleri. Bölünme gerekmiyorsa
        yalnızca ana ürün.

    """
    varyantli = [o for o in ana.rates if o.variant]
    varyantlar = sorted({str(o.variant) for o in varyantli})
    if len(varyantlar) < 2:
        return [ana]

    ana.rates = [o for o in ana.rates if not o.variant]

    cocuklar: list[RawProduct] = []
    for anahtar in varyantlar:
        oranlar = [o for o in varyantli if o.variant == anahtar]
        etiket = _varyant_etiketi(anahtar)
        cocuklar.append(
            RawProduct(
                external_key=product_external_key(ana.external_key.split("#", 1)[0], anahtar),
                name=f"{ana.name} — {etiket}",
                source_url=ana.source_url,
                product_type=ana.product_type,
                segment=ana.segment,
                parent_external_key=ana.external_key,
                variant_key=anahtar,
                variant_label=etiket,
                # ⚠️ Bileşik varyant (`sifir_arac+sigortali`) İKİ boyuta
                # yayılır; tek bir `variant_dimension` yazmak yanlış olur.
                variant_dimension=_tek_boyut(anahtar),
                variant_source="separate_page",
                collateral_type=ana.collateral_type,
                limits_source=ana.limits_source,
                non_binding_notice=ana.non_binding_notice,
                rates=oranlar,
            )
        )
    return [ana, *cocuklar]


# Kanonik anahtar → kullanıcıya gösterilecek ad. Katalogda "sifir arac"
# yazmak, veriyi doğru ama sunumu özensiz yapar.
_VARYANT_ADLARI: dict[str, str] = {
    "sifir_arac": "Sıfır Araç",
    "ikinci_el_arac": "2. El Araç",
    "ticari_arac": "Ticari Araç",
    "elektrikli_arac": "Elektrikli Araç",
    "hibrit_arac": "Hibrit Araç",
    "sifir_konut": "Sıfır Konut",
    "ikinci_el_konut": "İkinci El Konut",
    "kentsel_donusum": "Kentsel Dönüşüm",
    "sigortali": "Sigortalı",
    "sigortasiz": "Sigortasız",
    "enerji_a": "Enerji Sınıfı A",
    "enerji_b": "Enerji Sınıfı B",
    "enerji_diger": "Enerji Sınıfı Diğer",
}


def _varyant_etiketi(variant_key: str) -> str:
    """Kanonik anahtarı okunur ada çevirir; bileşik anahtarı ayırır."""
    parcalar = [_VARYANT_ADLARI.get(p, p.replace("_", " ")) for p in variant_key.split("+")]
    return " · ".join(parcalar)


def _tek_boyut(variant_key: str) -> str | None:
    """Varyant anahtarı TEK boyuta aitse o boyutu döndürür, değilse None."""
    if "+" in variant_key:
        return None
    for boyut, anahtarlar in VARIANT_VOCAB.items():
        if variant_key in anahtarlar:
            return boyut
    return None
