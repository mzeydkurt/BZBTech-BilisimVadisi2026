"""Tüm scraper'ların ortak şablonu.

Alt sınıflar YALNIZCA iki metod yazar: `discover()` ve `parse_detail()`.
Çekim, arşivleme, soft-404 denetimi, veritabanı kaydı, hata sayımı ve
çalıştırma özeti burada tek noktada yönetilir. Böylece 10 bankaya
ölçeklenirken bu mantık tekrar yazılmaz.

HATA YÖNETİMİ (§12): Tek bir URL'in hatası TÜM çalıştırmayı DURDURMAZ.
Hata sayılır, loglanır, döngü devam eder ve çalıştırma `partial` olarak kapanır.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from urllib.parse import urljoin, urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.core.exceptions import NotFoundError
from app.db.base import utc_now
from app.db.models import Bank, Campaign, ScrapeRun, SourceDocument
from app.logging_config import get_logger
from app.processing.cleaner import clean_html, extract_title
from app.processing.dates import (
    PeriodResult,
    PeriodSource,
    donem_gecerli_mi,
    find_period_in_sources,
)
from app.scrapers.calculator_inventory import (
    find_legal_notice,
    parse_form_controls,
    variant_candidates,
)
from app.scrapers.fetcher import Fetcher
from app.scrapers.models import (
    DiscoveredUrl,
    FetchResult,
    RawCampaign,
    RawProduct,
    ScrapeRunResult,
)
from app.services.campaign_service import compute_status
from app.utils.hashing import canonicalize_url, sha256_text, url_hash
from app.utils.slugify import slug_from_url_path

logger = get_logger(__name__)


class BaseScraper(ABC):
    """Banka scraper'ları için soyut taban sınıf."""

    bank_code: str = ""
    version: str = "1.0.0"

    # Başlık sayılmayacak marka metinleri. Sayfanın tepesindeki logo metni de
    # `<h1>` olabiliyor ve gerçek kampanya adının önüne geçiyor; gerekçe
    # `cleaner.extract_title` içinde. Yalnızca Ziraat Katılım dolduruyor.
    brand_headings: tuple[str, ...] = ()

    # ── ÜRÜN SAYFASI WHITELIST'İ ──────────────────────────
    #
    # `(yol, product_type, collateral_type)` üçlüleri. `product_base_url` ile
    # birleştirilerek adres kurulur.
    #
    # ⚠️ WHITELIST, KEŞFE TERCİH EDİLİR. Ürün sayfaları kampanya sayfalarının
    # aksine sabit ve azdır; otomatik keşif yanlış bir sayfayı ürün sayarsa
    # `parse_rate_tables` alakasız bir ücret tablosunu oran tablosu olarak
    # yazar. Aday adresler loglanır, elle eklenir.
    #
    # ⚠️ `collateral_type` sayfadan okunamıyor — ürünün teminat yapısı
    # bankanın ürün adlandırmasında örtük. Uydurmak yerine burada beyan edilir;
    # bilinmiyorsa None bırakılır.
    product_pages: tuple[tuple[str, str, str | None], ...] = ()
    product_base_url: str = ""

    def __init__(
        self,
        *,
        fetcher: Fetcher | None = None,
        settings: Settings | None = None,
        categories: Sequence[str] | None = None,
        limit: int | None = None,
    ) -> None:
        """
        Args:
            fetcher: Hazır çekici; testlerde sahte taşıyıcıyla verilir.
            settings: Uygulama ayarları.
            categories: Yalnızca bu kategoriler taransın. Alt sınıf bu listeyi
                `discover()` içinde dikkate alır; desteklemeyen scraper'da
                yok sayılır.
            limit: Çekilecek en fazla adres sayısı. Pilot doğrulamada tek bir
                bankaya birkaç istekle bakabilmek içindir; canlı çalıştırmada
                verilmez.
        """
        self.settings = settings or get_settings()
        self._fetcher = fetcher
        self._owns_fetcher = fetcher is None
        self.categories = tuple(categories) if categories else None
        self.limit = limit

    @property
    def fetcher(self) -> Fetcher:
        """Çekiciyi ilk kullanımda oluşturur."""
        if self._fetcher is None:
            self._fetcher = Fetcher(self.bank_code, settings=self.settings)
        return self._fetcher

    def close(self) -> None:
        """Kendi oluşturduğu çekiciyi kapatır."""
        if self._owns_fetcher and self._fetcher is not None:
            self._fetcher.close()

    # ── ALT SINIFIN YAZACAĞI TEK İKİ METOD ────────────────

    @abstractmethod
    def discover(self) -> list[DiscoveredUrl]:
        """Kampanya adreslerini keşfeder.

        Returns:
            Çekilecek adreslerin listesi.
        """

    @abstractmethod
    def parse_detail(self, html: str, url: str, hint: DiscoveredUrl) -> RawCampaign | None:
        """Detay sayfasından kampanya verisini çıkarır.

        Args:
            html: Sayfanın ham HTML'i.
            url: Sayfanın (yönlendirme sonrası) adresi.
            hint: Keşif aşamasından gelen bağlam bilgisi.

        Returns:
            Çıkarılan kampanya veya sayfa kampanya değilse None.
        """

    # ── ÇOK KAMPANYALI SAYFA ──────────────────────────────

    def parse_page(self, html: str, url: str, hint: DiscoveredUrl) -> list[RawCampaign]:
        """Sayfadaki TÜM kampanyaları döndürür.

        Varsayılan gerçekleme `parse_detail()` çıktısını listeye sarar. Tek
        sayfada birden çok kampanya yayımlayan bankalar yalnızca bunu override
        eder; `parse_detail` dokunulmadan kalır.

        Args:
            html: Sayfanın ham HTML'i.
            url: Sayfanın (yönlendirme sonrası) adresi.
            hint: Keşif aşamasından gelen bağlam bilgisi.

        Returns:
            Sayfadaki kampanyalar, SAYFADAKİ SIRAYLA. Kampanya yoksa boş liste.
        """
        raw = self.parse_detail(html, url, hint)
        return [] if raw is None else [raw]

    # ── ÜRÜN / FİNANSMAN TARAFI (opsiyonel) ───────────────

    def discover_products(self) -> list[DiscoveredUrl]:
        """Ürün/finansman sayfası adreslerini keşfeder.

        Varsayılan olarak `product_pages` whitelist'ini adrese çevirir.
        Whitelist boşsa boş liste döner: ürün sayfası olmayan banka hiçbir şey
        yazmaz ve "veri yok" kendiliğinden belgelenir. Kampanya akışı bu
        metottan etkilenmez.

        Returns:
            Çekilecek ürün adresleri.
        """
        if not self.product_pages:
            return []
        return [
            DiscoveredUrl(
                url=urljoin(self.product_base_url, yol),
                doc_type="product",
                category_hint=urun_turu,
                segment_hint="bireysel",
                discovery_method="whitelist",
            )
            for yol, urun_turu, _ in self.product_pages
        ]

    def product_description(self, body_text: str, title: str) -> str | None:  # noqa: ARG002
        """Ürün sayfasının açıklama metni.

        Varsayılan `None`: boilerplate'i açıklama sanmaktansa alanı boş
        bırakmak doğrudur. Gövdesi düzenli olan banka override eder.

        Args:
            body_text: Sayfanın temizlenmiş metni.
            title: Ürün başlığı.

        Returns:
            Açıklama veya None.
        """
        return None

    def collateral_for(self, url: str) -> str | None:
        """Adresin whitelist'teki teminat türünü döndürür.

        Args:
            url: Ürün sayfasının adresi.

        Returns:
            Teminat türü; whitelist'te yoksa None.
        """
        yol = urlsplit(url).path.rstrip("/")
        for aday, _, teminat in self.product_pages:
            if yol.endswith(urlsplit(aday).path.rstrip("/")):
                return teminat
        return None

    def parse_products(self, html: str, url: str, hint: DiscoveredUrl) -> list[RawProduct]:
        """Ürün sayfasından ürün, varyant ve oranları çıkarır.

        ⚠️ BU UYGULAMA BANKADAN BAĞIMSIZ. Ürün sayfaları kampanya sayfalarının
        aksine aynı üç kaynağı taşıyor: statik oran tablosu, hesaplayıcı form
        envanteri ve serbest metin. Üçünün ayrıştırıcısı da ortak
        (`rate_tables.py`, `calculator_inventory.py`, `limits.py`), bu yüzden
        banka başına ayrı `parse_products()` yazmak aynı kodu on kez
        çoğaltmak olurdu. Sayfa yapısı gerçekten farklı olan banka override
        eder.

        ⚠️ HESAPLAYICIYA İSTEK ATILMAZ. Dropdown seçenekleri yalnızca form
        niteliklerinden okunur; bu yüzden değerler `is_binding=True` kalır.

        Args:
            html: Sayfanın ham HTML'i.
            url: Sayfanın adresi.
            hint: Keşiften gelen ürün türü/segment bilgisi.

        Returns:
            Sayfadaki ürün ve varyantları; başlık bulunamazsa boş liste.
        """
        # ⚠️ YEREL İÇE AKTARMA ZORUNLU: `products.py` bu modülü içe aktarıyor,
        # modül düzeyinde yazılırsa döngü oluşur.
        from app.scrapers.products import (
            limits_from_page,
            product_external_key,
            rates_from_ltv_matrices,
            rates_from_payment_plan,
            rates_from_tables,
        )

        title = extract_title(html, ignore_headings=self.brand_headings)
        if not title:
            return []

        body_text = clean_html(html, bank_code=self.bank_code, title=title)
        slug = slug_from_url_path(url)
        teminat = self.collateral_for(url)
        limitler, limit_kaynagi = limits_from_page(html, body_text)
        form = parse_form_controls(html)

        ana = RawProduct(
            external_key=product_external_key(slug, None),
            name=title,
            source_url=url,
            product_type=hint.category_hint,
            segment=hint.segment_hint,
            description=self.product_description(body_text, title),
            collateral_type=teminat,
            limits_source=limit_kaynagi,
            limits_evidence=None if limit_kaynagi == "none" else body_text[:400],
            has_calculator=bool(form.input_fields),
            calculator_url=url if form.input_fields else None,
            non_binding_notice=find_legal_notice(html),
            rates=[
                *rates_from_tables(html),
                *rates_from_ltv_matrices(html),
                *rates_from_payment_plan(html),
            ],
            **limitler,  # type: ignore[arg-type]
        )

        urunler: list[RawProduct] = [ana]
        for aday in variant_candidates(form):
            urunler.append(
                RawProduct(
                    external_key=product_external_key(slug, aday.variant_key or aday.label),
                    name=f"{title} — {aday.label}",
                    source_url=url,
                    product_type=hint.category_hint,
                    segment=hint.segment_hint,
                    parent_external_key=ana.external_key,
                    # ⚠️ Eşleşme yoksa anahtar UYDURULMAZ; ham etiket saklanır
                    # ve `docs/variant_mapping.md`'ye "eşlenmedi" düşer.
                    variant_key=aday.variant_key,
                    variant_label=aday.label,
                    variant_dimension=aday.variant_dimension,
                    variant_source="dropdown_option",
                    collateral_type=teminat,
                    limits_source=limit_kaynagi,
                    has_calculator=True,
                    calculator_url=url,
                    non_binding_notice=ana.non_binding_notice,
                    **limitler,  # type: ignore[arg-type]
                )
            )

        return urunler

    # ── ALT SINIFIN TARİH KONUSUNDA YAZACAĞI TEK METOD ────

    def structured_period_text(self, html: str) -> str | None:  # noqa: ARG002
        """Bankaya özgü, tarih taşıyan DOM düğümünün metni.

        Varsayılan `None`; yapısal alanı olan bankalar (Ziraat, Vakıf, Albaraka)
        override eder. ⚠️ Alt sınıflar tarih alanlarına doğrudan yazmaz —
        `_apply_period()` belirler, bu metod yalnızca ona kaynak sunar.

        Args:
            html: Detay sayfasının ham HTML'i.

        Returns:
            Yapısal tarih alanının metni veya böyle bir alan yoksa None.
        """
        return None

    def resolve_period(
        self,
        *,
        html: str,
        conditions_text: str | None,
        body_text: str,
    ) -> PeriodResult:
        """Kampanya dönemini ortak kuralla çözer.

        Alt sınıflar çağırmaz ve override etmez; `_apply_period()` çağırır.
        Genel olması testlerin yazma yapmadan doğrulayabilmesi içindir.

        Args:
            html: Detay sayfasının ham HTML'i.
            conditions_text: Koşul bölümünün metni (varsa).
            body_text: Temizlenmiş gövde metni.

        Returns:
            İlk güvenilir bulgu; hiçbiri tutmazsa `precision="unknown"`.
        """
        return find_period_in_sources(
            (
                (PeriodSource.STRUCTURED, self.structured_period_text(html)),
                (PeriodSource.CONDITIONS, conditions_text),
                (PeriodSource.BODY, body_text),
            )
        )

    # ── ORTAK ŞABLON METOD (alt sınıf DEĞİŞTİRMEZ) ────────

    def run(self, session: Session, *, dry_run: bool = False) -> ScrapeRunResult:
        """Kazıma çalıştırmasını baştan sona yürütür.

        Args:
            session: Veritabanı oturumu.
            dry_run: True ise hiçbir şey yazılmaz, yalnızca raporlanır.

        Returns:
            Çalıştırma özeti.

        Raises:
            NotFoundError: Banka kaydı yoksa (önce seed çalıştırılmalı).
        """
        result = ScrapeRunResult(bank_code=self.bank_code)

        bank = session.scalar(select(Bank).where(Bank.code == self.bank_code))
        if bank is None:
            raise NotFoundError(
                f"Banka kaydı bulunamadı: {self.bank_code}. Önce 'make seed' çalıştırın."
            )

        run_row: ScrapeRun | None = None
        if not dry_run:
            run_row = ScrapeRun(bank_id=bank.id, status="running", scraper_version=self.version)
            session.add(run_row)
            session.flush()
            result.run_id = run_row.id

        logger.info("kazima_basladi", banka=self.bank_code, dry_run=dry_run)

        try:
            discovered = self.discover()
        except Exception as exc:
            result.add_error(f"discover() hatası: {type(exc).__name__}: {exc}")
            result.status = "failed"
            logger.error("kesif_basarisiz", banka=self.bank_code, hata=str(exc))
            self._close_run(session, run_row, result, dry_run=dry_run)
            return result

        result.urls_discovered = len(discovered)
        logger.info("kesif_tamamlandi", banka=self.bank_code, adres_sayisi=len(discovered))

        if not discovered:
            # ⚠️ SIFIR KEŞİF BAŞARI DEĞİLDİR. Ölçüldü: Türkiye Finans bir
            # çalıştırmada `kesif=0` verdi ve çalıştırma `success` kapandı;
            # 22 kampanya sessizce veri setinden düştü. Site geçici olarak
            # erişilemezdi, kod sağlamdı — ama fark yalnızca elle sayım
            # yapıldığında görüldü.
            #
            # Hiçbir banka normal durumda sıfır adres keşfetmez; kampanya
            # sayfası olmayan Adil Katılım bile 9 aday adres üretiyor.
            result.add_error(
                "discover() sıfır adres döndürdü — site erişilemez ya da yapı değişmiş"
            )
            logger.warning("kesif_bos", banka=self.bank_code)

        # Limit keşiften SONRA uygulanır: `urls_discovered` bankada gerçekte
        # kaç kampanya bulunduğunu göstermeye devam eder, yalnızca çekim daralır.
        if self.limit is not None and len(discovered) > self.limit:
            logger.info(
                "limit_uygulandi",
                banka=self.bank_code,
                kesfedilen=len(discovered),
                cekilecek=self.limit,
            )
            discovered = discovered[: self.limit]

        seen_slugs: set[str] = set()
        recorded_urls: set[str] = set()

        for hint in discovered:
            try:
                self._process_url(
                    session, bank, hint, result, seen_slugs, recorded_urls, dry_run=dry_run
                )
            except Exception as exc:
                # Tek URL hatası çalıştırmayı durdurmaz.
                result.add_error(f"{hint.url}: {type(exc).__name__}: {exc}")
                logger.warning("url_islenemedi", url=hint.url, banka=self.bank_code, hata=str(exc))

        self._record_auxiliary_documents(session, bank, recorded_urls, dry_run=dry_run)
        self._log_unseen_campaigns(session, bank, seen_slugs)

        result.status = "partial" if result.errors_count else "success"
        self._close_run(session, run_row, result, dry_run=dry_run)

        logger.info(
            "kazima_bitti",
            banka=self.bank_code,
            durum=result.status,
            kesfedilen=result.urls_discovered,
            cekilen=result.urls_fetched,
            yeni=result.campaigns_new,
            guncellenen=result.campaigns_updated,
            hata=result.errors_count,
        )
        return result

    # ── İç adımlar ────────────────────────────────────────

    def _process_url(
        self,
        session: Session,
        bank: Bank,
        hint: DiscoveredUrl,
        result: ScrapeRunResult,
        seen_slugs: set[str],
        recorded_urls: set[str],
        *,
        dry_run: bool,
    ) -> None:
        """Tek bir adresi çeker, kaydeder ve kampanyaya dönüştürür."""
        fetch = self.fetcher.fetch(hint.url)
        result.urls_fetched += 1
        recorded_urls.add(hint.url)

        # Başlık, yabancı kampanya bloklarının kesiminde çıpa olarak kullanılır
        # (bkz. `processing/boilerplate.py`). `parse_detail()` henüz
        # çalışmadığı için burada doğrudan çıkarılır.
        title = extract_title(fetch.html, ignore_headings=self.brand_headings)
        clean_text = (
            clean_html(fetch.html, bank_code=self.bank_code, title=title) if fetch.html else ""
        )

        document = self._build_source_document(bank, hint, fetch, clean_text)
        if not dry_run:
            session.add(document)
            session.flush()

        if not fetch.is_success:
            if fetch.robots_allowed is False:
                # robots yasağı hata değildir; belgelenir ve geçilir.
                logger.info("robots_atlandi", url=hint.url)
                return
            if fetch.is_soft_404:
                logger.info("soft_404_atlandi", url=hint.url)
                return
            result.add_error(f"{hint.url}: {fetch.error or 'başarısız çekim'}")
            if fetch.status_code == 404:
                self._mark_expired_if_exists(session, bank, hint, dry_run=dry_run)
            return

        assert fetch.html is not None  # is_success bunu garanti eder
        raws = self.parse_page(fetch.html, fetch.final_url or hint.url, hint)
        if not raws:
            logger.info("kampanya_cikarilamadi", url=hint.url, banka=self.bank_code)
            return

        bugun = utc_now().date()
        kabul_edilen: list[RawCampaign] = []
        for raw in raws:
            period = self._apply_period(raw, fetch.html, clean_text)

            kabul, red_nedeni = donem_gecerli_mi(
                period,
                min_yil=self.settings.min_campaign_year,
                bugun=bugun,
            )
            if not kabul:
                # Kampanya yazılmaz; ham HTML ve `source_documents` kaydı durur.
                result.campaigns_skipped += 1
                logger.info(
                    "kampanya_atlandi",
                    url=hint.url,
                    banka=self.bank_code,
                    slug=raw.external_slug,
                    neden=red_nedeni,
                    baslangic=str(period.start),
                    bitis=str(period.end),
                )
                self._expire_if_exists(session, bank, raw.external_slug, dry_run=dry_run)
                continue

            seen_slugs.add(raw.external_slug)
            kabul_edilen.append(raw)

        self._upsert_campaigns(session, bank, kabul_edilen, document, result, dry_run=dry_run)

    def _apply_period(self, raw: RawCampaign, html: str, clean_text: str) -> PeriodResult:
        """Kampanyanın dönemini ortak yolla belirler ve kanıtıyla `raw`'a yazar.

        ⚠️ "Scraper bulduysa dokunma" istisnası yoktur: tarihi üreten fonksiyon
        artık bu olduğu için çakışma olamaz.

        Args:
            raw: Scraper'ın ürettiği kampanya; yerinde güncellenir.
            html: Detay sayfasının ham HTML'i.
            clean_text: Kampanyanın temiz metni.

        Returns:
            Çözülmüş dönem (denetim için çağırana da döndürülür).
        """
        period = self.resolve_period(
            html=html,
            conditions_text=raw.conditions_text,
            body_text=clean_text,
        )

        raw.start_date = period.start
        raw.end_date = period.end
        raw.date_precision = period.precision
        raw.date_evidence_text = period.evidence_text
        raw.date_evidence_source = str(period.source) if period.source else None

        if period.bulundu:
            logger.debug(
                "tarih_cozuldu",
                slug=raw.external_slug,
                kaynak=raw.date_evidence_source,
                kesinlik=period.precision,
            )
        return period

    def _expire_if_exists(
        self,
        session: Session,
        bank: Bank,
        external_slug: str,
        *,
        dry_run: bool,
    ) -> None:
        """Dönem denetimini geçemeyen mevcut kaydı `expired` yapar.

        Kayıt silinmez; "bir zamanlar vardı" bilgisi de veridir.

        Args:
            session: Veritabanı oturumu.
            bank: Kampanyanın bankası.
            external_slug: Kampanyanın kararlı anahtarı.
            dry_run: True ise yazılmaz.
        """
        if dry_run:
            return
        mevcut = session.scalar(
            select(Campaign).where(
                Campaign.bank_id == bank.id,
                Campaign.external_slug == external_slug,
            )
        )
        if mevcut is None or mevcut.status == "expired":
            return
        mevcut.status = "expired"
        logger.info("bayat_kampanya_suresi_doldu", slug=external_slug, banka=self.bank_code)

    def _build_source_document(
        self,
        bank: Bank,
        hint: DiscoveredUrl,
        fetch: FetchResult,
        clean_text: str,
    ) -> SourceDocument:
        """Çekim sonucundan `source_documents` kaydı üretir.

        Başarısız çekimler de kaydedilir: verinin neden eksik olduğu
        sonradan kanıtlanabilir olmalıdır.
        """
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
            scraper_name=self.bank_code,
            scraper_version=self.version,
            robots_allowed=fetch.robots_allowed,
            is_soft_404=fetch.is_soft_404,
            discovery_method=hint.discovery_method,
        )

    def _upsert_campaigns(
        self,
        session: Session,
        bank: Bank,
        raws: list[RawCampaign],
        document: SourceDocument,
        result: ScrapeRunResult,
        *,
        dry_run: bool,
    ) -> None:
        """Kökleri ve alt kampanyaları iki geçişte yazar.

        Önce kökler yazılıp `flush()` ile id alır, sonra çocuklar bu id'ye
        bağlanır. Ebeveyni bulunamayan çocuk ATILMAZ, kök olarak yazılır.

        Args:
            session: Veritabanı oturumu.
            bank: Kampanyaların bankası.
            raws: Dönem denetimini geçmiş kampanyalar.
            document: Kaynak belge.
            result: Çalıştırma özeti; sayaçlar güncellenir.
            dry_run: True ise yazılmaz.
        """
        if not raws:
            return

        kokler = [r for r in raws if r.parent_slug is None]
        cocuklar = [r for r in raws if r.parent_slug is not None]

        slug_to_id: dict[str, int] = {}
        for raw in kokler:
            kampanya = self._upsert_campaign(
                session, bank, raw, document, result, parent_id=None, dry_run=dry_run
            )
            if kampanya is not None:
                slug_to_id[raw.external_slug] = kampanya.id

        for raw in cocuklar:
            parent_id = slug_to_id.get(raw.parent_slug or "")
            if parent_id is None and not dry_run:
                parent_id = self._parent_id_from_db(session, bank, raw.parent_slug or "")
            if parent_id is None:
                logger.warning(
                    "alt_kampanya_ebeveynsiz",
                    banka=self.bank_code,
                    slug=raw.external_slug,
                    ebeveyn=raw.parent_slug,
                )
            self._upsert_campaign(
                session, bank, raw, document, result, parent_id=parent_id, dry_run=dry_run
            )

    @staticmethod
    def _parent_id_from_db(session: Session, bank: Bank, parent_slug: str) -> int | None:
        """Ebeveyn kampanyayı veritabanından arar (önceki çalıştırmadan kalma)."""
        if not parent_slug:
            return None
        return session.scalar(
            select(Campaign.id).where(
                Campaign.bank_id == bank.id,
                Campaign.external_slug == parent_slug,
            )
        )

    def _upsert_campaign(
        self,
        session: Session,
        bank: Bank,
        raw: RawCampaign,
        document: SourceDocument,
        result: ScrapeRunResult,
        *,
        parent_id: int | None,
        dry_run: bool,
    ) -> Campaign | None:
        """Kampanyayı ekler veya günceller (bank_id + external_slug tekildir)."""
        status = compute_status(raw.start_date, raw.end_date)
        now = utc_now()

        existing = session.scalar(
            select(Campaign).where(
                Campaign.bank_id == bank.id,
                Campaign.external_slug == raw.external_slug,
            )
        )

        if existing is None:
            result.campaigns_new += 1
            if dry_run:
                return None
            kampanya = Campaign(
                bank_id=bank.id,
                source_document_id=document.id,
                parent_campaign_id=parent_id,
                block_index=raw.block_index,
                slug_source=raw.slug_source,
                external_slug=raw.external_slug,
                title=raw.title,
                description=raw.description,
                segment=raw.segment,
                target_customer=raw.target_customer,
                category=raw.category,
                bank_category=raw.bank_category,
                start_date=raw.start_date,
                end_date=raw.end_date,
                date_precision=raw.date_precision,
                date_evidence_text=raw.date_evidence_text,
                date_evidence_source=raw.date_evidence_source,
                status=status,
                participation_method=raw.participation_method,
                participation_channel=raw.participation_channel,
                sms_keyword=raw.sms_keyword,
                sms_number=raw.sms_number,
                coupon_code=raw.coupon_code,
                conditions_text=raw.conditions_text,
                exclusions_text=raw.exclusions_text,
                source_url=raw.source_url,
                first_seen_at=now,
                last_seen_at=now,
                is_archived=raw.is_archived,
            )
            session.add(kampanya)
            # Alt kampanyaların bağlanabilmesi için id hemen gerekir.
            session.flush()
            return kampanya

        result.campaigns_updated += 1
        if dry_run:
            return None

        existing.parent_campaign_id = parent_id
        existing.block_index = raw.block_index
        existing.slug_source = raw.slug_source
        existing.source_document_id = document.id
        existing.title = raw.title
        existing.description = raw.description
        existing.bank_category = raw.bank_category
        existing.segment = raw.segment
        existing.target_customer = raw.target_customer
        existing.start_date = raw.start_date
        existing.end_date = raw.end_date
        existing.date_precision = raw.date_precision
        existing.date_evidence_text = raw.date_evidence_text
        existing.date_evidence_source = raw.date_evidence_source
        existing.status = status
        existing.participation_method = raw.participation_method
        existing.participation_channel = raw.participation_channel
        existing.sms_keyword = raw.sms_keyword
        existing.sms_number = raw.sms_number
        existing.coupon_code = raw.coupon_code
        existing.conditions_text = raw.conditions_text
        existing.exclusions_text = raw.exclusions_text
        existing.source_url = raw.source_url
        existing.is_archived = raw.is_archived
        existing.last_seen_at = now
        return existing

    def _mark_expired_if_exists(
        self, session: Session, bank: Bank, hint: DiscoveredUrl, *, dry_run: bool
    ) -> None:
        """404 alınan bir adresin kampanyası varsa süresi dolmuş işaretler.

        Hayat Finans'ta biten kampanyalar sert HTTP 404 döndürüyor. Kayıt
        silinmez; durum `expired` yapılır ve ham HTML arşivde kalır.
        """
        if dry_run:
            return

        existing = session.scalar(
            select(Campaign).where(Campaign.bank_id == bank.id, Campaign.source_url == hint.url)
        )
        if existing is not None and existing.status != "expired":
            existing.status = "expired"
            logger.info("kampanya_404_expired", url=hint.url, banka=self.bank_code)

    def _record_auxiliary_documents(
        self, session: Session, bank: Bank, recorded_urls: set[str], *, dry_run: bool
    ) -> None:
        """Listeleme ve sitemap gibi yardımcı çekimleri de kaydeder.

        Keşif aşamasında çekilen sayfalar kampanya detayı değildir ama yine de
        yapılmış birer istektir. Kaydedilmezlerse "hangi adresler ne zaman
        çekildi" sorusu ham HTML arşiviyle veritabanı arasında tutarsız kalırdı.
        """
        if dry_run:
            return

        for fetch in self.fetcher.history:
            if fetch.url in recorded_urls:
                continue
            recorded_urls.add(fetch.url)

            is_xml = fetch.url.endswith((".xml", ".xml.gz"))
            hint = DiscoveredUrl(
                url=fetch.url,
                doc_type="other" if is_xml else "listing",
                discovery_method="listing",
            )
            # XML (sitemap) belgelerinde temiz metin üretilmez: HTML temizleyicisi
            # XML üzerinde anlamlı çıktı vermez. Ham içerik yine arşivlenmiştir.
            #
            # ⚠️ Burada `bank_code` GEÇİLMEZ. Bunlar liste sayfalarıdır; sayfanın
            # tamamı kampanya listesidir. "Tüm Kampanyalar" başlığından kesmek
            # liste sayfasının kendi içeriğini silerdi.
            clean_text = "" if is_xml or not fetch.html else clean_html(fetch.html)
            session.add(self._build_source_document(bank, hint, fetch, clean_text))

        session.flush()

    def _log_unseen_campaigns(self, session: Session, bank: Bank, seen_slugs: set[str]) -> None:
        """Bu çalıştırmada görülmeyen kampanyaları raporlar.

        PART 1'de yalnızca LOGLANIR. Otomatik `expired` işaretleme PART 2'deki
        diff mantığına bırakıldı: tek bir başarısız çalıştırma yüzünden tüm
        kampanyaların süresi dolmuş görünmesi kabul edilemez bir veri hatasıdır.
        """
        if not seen_slugs:
            return

        unseen = session.scalars(
            select(Campaign).where(
                Campaign.bank_id == bank.id,
                Campaign.external_slug.notin_(seen_slugs),
            )
        ).all()

        if unseen:
            logger.info(
                "bu_calistirmada_gorulmeyen_kampanyalar",
                banka=self.bank_code,
                sayi=len(unseen),
                slug_ornekleri=[c.external_slug for c in unseen[:5]],
                not_="PART 1'de otomatik expired yapılmaz",
            )

    def _close_run(
        self,
        session: Session,
        run_row: ScrapeRun | None,
        result: ScrapeRunResult,
        *,
        dry_run: bool,
    ) -> None:
        """`scrape_runs` kaydını sayaçlarla kapatır."""
        if dry_run or run_row is None:
            return

        run_row.finished_at = utc_now()
        run_row.status = result.status
        run_row.urls_discovered = result.urls_discovered
        run_row.urls_fetched = result.urls_fetched
        run_row.campaigns_new = result.campaigns_new
        run_row.campaigns_updated = result.campaigns_updated
        run_row.errors_count = result.errors_count
        run_row.error_log = "\n".join(result.errors) if result.errors else None
        session.commit()
