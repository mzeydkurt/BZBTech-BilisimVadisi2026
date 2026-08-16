"""LLM sağlayıcı sözleşmesi — ⚠️ DONMUŞ ARAYÜZ, DEĞİŞTİRİLMEYECEK.

Bu dosya SPRINT 3A ile SPRINT 3B arasındaki PAYLAŞILAN SÖZLEŞMEDİR. 3A çıkarım
motorunu bu arayüzün üzerine kurar; 3B yalnızca `LocalProvider`'ın İÇİNİ gerçek
model çağrısıyla doldurur. İmzalar değişirse iki sprint birbirini bekler hâle
gelir ve paralel çalışma biter.

TASARIM KARARI — MODEL ARKAYA TAKILAN BİR BİLEŞENDİR. Çıkarım motorunun hiçbir
katmanı hangi modelin kullanıldığını bilmez; yalnızca bu arayüzü çağırır. Bu
sayede SPRINT 3A'nın tamamı tek bir gerçek LLM çağrısı yapılmadan, `MockProvider`
ile geliştirilip test edilebilir.

⚠️ BULUT SAĞLAYICI EKLENMEZ. Şartname madde 8 ücretli hizmet kullanımını
yasaklıyor ve 5.9 on-premise çalışmayı istiyor. Arayüzün genişletilebilir olması
(yeni bir sınıf `LLMProvider`'ı uygulayarak eklenebilir) mimari iddiayı zaten
karşılar; bunu kanıtlamak için dışarıya çağrı yapan kod yazmak gerekmez.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ModelInfo:
    """Kullanılan modelin kimliği.

    Her çıkarım kaydına yazılır: hangi sürümün ürettiği bilinmeyen bir sonuç
    yeniden üretilemez ve ablasyon karşılaştırmasına giremez.
    """

    name: str
    version: str
    license: str
    # ⚠️ Her zaman True olmalı. Şartname 5.9 on-premise çalışmayı zorunlu
    # kılıyor; False dönen bir sağlayıcı bu iddiayı bozar.
    is_local: bool
    context_tokens: int


@dataclass
class LLMResponse:
    """Tek bir model çağrısının sonucu."""

    text: str
    # Şema verildiyse doğrulanmış JSON; verilmediyse None.
    parsed: dict[str, Any] | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    latency_ms: int = 0
    # Önbellekten geldiyse True — `extraction_runs.cache_hits` bunu sayar.
    from_cache: bool = False
    model_name: str | None = None


class LLMProviderError(Exception):
    """Sağlayıcı kaynaklı hataların ortak atası."""


class LLMTimeoutError(LLMProviderError):
    """Model yanıt vermedi (zaman aşımı).

    ⚠️ Kalıcı hata DEĞİLDİR: o kampanya atlanır, çalıştırma devam eder.
    """


class LLMInvalidJSONError(LLMProviderError):
    """Model şema istendiği hâlde geçerli JSON döndürmedi.

    Küçük modellerde sık görülür. Bir kez yeniden denenir; yine bozuksa o
    kampanyada LLM katmanı atlanır ve kural sonuçlarıyla devam edilir.
    """


class LLMUnavailableError(LLMProviderError):
    """Model servisine hiç ulaşılamıyor (kurulu değil, ayakta değil)."""


class LLMProvider(ABC):
    """Bir dil modeli sağlayıcısının uygulaması gereken sözleşme."""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        """Verilen istemden bir yanıt üretir.

        Args:
            prompt: Kullanıcı istemi (kaynak metin dahil).
            system: Sistem istemi; verilmezse sağlayıcı varsayılanı.
            schema: JSON şeması. Verilirse yanıt JSON'a zorlanır ve
                `LLMResponse.parsed` doldurulur.
            temperature: Örnekleme sıcaklığı. ⚠️ Varsayılan 0: bilgi çıkarımı
                yaratıcılık değil, aynı girdide aynı çıktı ister.
            max_tokens: Üretilecek en fazla token.

        Returns:
            Model yanıtı.

        Raises:
            LLMInvalidJSONError: Şema istendi ama yanıt geçerli JSON değil.
            LLMTimeoutError: Model zamanında yanıt vermedi.
            LLMUnavailableError: Servise ulaşılamıyor.
        """

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Metinleri vektöre çevirir.

        ⚠️ SPRINT 5'te kullanılacak. 3A'da `NotImplementedError` yükseltmek
        geçerlidir; imza şimdiden sabitlenir ki sonradan arayüz değişmesin.

        Args:
            texts: Gömme hesaplanacak metinler.

        Returns:
            Her metin için bir vektör.
        """

    @property
    @abstractmethod
    def model_info(self) -> ModelInfo:
        """Kullanılan modelin kimliği."""

    @abstractmethod
    async def health(self) -> bool:
        """Servis ayakta ve model yüklü mü?

        ⚠️ İSTİSNA YÜKSELTMEZ. Sağlık kontrolünün amacı durumu ÖĞRENMEKtir;
        servisin kapalı olması beklenen bir cevaptır, hata değil. SPRINT 3A'da
        `LocalProvider` için False dönmesi NORMALDİR (model henüz kurulmadı).

        Returns:
            Servis kullanılabilir durumdaysa True.
        """
