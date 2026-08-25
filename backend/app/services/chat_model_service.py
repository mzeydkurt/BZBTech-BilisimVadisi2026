"""Sohbette seçilebilecek modeller — canlı keşif ve sağlık durumu.

 LİSTE SABİT DEĞİL, SERVİSTEN KEŞFEDİLİR. Elle yazılmış bir model listesi,
servis yeni bir model eklediğinde ya da kaldırdığında sessizce yalan söyler.
EVREN `/v1/models`, Ollama `/api/tags` ile sorulur.

SEÇİM SAĞLAYICIYI **VE** MODEL ADINI DEĞİŞTİRİR. İlk uygulamada yalnızca
sağlayıcı geçiliyordu; `evren:llm-large` seçmek sağlayıcıyı EVREN'de tutuyor
ama modeli `.env`'deki `llm-fast` olarak bırakıyordu — kullanıcı seçim yaptı
sanıyor, model değişmiyordu ve hata da vermiyordu.

SEÇİM İSTEK BAŞINADIR, `.env` YAZILMAZ. Bir kullanıcının tercihi tüm
kurumun yapılandırmasını değiştirmemeli — hele jüri demosu sırasında.

YEREL MODELLER LİSANS HAVUZUNA GÖRE SÜZÜLÜR. `docs/SPRINT3B_LLM_LOCAL_KURULUM.md`
§3.1 yalnızca izin verici lisanslı modelleri kabul ediyor; Ollama'da kurulu
olsa bile Llama türevi ya da "Research License" taşıyan bir model seçenek
olarak SUNULMAZ. Sunmak, şartname madde 5.10'a aykırı bir kurulumu tek tıkla
mümkün kılmak olurdu.

⚠️ ERİŞİLEMEYEN MODEL GİZLENMEZ, DEVRE DIŞI GÖSTERİLİR. Gizlemek "böyle bir
seçenek yok" izlenimi verir; oysa yerel model kapalı ağ gösteriminin kanıtı.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Final

import httpx

from app.config import Settings, get_settings
from app.logging_config import get_logger
from app.schemas.chat import ChatModelOption, ChatModelsResponse

logger = get_logger(__name__)

# Keşif ve sağlık sonucunun geçerli kalma süresi.
DISCOVERY_TTL_SECONDS: Final[float] = 90.0

# Keşif isteklerinin zaman aşımı — arayüzü bekletmemek için kısa.
DISCOVERY_TIMEOUT_SECONDS: Final[float] = 8.0

# ── EVREN: metin üretimine uygun olmayan modeller ─────────
# Gömme, yeniden sıralama ve seyrek/çok-vektörlü erişim modelleri sohbet
# yanıtı üretemez; listeye girerse kullanıcı seçer ve sistem hata verir.
EVREN_NON_CHAT: Final[frozenset[str]] = frozenset(
    {"embed", "bge-m3-embed", "rerank", "bge-m3-sparse", "bge-m3-colbert"}
)

# Özel amaçlı modeller — seçilebilir ama ne oldukları yazılır.
EVREN_SPECIAL_NOTES: Final[dict[str, str]] = {
    "router": "Yönlendirme modeli; sohbet yanıtı için tasarlanmadı.",
    "guard": "Güvenlik denetim modeli; sohbet yanıtı için tasarlanmadı.",
    "vlm": "Görsel-dil modeli; bu arayüz yalnızca metin gönderiyor.",
}

# ── Yerel: izin verici lisanslı model önekleri ────────────
# ⚠️ BEYAZ LİSTE, SİYAH LİSTE DEĞİL. Yeni bir model kurulduğunda varsayılan
# davranış "sunma" olmalı; bilinmeyen lisansı izin verici saymak, şartname
# madde 5.10'un tam olarak yasakladığı riski üretir.
LOCAL_ALLOWED_PREFIXES: Final[tuple[str, ...]] = (
    "qwen3",
    "qwen2.5-coder",
    "qwen2.5:7b",
    "qwen2.5:14b",
    "mistral",
    "mistral-nemo",
)

# Lisansı izin verici OLMAYAN, açıkça dışlanan önekler (gerekçe için).
LOCAL_BLOCKED_REASON: Final[dict[str, str]] = {
    "deepseek-r1": "Llama-3.x türevi damıtma — Llama Community License",
    "llama": "Llama Community License",
    "gemma": "Gemma Terms of Use",
    "qwen2.5:3b": "Qwen Research License",
}

PROVIDER_LABELS: Final[dict[str, str]] = {
    "evren": "EVREN",
    "local": "Yerel (Ollama)",
}

PROVIDER_NOTES: Final[dict[str, str]] = {
    "evren": "TEKNOFEST çıkarım servisi (SSB tahsisli). Dış ağ gerektirir.",
    "local": "Kapalı ağda çalışır — on-prem gösteriminin kanıtı.",
}


@dataclass
class _Kesif:
    """Önbelleklenmiş keşif sonucu."""

    modeller: list[str]
    zaman: float


_kesif_onbellegi: dict[str, _Kesif] = {}


def kesif_onbellegini_bosalt() -> None:
    """Önbelleği düşürür (testler ve model kurulumu sonrası)."""
    _kesif_onbellegi.clear()


def model_id(provider: str, model: str) -> str:
    """Kararlı seçim anahtarı üretir."""
    return f"{provider}:{model}"


def yerel_lisans_engeli(model: str) -> str | None:
    """Modelin lisans gerekçesiyle dışlanma nedeni; yoksa `None`."""
    ad = model.strip().lower()
    for onek, gerekce in LOCAL_BLOCKED_REASON.items():
        if ad.startswith(onek):
            return gerekce
    if not any(ad.startswith(onek) for onek in LOCAL_ALLOWED_PREFIXES):
        return "lisansı doğrulanmadı (beyaz listede değil)"
    return None


async def _evren_modelleri(ayarlar: Settings) -> list[str]:
    """EVREN'in yayımladığı model adlarını döndürür."""
    if not ayarlar.evren_api_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=DISCOVERY_TIMEOUT_SECONDS) as client:
            yanit = await client.get(
                f"{ayarlar.evren_base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {ayarlar.evren_api_key}"},
            )
        if yanit.status_code != httpx.codes.OK:
            logger.info("evren_model_listesi_alinamadi", durum=yanit.status_code)
            return []
        veri: Any = yanit.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.info("evren_kesif_hatasi", hata=str(exc) or type(exc).__name__)
        return []
    return [str(m.get("id", "")) for m in veri.get("data", []) if m.get("id")]


