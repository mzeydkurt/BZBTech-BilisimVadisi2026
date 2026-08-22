"""Yerel model sağlayıcısı — Ollama üzerinden.

⚠️ ARAYÜZ İMZALARI DEĞİŞMEZ. Yalnızca bu sınıfın içi düzeltilebilir: uç
adresi, istek gövdesi, yanıt ayrıştırma. `LLMProvider` sözleşmesine
(`providers/base.py`) dokunulmaz — çıkarım motorunun tamamı o sözleşmenin
üzerine kurulu.

⚠️ AIRGAP_MODE BU SAĞLAYICIYI ENGELLEMEZ. Model `localhost`ta çalışır; kurum
ağının dışına çıkan bir istek değildir. Aksine on-premise iddiasının ta
kendisidir: veri kurumdan çıkmadan çıkarım yapılır. Airgap yalnızca kazımayı
(bankalara giden istekleri) durdurur.

⚠️ ÜRETİM ÇAĞRISI OPENAI UYUMLU `/v1` UCUNU KULLANMAZ — Ollama'nın kendi
`/api/chat` ucunu kullanır. Gerekçe ölçüldü (22 Ağustos 2026, `qwen3:8b`):

    POST /v1/chat/completions
      + chat_template_kwargs={"enable_thinking": false}
    → HTTP 200 · finish_reason="length" · choices[0].message.content = ""

Düşünen modellerde `/v1` ucu düşünme çıktısını `content` alanına koymuyor;
üretim bütçesinin tamamı düşünmeye gidiyor ve geriye BOŞ metin kalıyor.
HATA FIRLATMIYOR — yalnızca hiçbir alan çıkarılamıyor ve F1 sıfıra düşüyor.
`/api/chat` ucundaki `think: false` parametresi düşünmeyi gerçekten kapatıyor;
aynı istem orada geçerli JSON döndürdü.

`think: false` düşünmeyen modellerde de güvenlidir (`qwen2.5-coder:7b` ile
denendi: HTTP 200, yok sayılıyor), bu yüzden koşulsuz gönderilir.

⚠️ SAĞLIK YOKLAMASI `/v1/models` UCUNDA KALIR. Model listesini vermek için
yeterlidir ve `LOCAL_LLM_BASE_URL` ayarının anlamı korunur.
"""

from __future__ import annotations

import asyncio
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

# Ollama'nın kendi sohbet ucu — `/v1` önekinin DIŞINDADIR (yukarıdaki nota bak).
NATIVE_CHAT_PATH: Final[str] = "/api/chat"
# OpenAI uyumlu model listesi ucu; yalnızca sağlık yoklaması için.
MODELS_PATH: Final[str] = "/models"

