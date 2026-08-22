"""Ortak pytest fixture'ları.

Testler ASLA gerçek ağa çıkmaz (§13). Ağ gerektiren her şey fixture ile
sahte yanıtlara bağlanır.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.processing.cleaner import clean_html, extract_title
from app.scrapers.base import BaseScraper
from app.scrapers.models import RawCampaign

# Ayarlar içe aktarılmadan ÖNCE ortam değişkenleri sabitlenir; testler geliştirici
# makinesindeki .env dosyasından etkilenmemelidir.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("AIRGAP_MODE", "false")

# ⚠️ `setdefault` DEĞİL, doğrudan atama. Testler ASLA gerçek bir modele
# gitmemelidir: `.env` içinde `LLM_PROVIDER=local` bırakıldığında
# `/api/v1/extract` hibrit testi Ollama'ya çıkıyor, ağ koruması onu kesiyor
# ve test "ürün hatası" gibi görünen bir yapılandırma hatasıyla kırılıyordu.
# Ölçüm sabit olmalı; sağlayıcı seçimi geliştiricinin .env dosyasına
# bırakılamaz.
os.environ["LLM_PROVIDER"] = "mock"

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    """Kaydedilmiş HTML örneklerinin bulunduğu dizin."""
    return FIXTURES_DIR


@pytest.fixture
def read_fixture(fixtures_dir: Path):  # type: ignore[no-untyped-def]
    """Fixture dosyasını okuyan yardımcı fonksiyon döndürür.

    Kullanım:
        def test_x(read_fixture):
            html = read_fixture("emlak_katilim/kampanya_detay.html")
    """

    def _read(relative_path: str) -> str:
        return (fixtures_dir / relative_path).read_text(encoding="utf-8")

    return _read


@pytest.fixture
def donem_uygula():  # type: ignore[no-untyped-def]
    """`parse_detail()` çıktısına ORTAK tarih yolunu uygular.

    Tarih artık `parse_detail()` içinde çıkarılmıyor; `BaseScraper._apply_period()`
    belirliyor (gerekçe `app/processing/dates.py` "ORTAK DÖNEM ÇÖZÜMÜ"). Bu
    fixture aynı kod yolunu çalıştırır, böylece bir bankanın tarih biçimini
    sınayan testler veritabanına yazmadan çalışmaya devam eder.

    Kullanım:
        ham = scraper.parse_detail(html, url, hint)
        donem_uygula(scraper, html, ham)
        assert ham.start_date == date(2026, 8, 11)
    """

    def _uygula(scraper: BaseScraper, html: str, ham: RawCampaign) -> RawCampaign:
        title = extract_title(html, ignore_headings=scraper.brand_headings)
        body_text = clean_html(html, bank_code=scraper.bank_code, title=title) if html else ""
        scraper._apply_period(ham, html, body_text)
        return ham

    return _uygula


@pytest.fixture(autouse=True)
def _ag_erisimini_engelle(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Testlerde kazara gerçek HTTP isteği yapılmasını engeller (§13).

    Engel, istemci katmanına değil GERÇEK TAŞIYICI katmanına konur:
    `httpx.MockTransport` ile yazılan testler çalışmaya devam eder, ancak
    ağa çıkan her istek testi anında düşürür. Böylece "test geçti ama aslında
    internete çıktı" durumu oluşamaz.
    """
    import httpx

    def _blocked(*args: object, **kwargs: object) -> None:
        raise RuntimeError("Testler gerçek ağa çıkamaz. httpx.MockTransport veya fixture kullanın.")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _blocked, raising=True)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _blocked, raising=True)
    yield


# ── Veritabanı fixture'ları ───────────────────────────────


@pytest.fixture
def db_engine() -> Iterator[Engine]:
    """Bellek içi SQLite motoru.

    `StaticPool` zorunludur: bellek içi veritabanı bağlantı başına ayrı
    oluşturulur, havuz sabitlenmezse her oturum boş bir veritabanı görür.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    import app.db.models  # noqa: F401  (içe aktarım metadata'yı doldurur)
    from app.db.base import Base

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine: Engine) -> Iterator[Session]:
    """Boş şemaya bağlı veritabanı oturumu."""
    with Session(db_engine, expire_on_commit=False) as session:
        yield session


@pytest.fixture
def seeded_session(db_session: Session) -> Session:
    """10 banka ve terminoloji sözlüğü yüklenmiş oturum."""
    from app.db.seed import run_seed

    run_seed(db_session)
    return db_session


# ── HTTP sahte taşıyıcı ───────────────────────────────────


@pytest.fixture
def api_client(seeded_session: Session) -> Iterator[httpx.Client]:
    """Test veritabanına bağlı FastAPI istemcisi.

    `get_db` bağımlılığı test oturumuyla değiştirilir; böylece API testleri
    geliştiricinin gerçek veritabanına dokunmaz.
    """
    from fastapi.testclient import TestClient

    from app.api.deps import db_session
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[db_session] = lambda: seeded_session

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture
def make_transport() -> Callable[..., httpx.MockTransport]:
    """Adres → yanıt eşlemesinden sahte HTTP taşıyıcı üretir.

    Eşlemede olmayan her adres HTTP 404 döndürür; böylece scraper'ın eksik
    sayfa davranışı da gerçekçi biçimde test edilir.
    """

    def _make(
        routes: dict[str, tuple[int, str]],
        *,
        robots_body: str = "User-agent: *\nAllow: /\n",
    ) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url.endswith("/robots.txt"):
                return httpx.Response(200, text=robots_body)
            if url in routes:
                status, body = routes[url]
                return httpx.Response(
                    status,
                    text=body,
                    headers={"content-type": "text/html; charset=utf-8"},
                )
            return httpx.Response(
                404,
                text="<html><head><title>404</title></head><body>Sayfa bulunamadı</body></html>",
                headers={"content-type": "text/html; charset=utf-8"},
            )

        return httpx.MockTransport(handler)

    return _make
