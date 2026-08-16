"""Deterministik sahte sağlayıcı — SPRINT 3A'nın ÇALIŞAN sağlayıcısı.

Gerçek modelin yerine GEÇMEZ; pipeline'ın çalıştığını, hataları doğru
karşıladığını ve halüsinasyona karşı korunduğunu gerçek model olmadan kanıtlar.

⚠️ VARSAYILAN DAVRANIŞ "HER ALAN NULL"DUR. Bu bilinçli bir seçimdir: sistemin
bilgi yokken bilgi üretmemesi ASIL istenen davranıştır (şartname 7'de puanlanır),
dolayısıyla testlerin varsayılan hâli de bu olmalıdır. Sahte sağlayıcı zengin
veri üretseydi, pipeline "her zaman dolu yanıt gelir" varsayımıyla yazılır ve
gerçek modelde boş dönen alanlar çökme üretirdi.

⭐ `halluc` KİPİ — projenin en savunulabilir teknik farkının kanıtı.
Kaynak metinde GEÇMEYEN bir kanıt (evidence) üretir. Halüsinasyon guard'ının
(KAPI A7) bunu reddettiği, gerçek model kurulmadan gösterilebilir hâle gelir.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

from app.ai.providers.base import (
    LLMInvalidJSONError,
    LLMProvider,
    LLMResponse,
    LLMTimeoutError,
    ModelInfo,
)
from app.utils.hashing import sha256_text

# backend/app/ai/providers/mock.py -> backend/
BACKEND_DIR: Final[Path] = Path(__file__).resolve().parents[3]

# ⚠️ Fixture'lar test ağacında durur: bunlar üretim verisi değil, ÖLÇÜM
# girdisidir. Yol dışarıdan verilebilir ki uygulama kodu test dizinine
# bağımlı hâle gelmesin.
DEFAULT_FIXTURE_DIR: Final[Path] = BACKEND_DIR / "tests" / "fixtures" / "mock_llm"

# Fixture dosya adında kullanılan özet uzunluğu. Tam sha256 okunaksız uzunlukta.
FIXTURE_HASH_LENGTH: Final[int] = 16

MOCK_MODES: Final[tuple[str, ...]] = ("null", "fixture", "invalid", "timeout", "halluc")

# Sahte gecikme: gerçek model saniyeler sürer, mock sabit kalır ki testler
# zamana bağlı olmasın.
MOCK_LATENCY_MS: Final[int] = 5

# ⚠️ Kaynak metinlerde GEÇMEYECEK kadar özgül bir cümle. Guard'ın substring
# doğrulaması bunu kaynakta arayacak ve bulamayacak — testin can alıcı noktası.
FABRICATED_EVIDENCE: Final[str] = (
    "Bu kampanyada kâr payı oranı %1,23 olarak uygulanmaktadır (uydurulmuş kanıt)."
)
FABRICATED_VALUE: Final[float] = 1.23


class MockProvider(LLMProvider):
    """Testler ve geliştirme için deterministik sahte sağlayıcı."""

    def __init__(self, *, mode: str = "null", fixture_dir: Path | None = None) -> None:
        """Sağlayıcıyı kurar.

        Args:
            mode: `null` | `fixture` | `invalid` | `timeout` | `halluc`.
            fixture_dir: Fixture kökü; verilmezse `tests/fixtures/mock_llm`.

        Raises:
            ValueError: Tanımsız kip verildiyse. ⚠️ Sessizce varsayılana
                düşülmez: yazım hatası yüzünden `halluc` yerine `null` çalışan
                bir guard testi, guard'ı test etmediği hâlde YEŞİL görünür.
        """
        if mode not in MOCK_MODES:
            raise ValueError(f"Bilinmeyen MOCK_LLM_MODE: {mode!r}. Geçerli: {MOCK_MODES}")
        self._mode = mode
        self._fixture_dir = fixture_dir or DEFAULT_FIXTURE_DIR

    @property
    def mode(self) -> str:
        """Etkin sahte davranış kipi."""
        return self._mode

    @property
    def model_info(self) -> ModelInfo:
        """Sahte modelin kimliği.

        ⚠️ Ad `mock` ile başlar: bu sağlayıcıyla üretilmiş bir çıkarım kaydı
        veritabanında gerçek model çıktısıyla karışmaz.
        """
        return ModelInfo(
            name=f"mock:{self._mode}",
            version="1",
            license="—",
            is_local=True,
            context_tokens=4096,
        )

    async def health(self) -> bool:
        """Sahte sağlayıcı her zaman ayaktadır."""
        return True

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """SPRINT 5'te uygulanacak.

        ⚠️ Sahte vektör ÜRETİLMEZ. Anlamsal olmayan bir vektör, benzerlik
        testlerini "çalışıyor" gösterip gerçek modelde bambaşka sonuç verirdi.
        """
        raise NotImplementedError("Gömme SPRINT 5'te uygulanacak (bkz. embeddings tablosu).")

    @staticmethod
    def fixture_name(prompt: str) -> str:
        """İstemin fixture dosya adını üretir.

        Fixture yazmak isteyen testin dosyayı hangi adla kaydedeceğini bilmesi
        gerekir; ad üretimi tek yerde tutulur.

        Args:
            prompt: Modele gönderilen istem.

        Returns:
            `<özet>.json` biçiminde dosya adı.
        """
        return f"{sha256_text(prompt)[:FIXTURE_HASH_LENGTH]}.json"

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        """Kipe göre deterministik bir yanıt üretir.

        Args:
            prompt: Kullanıcı istemi.
            system: Yok sayılır (sahte sağlayıcı sistem istemine tepki vermez).
            schema: Verilirse yanıt bu şemanın alanlarıyla üretilir.
            temperature: Yok sayılır.
            max_tokens: Yok sayılır.

        Returns:
            Sahte model yanıtı.

        Raises:
            LLMTimeoutError: `timeout` kipinde.
            LLMInvalidJSONError: `invalid` kipinde ve şema istendiğinde.
        """
        del system, temperature, max_tokens  # Sahte sağlayıcı bunlara tepki vermez.

        if self._mode == "timeout":
            raise LLMTimeoutError("MockProvider: zaman aşımı benzetimi")

        if self._mode == "invalid":
            return self._invalid_response(schema)

        if self._mode == "fixture":
            fixture = self._read_fixture(prompt)
            if fixture is not None:
                return self._response(json.dumps(fixture, ensure_ascii=False), fixture)

        payload = self._hallucinated(schema) if self._mode == "halluc" else self._null(schema)
        if payload is None:
            # Şema verilmedi: düz metin beklenen bir çağrı.
            return self._response(FABRICATED_EVIDENCE if self._mode == "halluc" else "", None)
        return self._response(json.dumps(payload, ensure_ascii=False), payload)

    # ── İç yardımcılar ────────────────────────────────────

    def _response(self, text: str, parsed: dict[str, Any] | None) -> LLMResponse:
        """Ortak alanları doldurulmuş yanıt üretir."""
        return LLMResponse(
            text=text,
            parsed=parsed,
            latency_ms=MOCK_LATENCY_MS,
            from_cache=False,
            model_name=self.model_info.name,
        )

    def _invalid_response(self, schema: dict[str, Any] | None) -> LLMResponse:
        """Bozuk JSON üretir.

        Şema istenmediyse bozuk metin bir hata değildir — çağıran zaten düz
        metin bekliyordur; bu yüzden istisna yalnızca şema varken yükseltilir.
        """
        bozuk = '{"profit_rate_pct": {"value": 2.05, "evidence": "eksik kapanı'
        if schema is None:
            return self._response(bozuk, None)
        raise LLMInvalidJSONError(f"MockProvider: geçersiz JSON benzetimi: {bozuk[:40]}...")

    def _read_fixture(self, prompt: str) -> dict[str, Any] | None:
        """Kayıtlı fixture'ı okur; yoksa None.

        ⚠️ Fixture bulunamadığında hata YÜKSELTİLMEZ, `null` davranışına
        düşülür: eksik fixture testi çökertmemeli, "bilgi yok" varsayılanıyla
        pipeline'ın yine de tamamlandığını göstermeli.
        """
        path = self._fixture_dir / "extract" / self.fixture_name(prompt)
        if not path.is_file():
            # Göreve göre alt klasör aranır; `extract` dışındaki görevler için
            # de aynı ad kuralı geçerlidir.
            adaylar = list(self._fixture_dir.glob(f"*/{self.fixture_name(prompt)}"))
            if not adaylar:
                return None
            path = adaylar[0]

        icerik: Any = json.loads(path.read_text(encoding="utf-8"))
        return icerik if isinstance(icerik, dict) else None

    @staticmethod
    def _schema_fields(schema: dict[str, Any] | None) -> list[str] | None:
        """Şemadaki alan adlarını çıkarır."""
        if not schema:
            return None
        properties = schema.get("properties")
        return list(properties) if isinstance(properties, dict) else None

    def _null(self, schema: dict[str, Any] | None) -> dict[str, Any] | None:
        """Şemaya uygun ama TÜM ALANLARI null yanıt üretir."""
        alanlar = self._schema_fields(schema)
        if alanlar is None:
            return None
        return {alan: {"value": None, "evidence": None} for alan in alanlar}

    def _hallucinated(self, schema: dict[str, Any] | None) -> dict[str, Any] | None:
        """Kaynakta GEÇMEYEN kanıtla dolu yanıt üretir (guard testi için)."""
        alanlar = self._schema_fields(schema)
        if alanlar is None:
            return None
        return {
            alan: {"value": FABRICATED_VALUE, "evidence": FABRICATED_EVIDENCE} for alan in alanlar
        }
