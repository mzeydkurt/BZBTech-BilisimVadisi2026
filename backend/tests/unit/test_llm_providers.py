"""LLM sağlayıcı soyutlaması ve sahte sağlayıcının beş kipi.

Bu testler SPRINT 3A'nın temel iddiasını doğrular: çıkarım motoru gerçek bir
model olmadan uçtan uca çalıştırılabilir ve HATA YOLLARI dahil test edilebilir.
Model kurulduğunda (SPRINT 3B) yalnızca `LocalProvider`'ın içi değişir; burada
sınanan davranışların hiçbiri değişmez.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.ai.providers import (
    LLMInvalidJSONError,
    LLMTimeoutError,
    LocalProvider,
    MockProvider,
    get_provider,
)
from app.config import Settings

# Çıkarım şemasının sadeleştirilmiş hâli: her alan {value, evidence} taşır.
SEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "profit_rate_pct": {"type": "object"},
        "end_date": {"type": "object"},
    },
}

KAYNAK_METIN = "Colin's mağazalarında vade farksız 4 aya varan taksit fırsatı."


# ── null kipi (varsayılan) ────────────────────────────────


async def test_null_kipi_tum_alanlari_bos_dondurur() -> None:
    """⚠️ VARSAYILAN DAVRANIŞ "BİLGİ YOK"TUR.

    Sahte sağlayıcı zengin veri üretseydi, pipeline "her zaman dolu yanıt
    gelir" varsayımıyla yazılır ve gerçek modelde boş dönen alanlar çökme
    üretirdi.
    """
    provider = MockProvider(mode="null")

    yanit = await provider.generate(KAYNAK_METIN, schema=SEMA)

    assert yanit.parsed == {
        "profit_rate_pct": {"value": None, "evidence": None},
        "end_date": {"value": None, "evidence": None},
    }
    assert yanit.from_cache is False
    assert yanit.model_name == "mock:null"


async def test_sema_verilmezse_duz_metin_doner() -> None:
    """Şema istenmeyen çağrıda `parsed` boş kalır."""
    yanit = await MockProvider(mode="null").generate(KAYNAK_METIN)

    assert yanit.parsed is None


# ── halluc kipi — guard'ın kanıtı ─────────────────────────


async def test_halluc_kipi_kaynakta_olmayan_kanit_uretir() -> None:
    """⭐ Halüsinasyon guard'ının (KAPI A7) test edilebilmesinin tek yolu.

    Üretilen `evidence` kaynak metinde GEÇMEMELİ; guard'ın substring
    doğrulaması tam olarak bunu yakalayacak.
    """
    yanit = await MockProvider(mode="halluc").generate(KAYNAK_METIN, schema=SEMA)

    assert yanit.parsed is not None
    for alan in yanit.parsed.values():
        assert alan["value"] is not None
        assert alan["evidence"] not in KAYNAK_METIN


# ── hata yolları ──────────────────────────────────────────


async def test_timeout_kipi_istisna_yukseltir() -> None:
    """Zaman aşımı ayrı bir istisna türüdür: kampanya atlanır, çalıştırma sürer."""
    with pytest.raises(LLMTimeoutError):
        await MockProvider(mode="timeout").generate(KAYNAK_METIN, schema=SEMA)


async def test_invalid_kipi_sema_istendiginde_istisna_yukseltir() -> None:
    """Şema istendiği hâlde bozuk JSON gelirse ayrı istisna yükselir."""
    with pytest.raises(LLMInvalidJSONError):
        await MockProvider(mode="invalid").generate(KAYNAK_METIN, schema=SEMA)


async def test_invalid_kipi_sema_yokken_istisna_yukseltmez() -> None:
    """Şema istenmediyse bozuk metin hata değildir.

    Çağıran düz metin bekliyordur; JSON zorunluluğu yalnızca şema verildiğinde
    doğar.
    """
    yanit = await MockProvider(mode="invalid").generate(KAYNAK_METIN)

    assert yanit.parsed is None
    assert yanit.text


# ── fixture kipi ──────────────────────────────────────────


async def test_fixture_kipi_kayitli_yaniti_okur(tmp_path: Path) -> None:
    """Bilinen girdiye bilinen çıktı: merger ve dönüşüm testlerinin temeli."""
    beklenen = {"profit_rate_pct": {"value": 0, "evidence": "vade farksız"}}
    gorev_dizini = tmp_path / "extract"
    gorev_dizini.mkdir()
    (gorev_dizini / MockProvider.fixture_name(KAYNAK_METIN)).write_text(
        json.dumps(beklenen, ensure_ascii=False), encoding="utf-8"
    )

    provider = MockProvider(mode="fixture", fixture_dir=tmp_path)
    yanit = await provider.generate(KAYNAK_METIN, schema=SEMA)

    assert yanit.parsed == beklenen


async def test_fixture_yoksa_null_davranisina_duser(tmp_path: Path) -> None:
    """⚠️ Eksik fixture testi ÇÖKERTMEZ.

    Fixture bulunamadığında "bilgi yok" varsayılanına düşülür; pipeline'ın
    yine de tamamlandığı görülmelidir.
    """
    provider = MockProvider(mode="fixture", fixture_dir=tmp_path)

    yanit = await provider.generate(KAYNAK_METIN, schema=SEMA)

    assert yanit.parsed == {
        "profit_rate_pct": {"value": None, "evidence": None},
        "end_date": {"value": None, "evidence": None},
    }


# ── kip doğrulaması ───────────────────────────────────────


def test_tanimsiz_kip_sessizce_kabul_edilmez() -> None:
    """⚠️ Yazım hatası varsayılana DÜŞMEZ.

    `halluc` yerine `hallucinate` yazılmış bir guard testi, guard'ı hiç test
    etmediği hâlde yeşil görünürdü.
    """
    with pytest.raises(ValueError, match="MOCK_LLM_MODE"):
        MockProvider(mode="hallucinate")


# ── sağlık ve kimlik ──────────────────────────────────────


async def test_mock_saglayici_her_zaman_ayakta() -> None:
    """Sahte sağlayıcı sağlık kontrolünden geçer."""
    assert await MockProvider().health() is True


async def test_mock_model_adi_sahte_oldugunu_belli_eder() -> None:
    """⚠️ Model adı `mock` ile başlar.

    Sahte sağlayıcıyla üretilmiş bir çıkarım kaydı, veritabanında gerçek model
    çıktısıyla karışmamalıdır.
    """
    bilgi = MockProvider(mode="halluc").model_info

    assert bilgi.name.startswith("mock:")
    assert bilgi.is_local is True


async def test_gomme_henuz_uygulanmadi() -> None:
    """Gömme SPRINT 5'te gelecek; imza şimdiden sabit."""
    with pytest.raises(NotImplementedError):
        await MockProvider().embed(["metin"])


