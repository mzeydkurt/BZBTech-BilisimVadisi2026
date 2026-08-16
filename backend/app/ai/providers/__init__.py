"""LLM sağlayıcıları ve fabrikası.

⚠️ BURAYA BULUT SAĞLAYICI EKLENMEZ — `gemini.py`, `openai.py`, API anahtarı
okuyan hiçbir dosya. Şartname madde 8 ücretli hizmeti, madde 5.9 dış bağımlılığı
kısıtlıyor. Genişletilebilirlik iddiası soyutlamanın kendisiyle kanıtlanır:
yeni bir sağlayıcı `LLMProvider` arayüzünü uygulayarak eklenebilir.
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
from app.ai.providers.local import LocalProvider
from app.ai.providers.mock import MockProvider
from app.config import Settings

PROVIDERS: Final[tuple[str, ...]] = ("local", "mock")


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
    raise ValueError(f"Bilinmeyen LLM_PROVIDER: {settings.llm_provider!r}. Geçerli: {PROVIDERS}")


__all__ = [
    "PROVIDERS",
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
