"""Sohbette seçilebilecek modeller ve sağlık durumları.

⚠️ SEÇİM İSTEK BAŞINADIR, KALICI DEĞİL. Arayüzden gelen model seçimi yalnızca
o isteği etkiler; `.env` dosyasına yazılmaz. Bir kullanıcının seçimi tüm
kurumun yapılandırmasını değiştirmemeli — hele jüri demosu sırasında.

⚠️ ERİŞİLEMEYEN MODEL LİSTEDEN GİZLENMEZ. Kullanıcı neden seçemediğini
görmeli; gizlemek "böyle bir seçenek yok" izlenimi verir ve EVREN kapandığında
sistemin yerel yedeği olduğunu kimse fark etmez.

⚠️ SAĞLIK YOKLAMASI ÖNBELLEKLENİR. Her sayfa açılışında üç sağlayıcıya ağ
isteği atmak, ortak kullanılan EVREN'i boşuna meşgul eder ve arayüzü
yavaşlatır. Süre kısa tutulur ki bir servis düştüğünde arayüz makul sürede
fark etsin.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Final

from app.ai.providers import get_provider
from app.config import Settings, get_settings
from app.logging_config import get_logger
from app.schemas.chat import ChatModelOption, ChatModelsResponse

logger = get_logger(__name__)

# Sağlık sonucunun geçerli kalma süresi.
HEALTH_TTL_SECONDS: Final[float] = 60.0

# Sağlayıcı → arayüzde gösterilecek ad ve açıklama.
PROVIDER_LABELS: Final[dict[str, tuple[str, str]]] = {
    "evren": (
        "EVREN",
        "TEKNOFEST çıkarım servisi (SSB tahsisli). Hızlı ve güçlü; dış ağ gerektirir.",
    ),
    "local": (
        "Yerel (Ollama)",
        "Kapalı ağda çalışır. Bu donanımda yavaş (ölçüldü: ~70 sn/yanıt), "
        "on-prem gösteriminin kanıtı.",
    ),
    "mock": (
        "Sahte sağlayıcı",
        "Yalnızca test. Gerçek model çağrısı yapmaz; ölçüm için kullanılmaz.",
    ),
}


@dataclass
class _SaglikKaydi:
    """Önbelleklenmiş sağlık sonucu."""

    saglikli: bool
    zaman: float


_saglik_onbellegi: dict[str, _SaglikKaydi] = {}


def saglik_onbellegini_bosalt() -> None:
    """Önbelleği düşürür (testler için)."""
    _saglik_onbellegi.clear()


def model_id(provider: str, model: str) -> str:
    """Kararlı seçim anahtarı üretir."""
    return f"{provider}:{model}"


def _yapilandirilmis_model(ayarlar: Settings, saglayici: str) -> str:
    """Bir sağlayıcının `.env`'de yapılandırılmış model adı."""
    if saglayici == "evren":
        return ayarlar.evren_model
    if saglayici == "local":
        return ayarlar.local_llm_model
    return f"mock:{ayarlar.mock_llm_mode}"


async def _saglik(saglayici: str, ayarlar: Settings) -> bool:
    """Sağlayıcının sağlığını (önbellekli) döndürür."""
    kayit = _saglik_onbellegi.get(saglayici)
    simdi = time.monotonic()
    if kayit is not None and simdi - kayit.zaman < HEALTH_TTL_SECONDS:
        return kayit.saglikli

    gecici = ayarlar.model_copy(update={"llm_provider": saglayici})
    try:
        saglikli = await get_provider(gecici).health()
    except (ValueError, OSError) as exc:
        # ⚠️ İstisna yükseltilmez: bir sağlayıcının kurulu olmaması bir hata
        # değil, bir DURUM. Liste yine dönmeli.
        logger.info("saglayici_saglik_hatasi", saglayici=saglayici, hata=str(exc))
        saglikli = False

    _saglik_onbellegi[saglayici] = _SaglikKaydi(saglikli=saglikli, zaman=simdi)
    return saglikli


async def list_models() -> ChatModelsResponse:
    """Seçilebilir modelleri ve sağlık durumlarını döndürür."""
    ayarlar = get_settings()
    etkin = ayarlar.llm_provider.strip().lower()

    secenekler: list[ChatModelOption] = []
    for saglayici in ("evren", "local"):
        model = _yapilandirilmis_model(ayarlar, saglayici)
        etiket, aciklama = PROVIDER_LABELS[saglayici]
        if not model:
            secenekler.append(
                ChatModelOption(
                    id=model_id(saglayici, "(tanımsız)"),
                    provider=saglayici,
                    model="(tanımsız)",
                    label=etiket,
                    is_local=saglayici == "local",
                    is_active=False,
                    available=False,
                    note=f"{aciklama} · `.env` içinde model adı tanımlı değil.",
                )
            )
            continue

        saglikli = await _saglik(saglayici, ayarlar)
        secenekler.append(
            ChatModelOption(
                id=model_id(saglayici, model),
                provider=saglayici,
                model=model,
                label=f"{etiket} — {model}",
                is_local=saglayici == "local",
                is_active=saglayici == etkin,
                available=saglikli,
                note=aciklama if saglikli else f"{aciklama} · şu an erişilemiyor.",
            )
        )

    etkin_model = _yapilandirilmis_model(ayarlar, etkin) or "(tanımsız)"
    return ChatModelsResponse(active_id=model_id(etkin, etkin_model), items=secenekler)


def resolve_override(secim: str | None) -> str | None:
    """Arayüzden gelen `provider:model` seçimini sağlayıcı adına çevirir.

    ⚠️ BİLİNMEYEN SEÇİM SESSİZCE YOK SAYILIR, HATA VERİLMEZ. Kullanıcı eski
    bir sekmeden artık tanımlı olmayan bir model gönderebilir; isteği
    reddetmek yerine yapılandırılmış sağlayıcıyla yanıtlamak doğru davranıştır
    ve `answer.model_name` hangi modelin kullanıldığını yine bildirir.

    Args:
        secim: `provider:model` biçiminde anahtar ya da `None`.

    Returns:
        Geçerliyse sağlayıcı adı, değilse `None`.
    """
    if not secim:
        return None
    saglayici = secim.split(":", 1)[0].strip().lower()
    if saglayici not in PROVIDER_LABELS:
        logger.info("bilinmeyen_model_secimi", secim=secim)
        return None
    return saglayici
