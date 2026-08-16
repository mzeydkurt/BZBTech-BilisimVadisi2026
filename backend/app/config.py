"""Uygulama yapılandırması.

KURAL: Hiçbir modül `os.environ`'a doğrudan erişmez. Tüm ayarlar `get_settings()`
üzerinden okunur. Böylece testlerde ayarları geçersiz kılmak tek noktadan yapılır.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> backend/
BACKEND_DIR = Path(__file__).resolve().parent.parent
# backend/ -> depo kökü
REPO_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    """Ortam değişkenlerinden okunan uygulama ayarları."""

    model_config = SettingsConfigDict(
        # .env depo kökünde tutulur; backend/.env varsa o da okunur (sonraki öncelikli).
        env_file=(REPO_ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Uygulama ──────────────────────────────────────────
    app_name: str = "Katılım Kampanya Analiz Platformu"
    app_env: str = "development"
    debug: bool = True
    api_v1_prefix: str = "/api/v1"
    # Virgülle ayrılmış liste olarak okunur; `cors_origin_list` ile parçalanır.
    cors_origins: str = "http://localhost:5173"

    # ── Veritabanı ────────────────────────────────────────
    # PostgreSQL'e geçiş için sadece bu değer değişir:
    #   postgresql+psycopg://user:pass@host:5432/dbname
    database_url: str = "sqlite:///./data/app.db"

    # ── Scraping ──────────────────────────────────────────
    scraper_user_agent: str = (
        "TeknofestKatilimBot/1.0 (+https://github.com/BZBTech/katilim-kampanya-analiz)"
    )
    scraper_request_delay_seconds: float = 1.5
    scraper_timeout_seconds: float = 30.0
    scraper_max_retries: int = 3
    scraper_respect_robots: bool = True
    raw_html_dir: str = "./data/raw_html"

    # ── On-premise ────────────────────────────────────────
    # true iken sistem hiçbir dış HTTP çağrısı yapmaz (scraping dahil devre dışı).
    airgap_mode: bool = False

    # Derlenmiş frontend dosyalarının dizini. Üretimde FastAPI bu dizini "/"
    # altından servis eder; böylece tek port (8000) yeterli olur ve on-prem
    # kurulumda ayrı bir Node çalışma zamanı gerekmez.
    frontend_dist_dir: str = "../frontend/dist"

    # ── Çıkarım motoru / LLM (SPRINT 3) ───────────────────
    # ⚠️ SPRINT 3A varsayılanı `mock`: bu sprintte tek bir gerçek model çağrısı
    # yapılmaz. SPRINT 3B modeli kurup bu değeri `local` yapacak.
    llm_provider: str = "mock"
    local_llm_base_url: str = "http://localhost:11434/v1"
    # ⚠️ Boş bırakıldı — model seçimi SPRINT 3B'nin kararı. Uydurma bir
    # varsayılan, kurulu olmayan bir modeli "yapılandırılmış" gösterirdi.
    local_llm_model: str = ""
    local_llm_context: int = 4096
    llm_timeout_seconds: float = 180.0
    llm_max_retries: int = 2
    # Prompt sürümü her çıkarım kaydına yazılır ve önbellek anahtarına girer:
    # prompt değişince eski yanıtlar kendiliğinden geçersizleşir.
    prompt_version: str = "v1"
    # null | fixture | invalid | timeout | halluc  (yalnızca MockProvider için)
    mock_llm_mode: str = "null"
    # SPRINT 5'te kullanılacak.
    embedding_model: str = "BAAI/bge-m3"

    # ── Türetilmiş değerler ───────────────────────────────

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS_ORIGINS değerini listeye çevirir."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        """Üretim ortamında mı çalışıyoruz?"""
        return self.app_env.lower() == "production"

    @property
    def sqlalchemy_url(self) -> str:
        """SQLAlchemy'ye verilecek bağlantı adresi.

        SQLite'ta göreli yol, çalışma dizinine değil `backend/` dizinine göre çözülür.
        Böylece uygulama hangi dizinden başlatılırsa başlatılsın aynı dosyaya bağlanır.
        PostgreSQL adresleri olduğu gibi bırakılır.
        """
        url = self.database_url
        prefix = "sqlite:///"
        if not url.startswith(prefix):
            return url

        raw_path = url[len(prefix) :]
        # sqlite:///:memory: gibi özel adresler dokunulmadan geçer.
        if raw_path.startswith(":"):
            return url

        path = Path(raw_path)
        if not path.is_absolute():
            path = BACKEND_DIR / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return f"{prefix}{path.resolve().as_posix()}"

    @property
    def frontend_dist_path(self) -> Path:
        """Derlenmiş frontend dizininin mutlak yolu."""
        path = Path(self.frontend_dist_dir)
        if not path.is_absolute():
            path = BACKEND_DIR / path
        return path.resolve()

    @property
    def raw_html_path(self) -> Path:
        """Ham HTML arşiv dizininin mutlak yolu.

        Ham HTML asla silinmez: bazı bankalarda biten kampanyalar 404'e düşüyor
        ve veri geri gelmiyor.
        """
        path = Path(self.raw_html_dir)
        if not path.is_absolute():
            path = BACKEND_DIR / path
        return path.resolve()


@lru_cache
def get_settings() -> Settings:
    """Ayarları tek örnek (singleton) olarak döndürür."""
    return Settings()
