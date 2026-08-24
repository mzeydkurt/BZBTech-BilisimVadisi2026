"""Sohbet top-3 puanlama — RRF sırası + niyet + güncellik.

⚠️ Sayısal "en düşük/en yüksek" bu modüle emanet edilmez; o yollar
`aggregate` / `rank_products` yapısal kalır. Burada yalnızca serbest arama
ve tekil/ürün listelerinde göreli sıra üretilir.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from app.schemas.chat import ChatTopMatch

TOP_N: Final[int] = 3
_YUZ: Final[Decimal] = Decimal("100")


@dataclass(frozen=True)
class RankCandidate:
    """Puanlanacak tek aday."""

    entity_type: str
    id: int
    title: str
    bank_name: str | None
    source_url: str | None
    detail_path: str | None
    # 0 = en iyi sıra (RRF/BM25); None = sırasız
    rank_index: int | None = None
    is_active: bool = True
    intent_boost: float = 0.0
    reason: str | None = None


def _rrf_puan(rank_index: int | None, *, k: int = 60) -> float:
    if rank_index is None:
        return 0.0
    return 1.0 / (k + max(rank_index, 0) + 1)


def score_candidates(adaylar: list[RankCandidate], *, limit: int = TOP_N) -> list[ChatTopMatch]:
    """Adayları puanlar ve en iyi `limit` sonucu döner."""
    if not adaylar:
        return []

    ham: list[tuple[float, RankCandidate]] = []
    for aday in adaylar:
        puan = _rrf_puan(aday.rank_index)
        puan += aday.intent_boost
        if aday.is_active:
            puan += 0.05
        ham.append((puan, aday))

    ham.sort(key=lambda ikili: (-ikili[0], ikili[1].id))
    en_yuksek = ham[0][0] if ham[0][0] > 0 else 1.0

    sonuc: list[ChatTopMatch] = []
    for puan, aday in ham[:limit]:
        normalize = Decimal(str(round(min(puan / en_yuksek, 1.0) * 100, 2)))
        sonuc.append(
            ChatTopMatch(
                entity_type=aday.entity_type,
                id=aday.id,
                title=aday.title,
                bank_name=aday.bank_name,
                score=normalize,
                source_url=aday.source_url,
                reason=aday.reason,
                detail_path=aday.detail_path,
            )
        )
    return sonuc


__all__ = ["RankCandidate", "TOP_N", "score_candidates"]
