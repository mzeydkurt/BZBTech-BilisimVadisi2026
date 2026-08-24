"""EVREN sağlayıcısı — TEKNOFEST 2026 çıkarım servisi.

BU BİR TİCARİ BULUT SAĞLAYICI DEĞİLDİR. EVREN, TEKNOFEST 2026 kapsamında
T.C. Cumhurbaşkanlığı Savunma Sanayii Başkanlığı tarafından yarışmacı takımlara
tahsis edilmiş, kotasız ve ücretsiz bir çıkarım servisidir (8 × NVIDIA H200,
vLLM, BF16, kuantizasyon yok). `providers/__init__.py` başındaki "bulut
sağlayıcı eklenmez" kuralının dayanağı şartname madde 8 (ücretli hizmet) ve
madde 5.9 (dış bağımlılık); EVREN ikisine de girmiyor.

YEREL YOL KALDIRILMADI. `LocalProvider` çalışır durumda kalır ve on-prem /
airgap gösterimi ona bağlıdır. Geçiş tek `.env` satırıdır
(`LLM_PROVIDER=evren` ↔ `local`); kodda hiçbir yer EVREN'e mahkûm değildir.

ANAHTAR KODA GÖMÜLMEZ. `get_settings()` üzerinden okunur, varsayılanı
boştur ve `.env` `.gitignore`'dadır.

⚠️ ÖLÇÜLEN FARK (24 Ağustos 2026, aynı Türkçe konut finansmanı metni,
aynı 5 alan):

    llm-fast (EVREN)   1,6 sn   5/5 doğru   tarihi ISO'ya normalize etti
    llm-large (EVREN)  4,7 sn   5/5 doğru   tarihi ham bıraktı
    qwen3:8b (yerel)  70,0 sn   4/5 doğru   "masraf alınmaz" → 50.000 yazdı

`llm-fast` bu testte `llm-large`'a üstün çıktığı için varsayılan odur.

SERVİS ORTAK KULLANIMDA. Duyuru, aynı bağlam üzerinden tekrarlı soru
sormanın (ön ek önbelleği) hem bizim hem sistemin performansını artırdığını
söylüyor. `llm_cache` katmanı bunu zaten yapıyor: aynı (model + prompt sürümü
+ metin özeti) ikinci kez servise gitmiyor.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
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

CHAT_PATH: Final[str] = "/chat/completions"
EMBEDDINGS_PATH: Final[str] = "/embeddings"
MODELS_PATH: Final[str] = "/models"
RERANK_PATH: Final[str] = "/rerank"

RETRY_BASE_DELAY_SECONDS: Final[float] = 1.0

# Tek istekte gönderilecek en fazla metin. Ortak kullanılan bir serviste
# 1.253 kartı tek gövdede göndermek hem zaman aşımı riski hem de diğer
# takımlara karşı nezaketsizlik olurdu.
EMBED_BATCH_SIZE: Final[int] = 32


@dataclass(frozen=True)
class RerankHit:
    """Yeniden sıralama sonucu — girdi sırası ve ilgililik puanı."""

    index: int
    score: float


class EvrenProvider(LLMProvider):
    """EVREN'in OpenAI uyumlu uçlarını kullanır."""

    def __init__(self, settings: Settings) -> None:
        """Sağlayıcıyı ayarlardan kurar.

        Args:
            settings: `get_settings()` çıktısı. ⚠️ Ortam değişkenine doğrudan
                erişilmez.
        """
        self._settings = settings
        self._base_url = settings.evren_base_url.rstrip("/")
        self._model = settings.evren_model
        self._api_key = settings.evren_api_key

    # ── Sözleşme ──────────────────────────────────────────

    @property
    def model_info(self) -> ModelInfo:
        """Kullanılan modelin kimliği.

        ⚠️ `license` alanı "TEKNOFEST/SSB tahsisli" yazar, Apache-2.0 DEĞİL.
        Servisin arkasındaki modellerin lisansı bize bildirilmedi; Apache-2.0
        yazmak doğrulanmamış bir iddia olurdu ve `LICENSES.md`'ye yanlış bilgi
        taşırdı.
        """
        return ModelInfo(
            name=self._model or "(tanımlanmadı)",
            version=self._settings.prompt_version,
            license="TEKNOFEST/SSB tahsisli çıkarım servisi",
            is_local=False,
            context_tokens=self._settings.local_llm_context,
        )

    async def health(self) -> bool:
        """Servise ulaşılabiliyor ve model listede mi?

        ⚠️ İSTİSNA YÜKSELTMEZ (bkz. `LLMProvider.health`).
        """
        if not self._api_key:
            logger.info("evren_anahtari_tanimlanmadi", not_=".env içindeki EVREN_API_KEY boş")
            return False
        if not self._model:
            logger.info("evren_modeli_tanimlanmadi")
            return False

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    f"{self._base_url}{MODELS_PATH}", headers=self._headers()
                )
        except httpx.HTTPError as exc:
            logger.info("evren_ulasilamiyor", url=self._base_url, hata=str(exc))
            return False

        if response.status_code != httpx.codes.OK:
            logger.warning("evren_saglik_basarisiz", durum=response.status_code)
            return False

        yuklu = {str(m.get("id", "")) for m in response.json().get("data", [])}
        if self._model not in yuklu:
            logger.warning("evren_modeli_listede_yok", istenen=self._model, yuklu=sorted(yuklu))
            return False
        return True

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        """Modelden yanıt alır.

        Args:
            prompt: Kullanıcı istemi.
            system: Sistem istemi.
            schema: Verilirse yanıt JSON'a zorlanır.
            temperature: Örnekleme sıcaklığı (varsayılan 0).
            max_tokens: Üretilecek en fazla token.

        Returns:
            Model yanıtı.

        Raises:
            LLMUnavailableError: Servise ulaşılamıyor.
            LLMTimeoutError: Servis zamanında yanıt vermedi.
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
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if schema is not None:
            govde["response_format"] = {"type": "json_object"}

        baslangic = time.monotonic()
        yanit = await self._istek(f"{self._base_url}{CHAT_PATH}", govde)
        gecen_ms = int((time.monotonic() - baslangic) * 1000)

        metin = self._icerik(yanit)
        kullanim = yanit.get("usage") or {}
        return LLMResponse(
            text=metin,
            parsed=self._ayristir(metin) if schema is not None else None,
            prompt_tokens=kullanim.get("prompt_tokens"),
            completion_tokens=kullanim.get("completion_tokens"),
            latency_ms=gecen_ms,
            from_cache=False,
            model_name=self._model,
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Metinleri gömme vektörlerine çevirir.

        ⚠️ PARÇA PARÇA GÖNDERİLİR. Servis tüm takımlarca ortak kullanılıyor;
        1.253 kartı tek gövdede göndermek zaman aşımı riski taşır.

        ⚠️ BOŞ METİN GÖNDERİLMEZ. Boş girdinin vektörü tanımsızdır ve kosinüs
        sıralamasını sessizce bozar.

        Args:
            texts: Gömülecek metinler.

        Returns:
            Her metin için bir vektör; sıra girdi sırasıyla aynıdır.

        Raises:
            ValueError: Metinlerden biri boş.
            LLMUnavailableError: Servise ulaşılamıyor.
            LLMTimeoutError: Servis zamanında yanıt vermedi.
        """
        if not texts:
            return []
        for sira, metin in enumerate(texts):
            if not metin.strip():
                raise ValueError(f"Boş metin gömülemez (sıra {sira})")

        model = self._settings.evren_embedding_model
        sonuc: list[list[float]] = []

        for basla in range(0, len(texts), EMBED_BATCH_SIZE):
            parca = texts[basla : basla + EMBED_BATCH_SIZE]
            yanit = await self._istek(
                f"{self._base_url}{EMBEDDINGS_PATH}", {"model": model, "input": parca}
            )
            satirlar = yanit.get("data")
            if not isinstance(satirlar, list) or len(satirlar) != len(parca):
                raise LLMInvalidJSONError(
                    f"Gömme yanıtı beklenen biçimde değil: {len(parca)} metin gönderildi, "
                    f"{len(satirlar) if isinstance(satirlar, list) else '?'} vektör döndü"
                )
            # ⚠️ `index` alanına göre sıralanır: servis sırayı korumak zorunda
            # değil ve karışık sıra, kartları YANLIŞ vektörle eşleştirir —
            # hata vermez, yalnızca arama anlamsızlaşır.
            sirali = sorted(satirlar, key=lambda satir: int(satir.get("index", 0)))
            sonuc.extend([float(x) for x in satir["embedding"]] for satir in sirali)

        return sonuc

    # ── Sözleşme dışı yetenek ─────────────────────────────

    async def rerank(
        self, query: str, documents: list[str], *, top_n: int | None = None
    ) -> list[RerankHit]:
        """Belgeleri sorguya göre yeniden sıralar.

        ⚠️ SÖZLEŞMEDE YOK. `LLMProvider` (donmuş `base.py`) yeniden sıralama
        tanımlamıyor; bu yüzden çağıran taraf `hasattr(provider, "rerank")`
        ile yoklar. `base.py`'ye metot eklemek tüm sağlayıcıları ve testleri
        kırardı.

        ⚠️ BAŞARISIZLIK SESSİZ DEĞİL AMA ÖLÜMCÜL DE DEĞİL. Yeniden sıralama
        bir iyileştirmedir; servis hata verirse çağıran taraf RRF sıralamasıyla
        devam eder ve bu durum yanıtta bildirilir.

        Args:
            query: Kullanıcı sorgusu.
            documents: Sıralanacak belge metinleri.
            top_n: Döndürülecek en fazla sonuç; verilmezse tamamı.

        Returns:
            Azalan ilgililik puanına göre sıralı `(index, score)` çiftleri.
            `index`, `documents` listesindeki konumdur.

        Raises:
            LLMUnavailableError: Servise ulaşılamıyor.
            LLMTimeoutError: Servis zamanında yanıt vermedi.
        """
        model = self._settings.evren_rerank_model
        if not model or not documents:
            return []

        govde: dict[str, Any] = {"model": model, "query": query, "documents": documents}
        if top_n is not None:
            govde["top_n"] = top_n

        yanit = await self._istek(f"{self._base_url}{RERANK_PATH}", govde)
        satirlar = yanit.get("results")
        if not isinstance(satirlar, list):
            raise LLMInvalidJSONError("Yeniden sıralama yanıtında 'results' yok")

        return [
            RerankHit(index=int(satir["index"]), score=float(satir["relevance_score"]))
            for satir in satirlar
            if "index" in satir and "relevance_score" in satir
        ]

    # ── İç yardımcılar ────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        """Yetkilendirme başlıkları."""
        return {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

    async def _istek(self, url: str, govde: dict[str, Any]) -> dict[str, Any]:
        """İsteği yeniden denemeli olarak yapar.

        ⚠️ YENİDEN DENEME YALNIZCA ZAMAN AŞIMI VE 429/5xx İÇİN. 400 ya da 401
        gibi anlamlı hatalarda tekrar denemek aynı sonucu verir ve ortak
        kullanılan servisi boşuna meşgul eder.

        ⚠️ ÜSTEL BEKLEME VAR. Servis tüm takımlarca paylaşılıyor; 429
        durumunda hemen tekrar denemek sıkışıklığı artırır.
        """
        son_hata: Exception | None = None

        for deneme in range(self._settings.llm_max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self._settings.llm_timeout_seconds) as client:
                    response = await client.post(url, json=govde, headers=self._headers())
                if response.status_code in _GECICI_DURUMLAR:
                    son_hata = LLMUnavailableError(
                        f"EVREN geçici olarak yanıt vermiyor: HTTP {response.status_code}"
                    )
                    logger.warning(
                        "evren_gecici_hata", durum=response.status_code, deneme=deneme + 1
                    )
                    if deneme < self._settings.llm_max_retries:
                        await asyncio.sleep(RETRY_BASE_DELAY_SECONDS * (2**deneme))
                    continue
                response.raise_for_status()
                sonuc: Any = response.json()
                if not isinstance(sonuc, dict):
                    raise LLMInvalidJSONError(f"Beklenmeyen yanıt biçimi: {type(sonuc).__name__}")
                return sonuc
            except httpx.TimeoutException as exc:
                son_hata = exc
                logger.warning("evren_zaman_asimi", deneme=deneme + 1, url=url)
                if deneme < self._settings.llm_max_retries:
                    await asyncio.sleep(RETRY_BASE_DELAY_SECONDS * (2**deneme))
            except httpx.HTTPStatusError as exc:
                raise _durum_hatasi(exc) from exc
            except httpx.HTTPError as exc:
                raise LLMUnavailableError(f"EVREN servisine ulaşılamıyor: {exc}") from exc

        if isinstance(son_hata, LLMUnavailableError):
            raise son_hata
        raise LLMTimeoutError(
            f"EVREN {self._settings.llm_timeout_seconds}s içinde yanıt vermedi"
        ) from son_hata

    @staticmethod
    def _icerik(yanit: dict[str, Any]) -> str:
        """Yanıt gövdesinden metni çıkarır.

        ⚠️ BOŞ METİN SESSİZCE GEÇİRİLMEZ — `LocalProvider` ile aynı gerekçe.
        HTTP 200 dönüp `content` boş geldiğinde bunu normal bir "alan
        bulunamadı" yanıtı saymak, tüm çalıştırmanın sıfır çıkarımla ve hiçbir
        hata mesajı olmadan bitmesi demektir.
        """
        secenekler = yanit.get("choices") or []
        if not secenekler:
            raise LLMInvalidJSONError("Yanıtta 'choices' alanı yok")

        mesaj = secenekler[0].get("message") or {}
        metin = str(mesaj.get("content") or "")
        if not metin.strip():
            neden = secenekler[0].get("finish_reason") or "bilinmiyor"
            raise LLMInvalidJSONError(
                f"EVREN boş yanıt döndürdü (finish_reason={neden}). max_tokens yetersiz olabilir."
            )
        return metin

    @staticmethod
    def _ayristir(metin: str) -> dict[str, Any]:
        """Yanıt metnini JSON'a çevirir.

        Modeller JSON'u kod bloğu içine sarabiliyor; ham metin
        ayrıştırılamazsa ilk süslü parantez bloğu denenir.
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


# Yeniden denenmeye değer durum kodları: sıkışıklık ve geçici sunucu hataları.
_GECICI_DURUMLAR: Final[frozenset[int]] = frozenset({429, 500, 502, 503, 504})


def _durum_hatasi(exc: httpx.HTTPStatusError) -> LLMUnavailableError:
    """HTTP durum hatasını sağlayıcı hatasına çevirir."""
    durum = exc.response.status_code
    if durum in {httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN}:
        return LLMUnavailableError(
            f"EVREN yetkilendirme hatası (HTTP {durum}). `.env` içindeki EVREN_API_KEY doğru mu?"
        )
    if durum == httpx.codes.NOT_FOUND:
        return LLMUnavailableError(
            f"EVREN ucu bulunamadı ({exc.request.url}). Model adı `/v1/models` listesinde mi?"
        )
    return LLMUnavailableError(f"EVREN hata döndürdü: HTTP {durum}")