async def _yerel_modeller(ayarlar: Settings) -> list[str]:
    """Ollama'da kurulu model adlarını döndürür."""
    kok = ayarlar.local_llm_base_url.rstrip("/")
    if kok.endswith("/v1"):
        kok = kok[: -len("/v1")]
    try:
        async with httpx.AsyncClient(timeout=DISCOVERY_TIMEOUT_SECONDS) as client:
            yanit = await client.get(f"{kok}/api/tags")
        if yanit.status_code != httpx.codes.OK:
            return []
        veri: Any = yanit.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.info("yerel_kesif_hatasi", hata=str(exc) or type(exc).__name__)
        return []
    return [str(m.get("name", "")) for m in veri.get("models", []) if m.get("name")]


async def _kesfet(saglayici: str, ayarlar: Settings) -> list[str]:
    """Sağlayıcının modellerini (önbellekli) keşfeder."""
    kayit = _kesif_onbellegi.get(saglayici)
    simdi = time.monotonic()
    if kayit is not None and simdi - kayit.zaman < DISCOVERY_TTL_SECONDS:
        return kayit.modeller

    modeller = (
        await _evren_modelleri(ayarlar) if saglayici == "evren" else await _yerel_modeller(ayarlar)
    )
    _kesif_onbellegi[saglayici] = _Kesif(modeller=modeller, zaman=simdi)
    return modeller


def _evren_secenekleri(
    modeller: list[str], *, etkin_saglayici: str, etkin_model: str
) -> list[ChatModelOption]:
    """EVREN modellerini seçeneğe çevirir."""
    secenekler: list[ChatModelOption] = []
    for model in modeller:
        if model in EVREN_NON_CHAT:
            # Gömme / yeniden sıralama modelleri sohbet yanıtı üretemez.
            continue
        ozel = EVREN_SPECIAL_NOTES.get(model)
        secenekler.append(
            ChatModelOption(
                id=model_id("evren", model),
                provider="evren",
                model=model,
                label=f"{PROVIDER_LABELS['evren']} — {model}",
                is_local=False,
                is_active=etkin_saglayici == "evren" and etkin_model == model,
                # Servis modeli yayımlıyorsa erişilebilir sayılır; ayrıca
                # yoklama yapmak her sayfa açılışında N istek demek olurdu.
                available=True,
                note=ozel or PROVIDER_NOTES["evren"],
            )
        )
    # `llm-fast` ölçümde `llm-large`'a üstün çıktı; önce o görünsün.
    sira = {"llm-fast": 0, "llm-large": 1}
    secenekler.sort(key=lambda secenek: (sira.get(secenek.model, 5), secenek.model))
    return secenekler