# ── fabrika ───────────────────────────────────────────────


def test_fabrika_mock_dondurur() -> None:
    """`LLM_PROVIDER=mock` sahte sağlayıcıyı kurar ve kipi aktarır."""
    provider = get_provider(Settings(llm_provider="mock", mock_llm_mode="halluc"))

    assert isinstance(provider, MockProvider)
    assert provider.mode == "halluc"


def test_fabrika_local_dondurur() -> None:
    """`LLM_PROVIDER=local` yerel sağlayıcıyı kurar (çağrı yapılmaz)."""
    assert isinstance(get_provider(Settings(llm_provider="local")), LocalProvider)


def test_fabrika_bilinmeyen_saglayicida_hata_verir() -> None:
    """⚠️ Sessizce `mock`a düşülmez.

    Gerçek model beklenirken sahte sağlayıcıyla üretilmiş bir F1 değeri,
    ölçümün tamamını geçersiz kılar ve fark edilmez.
    """
    with pytest.raises(ValueError, match="LLM_PROVIDER"):
        get_provider(Settings(llm_provider="gemini"))


# ── on-premise güvencesi ──────────────────────────────────


def test_hicbir_saglayici_bulut_degil() -> None:
    """Şartname 5.9: her sağlayıcı yerel çalışmalı."""
    for settings in (Settings(llm_provider="mock"), Settings(llm_provider="local")):
        assert get_provider(settings).model_info.is_local is True


async def test_yerel_saglayici_model_tanimsizsa_saglikli_degil() -> None:
    """Model adı boşken sağlık kontrolü ağa hiç çıkmadan False döner.

    SPRINT 3A'da beklenen durum budur; istisna YÜKSELTİLMEZ.
    """
    provider = LocalProvider(Settings(llm_provider="local", local_llm_model=""))

    assert await provider.health() is False
