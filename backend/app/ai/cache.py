"""LLM yanıt önbelleği.

NEDEN YEREL MODELDE DE GEREKLİ: Yerel model ücretsizdir ama yavaştır. 500
kampanya × birkaç saniye, her yeniden çalıştırmada saatler eder. Prompt üzerinde
yineleme yapmak (KAPI A6-A9 boyunca sürekli yapılacak) önbelleksiz pratikte
imkânsız hâle gelir.

⚠️ ANAHTAR DÖRT PARÇALIDIR: metin özeti + görev + prompt sürümü + model adı.
Yalnızca metinden türetilseydi, prompt iyileştirmesinden sonra ESKİ yanıtlar
geri gelir ve değişikliğin etkisi ölçülemezdi. Dört parça sayesinde model ya da
prompt değişince önbellek KENDİLİĞİNDEN geçersizleşir — bu istenen davranıştır.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.providers.base import LLMProvider, LLMResponse
from app.db.models import LLMCache
from app.logging_config import get_logger
from app.utils.hashing import sha256_text

logger = get_logger(__name__)


def cache_key(text_hash: str, task: str, prompt_version: str, model_name: str) -> str:
    """Önbellek anahtarını üretir.

    Args:
        text_hash: Modele gönderilen metnin sha256 özeti.
        task: `extract` | `classify` | `summarize`.
        prompt_version: Etkin prompt sürümü.
        model_name: Yanıtı üreten modelin adı.

    Returns:
        sha256 özeti.
    """
    return sha256_text(f"{text_hash}|{task}|{prompt_version}|{model_name}")


def _parse(text: str) -> dict[str, Any] | None:
    """Önbellekten okunan metni JSON'a çevirir; düz metinse None.

    ⚠️ Bozuk JSON'da İSTİSNA YÜKSELTİLMEZ. Önbellek bir hızlandırmadır;
    okunamayan bir kayıt yüzünden çalıştırmanın durması, hızlandırmayı
    kırılganlık kaynağına çevirirdi.
    """
    try:
        cozulen: Any = json.loads(text)
    except json.JSONDecodeError:
        return None
    return cozulen if isinstance(cozulen, dict) else None


async def cached_generate(
    provider: LLMProvider,
    session: Session,
    *,
    text: str,
    task: str,
    prompt_version: str,
    use_cache: bool = True,
    **kwargs: Any,
) -> LLMResponse:
    """Yanıtı önbellekten döndürür, yoksa modeli çağırıp önbelleğe yazar.

    ⚠️ Sağlayıcıdan BAĞIMSIZDIR: `MockProvider` ile de çalışır. Önbellek
    mantığının gerçek modele bağlı olması, SPRINT 3A'da test edilememesi
    demek olurdu.

    Args:
        provider: Kullanılacak sağlayıcı.
        session: Veritabanı oturumu.
        text: Modele gönderilecek istem (anahtar bundan türetilir).
        task: Görev türü.
        prompt_version: Etkin prompt sürümü.
        use_cache: False ise önbellek OKUNMAZ ama yine YAZILIR
            (`python dev.py cikarim --yeniden`). Prompt metni değişmeden
            model davranışını yeniden görmek gerektiğinde kullanılır;
            anahtar aynı kaldığı için kayıt tazelenir.
        **kwargs: `provider.generate()`e aktarılır (`system`, `schema`, ...).

    Returns:
        Model yanıtı; önbellekten geldiyse `from_cache=True`.
    """
    model_adi = provider.model_info.name
    anahtar = cache_key(sha256_text(text), task, prompt_version, model_adi)

    kayit = session.scalar(select(LLMCache).where(LLMCache.cache_key == anahtar))
    if kayit is not None and use_cache:
        logger.debug("onbellek_isabet", gorev=task, model=model_adi)
        return LLMResponse(
            text=kayit.response_json,
            parsed=_parse(kayit.response_json),
            latency_ms=0,
            from_cache=True,
            model_name=model_adi,
        )

    yanit = await provider.generate(text, **kwargs)

    if kayit is not None:
        # ⚠️ Anahtar benzersizdir; yeni satır eklemek kısıtı ihlal ederdi.
        kayit.response_json = yanit.text
    else:
        session.add(
            LLMCache(
                cache_key=anahtar,
                task=task,
                response_json=yanit.text,
                model_name=model_adi,
                prompt_version=prompt_version,
            )
        )
    session.flush()
    return yanit
