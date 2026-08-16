"""Yerel model sağlayıcısı — Ollama'nın OpenAI uyumlu ucu üzerinden.

⚠️ SPRINT 3A'DA BU DOSYA ÇALIŞTIRILMAZ. Kod yazılır ama model kurulu olmadığı
için test EDİLMEZ; `health()` False döner ve bu BEKLENEN durumdur. Gerçek
modelle doğrulama ve prompt ince ayarı SPRINT 3B'nin işidir.

⚠️ SPRINT 3B'DE ARAYÜZ İMZALARI DEĞİŞMEYECEK. Yalnızca bu sınıfın içi
düzeltilebilir: uç adresi, istek gövdesi, yanıt ayrıştırma. `LLMProvider`
sözleşmesine (`providers/base.py`) dokunulmaz — çıkarım motorunun tamamı o
sözleşmenin üzerine kurulu.

⚠️ AIRGAP_MODE BU SAĞLAYICIYI ENGELLEMEZ. Model `localhost`ta çalışır; kurum
ağının dışına çıkan bir istek değildir. Aksine on-premise iddiasının ta
kendisidir: veri kurumdan çıkmadan çıkarım yapılır. Airgap yalnızca kazımayı
(bankalara giden istekleri) durdurur.
"""

from __future__ import annotations

import json
import time
from typing import Any, Final

import httpx

from app.ai.providers.base import (
    LLMInvalidJSONError,
    LLMProvider,
    LLMResponse,
    LLMTimeoutError,
    LLMUnavailableError,
    ModelInfo,
)
from app.config import Settings
from app.logging_config import get_logger

logger = get_logger(__name__)

# Ollama'nın OpenAI uyumlu uçları.
CHAT_PATH: Final[str] = "/chat/completions"
MODELS_PATH: Final[str] = "/models"


