"""AIRGAP_MODE kapısı — kapalı ağda dış servis yapılandırması reddedilir.

Bu test, on-prem iddiasının kanıtıdır: `AIRGAP_MODE=true` iken sistem dış
servise bağlı yapılandırmayla AYAĞA KALKMAZ.

Çalışma anında engellemek yetmez. Ölçüldü: kilit yalnızca kazıma
katmanındayken (`Fetcher._guard_airgap`, `scrapers/browser.py`) kapalı ağ
kipiyle açılan sunucu EVREN'e ve Qdrant'a çıkmaya devam ediyordu — sağlayıcı
ve vektör deposu o kapıdan geçmiyor. Tek komutla yanlışlanabilen bir iddia,
iddia değildir.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


def _ayarlar(monkeypatch: pytest.MonkeyPatch, **degerler: str) -> Settings:
    for anahtar, deger in degerler.items():
        monkeypatch.setenv(anahtar, deger)
    return Settings()


class TestAirgapKapisi:
    """Kapalı ağ yapılandırma denetimi."""

    def test_evren_saglayicisi_reddedilir(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with pytest.raises(ValidationError, match="AIRGAP_MODE"):
            _ayarlar(monkeypatch, AIRGAP_MODE="true", LLM_PROVIDER="evren", VECTOR_BACKEND="local")

    def test_qdrant_arka_ucu_reddedilir(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with pytest.raises(ValidationError, match="AIRGAP_MODE"):
            _ayarlar(monkeypatch, AIRGAP_MODE="true", LLM_PROVIDER="local", VECTOR_BACKEND="qdrant")

    def test_hata_mesaji_hangi_ayarin_bozuk_oldugunu_yazar(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Nedeni yazmayan bir ret, kullanıcıyı ayar dosyasında kör bırakır."""
        with pytest.raises(ValidationError) as hata:
            _ayarlar(monkeypatch, AIRGAP_MODE="true", LLM_PROVIDER="evren", VECTOR_BACKEND="qdrant")
        mesaj = str(hata.value)
        assert "LLM_PROVIDER" in mesaj
        assert "VECTOR_BACKEND" in mesaj

    def test_yerel_yol_kapali_agda_calisir(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ayarlar = _ayarlar(
            monkeypatch, AIRGAP_MODE="true", LLM_PROVIDER="local", VECTOR_BACKEND="local"
        )
        assert ayarlar.airgap_mode is True
        assert ayarlar.llm_provider == "local"

    def test_mock_saglayici_kapali_agda_calisir(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Testler `mock` ile koşar; kapalı ağ denetimi onları kilitlememeli."""
        ayarlar = _ayarlar(
            monkeypatch, AIRGAP_MODE="true", LLM_PROVIDER="mock", VECTOR_BACKEND="local"
        )
        assert ayarlar.airgap_mode is True

    def test_airgap_kapaliyken_dis_servis_serbest(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ayarlar = _ayarlar(
            monkeypatch, AIRGAP_MODE="false", LLM_PROVIDER="evren", VECTOR_BACKEND="qdrant"
        )
        assert ayarlar.airgap_mode is False
        assert ayarlar.llm_provider == "evren"
