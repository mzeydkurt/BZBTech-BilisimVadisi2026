"""Düşük güvenli alan yönlendirmesinde LLM router.

⚠️ Yalnızca `CHAT_ROUTER_LLM=true` ve güven eşiğinin altında çağrılır.
⚠️ Model sayı ÜRETMEZ: dönen sayısal slotlar sorgu metnine karşı doğrulanır;
sorguda geçmeyen sayı düşürülür. Hata/zaman aşımında deterministik karara
sessizce dönülür — sohbet bloke olmaz.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from app.ai.providers.base import LLMProvider, LLMProviderError
from app.config import get_settings
from app.logging_config import get_logger
from app.retrieval.routing import LOW_CONFIDENCE, DomainDecision
from app.retrieval.slots import validate_numeric_slots_against_query

logger = get_logger(__name__)

_PROMPT: Final[Path] = Path(__file__).resolve().parent / "prompts" / "router_v1.txt"

_ROUTER_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "domain": {
            "type": "string",
            "enum": ["kampanya", "finansman", "katilma", "tanim", "sohbet", "kapsam_disi"],
        },
        "tool": {
            "type": ["string", "null"],
            "enum": [
                "finansman_teklif",
                "bddk_limit",
                "katilma_getiri",
                "urun_karsilastir",
                None,
            ],
        },
        "slots": {
            "type": "object",
            "properties": {
                "amount_try": {"type": ["string", "null"]},
                "term_months": {"type": ["integer", "null"]},
                "term_days": {"type": ["integer", "null"]},
                "product_type": {
                    "type": ["string", "null"],
                    "enum": [
                        "tasit_finansmani",
                        "konut_finansmani",
                        "ihtiyac_finansmani",
                        None,
                    ],
                },
                "asset_type": {
                    "type": ["string", "null"],
                    "enum": ["tasit", "konut", "ihtiyac", None],
                },
                "asset_value_try": {"type": ["string", "null"]},
                "energy_class": {"type": ["string", "null"]},
                "first_home": {"type": ["boolean", "null"]},
                "deposit_try": {"type": ["string", "null"]},
                "currency": {"type": ["string", "null"]},
            },
            "additionalProperties": False,
        },
        "reason": {"type": "string"},
    },
    "required": ["domain"],
    "additionalProperties": False,
}

_ALLOWED_DOMAINS: Final[frozenset[str]] = frozenset(
    {"kampanya", "finansman", "katilma", "tanim", "sohbet", "kapsam_disi"}
)
_ALLOWED_TOOLS: Final[frozenset[str]] = frozenset(
    {"finansman_teklif", "bddk_limit", "katilma_getiri", "urun_karsilastir"}
)


@dataclass(frozen=True)
class RouterResult:
    """LLM router çıktısı — doğrulanmış."""

    domain: str | None
    tool: str | None = None
    slots: dict[str, Any] = field(default_factory=dict)
    rejected_slots: tuple[str, ...] = ()
    llm_used: bool = False
    reason: str | None = None


def _system_prompt() -> str:
    try:
        return _PROMPT.read_text(encoding="utf-8").strip()
    except OSError:
        return (
            "Katibim yönlendiricisi. domain ve isteğe bağlı tool/slots JSON döndür. "
            "Metinde olmayan sayı uydurma."
        )


def should_call_router(decision: DomainDecision) -> bool:
    """Ayar ve güven eşiğine göre LLM router çağrılsın mı?"""
    ayar = get_settings()
    if not ayar.chat_router_llm:
        return False
    esik = ayar.chat_router_confidence_threshold or LOW_CONFIDENCE
    return decision.confidence < esik or decision.is_ambiguous


async def route_with_llm(
    raw: str,
    decision: DomainDecision,
    *,
    provider: LLMProvider | None,
) -> RouterResult:
    """Düşük güvende LLM ile alan/araç önerir; sayıları sorguya karşı doğrular."""
    if provider is None or not should_call_router(decision):
        return RouterResult(domain=None, llm_used=False)

    istem = (
        f"Deterministik karar: domain={decision.domain}, "
        f"confidence={decision.confidence}, ambiguous={decision.is_ambiguous}, "
        f"scores={json.dumps(decision.scores, ensure_ascii=False)}\n\n"
        f"SORU: {raw}"
    )
    try:
        yanit = await provider.generate(
            istem,
            system=_system_prompt(),
            schema=_ROUTER_SCHEMA,
            temperature=0.0,
            max_tokens=256,
        )
    except LLMProviderError as exc:
        logger.info("router_llm_hata", hata=str(exc))
        return RouterResult(domain=None, llm_used=False, reason=str(exc))
    except Exception as exc:
        logger.info("router_llm_beklenmeyen", hata=str(exc))
        return RouterResult(domain=None, llm_used=False, reason=str(exc))

    parsed = yanit.parsed
    if parsed is None and yanit.text:
        try:
            parsed = json.loads(yanit.text)
        except json.JSONDecodeError:
            parsed = None
    if not isinstance(parsed, dict):
        return RouterResult(domain=None, llm_used=True, reason="geçersiz JSON")

    domain = parsed.get("domain")
    if not isinstance(domain, str) or domain not in _ALLOWED_DOMAINS:
        domain = None

    tool = parsed.get("tool")
    if not isinstance(tool, str) or tool not in _ALLOWED_TOOLS:
        tool = None

    ham_slots = parsed.get("slots") or {}
    if not isinstance(ham_slots, dict):
        ham_slots = {}
    # None değerleri temizle.
    ham_slots = {k: v for k, v in ham_slots.items() if v is not None}
    temiz, reddedilen = validate_numeric_slots_against_query(raw, ham_slots)

    return RouterResult(
        domain=domain,
        tool=tool,
        slots=temiz,
        rejected_slots=tuple(reddedilen),
        llm_used=True,
        reason=parsed.get("reason") if isinstance(parsed.get("reason"), str) else None,
    )


__all__ = [
    "RouterResult",
    "route_with_llm",
    "should_call_router",
]
