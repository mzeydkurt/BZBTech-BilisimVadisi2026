"""EVREN sağlayıcısı ve Qdrant deposu — ağa çıkmayan birim testleri.

AĞA ÇIKMAZ. Yalnızca saf işlevler ve ayrıştırma sınanır; `conftest.py`'nin
ağ koruması gerçek isteği zaten düşürür.
"""

from __future__ import annotations

import pytest

from app.ai.providers import PROVIDERS, active_embedding_model, get_provider
from app.ai.providers.base import LLMInvalidJSONError
from app.ai.providers.evren import EvrenProvider
from app.config import Settings
from app.retrieval.qdrant_store import point_id


def _ayarlar(**ek: object) -> Settings:
    """Test için ayar nesnesi üretir."""
    return Settings(**ek)  # type: ignore[arg-type]


class TestGommeModeliTekKaynak:
    """⚠️ SAHADA ÖLÇÜLEN HATANIN REGRESYON TESTİ.

    `embeddings.model_name` hem yazılırken hem okunurken `settings.embedding_model`
    okunuyordu; etiket, vektörü gerçekten üreten modelden bağımsız kalıyordu.
    Sonuç: EVREN'in `bge-m3-embed` modeliyle üretilmiş 1.519 vektör
    `nomic-embed-text` etiketiyle kaydedildi (boyut 1024; oysa
    `nomic-embed-text` 768 üretir).

    Yazan ve okuyan aynı yanlış etiketi kullandığı için hata GÖRÜNMÜYORDU;
    airgap gösteriminde `LLM_PROVIDER=local` yapıldığı anda sorgu vektörü 768,
    saklanan 1024 olur ve anlamsal kanal hiçbir hata vermeden ölür.
    """

    def test_evren_saglayicisinda_evren_gomme_modeli_doner(self) -> None:
        ayar = _ayarlar(
            llm_provider="evren",
            evren_embedding_model="bge-m3-embed",
            embedding_model="nomic-embed-text",
        )
        assert active_embedding_model(ayar) == "bge-m3-embed"

    def test_yerel_saglayicida_yerel_gomme_modeli_doner(self) -> None:
        ayar = _ayarlar(
            llm_provider="local",
            evren_embedding_model="bge-m3-embed",
            embedding_model="nomic-embed-text",
        )
        assert active_embedding_model(ayar) == "nomic-embed-text"

    def test_mock_saglayicida_yerel_gomme_modeli_doner(self) -> None:
        """Mock, yerel yapılandırmayı kullanır — testler tek boyutta kalsın."""
        ayar = _ayarlar(llm_provider="mock", embedding_model="nomic-embed-text")
        assert active_embedding_model(ayar) == "nomic-embed-text"


class TestSaglayiciFabrikasi:
    def test_evren_kayitli(self) -> None:
        assert "evren" in PROVIDERS

    def test_yerel_yol_kaldirilmadi(self) -> None:
        """⚠️ On-prem / airgap gösterimi `local` yoluna bağlı; kaldırılamaz."""
        assert "local" in PROVIDERS

    def test_evren_saglayicisi_uretilir(self) -> None:
        saglayici = get_provider(_ayarlar(llm_provider="evren", evren_api_key="test"))
        assert isinstance(saglayici, EvrenProvider)

    def test_tanimsiz_saglayici_sessizce_mocka_dusmez(self) -> None:
        """⚠️ Sessizce mock'a düşmek, sahte sağlayıcıyla üretilmiş bir F1'i
        gerçek sanmak demektir."""
        with pytest.raises(ValueError, match="Bilinmeyen LLM_PROVIDER"):
            get_provider(_ayarlar(llm_provider="sihirli"))


class TestEvrenModelKimligi:
    def test_lisans_kunyeden_okunur(self) -> None:
        """Künye SSB tarafından yayımlandı; lisans model kartından doğrulandı.

        Bu test eskiden "Apache yazılmaz" diyordu. Kural değişmedi — künye
        yayımlandığı için artık DOĞRULANMIŞ bir değer yazılabiliyor.
        """
        bilgi = EvrenProvider(_ayarlar(llm_provider="evren", evren_model="llm-fast")).model_info
        assert "Apache-2.0" in bilgi.license
        assert "Qwen/Qwen3.6-35B-A3B" in bilgi.license
        assert bilgi.is_local is False

    def test_kunyesi_olmayan_model_dogrulanmadi_der(self) -> None:
        """Bilinmeyeni izin verici saymak, doğrulanmamış bir iddiadır."""
        bilgi = EvrenProvider(_ayarlar(llm_provider="evren", evren_model="yeni-model")).model_info
        assert "doğrulanmadı" in bilgi.license
        assert "Apache" not in bilgi.license


class TestEvrenYanitAyristirma:
    def test_bos_yanit_hata_firlatir(self) -> None:
        """⚠️ HTTP 200 + boş `content`, tüm çalıştırmanın sıfır çıkarımla ve
        hiçbir hata mesajı olmadan bitmesi demektir."""
        with pytest.raises(LLMInvalidJSONError, match="boş yanıt"):
            EvrenProvider._icerik(
                {"choices": [{"message": {"content": "   "}, "finish_reason": "length"}]}
            )

    def test_choices_yoksa_hata_firlatir(self) -> None:
        with pytest.raises(LLMInvalidJSONError, match="choices"):
            EvrenProvider._icerik({})

    def test_kod_blogu_icindeki_json_ayristirilir(self) -> None:
        """Modeller JSON'u markdown kod bloğuna sarabiliyor."""
        cozulen = EvrenProvider._ayristir('```json\n{"profit_rate_pct": 1.89}\n```')
        assert cozulen == {"profit_rate_pct": 1.89}

    def test_json_olmayan_yanit_hata_firlatir(self) -> None:
        with pytest.raises(LLMInvalidJSONError, match="JSON değil"):
            EvrenProvider._ayristir("Merhaba, size nasıl yardımcı olabilirim?")

    def test_dizi_yaniti_nesne_sayilmaz(self) -> None:
        with pytest.raises(LLMInvalidJSONError, match="nesne değil"):
            EvrenProvider._ayristir("[1, 2, 3]")


class TestQdrantNoktaKimligi:
    def test_ayni_kart_ayni_kimlik_uretir(self) -> None:
        """⚠️ KARARLI OLMAK ZORUNDA. Kararsız kimlik, her yükleme turunda aynı
        kartı yeni bir nokta olarak ekler; koleksiyon şişer ve arama aynı
        kaydı birden fazla kez döndürür."""
        assert point_id("campaign", 496, 0) == point_id("campaign", 496, 0)

    def test_farkli_turler_ayni_kimlige_dusmez(self) -> None:
        """`campaign:5` ile `product:5` aynı noktaya yazmamalı."""
        assert point_id("campaign", 5, 0) != point_id("product", 5, 0)

    def test_farkli_parcalar_ayni_kimlige_dusmez(self) -> None:
        assert point_id("campaign", 5, 0) != point_id("campaign", 5, 1)

    def test_komsu_kimlikler_carpismaz(self) -> None:
        """Parça adımı, kimlik adımından küçük olmalı."""
        assert point_id("campaign", 5, 999) != point_id("campaign", 6, 0)

    def test_tanimsiz_tur_sessizce_kabul_edilmez(self) -> None:
        """⚠️ Sessizce 0 öneki kullanmak, iki türü aynı kimlik uzayına
        sıkıştırıp veri kaybettirirdi."""
        with pytest.raises(ValueError, match="Tanımsız varlık türü"):
            point_id("bilinmeyen", 1, 0)
