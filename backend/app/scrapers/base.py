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

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.core.exceptions import NotFoundError
from app.db.base import utc_now
from app.db.models import Bank, Campaign, ScrapeRun, SourceDocument
from app.logging_config import get_logger
from app.processing.cleaner import clean_html, extract_title
from app.processing.dates import find_campaign_period
from app.scrapers.fetcher import Fetcher
from app.scrapers.models import DiscoveredUrl, FetchResult, RawCampaign, ScrapeRunResult
from app.services.campaign_service import compute_status
from app.utils.hashing import canonicalize_url, sha256_text, url_hash

logger = get_logger(__name__)


class BaseScraper(ABC):
    """Banka scraper'ları için soyut taban sınıf."""

    bank_code: str = ""
    version: str = "1.0.0"

    # Başlık sayılmayacak marka metinleri. Sayfanın tepesindeki logo metni de
    # `<h1>` olabiliyor ve gerçek kampanya adının önüne geçiyor; gerekçe
    # `cleaner.extract_title` içinde. Yalnızca Ziraat Katılım dolduruyor.
    brand_headings: tuple[str, ...] = ()

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
        raw = self.parse_detail(fetch.html, fetch.final_url or hint.url, hint)
        if raw is None:
            logger.info("kampanya_cikarilamadi", url=hint.url, banka=self.bank_code)
            return

        self._fill_missing_dates(raw, clean_text)

        seen_slugs.add(raw.external_slug)
        self._upsert_campaign(session, bank, raw, document, result, dry_run=dry_run)

    @staticmethod
    def _fill_missing_dates(raw: RawCampaign, clean_text: str) -> None:
        """Scraper tarih bulamadıysa dönemi METİNDEN çıkarmayı dener.

        ⚠️ Yalnızca scraper HİÇBİR tarih bulamadığında çalışır; bulunmuş bir
        tarihin üzerine ASLA yazmaz. Yapısal alan her zaman daha güvenilirdir.

        Gerekçe (canlı veride ölçüldü): Türkiye Finans'ın 22 kampanyasının
        tamamı `unknown` kayıtlıydı; oysa 18'inin metninde tarih açıkça
        yazıyor ("Kampanya 25 Mayıs - 31 Aralık 2026 tarihleri arasında
        geçerlidir"). Scraper yapısal alan aradığı için bunları göremiyordu.
        "Veri yok" ile "veri okunmadı" ayrı şeylerdir.

        Bulgu güvenilir değilse alanlar `NULL` kalır — tarih uydurulmaz.

        Args:
            raw: Scraper'ın ürettiği kampanya; yerinde güncellenir.
            clean_text: Kampanyanın temiz metni.
        """
        if raw.start_date is not None or raw.end_date is not None:
            return

        start, end, precision = find_campaign_period(clean_text)
        if precision == "unknown":
            return

        raw.start_date = start
        raw.end_date = end
        raw.date_precision = precision
        logger.info(
            "tarih_metinden_cikarildi",
            slug=raw.external_slug,
            baslangic=str(start),
            bitis=str(end),
            kesinlik=precision,
        )

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

    def _upsert_campaign(
        self,
        session: Session,
        bank: Bank,
        raw: RawCampaign,
        document: SourceDocument,
        result: ScrapeRunResult,
        *,
        dry_run: bool,
    ) -> None:
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
                return
            session.add(
                Campaign(
                    bank_id=bank.id,
                    source_document_id=document.id,
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
            )
            return

        result.campaigns_updated += 1
        if dry_run:
            return

        existing.source_document_id = document.id
        existing.title = raw.title
        existing.description = raw.description
        existing.bank_category = raw.bank_category
        existing.segment = raw.segment
        existing.target_customer = raw.target_customer
        existing.start_date = raw.start_date
        existing.end_date = raw.end_date
        existing.date_precision = raw.date_precision
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
