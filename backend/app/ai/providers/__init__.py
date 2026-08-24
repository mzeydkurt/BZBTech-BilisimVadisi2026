"""LLM sağlayıcıları ve fabrikası.

⚠️ TİCARİ BULUT SAĞLAYICI EKLENMEZ — `gemini.py`, `openai.py`, ücretli bir
API anahtarı okuyan hiçbir dosya. Şartname madde 8 ücretli hizmeti, madde 5.9
dış bağımlılığı kısıtlıyor.

⚠️ `evren.py` BU KURALIN İSTİSNASI DEĞİL, KAPSAMI DIŞINDA. EVREN, TEKNOFEST
2026 kapsamında Savunma Sanayii Başkanlığı tarafından yarışmacı takımlara
tahsis edilmiş, kotasız ve ücretsiz bir çıkarım servisidir — ne ücretli bir
hizmet ne de üçüncü taraf bir buluttur. Gerekçe `evren.py` başında.

⚠️ `local` YOLU KALDIRILMAZ. On-prem / airgap gösterimi ona bağlıdır; EVREN
üretim kalitesi, Ollama kapalı ağ kanıtı içindir.

Genişletilebilirlik iddiası soyutlamanın kendisiyle kanıtlanır: yeni bir
sağlayıcı `LLMProvider` arayüzünü uygulayarak eklenir, çağıran kod değişmez.
"""

from __future__ import annotations

from typing import Final

from app.ai.providers.base import (
    LLMInvalidJSONError,
    LLMProvider,
    LLMProviderError,
    LLMResponse,
    LLMTimeoutError,
    LLMUnavailableError,
    ModelInfo,
)
from app.ai.providers.evren import EvrenProvider
from app.ai.providers.local import LocalProvider
from app.ai.providers.mock import MockProvider
from app.config import Settings

PROVIDERS: Final[tuple[str, ...]] = ("evren", "local", "mock")


def get_provider(settings: Settings) -> LLMProvider:
    """`LLM_PROVIDER` ayarına göre sağlayıcı örneği döndürür.

    Args:
        settings: `get_settings()` çıktısı.

    Returns:
        Yapılandırılmış sağlayıcı.

    Raises:
        ValueError: Tanımsız sağlayıcı adı. ⚠️ Sessizce `mock`a düşülmez:
            gerçek model beklenirken sahte sağlayıcıyla üretilmiş bir F1
            değeri, ölçümün tamamını geçersiz kılar ve fark edilmez.
    """
    ad = settings.llm_provider.strip().lower()
    if ad == "mock":
        return MockProvider(mode=settings.mock_llm_mode)
    if ad == "local":
        return LocalProvider(settings)
    if ad == "evren":
        return EvrenProvider(settings)
    raise ValueError(f"Bilinmeyen LLM_PROVIDER: {settings.llm_provider!r}. Geçerli: {PROVIDERS}")


__all__ = [
    "PROVIDERS",
    "EvrenProvider",
    "LLMInvalidJSONError",
    "LLMProvider",
    "LLMProviderError",
    "LLMResponse",
    "LLMTimeoutError",
    "LLMUnavailableError",
    "LocalProvider",
    "MockProvider",
    "ModelInfo",
    "get_provider",
]
