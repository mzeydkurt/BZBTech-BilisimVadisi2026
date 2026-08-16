"""Kampanya özetleme (KAPI A8).

3-5 maddelik Türkçe özet → `campaigns.summary_ai`.

⚠️ ÖZET ÜRETİLDİKTEN SONRA DOĞRULANIR, önce değil. Prompt'ta "uydurma"
demek bir niyet beyanıdır; garanti değildir. İki denetim uygulanır:

    1. Özetteki HER SAYI kaynakta geçmeli   (`unsupported_numbers`)
    2. Konvansiyonel terim bulunmamalı      (`check_terminology`)

Geçemeyen özet REDDEDİLİR ve `summary_ai` **None kalır**. Yanlış bir özet
göstermektense özet göstermemek doğrudur: bu alan arayüzde kampanyanın
resmî tanımı gibi okunur.

⚠️ ÖZET, KAYNAĞIN KISALTILMIŞ HÂLİDİR. Yeni bilgi ekleyen bir özet, özet
değil uydurmadır. Sayı denetiminin dayanağı budur.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Final

from sqlalchemy.orm import Session

from app.ai.cache import cached_generate
from app.ai.fields import MAX_PROMPT_CHARS
from app.ai.prompts import load_prompt
from app.ai.providers.base import LLMProvider, LLMProviderError
from app.ai.validation import TerminologyWarning, check_terminology
from app.ai.validation.numbers import unsupported_numbers
from app.db.models import Campaign
from app.logging_config import get_logger

logger = get_logger(__name__)

# Red gerekçeleri.
REASON_UNSUPPORTED_NUMBER: Final[str] = "summary_number_not_in_source"
REASON_FORBIDDEN_TERM: Final[str] = "summary_forbidden_term"
REASON_EMPTY: Final[str] = "summary_empty"

# Özetin kabul edilebilir en kısa uzunluğu. Bunun altındaki bir çıktı
# özet değil, artık bir metindir.
MIN_SUMMARY_CHARS: Final[int] = 40

SUMMARY_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "summary": {"type": ["string", "null"]},
        "key_points": {"type": ["array", "null"], "items": {"type": "string"}},
    },
    "required": ["summary"],
}


@dataclass
class SummaryResult:
    """Özetleme çıktısı ve doğrulama sonucu."""

    summary: str | None = None
    key_points: list[str] = field(default_factory=list)
    llm_calls: int = 0
    cache_hits: int = 0
    # Dolu ise özet REDDEDİLDİ ve `summary` None'dır.
    rejected_reason: str | None = None
    unsupported_numbers: list[Decimal] = field(default_factory=list)
    terminology_warnings: list[TerminologyWarning] = field(default_factory=list)
    skipped_reason: str | None = None

    @property
    def accepted(self) -> bool:
        """Özet doğrulamayı geçti mi?"""
        return self.summary is not None and self.rejected_reason is None


def validate_summary(
    summary: str | None,
    clean_text: str,
    forbidden_terms: dict[str, str | None],
) -> SummaryResult:
    """Üretilen özeti iki katmandan geçirir.

    Args:
        summary: Modelin ürettiği özet.
        clean_text: Kaynak metin.
        forbidden_terms: `load_forbidden_terms()` çıktısı.

    Returns:
        Doğrulama sonucu; geçemezse `summary=None` ve `rejected_reason` dolu.
    """
    temiz = (summary or "").strip()
    if len(temiz) < MIN_SUMMARY_CHARS:
        return SummaryResult(rejected_reason=REASON_EMPTY)

    # 1. Kaynakta olmayan sayı.
    desteksiz = unsupported_numbers(temiz, clean_text)
    if desteksiz:
        return SummaryResult(
            rejected_reason=REASON_UNSUPPORTED_NUMBER, unsupported_numbers=desteksiz
        )

    # 2. Konvansiyonel terim.
    # ⚠️ Kaynak metin de verilir: banka "kredi kartı" yazmışsa bu bizim
    # hatamız değildir ve özet onu tekrarlayabilir.
    uyarilar = check_terminology(temiz, forbidden_terms, source_text=clean_text)
    if uyarilar:
        return SummaryResult(rejected_reason=REASON_FORBIDDEN_TERM, terminology_warnings=uyarilar)

    return SummaryResult(summary=temiz)


async def summarize(
    provider: LLMProvider,
    session: Session,
    campaign: Campaign,
    clean_text: str,
    forbidden_terms: dict[str, str | None],
    *,
    prompt_version: str,
    use_cache: bool = True,
) -> SummaryResult:
    """Kampanya için doğrulanmış bir özet üretir.

    Args:
        provider: LLM sağlayıcısı.
        session: Veritabanı oturumu.
        campaign: Özetlenecek kampanya.
        clean_text: Kampanyanın temiz metni.
        forbidden_terms: Yasaklı terim sözlüğü.
        prompt_version: Etkin prompt sürümü.
        use_cache: False ise önbellek okunmaz.

    Returns:
        Özet ve doğrulama sonucu. Doğrulamayı geçemeyen özet KAYDEDİLMEZ.
    """
    if not clean_text.strip():
        return SummaryResult(skipped_reason="empty_text")

    istem = load_prompt(
        "summarize",
        prompt_version,
        # ⚠️ Özet TEK ÇAĞRIDA üretilir; bölünmüş parçaların özetleri
        # birleştirilirse kampanyanın bütünü hiçbir yerde görülmez.
        clean_text=clean_text[:MAX_PROMPT_CHARS],
    )

    try:
        yanit = await cached_generate(
            provider,
            session,
            text=istem,
            task="summarize",
            prompt_version=prompt_version,
            use_cache=use_cache,
            system=load_prompt("system", prompt_version),
            schema=SUMMARY_SCHEMA,
        )
    except LLMProviderError as exc:
        logger.warning(
            "ozetleme_atlandi", kampanya_id=campaign.id, hata=f"{type(exc).__name__}: {exc}"
        )
        return SummaryResult(skipped_reason=type(exc).__name__)

    parsed = yanit.parsed or {}
    ham_ozet = parsed.get("summary") if isinstance(parsed, dict) else None
    maddeler = parsed.get("key_points") if isinstance(parsed, dict) else None

    sonuc = validate_summary(
        ham_ozet if isinstance(ham_ozet, str) else None, clean_text, forbidden_terms
    )
    sonuc.llm_calls = 1
    sonuc.cache_hits = 1 if yanit.from_cache else 0
    if isinstance(maddeler, list) and sonuc.accepted:
        sonuc.key_points = [str(m) for m in maddeler if str(m).strip()]

    if sonuc.rejected_reason:
        logger.warning(
            "ozet_reddedildi",
            kampanya_id=campaign.id,
            gerekce=sonuc.rejected_reason,
            desteksiz_sayilar=[str(s) for s in sonuc.unsupported_numbers],
        )

    return sonuc
