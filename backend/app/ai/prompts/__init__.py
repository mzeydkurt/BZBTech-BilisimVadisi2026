"""Prompt yükleyici ve sürüm yönetimi.

⚠️ PROMPT'LAR KODA GÖMÜLMEZ. SPRINT 3B'de gerçek modelle ince ayar yapılacak;
her denemede Python dosyası değiştirmek gerekirse hem sürüm izlenemez hem de
kod incelemesi prompt metniyle kirlenir. Metinler `.txt` dosyalarında durur,
sürüm dosya adında taşınır: `extract_v1.txt` → `extract_v2.txt`.

⚠️ SÜRÜM HER ÇIKARIM KAYDINA YAZILIR (`campaign_extractions.prompt_version`) ve
önbellek anahtarına girer. Böylece prompt değişince eski yanıtlar kendiliğinden
geçersizleşir; hangi sonucun hangi metinle üretildiği sonradan bulunabilir.

⚠️ FEW-SHOT ÖRNEKLERİ ELLE YAZILDI, gold set'ten SEÇİLMEDİ. Aynı kaydı hem
örnek hem test olarak kullanmak sızıntıdır: model o kaydın cevabını ezberler ve
F1 gerçekte olduğundan yüksek çıkar. `FEW_SHOT_MARKERS`, gold set örneklemesinin
(KAPI A3) bu metinleri dışarıda bırakabilmesi için dışa açılır.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Final

from app.config import get_settings

PROMPT_DIR: Final[Path] = Path(__file__).resolve().parent

# Tanımlı prompt adları. Dosya adı `{ad}_{sürüm}.txt` kalıbındadır.
PROMPT_NAMES: Final[tuple[str, ...]] = ("system", "extract", "classify", "summarize")

# ⚠️ Few-shot örneklerinde geçen özgün ifadeler. Gold set örneklemesi, bu
# ifadeleri içeren kampanyaları DIŞARIDA BIRAKIR: örnek olarak modele gösterilen
# bir metin, aynı zamanda test kaydı olamaz.
FEW_SHOT_MARKERS: Final[tuple[str, ...]] = (
    "Colin's mağazalarında Kuveyt Türk kredi kartınızla",
    "Konut finansmanında avantajlı kâr payı fırsatı sizi bekliyor",
    "5.000 TL ve üzeri harcamalarda 250 TL, 10.000 TL ve üzeri",
)


class PromptError(Exception):
    """Prompt dosyası bulunamadı ya da yer tutucusu doldurulamadı."""


@lru_cache(maxsize=64)
def _read(name: str, version: str) -> str:
    """Prompt dosyasını okur ve önbelleğe alır.

    ⚠️ Önbellek süreç ömrü boyuncadır: çalışan bir işlemde dosyayı düzenlemek
    etkisiz kalır. SPRINT 3B'de ince ayar yaparken süreç yeniden başlatılır.

    Args:
        name: Prompt adı (`extract`, `system`, ...).
        version: Sürüm etiketi (`v1`).

    Returns:
        Dosyanın ham içeriği.

    Raises:
        PromptError: Dosya yoksa.
    """
    path = PROMPT_DIR / f"{name}_{version}.txt"
    if not path.is_file():
        mevcut = sorted(p.name for p in PROMPT_DIR.glob("*.txt"))
        raise PromptError(f"Prompt bulunamadı: {path.name}. Mevcut olanlar: {mevcut}")
    return path.read_text(encoding="utf-8")


def load_prompt(name: str, version: str | None = None, **degiskenler: Any) -> str:
    """Prompt metnini yükler ve yer tutucularını doldurur.

    Args:
        name: Prompt adı.
        version: Sürüm; verilmezse `PROMPT_VERSION` ayarından okunur.
        **degiskenler: `{ad}` yer tutucularına yazılacak değerler.

    Returns:
        Doldurulmuş prompt metni.

    Raises:
        PromptError: Dosya yoksa ya da bir yer tutucu doldurulmadıysa.
    """
    surum = version or get_settings().prompt_version
    ham = _read(name, surum)

    try:
        return ham.format(**degiskenler)
    except KeyError as exc:
        # ⚠️ Eksik yer tutucu SESSİZCE geçilmez: `{clean_text}` doldurulmadan
        # gönderilen bir istem, modele kaynak metni hiç vermez ve model
        # "bilgi yok" yerine UYDURMAYA yönelir.
        raise PromptError(f"{name}_{surum}.txt içindeki {exc} yer tutucusu doldurulmadı") from exc
    except IndexError as exc:
        raise PromptError(
            f"{name}_{surum}.txt içinde kaçırılmamış süslü parantez var; "
            "JSON örneklerinde {{ }} kullanılmalı"
        ) from exc


def available_versions(name: str) -> list[str]:
    """Bir prompt için diskteki sürümleri döndürür.

    Args:
        name: Prompt adı.

    Returns:
        Sürüm etiketleri, artan sırada.
    """
    return sorted(p.stem.removeprefix(f"{name}_") for p in PROMPT_DIR.glob(f"{name}_*.txt"))


def contains_few_shot_example(text: str | None) -> bool:
    """Metin, few-shot örneklerinden birini içeriyor mu?

    Gold set örneklemesi bu kayıtları dışarıda bırakır (sızıntı koruması).

    Args:
        text: Kampanyanın temizlenmiş metni.

    Returns:
        İçeriyorsa True.
    """
    if not text:
        return False
    return any(isaret in text for isaret in FEW_SHOT_MARKERS)


__all__ = [
    "FEW_SHOT_MARKERS",
    "PROMPT_DIR",
    "PROMPT_NAMES",
    "PromptError",
    "available_versions",
    "contains_few_shot_example",
    "load_prompt",
]