def _yerel_secenekler(
    modeller: list[str], *, etkin_saglayici: str, etkin_model: str
) -> list[ChatModelOption]:
    """Yerel modelleri lisans havuzuna göre süzerek seçeneğe çevirir."""
    secenekler: list[ChatModelOption] = []
    for model in sorted(modeller):
        engel = yerel_lisans_engeli(model)
        if engel:
            # ⚠️ Lisansı uygun olmayan model SEÇENEK OLARAK SUNULMAZ ama
            # gerekçesi loglanır; sessizce yok saymak, neden görünmediğini
            # sonraki geliştiriciye bırakmak olurdu.
            logger.info("yerel_model_lisans_disi", model=model, gerekce=engel)
            continue
        secenekler.append(
            ChatModelOption(
                id=model_id("local", model),
                provider="local",
                model=model,
                label=f"{PROVIDER_LABELS['local']} — {model}",
                is_local=True,
                is_active=etkin_saglayici == "local" and etkin_model == model,
                available=True,
                note=PROVIDER_NOTES["local"],
            )
        )
    return secenekler


async def list_models() -> ChatModelsResponse:
    """Seçilebilir modelleri canlı keşifle döndürür."""
    ayarlar = get_settings()
    etkin_saglayici = ayarlar.llm_provider.strip().lower()
    etkin_model = (
        ayarlar.evren_model if etkin_saglayici == "evren" else ayarlar.local_llm_model
    ) or "(tanımsız)"

    evren = await _kesfet("evren", ayarlar)
    yerel = await _kesfet("local", ayarlar)

    secenekler = _evren_secenekleri(
        evren, etkin_saglayici=etkin_saglayici, etkin_model=etkin_model
    ) + _yerel_secenekler(yerel, etkin_saglayici=etkin_saglayici, etkin_model=etkin_model)

    # ⚠️ Bir sağlayıcı hiç yanıt vermediyse LİSTE BOŞ BIRAKILMAZ; erişilemez
    # bir satırla temsil edilir. Aksi hâlde "yerel seçenek yok" izlenimi
    # doğar ve kapalı ağ yeteneği görünmez olur.
    for saglayici, bulunan in (("evren", evren), ("local", yerel)):
        if bulunan:
            continue
        secenekler.append(
            ChatModelOption(
                id=model_id(saglayici, "(erişilemiyor)"),
                provider=saglayici,
                model="(erişilemiyor)",
                label=f"{PROVIDER_LABELS[saglayici]} — erişilemiyor",
                is_local=saglayici == "local",
                is_active=False,
                available=False,
                note=(
                    f"{PROVIDER_NOTES[saglayici]} Şu an model listesi alınamadı; "
                    "servis kapalı ya da yapılandırma eksik."
                ),
            )
        )

    return ChatModelsResponse(active_id=model_id(etkin_saglayici, etkin_model), items=secenekler)


def resolve_override(secim: str | None) -> dict[str, str] | None:
    """`provider:model` seçimini ayar güncellemesine çevirir.

    ⚠️ SAĞLAYICI **VE** MODEL BİRLİKTE DEĞİŞİR. Yalnızca sağlayıcıyı
    geçirmek, `evren:llm-large` seçildiğinde modeli `.env`'deki `llm-fast`
    olarak bırakıyordu: kullanıcı seçim yaptı sanıyor, hiçbir şey değişmiyordu
    ve hata da verilmiyordu.

    ⚠️ BİLİNMEYEN SEÇİM SESSİZCE YOK SAYILIR. Kullanıcı eski bir sekmeden
    artık tanımlı olmayan bir model gönderebilir; isteği reddetmek yerine
    yapılandırılmış sağlayıcıyla yanıtlamak doğru davranıştır ve
    `answer.model_name` hangi modelin kullanıldığını yine bildirir.

    Args:
        secim: `provider:model` biçiminde anahtar ya da `None`.

    Returns:
        `Settings.model_copy(update=...)` için sözlük; geçersizse `None`.
    """
    if not secim or ":" not in secim:
        return None

    saglayici, _, model = secim.partition(":")
    saglayici = saglayici.strip().lower()
    model = model.strip()

    if saglayici not in PROVIDER_LABELS or not model or model.startswith("("):
        logger.info("bilinmeyen_model_secimi", secim=secim)
        return None

    if saglayici == "local" and yerel_lisans_engeli(model):
        # Arayüz sunmuyor ama istek elle de gelebilir; lisans kuralı API
        # düzeyinde de uygulanır.
        logger.warning("lisans_disi_model_reddedildi", model=model)
        return None

    if saglayici == "evren":
        if model in EVREN_NON_CHAT:
            logger.info("sohbete_uygun_olmayan_model", model=model)
            return None
        return {"llm_provider": "evren", "evren_model": model}
    return {"llm_provider": "local", "local_llm_model": model}
