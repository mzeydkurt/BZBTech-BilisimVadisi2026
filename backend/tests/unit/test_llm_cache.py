"""LLM yanıt önbelleği.

Önbellek yalnızca hız için değil, YİNELENEBİLİRLİK için de var: aynı girdi
aynı çıktıyı vermezse ablasyon karşılaştırması anlamsızlaşır.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.cache import cache_key, cached_generate
from app.ai.providers import MockProvider
from app.db.models import LLMCache

SEMA: dict[str, Any] = {"type": "object", "properties": {"profit_rate_pct": {"type": "object"}}}
METIN = "Vade farksız 4 aya varan taksit."


async def test_ikinci_cagri_onbellekten_gelir(db_session: Session) -> None:
    """Aynı istem ikinci kez sorulduğunda modele gidilmez."""
    provider = MockProvider(mode="null")

    ilk = await cached_generate(
        provider, db_session, text=METIN, task="extract", prompt_version="v1", schema=SEMA
    )
    ikinci = await cached_generate(
        provider, db_session, text=METIN, task="extract", prompt_version="v1", schema=SEMA
    )

    assert ilk.from_cache is False
    assert ikinci.from_cache is True
    assert ikinci.parsed == ilk.parsed
    # Tek kayıt yazılmalı: ikinci çağrı satır çoğaltmamalı.
    assert db_session.scalar(select(LLMCache).where(LLMCache.task == "extract")) is not None
    assert len(list(db_session.scalars(select(LLMCache)))) == 1


async def test_prompt_surumu_degisince_onbellek_gecersizlesir(db_session: Session) -> None:
    """⚠️ Prompt iyileştirmesinden sonra ESKİ yanıt geri gelmemeli.

    Aksi hâlde değişikliğin etkisi ölçülemez: F1 aynı kalır ve "prompt işe
    yaramadı" sonucu çıkarılır.
    """
    provider = MockProvider(mode="null")

    await cached_generate(
        provider, db_session, text=METIN, task="extract", prompt_version="v1", schema=SEMA
    )
    yeni = await cached_generate(
        provider, db_session, text=METIN, task="extract", prompt_version="v2", schema=SEMA
    )

    assert yeni.from_cache is False
    assert len(list(db_session.scalars(select(LLMCache)))) == 2


async def test_model_degisince_onbellek_gecersizlesir(db_session: Session) -> None:
    """Model adı anahtara dahildir: SPRINT 3B'de model takılınca önbellek tazelenir."""
    await cached_generate(
        MockProvider(mode="null"),
        db_session,
        text=METIN,
        task="extract",
        prompt_version="v1",
        schema=SEMA,
    )
    # Farklı kip → farklı model adı (`mock:null` vs `mock:halluc`).
    yeni = await cached_generate(
        MockProvider(mode="halluc"),
        db_session,
        text=METIN,
        task="extract",
        prompt_version="v1",
        schema=SEMA,
    )

    assert yeni.from_cache is False
    assert len(list(db_session.scalars(select(LLMCache)))) == 2


async def test_farkli_gorev_ayri_onbelleklenir(db_session: Session) -> None:
    """Aynı metin farklı görevde farklı yanıt verir; anahtarlar ayrışmalı."""
    provider = MockProvider(mode="null")

    await cached_generate(
        provider, db_session, text=METIN, task="extract", prompt_version="v1", schema=SEMA
    )
    ozet = await cached_generate(
        provider, db_session, text=METIN, task="summarize", prompt_version="v1", schema=SEMA
    )

    assert ozet.from_cache is False
    assert len(list(db_session.scalars(select(LLMCache)))) == 2


async def test_onbellek_saglayicidan_bagimsiz(db_session: Session) -> None:
    """⚠️ Önbellek mantığı sahte sağlayıcıyla da çalışmalı.

    Gerçek modele bağlı olsaydı SPRINT 3A'da hiç test edilemezdi.
    """
    provider = MockProvider(mode="halluc")

    ilk = await cached_generate(
        provider, db_session, text=METIN, task="extract", prompt_version="v1", schema=SEMA
    )
    ikinci = await cached_generate(
        provider, db_session, text=METIN, task="extract", prompt_version="v1", schema=SEMA
    )

    assert ikinci.from_cache is True
    assert ikinci.parsed == ilk.parsed


def test_anahtar_dort_parcadan_turer() -> None:
    """Dört bileşenden herhangi biri değişince anahtar değişir."""
    temel = cache_key("ozet", "extract", "v1", "mock:null")

    assert temel != cache_key("baska", "extract", "v1", "mock:null")
    assert temel != cache_key("ozet", "classify", "v1", "mock:null")
    assert temel != cache_key("ozet", "extract", "v2", "mock:null")
    assert temel != cache_key("ozet", "extract", "v1", "qwen3:8b")
    # Aynı girdiler her zaman aynı anahtarı üretir (yinelenebilirlik).
    assert temel == cache_key("ozet", "extract", "v1", "mock:null")