# Yeniden denemeler arasındaki temel bekleme; her denemede ikiye katlanır.
RETRY_BASE_DELAY_SECONDS: Final[float] = 1.0


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

        ⚠️ `license` alanı sabit "Apache-2.0" yazar ve bu YALNIZCA seçim
        havuzundaki modeller (Qwen2.5 / Qwen3 / Mistral) için doğrudur.
        Havuz dışı bir model yapılandırılırsa bu alan yalan söyler; havuz
        `docs/SPRINT3B_LLM_LOCAL_KURULUM.md` §3.1'de tanımlıdır.
        """
        return ModelInfo(
            name=self._model or "(tanımlanmadı)",
            version=self._settings.prompt_version,
            license="Apache-2.0",
            is_local=True,
            context_tokens=self._settings.local_llm_context,
        )

    async def health(self) -> bool:
        """Servise ulaşılabiliyor ve model yüklü mü?

        ⚠️ İSTİSNA YÜKSELTMEZ (bkz. `LLMProvider.health`). Model kurulu
        değilken False dönmesi beklenen sonuçtur, hata değil.
        """
        if not self._model:
            logger.info("yerel_model_tanimlanmadi", not_=".env içindeki LOCAL_LLM_MODEL boş")
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
        """Metinleri gömme vektörlerine çevirir.

        Gömme modeli sohbet modelinden AYRIDIR (`EMBEDDING_MODEL`); aynı
        modelden hem üretim hem gömme istemek Ollama'da modeli boşuna
        yeniden yükletir.

        ⚠️ BOŞ METİN GÖNDERİLMEZ. Ollama boş girdi için sıfır vektör
        döndürüyor; sıfır vektörün kosinüs benzerliği tanımsızdır ve sıralamayı
        sessizce bozar. Boş girdi hata olarak bildirilir.

        Args:
            texts: Gömülecek metinler.

        Returns:
            Her metin için bir vektör; sıra girdi sırasıyla aynıdır.

        Raises:
            ValueError: Metinlerden biri boş.
            LLMUnavailableError: Servise ulaşılamıyor.
            LLMTimeoutError: Model zamanında yanıt vermedi.
        """
        if not texts:
            return []
        for sira, metin in enumerate(texts):
            if not metin.strip():
                raise ValueError(f"Boş metin gömülemez (sıra {sira})")

        govde: dict[str, Any] = {
            "model": self._settings.embedding_model,
            "input": texts,
        }
        yanit = await self._istek(self._native_url("/api/embed"), govde)

        vektorler = yanit.get("embeddings")
        if not isinstance(vektorler, list) or len(vektorler) != len(texts):
            raise LLMInvalidJSONError(
                f"Gömme yanıtı beklenen biçimde değil: {len(texts)} metin gönderildi, "
                f"{len(vektorler) if isinstance(vektorler, list) else '?'} vektör döndü"
            )
        return [[float(x) for x in vektor] for vektor in vektorler]

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
            schema: Verilirse yanıt JSON'a zorlanır (`format: json`).
            temperature: Örnekleme sıcaklığı (varsayılan 0).
            max_tokens: Üretilecek en fazla token.

        Returns:
            Model yanıtı.

        Raises:
            LLMUnavailableError: Servise ulaşılamıyor.
            LLMTimeoutError: Model zamanında yanıt vermedi.
            LLMInvalidJSONError: Şema istendi ama yanıt geçerli JSON değil,
                ya da model boş yanıt döndürdü.
        """
        mesajlar: list[dict[str, str]] = []
        if system:
            mesajlar.append({"role": "system", "content": system})
        mesajlar.append({"role": "user", "content": prompt})

        govde: dict[str, Any] = {
            "model": self._model,
            "messages": mesajlar,
            "stream": False,
            # Düşünme kapalı — açıkken üretim bütçesi tükeniyor ve `content`
            # boş kalıyor (dosya başındaki ölçüme bak).
            "think": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_ctx": self._settings.local_llm_context,
            },
        }
        if schema is not None:
            govde["format"] = "json"

        baslangic = time.monotonic()
        yanit = await self._istek(self._native_url(NATIVE_CHAT_PATH), govde)
        gecen_ms = int((time.monotonic() - baslangic) * 1000)

        metin = self._icerik(yanit)
        ayristirilan = self._ayristir(metin) if schema is not None else None

        return LLMResponse(
            text=metin,
            parsed=ayristirilan,
            prompt_tokens=yanit.get("prompt_eval_count"),
            completion_tokens=yanit.get("eval_count"),
            latency_ms=gecen_ms,
            from_cache=False,
            model_name=self._model,
        )

    # ── İç yardımcılar ────────────────────────────────────

    def _native_url(self, path: str) -> str:
        """Ollama'nın kendi uç adresini üretir.

        `LOCAL_LLM_BASE_URL` OpenAI uyumluluğu için `/v1` ile bitiyor; yerel
        uçlar o önekin dışındadır. Önek yoksa adres olduğu gibi kullanılır —
        Ollama'yı ters vekil arkasında çalıştıran kurulumlar bozulmasın.
        """
        kok = self._base_url[: -len("/v1")] if self._base_url.endswith("/v1") else self._base_url
        return f"{kok}{path}"

    async def _istek(self, url: str, govde: dict[str, Any]) -> dict[str, Any]:
        """İsteği yeniden denemeli olarak yapar.

        ⚠️ Yeniden deneme YALNIZCA zaman aşımı için. Model anlamlı bir hata
        döndürdüyse (ör. model bulunamadı) tekrar denemek aynı sonucu verir ve
        boşuna bekletir.

        ⚠️ ÜSTEL BEKLEME VAR. Zaman aşımının en sık nedeni modelin belleğe
        yüklenmesi (ilk çağrıda 12-20 sn ölçüldü); hemen tekrar denemek aynı
        yüklemeyi ikinci kez tetikleyip durumu kötüleştiriyor.
        """
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
                if deneme < self._settings.llm_max_retries:
                    await asyncio.sleep(RETRY_BASE_DELAY_SECONDS * (2**deneme))
            except httpx.HTTPStatusError as exc:
                raise _durum_hatasi(exc) from exc
            except httpx.HTTPError as exc:
                raise LLMUnavailableError(f"Yerel LLM servisine ulaşılamıyor: {exc}") from exc

        raise LLMTimeoutError(
            f"Yerel LLM {self._settings.llm_timeout_seconds}s içinde yanıt vermedi"
        ) from son_hata

    @staticmethod
    def _icerik(yanit: dict[str, Any]) -> str:
        """Yanıt gövdesinden metni çıkarır.

        ⚠️ BOŞ METİN SESSİZCE GEÇİRİLMEZ. Düşünme kipi açık kaldığında ya da
        `num_predict` düşük olduğunda Ollama HTTP 200 döndürüyor ama `content`
        boş geliyor. Bu durumu normal bir "alan bulunamadı" yanıtı gibi
        işlemek, tüm çalıştırmanın sıfır çıkarımla ve HİÇBİR HATA MESAJI
        OLMADAN bitmesi demektir.
        """
        mesaj = yanit.get("message")
        if not isinstance(mesaj, dict):
            raise LLMInvalidJSONError("Yanıtta 'message' alanı yok")

        metin = str(mesaj.get("content") or "")
        if not metin.strip():
            neden = yanit.get("done_reason") or "bilinmiyor"
            raise LLMInvalidJSONError(
                f"Model boş yanıt döndürdü (done_reason={neden}). "
                "Düşünme kipi açık kalmış ya da num_predict yetersiz olabilir."
            )
        return metin

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
    eder; mesaj bunu açıkça söyler ki vakit kaybedilmesin.
    """
    if exc.response.status_code == httpx.codes.NOT_FOUND:
        return LLMUnavailableError(f"Model bulunamadı ({exc.request.url}). 'ollama pull' gerekli.")
    return LLMUnavailableError(f"Yerel LLM hata döndürdü: HTTP {exc.response.status_code}")
