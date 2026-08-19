"""HTTP çekim katmanı: hız sınırlama, yeniden deneme, ham HTML arşivi.

ETİK KURALLAR (§8.2):
  - Kimliğimizi gizlemiyoruz: `SCRAPER_USER_AGENT` her istekte gönderilir.
  - İstekler arasında host bazlı bekleme uygulanır; robots.txt daha uzun bir
    süre talep ediyorsa ona uyulur.
  - robots.txt yasağı olan adrese istek YAPILMAZ.
  - `AIRGAP_MODE=true` iken hiçbir dış istek yapılmaz.

VERİ KAYBI ÖNLEMİ: Her yanıtın ham HTML'i diske yazılır ve ASLA silinmez.
Hayat Finans'ta biten kampanyalar sert 404 döndürüyor, Emlak Katılım'da arşiv
bölümü yok. Ham HTML saklanmazsa o veri bir daha elde edilemez.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from pathlib import Path
from threading import Event
from types import TracebackType
from typing import Final

import httpx
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import Settings, get_settings
from app.core.exceptions import AirgapError
from app.logging_config import get_logger
from app.scrapers.models import FetchResult
from app.scrapers.robots import RobotsCache
from app.scrapers.soft404 import is_soft_404
from app.utils.hashing import canonicalize_url, sha256_text, short_hash

logger = get_logger(__name__)

# Yeniden denenecek HTTP durum kodları.
# 493: Ziraat Katılım'ın WAF'ı bu STANDART DIŞI kodu döndürüyor. Kalıcı hata
#      sayılmaz, yeniden denenir.
RETRYABLE_STATUS_CODES: Final[frozenset[int]] = frozenset({408, 425, 429, 493})


class RetryableStatusError(Exception):
    """Yeniden denenmesi gereken HTTP durumu."""

    def __init__(self, status_code: int, url: str) -> None:
        super().__init__(f"HTTP {status_code} — yeniden denenecek: {url}")
        self.status_code = status_code


def _is_retryable_status(status_code: int) -> bool:
    """Durum kodu geçici bir hata mı?"""
    return status_code in RETRYABLE_STATUS_CODES or 500 <= status_code < 600


class Fetcher:
    """`httpx.Client` sarmalayıcısı: etik kazıma kurallarını uygular.

    Not (§8.2'den sapma ve gerekçesi): Bu sınıf `source_documents` tablosuna
    YAZMAZ, yalnızca yazılacak tüm bilgiyi `FetchResult` içinde döndürür.
    Kalıcılık, işlemi (transaction) yöneten `BaseScraper.run()` içinde tek
    noktadan yapılır. Böylece çekim mantığı veritabanı olmadan test edilebilir
    ve kısmi hatalarda tutarsız kayıt oluşmaz.
    """

    def __init__(
        self,
        bank_code: str,
        *,
        settings: Settings | None = None,
        client: httpx.Client | None = None,
        respect_robots: bool | None = None,
        soft_404_hashes: set[str] | None = None,
    ) -> None:
        """
        Args:
            bank_code: Ham HTML arşiv klasörünü belirler.
            settings: Uygulama ayarları; verilmezse `get_settings()`.
            client: Hazır httpx istemcisi; testlerde `MockTransport` ile verilir.
            respect_robots: robots.txt denetimi; verilmezse ayarlardan okunur.
            soft_404_hashes: Bilinen yer tutucu sayfa içerik özetleri.
        """
        self._settings = settings or get_settings()
        self._bank_code = bank_code
        self._soft_404_hashes = soft_404_hashes or set()
        self._respect_robots = (
            self._settings.scraper_respect_robots if respect_robots is None else respect_robots
        )

        self._owns_client = client is None
        self._client = client or httpx.Client(
            headers={"User-Agent": self._settings.scraper_user_agent},
            timeout=self._settings.scraper_timeout_seconds,
            # Cross-host yönlendirme ZORUNLU: albarakaturk -> albaraka,
            # emlakbank -> emlakkatilim adreslerine 302 ile geçiliyor.
            follow_redirects=True,
        )

        self._robots = RobotsCache(self._fetch_robots, self._settings.scraper_user_agent)
        self._last_request_at: dict[str, float] = {}

        # Yapılan TÜM çekimler burada birikir. `BaseScraper.run()` bu listeyi
        # kullanarak listeleme ve sitemap gibi yardımcı sayfaları da
        # `source_documents` tablosuna yazar; böylece hiçbir yanıt izsiz kalmaz.
        self.history: list[FetchResult] = []

    # ── Bağlam yöneticisi ─────────────────────────────────

    def __enter__(self) -> Fetcher:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Kendi oluşturduğu istemciyi kapatır."""
        if self._owns_client:
            self._client.close()

    def add_soft_404_hash(self, fingerprint: str) -> None:
        """Bilinen bir "sayfa yok" içerik özetini çalışma anında ekler.

        Bazı siteler yer tutucu sayfayı HTTP 200 ile döndürüyor ve o sayfada
        hiçbir hata ifadesi bulunmuyor; tek ayırt edici işaret içeriğin ana
        sayfayla birebir aynı olması. O özet ancak çalıştırma sırasında ana
        sayfa çekilerek öğrenilebildiği için yapıcıya verilemiyor.

        Args:
            fingerprint: `app.scrapers.soft404.content_fingerprint()` çıktısı.
        """
        if fingerprint:
            self._soft_404_hashes.add(fingerprint)

    # ── İç yardımcılar ────────────────────────────────────

    def _guard_airgap(self) -> None:
        """AIRGAP_MODE açıkken dışarı çıkışı engeller."""
        if self._settings.airgap_mode:
            raise AirgapError(
                "AIRGAP_MODE etkin: sistem dış ağa çıkmaz. "
                "Kazıma yapmak için AIRGAP_MODE=false yapın."
            )

    def _fetch_robots(self, robots_url: str) -> tuple[int | None, str | None]:
        """robots.txt indirir (RobotsCache tarafından çağrılır)."""
        self._guard_airgap()
        try:
            response = self._client.get(robots_url)
        except httpx.HTTPError as exc:
            logger.warning("robots_istegi_basarisiz", url=robots_url, hata=str(exc))
            return None, None
        return response.status_code, response.text

    def _throttle(self, url: str) -> None:
        """Aynı host'a ardışık istekler arasında bekler."""
        host = httpx.URL(url).host
        delay = self._settings.scraper_request_delay_seconds

        # ⚠️ Gecikme, izin denetimi kapalıyken de uygulanır. Yasağı geçmek
        # siteyi yormak için bir gerekçe değildir; ayrıca hızlı istek IP
        # engeline yol açar ve yarışma ortasında tüm kazımayı durdurur.
        robots_delay = self._robots.crawl_delay(url)
        if robots_delay is not None and robots_delay > delay:
            # Sitenin talep ettiği süre daha uzunsa ona uyulur.
            delay = robots_delay

        last = self._last_request_at.get(host)
        if last is not None:
            elapsed = time.monotonic() - last
            remaining = delay - elapsed
            if remaining > 0:
                time.sleep(remaining)

        self._last_request_at[host] = time.monotonic()

    def _archive(self, url: str, html: str) -> tuple[str, str]:
        """Ham HTML'i diske yazar ve arşiv yolunu döndürür.

        Dosya adı İÇERİK ADRESLİDİR: `{url_özeti}_{içerik_özeti}.html`.

        ⚠️ Yalnızca URL'den türetilen bir ad, her yeniden çalıştırmada önceki
        anlık görüntüyü ÜZERİNE YAZAR. Sayfalar her istekte birazcık değişiyor
        (oturum çerezi, güvenlik nonce'ı), dolayısıyla eski `source_documents`
        kayıtlarının `raw_html_sha256` değeri diskteki dosyayla artık
        eşleşmiyordu — ölçtüğümüzde 171 dosyanın 69'u tutmuyordu. Bu, "ham HTML
        asla kaybolmaz" güvencesini sessizce ortadan kaldırıyordu.

        İçerik adresli adlandırma iki sorunu birden çözer:
          - içerik değişmediyse aynı dosyaya yazılır (yer israfı olmaz)
          - içerik değiştiyse yeni dosya oluşur, ESKİ ANLIK GÖRÜNTÜ KORUNUR

        ⚠️ Ayrıca bayt kipinde yazılır: `Path.write_text` Windows'ta her
        `\\r\\n` değerini `\\r\\r\\n` yapar ve özet yine tutmaz.

        Args:
            url: Kaynağın adresi.
            html: Ham HTML gövdesi.

        Returns:
            (arşiv_kök_dizinine_göreli_yol, sha256_özeti).
        """
        directory = self._settings.raw_html_path / self._bank_code
        directory.mkdir(parents=True, exist_ok=True)

        digest = sha256_text(html)
        filename = f"{short_hash(canonicalize_url(url))}_{digest[:12]}.html"
        path: Path = directory / filename

        # Aynı içerik daha önce arşivlenmişse yeniden yazmaya gerek yok.
        if not path.exists():
            path.write_bytes(html.encode("utf-8"))

        relative = f"{self._bank_code}/{filename}"
        return relative, digest

    def _do_request(self, url: str) -> httpx.Response:
        """Tek bir HTTP isteği yapar; geçici hatalarda istisna fırlatır."""
        response = self._client.get(url)
        if _is_retryable_status(response.status_code):
            raise RetryableStatusError(response.status_code, url)
        return response

    def _request_with_retry(self, url: str) -> httpx.Response:
        """İsteği üstel geri çekilmeli yeniden denemeyle yapar (1s, 2s, 4s)."""
        retryer = Retrying(
            stop=stop_after_attempt(self._settings.scraper_max_retries),
            wait=wait_exponential(multiplier=1, min=1, max=8),
            retry=retry_if_exception_type(
                (httpx.TimeoutException, httpx.TransportError, RetryableStatusError)
            ),
            reraise=True,
        )
        return retryer(self._do_request, url)

    # ── Genel arayüz ──────────────────────────────────────

    def fetch(self, url: str) -> FetchResult:
        """Adresi çeker, ham HTML'i arşivler ve sonucu döndürür.

        İstisna FIRLATMAZ (AIRGAP hariç): hatalar `FetchResult.error` alanında
        taşınır, böylece tek bir URL'in hatası çalıştırmayı durdurmaz.

        Args:
            url: Çekilecek adres.

        Returns:
            Çekim sonucu.
        """
        result = self._fetch(url)
        self.history.append(result)
        return result

    def _fetch(self, url: str) -> FetchResult:
        """Çekim mantığı; kayıt tutma `fetch()` içinde yapılır."""
        self._guard_airgap()

        robots_izinli = self._robots.is_allowed(url)
        if self._respect_robots and not robots_izinli:
            if not self._settings.scraper_robots_override:
                logger.info("robots_nedeniyle_atlandi", url=url, banka=self._bank_code)
                return FetchResult(url=url, robots_allowed=False, error="robots.txt engelledi")
            # Açık izin beyanıyla geçiliyor; kayıt yine de işaretlenir.
            logger.warning("robots_yasagi_acik_izinle_gecildi", url=url, banka=self._bank_code)

        self._throttle(url)

        try:
            response = self._request_with_retry(url)
        except RetryableStatusError as exc:
            logger.warning("cekim_basarisiz_kalici", url=url, durum=exc.status_code)
            return FetchResult(url=url, status_code=exc.status_code, error=str(exc))
        except httpx.HTTPError as exc:
            logger.warning("cekim_basarisiz", url=url, hata=str(exc))
            return FetchResult(url=url, error=f"{type(exc).__name__}: {exc}")

        html = response.text
        content_type = response.headers.get("content-type")
        final_url = str(response.url)

        # Ham HTML her durumda arşivlenir — 404 yanıtları dahil.
        # Biten kampanyalarda 404 gövdesi tek kalan kanıttır.
        archive_path: str | None = None
        archive_hash: str | None = None
        if html:
            archive_path, archive_hash = self._archive(url, html)

        soft_404 = False
        if 200 <= response.status_code < 300:
            soft_404 = is_soft_404(html, url, known_soft_404_hashes=self._soft_404_hashes)
            if soft_404:
                logger.info("soft_404_tespit_edildi", url=url, banka=self._bank_code)

        if response.status_code >= 400:
            logger.info("http_hata_yaniti", url=url, durum=response.status_code)

        return FetchResult(
            url=url,
            final_url=final_url,
            status_code=response.status_code,
            html=html,
            content=response.content,
            content_type=content_type,
            raw_html_path=archive_path,
            raw_html_sha256=archive_hash,
            robots_allowed=robots_izinli,
            is_soft_404=soft_404,
            error=None if response.status_code < 400 else f"HTTP {response.status_code}",
        )

    # ── Toplu çekim ───────────────────────────────────────

    def fetch_many(
        self,
        urls: Iterable[str],
        *,
        cancel_event: Event | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> list[FetchResult]:
        """Birden çok adresi SIRAYLA, hız sınırına uyarak çeker.

        Sıralıdır ve bilinçli olarak paralelleştirilmemiştir: bu siteler gerçek
        bankalara ait ve eşzamanlı istek yükü hız sınırı sözleşmesini bozar.

        Args:
            urls: Çekilecek adresler.
            cancel_event: Kurulduğunda çekim durur ve o ana kadarki sonuçlar
                döner. Kullanıcı tetiklemeli çekimin iptal edilebilmesi için.
            on_progress: Her adresten sonra `(tamamlanan, toplam)` ile çağrılır.

        Returns:
            Çekim sonuçları; iptal edilmişse yalnızca tamamlananlar.
        """
        adresler = list(urls)
        toplam = len(adresler)
        sonuclar: list[FetchResult] = []

        for sira, url in enumerate(adresler, start=1):
            if cancel_event is not None and cancel_event.is_set():
                logger.info(
                    "toplu_cekim_iptal",
                    banka=self._bank_code,
                    tamamlanan=len(sonuclar),
                    toplam=toplam,
                )
                break

            sonuclar.append(self.fetch(url))

            if on_progress is not None:
                on_progress(sira, toplam)
            if sira % 10 == 0 or sira == toplam:
                logger.info(
                    "toplu_cekim_ilerleme", banka=self._bank_code, tamamlanan=sira, toplam=toplam
                )

        return sonuclar