class LocalProvider(LLMProvider):
    """Yerelde çalışan açık kaynaklı bir modeli kullanır."""

    def __init__(self, settings: Settings) -> None:
        """Sağlayıcıyı ayarlardan kurar.

        Args:
            settings: `get_settings()` çıktısı. ⚠️ Ortam değişkenine doğrudan
                erişilmez; tüm ayarlar buradan okunur.
        """
        self._settings = settings
        self._base_url = settings.local_llm_base_url.rstrip("/")
        self._model = settings.local_llm_model

    @property
    def model_info(self) -> ModelInfo:
        """Yapılandırılmış modelin kimliği.

        ⚠️ `local_llm_model` SPRINT 3B'de doldurulacak; 3A'da boş olması
        normaldir ve `health()` zaten False döndürür.
        """
        return ModelInfo(
            name=self._model or "(tanımlanmadı — SPRINT 3B)",
            version=self._settings.prompt_version,
            license="Apache-2.0",
            is_local=True,
            context_tokens=self._settings.local_llm_context,
        )

    async def health(self) -> bool:
        """Servise ulaşılabiliyor ve model yüklü mü?

        ⚠️ İSTİSNA YÜKSELTMEZ (bkz. `LLMProvider.health`). SPRINT 3A'da model
        kurulu olmadığı için False dönmesi beklenen sonuçtur, hata değil.
        """
        if not self._model:
            logger.info("yerel_model_tanimlanmadi", not_="SPRINT 3B'de .env'e yazılacak")
            return False

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self._base_url}{MODELS_PATH}")
        except httpx.HTTPError as exc:
            logger.info("yerel_llm_ulasilamiyor", url=self._base_url, hata=str(exc))
            return False

        if response.status_code != httpx.codes.OK:
            return False

        # Servis ayakta ama istenen model yüklü olmayabilir; ikisi ayrı sorundur.
        yuklu = {str(m.get("id", "")) for m in response.json().get("data", [])}
        if self._model not in yuklu:
            logger.warning("yerel_model_yuklu_degil", istenen=self._model, yuklu=sorted(yuklu))
            return False
        return True

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """SPRINT 5'te uygulanacak (bkz. `embeddings` tablosu)."""
        raise NotImplementedError("Gömme SPRINT 5'te uygulanacak.")

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        """Yerel modelden yanıt alır.

        Args:
            prompt: Kullanıcı istemi.
            system: Sistem istemi.
            schema: Verilirse yanıt JSON'a zorlanır (`response_format`).
            temperature: Örnekleme sıcaklığı (varsayılan 0).
            max_tokens: Üretilecek en fazla token.

        Returns:
            Model yanıtı.

        Raises:
            LLMUnavailableError: Servise ulaşılamıyor.
            LLMTimeoutError: Model zamanında yanıt vermedi.
            LLMInvalidJSONError: Şema istendi ama yanıt geçerli JSON değil.
        """
        mesajlar: list[dict[str, str]] = []
        if system:
            mesajlar.append({"role": "system", "content": system})
        mesajlar.append({"role": "user", "content": prompt})

        govde: dict[str, Any] = {
            "model": self._model,
            "messages": mesajlar,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if schema is not None:
            # Ollama'nın JSON kipi: yanıt geçerli JSON olmaya zorlanır.
            govde["response_format"] = {"type": "json_object"}

        baslangic = time.monotonic()
        yanit = await self._istek(govde)
        gecen_ms = int((time.monotonic() - baslangic) * 1000)

        metin = self._icerik(yanit)
        ayristirilan = self._ayristir(metin) if schema is not None else None
        kullanim = yanit.get("usage") or {}

        return LLMResponse(
            text=metin,
            parsed=ayristirilan,
            prompt_tokens=kullanim.get("prompt_tokens"),
            completion_tokens=kullanim.get("completion_tokens"),
            latency_ms=gecen_ms,
            from_cache=False,
            model_name=self._model,
        )

    # ── İç yardımcılar ────────────────────────────────────

    async def _istek(self, govde: dict[str, Any]) -> dict[str, Any]:
        """İsteği yeniden denemeli olarak yapar.

        ⚠️ Yeniden deneme YALNIZCA zaman aşımı ve bağlantı hatası için. Model
        anlamlı bir hata döndürdüyse (ör. model bulunamadı) tekrar denemek
        aynı sonucu verir ve boşuna bekletir.
        """
        url = f"{self._base_url}{CHAT_PATH}"
        son_hata: Exception | None = None

        for deneme in range(self._settings.llm_max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self._settings.llm_timeout_seconds) as client:
                    response = await client.post(url, json=govde)
                response.raise_for_status()
                sonuc: Any = response.json()
                if not isinstance(sonuc, dict):
                    raise LLMInvalidJSONError(f"Beklenmeyen yanıt biçimi: {type(sonuc).__name__}")
                return sonuc
            except httpx.TimeoutException as exc:
                son_hata = exc
                logger.warning("yerel_llm_zaman_asimi", deneme=deneme + 1, url=url)
            except httpx.HTTPStatusError as exc:
                raise _durum_hatasi(exc) from exc
            except httpx.HTTPError as exc:
                raise LLMUnavailableError(f"Yerel LLM servisine ulaşılamıyor: {exc}") from exc

        raise LLMTimeoutError(
            f"Yerel LLM {self._settings.llm_timeout_seconds}s içinde yanıt vermedi"
        ) from son_hata

    @staticmethod
    def _icerik(yanit: dict[str, Any]) -> str:
        """Yanıt gövdesinden metni çıkarır."""
        secenekler = yanit.get("choices") or []
        if not secenekler:
            raise LLMInvalidJSONError("Yanıtta 'choices' alanı yok")
        return str((secenekler[0].get("message") or {}).get("content", ""))

    @staticmethod
    def _ayristir(metin: str) -> dict[str, Any]:
        """Yanıt metnini JSON'a çevirir.

        ⚠️ Küçük modeller JSON'u kod bloğu içine sarabiliyor; bu yüzden ham
        metin doğrudan ayrıştırılamazsa ilk süslü parantez bloğu denenir.
        """
        try:
            cozulen: Any = json.loads(metin)
        except json.JSONDecodeError:
            bas, son = metin.find("{"), metin.rfind("}")
            if bas == -1 or son <= bas:
                raise LLMInvalidJSONError(f"Yanıt JSON değil: {metin[:120]!r}") from None
            try:
                cozulen = json.loads(metin[bas : son + 1])
            except json.JSONDecodeError as exc:
                raise LLMInvalidJSONError(f"Yanıt JSON değil: {metin[:120]!r}") from exc

        if not isinstance(cozulen, dict):
            raise LLMInvalidJSONError(f"Yanıt nesne değil: {type(cozulen).__name__}")
        return cozulen


def _durum_hatasi(exc: httpx.HTTPStatusError) -> LLMUnavailableError:
    """HTTP durum hatasını sağlayıcı hatasına çevirir.

    404 çoğunlukla "model yüklü değil" demektir ve kurulum sorununa işaret
    eder; mesaj bunu açıkça söyler ki SPRINT 3B'de vakit kaybedilmesin.
    """
    if exc.response.status_code == httpx.codes.NOT_FOUND:
        return LLMUnavailableError(f"Model bulunamadı ({exc.request.url}). 'ollama pull' gerekli.")
    return LLMUnavailableError(f"Yerel LLM hata döndürdü: HTTP {exc.response.status_code}")
