"""Olgu tabanlı anlatıcı — model hesap yapmaz, yalnızca yeniden ifade eder.

Deterministik katman (rank / pivot / aggregate) olguları üretir; yerel LLM
bunları akıcı Türkçeye çevirir. Guard reddederse şablon metin aynen döner
(regresyon yok).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from app.ai.providers.base import LLMProvider, LLMProviderError
from app.ai.validation.terminology import check_terminology
from app.logging_config import get_logger
from app.retrieval.answer import check_direction

logger = get_logger(__name__)

_PROMPT: Final[Path] = Path(__file__).resolve().parents[1] / "ai" / "prompts" / "narrate_v1.txt"
_FALLBACK: Final[str] = "Olguları Türkçeye çevir. Yeni sayı uydurma. faiz/kredi/mevduat yazma."
_SAYI_RE: Final[re.Pattern[str]] = re.compile(r"\d[\d.,]*")
MIN_LEN: Final[int] = 2
MAX_TOKENS: Final[int] = 360


@dataclass(frozen=True)
class FactTriple:
    """Tek bir olgu: etiket, değer, birim, isteğe bağlı kaynak."""

    etiket: str
    deger: str
    birim: str = ""
    kaynak_url: str | None = None


@dataclass(frozen=True)
class NarrationFacts:
    """Anlatıcıya verilen kesin olgu kümesi + şablon yedek metin."""

    facts: tuple[FactTriple, ...]
    template_text: str
    question: str = ""
    rate_type: str | None = None


@dataclass(frozen=True)
class NarrationResult:
    """Anlatıcı çıktısı."""

    text: str
    source: str  # model | computed
    model_name: str | None = None
    model_error: str | None = None
    latency_ms: int | None = None


def _system() -> str:
    try:
        return _PROMPT.read_text(encoding="utf-8").strip()
    except OSError:
        return _FALLBACK


def _olgu_havuzu(facts: NarrationFacts) -> str:
    """Olgulardaki sayıların doğrulama havuzu (noktalama yok)."""
    parcalar = [facts.template_text]
    for f in facts.facts:
        parcalar.append(f.deger)
        parcalar.append(f.birim)
    return re.sub(r"[.,\s]", "", " ".join(parcalar))


def _sayilar_olguya_uygun_mu(text: str, facts: NarrationFacts) -> bool:
    """Metindeki her sayı olgu kümesinde birebir geçmeli."""
    havuz = _olgu_havuzu(facts)
    for eslesme in _SAYI_RE.finditer(text):
        ham = eslesme.group(0).strip(".,")
        sade = re.sub(r"[.,]", "", ham)
        if len(sade) < MIN_LEN:
            continue
        if sade not in havuz:
            return False
    return True


def _istem(facts: NarrationFacts) -> str:
    satirlar = []
    for f in facts.facts:
        satir = f"- {f.etiket}: {f.deger}"
        if f.birim:
            satir += f" {f.birim}"
        if f.kaynak_url:
            satir += f" (kaynak: {f.kaynak_url})"
        satirlar.append(satir)
    olgu = "\n".join(satirlar) if satirlar else "(olgu yok; şablonu kısalt)"
    return (
        f"OLGULAR:\n{olgu}\n\n"
        f"ŞABLON (yedek / sayı kaynağı):\n{facts.template_text}\n\n"
        f"SORU: {facts.question or '(yok)'}"
    )


async def narrate(
    facts: NarrationFacts,
    *,
    provider: LLMProvider | None,
    forbidden_terms: dict[str, str | None] | None = None,
) -> NarrationResult:
    """Olguları yeniden ifade eder; guard reddederse şablona düşer."""
    if provider is None:
        return NarrationResult(text=facts.template_text, source="computed")

    try:
        yanit = await provider.generate(
            _istem(facts),
            system=_system(),
            temperature=0.0,
            max_tokens=MAX_TOKENS,
        )
        metin = (yanit.text or "").strip()
    except LLMProviderError as exc:
        logger.warning("anlatici_basarisiz", hata=str(exc))
        return NarrationResult(
            text=facts.template_text,
            source="computed",
            model_error=str(exc),
        )

    if not metin:
        return NarrationResult(text=facts.template_text, source="computed")

    if not _sayilar_olguya_uygun_mu(metin, facts):
        logger.info("anlatici_sayi_red")
        return NarrationResult(
            text=facts.template_text,
            source="computed",
            model_name=yanit.model_name,
            model_error="sayı birebir doğrulanamadı",
            latency_ms=yanit.latency_ms,
        )

    yasakli = forbidden_terms or {}
    if yasakli:
        uyarilar = check_terminology(metin, yasakli, source_text=facts.template_text)
        if uyarilar:
            # Tek yeniden yazma turu.
            try:
                yeniden = await provider.generate(
                    _istem(facts) + "\n\nÖNCEKİ ÇIKTI YASAKLI TERİM İÇERİYOR. "
                    "faiz/kredi/mevduat kullanmadan yeniden yaz.",
                    system=_system(),
                    temperature=0.0,
                    max_tokens=MAX_TOKENS,
                )
                metin2 = (yeniden.text or "").strip()
                if (
                    metin2
                    and _sayilar_olguya_uygun_mu(metin2, facts)
                    and not check_terminology(metin2, yasakli, source_text=facts.template_text)
                ):
                    metin = metin2
                    yanit = yeniden
                else:
                    return NarrationResult(
                        text=facts.template_text,
                        source="computed",
                        model_name=yanit.model_name,
                        model_error="terminoloji",
                        latency_ms=yanit.latency_ms,
                    )
            except LLMProviderError:
                return NarrationResult(
                    text=facts.template_text,
                    source="computed",
                    model_error="terminoloji yeniden yazma başarısız",
                )

    if check_direction(metin, facts.rate_type):
        logger.info("anlatici_yon_red")
        return NarrationResult(
            text=facts.template_text,
            source="computed",
            model_name=yanit.model_name,
            model_error="yön guard",
            latency_ms=yanit.latency_ms,
        )

    return NarrationResult(
        text=metin,
        source="model",
        model_name=yanit.model_name,
        latency_ms=yanit.latency_ms,
    )


def relaxation_to_natural(hints: list[tuple[str, str, str, int]]) -> str:
    """Boş sonuçta relaxation_hints → doğal cümle.

    hints: (kind, value, label, hit_count)
    """
    if not hints:
        return (
            "Bu soruya elimizdeki veriyle yanıt verilemiyor: sorgu süzgeçlerini "
            "sağlayan kayıt bulunamadı."
        )
    parcalar = []
    for _kind, value, label, hit in hints[:3]:
        parcalar.append(f"{label} ({value}) kaldırılsa {hit} kayıt çıkıyor")
    birlesen = "; ".join(parcalar)
    return (
        f"Bu süzgeçlerle kayıt yok. {birlesen}. "
        "İsterseniz bir süzgeci kaldırıp yeniden bakabilirim."
    )


__all__ = [
    "FactTriple",
    "NarrationFacts",
    "NarrationResult",
    "narrate",
    "relaxation_to_natural",
]
