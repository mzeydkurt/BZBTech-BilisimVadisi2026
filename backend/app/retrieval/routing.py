"""Kaynak alanı yönlendirmesi — güven puanlı, tek kelime kilidi yok.

⚠️ ESKİ DAVRANIŞ: `resolve_source_domain` sıralı `if/return` zinciriydi;
`"getiri"` gibi tek sözcük katılma alanına kilitleyip kampanya/finansman
erişimine hiç ulaşılmıyordu. Açık uçlu sorular ("kâr payı olarak ne kadar
öderim?") yanlış alana düşüyordu.

⚠️ YENİ DAVRANIŞ: her alan ağırlıklı sinyal toplar. En yüksek iki alan
arasındaki fark eşiğin altındaysa `is_ambiguous=True`. Tek sözcüklük geniş
terimler düşük puan alır; çok sözcüklü özgül ifadeler ve açık `rate_type`
yüksek puan alır. `resolve_source_domain` geriye dönük uyumluluk için
yalnızca `domain` dizesini döndüren ince sarmalayıcıdır.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final


def _sinyal_var(katlanmis: str, sinyal: str) -> bool:
    """Alan sinyalini kelime sınırına duyarlı arar.

    ⚠️ `\"mil\" in \"milyon\"` alt dizge eşleşmesi kampanyaya yanlış puan
    veriyordu. Kısa sinyaller (≤3) sağ sınırı da ister.
    """
    if not sinyal:
        return False
    if len(sinyal) <= 3:
        return re.search(rf"(?<![a-z0-9]){re.escape(sinyal)}(?![a-z0-9])", katlanmis) is not None
    return sinyal in katlanmis

# En yüksek iki alan arasındaki fark bu eşiğin altındaysa belirsiz.
AMBIGUITY_GAP: Final[float] = 0.30
# Bu güvenin altında LLM router (açıksa) devreye girebilir.
LOW_CONFIDENCE: Final[float] = 0.55

# Ağırlıklar — açık rate_type kesin; özgül ifade yüksek; tek sözcük düşük.
_W_RATE_TYPE: Final[float] = 1.0
_W_SPECIFIC: Final[float] = 0.70
_W_AXIS: Final[float] = 0.50
_W_BROAD: Final[float] = 0.25

# Çok sözcüklü / özgül sinyaller (yüksek ağırlık).
_KATILMA_SPECIFIC: Final[tuple[str, ...]] = (
    "katilim hesabi",
    "katilma hesabi",
    "katilim hesab",
    "katilma hesab",
    "standart katilma",
    "standart katilim",
    "birikim hesabi",
    "kar paylasim orani",
    "kar paylasimi",
    "dagitilan kar",
)
_FINANSMAN_SPECIFIC: Final[tuple[str, ...]] = (
    "konut finansmani",
    "tasit finansmani",
    "ihtiyac finansmani",
    "arac finansmani",
    "murabaha",
    "ltv",
    "kasko",
    "bddk",
)
_KAMPANYA_SPECIFIC: Final[tuple[str, ...]] = (
    "kampanya",
    "kampanyalar",
    "kampanyasi",
    "kampanyalari",
    "nakit iade",
    "nakit iadesi",
    "cashback",
    "hediye ceki",
    "taksit avantaji",
    "taksit avantaj",
)

# Tek sözcüklük / geniş sinyaller (düşük ağırlık).
_KATILMA_BROAD: Final[tuple[str, ...]] = (
    "katilma",
    "katilim",
    "getiri",
    "kar paylasim",
    "birikim",
)
_FINANSMAN_BROAD: Final[tuple[str, ...]] = (
    "finansman",
    "konut",
    "tasit",
    "ihtiyac",
    "taksit",
    "vade",
)
_KAMPANYA_BROAD: Final[tuple[str, ...]] = (
    "kart",
    "mil",
    "puan",
    "hediye",
    "indirim",
    "bonus",
)

# Birden fazla alana dokunan düşük sinyaller — tek başına karar vermez.
_SHARED_BROAD: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("kar payi", ("finansman", "katilma")),
    ("kar pay", ("finansman", "katilma")),
    ("oran", ("finansman", "katilma", "kampanya")),
)


@dataclass(frozen=True)
class DomainScore:
    """Tek bir alanın puanı ve kanıtları."""

    domain: str
    score: float
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class DomainDecision:
    """Yönlendirme kararı — alan + güven + belirsizlik."""

    domain: str
    confidence: float
    scores: dict[str, float] = field(default_factory=dict)
    evidence: tuple[str, ...] = ()
    is_ambiguous: bool = False
    runner_up: str | None = None

    @property
    def is_low_confidence(self) -> bool:
        """LLM router eşiğinin altında mı?"""
        return self.confidence < LOW_CONFIDENCE or self.is_ambiguous


def _ekle(
    puanlar: dict[str, float],
    kanitlar: dict[str, list[str]],
    alan: str,
    agirlik: float,
    kanit: str,
) -> None:
    """Aynı kanıtı iki kez saymadan puan ekler."""
    if kanit in kanitlar[alan]:
        return
    puanlar[alan] = puanlar.get(alan, 0.0) + agirlik
    kanitlar[alan].append(kanit)


def score_domains(
    katlanmis: str,
    *,
    intent: str,
    rate_type: str | None,
    axis_filters: dict[str, tuple[str, ...]],
) -> DomainDecision:
    """Sorgunun kaynak alanını güven puanıyla seçer.

    Returns:
        DomainDecision — domain, confidence, is_ambiguous.
    """
    if intent == "kapsam_disi":
        return DomainDecision(domain="kapsam_disi", confidence=1.0, scores={"kapsam_disi": 1.0})
    if intent == "sohbet":
        return DomainDecision(domain="sohbet", confidence=1.0, scores={"sohbet": 1.0})
    if intent == "tanim":
        return DomainDecision(domain="tanim", confidence=1.0, scores={"tanim": 1.0})

    puanlar: dict[str, float] = {"kampanya": 0.0, "finansman": 0.0, "katilma": 0.0}
    kanitlar: dict[str, list[str]] = {"kampanya": [], "finansman": [], "katilma": []}

    kampanya_modu = any(
        _sinyal_var(katlanmis, s)
        for s in ("kampanya", "kampanyalar", "kampanyasi", "kampanyalari")
    )

    if rate_type == "participation_yield" or rate_type == "profit_sharing_ratio":
        _ekle(puanlar, kanitlar, "katilma", _W_RATE_TYPE, f"rate_type={rate_type}")
    elif rate_type == "financing_rate":
        _ekle(puanlar, kanitlar, "finansman", _W_RATE_TYPE, f"rate_type={rate_type}")

    # Açık kampanya isteği — finansman/katılma araçlarına düşülmesin.
    if kampanya_modu:
        _ekle(puanlar, kanitlar, "kampanya", _W_RATE_TYPE, "kampanya_istegi")

    for sinyal in _KATILMA_SPECIFIC:
        if _sinyal_var(katlanmis, sinyal):
            _ekle(puanlar, kanitlar, "katilma", _W_SPECIFIC, sinyal)
    for sinyal in _FINANSMAN_SPECIFIC:
        if _sinyal_var(katlanmis, sinyal):
            _ekle(puanlar, kanitlar, "finansman", _W_SPECIFIC, sinyal)
    for sinyal in _KAMPANYA_SPECIFIC:
        if _sinyal_var(katlanmis, sinyal):
            _ekle(puanlar, kanitlar, "kampanya", _W_SPECIFIC, sinyal)

    for sinyal in _KATILMA_BROAD:
        if _sinyal_var(katlanmis, sinyal):
            # Özgül sinyal zaten eklendiyse geniş olanı sayma (çift sayım).
            if any(
                _sinyal_var(katlanmis, s)
                for s in _KATILMA_SPECIFIC
                if sinyal in s or s.startswith(sinyal)
            ):
                continue
            _ekle(puanlar, kanitlar, "katilma", _W_BROAD, sinyal)
    for sinyal in _FINANSMAN_BROAD:
        if _sinyal_var(katlanmis, sinyal):
            if kampanya_modu and sinyal == "taksit":
                # Kampanyada taksit = fayda ekseni; finansman simülasyonu değil.
                continue
            if any(_sinyal_var(katlanmis, s) for s in _FINANSMAN_SPECIFIC if sinyal in s):
                continue
            _ekle(puanlar, kanitlar, "finansman", _W_BROAD, sinyal)
    for sinyal in _KAMPANYA_BROAD:
        if _sinyal_var(katlanmis, sinyal):
            if any(_sinyal_var(katlanmis, s) for s in _KAMPANYA_SPECIFIC if sinyal in s):
                continue
            _ekle(puanlar, kanitlar, "kampanya", _W_BROAD, sinyal)

    for sinyal, alanlar in _SHARED_BROAD:
        if _sinyal_var(katlanmis, sinyal):
            for alan in alanlar:
                _ekle(puanlar, kanitlar, alan, _W_BROAD, sinyal)

    urun = axis_filters.get("product_type", ())
    for tip in urun:
        if "birikim" in tip or "katilma" in tip:
            _ekle(puanlar, kanitlar, "katilma", _W_AXIS, f"product_type={tip}")
        elif "finansman" in tip:
            _ekle(puanlar, kanitlar, "finansman", _W_AXIS, f"product_type={tip}")
        elif tip == "kart":
            _ekle(puanlar, kanitlar, "kampanya", _W_AXIS, f"product_type={tip}")

    sirali = sorted(puanlar.items(), key=lambda x: (-x[1], x[0]))
    en_yuksek_alan, en_yuksek = sirali[0]
    ikinci_alan, ikinci = sirali[1] if len(sirali) > 1 else (None, 0.0)

    # Hiç sinyal yoksa kampanya varsayılanı (serbest RAG) — düşük güven.
    if en_yuksek <= 0.0:
        return DomainDecision(
            domain="kampanya",
            confidence=0.40,
            scores=dict(puanlar),
            evidence=(),
            is_ambiguous=False,
            runner_up=None,
        )

    fark = en_yuksek - ikinci
    belirsiz = fark < AMBIGUITY_GAP and ikinci > 0.0
    # Güven: birincinin toplam puanı, tavan 1.0; belirsizlikte düşür.
    guven = min(en_yuksek, 1.0)
    if belirsiz:
        guven = min(guven, 0.50)

    return DomainDecision(
        domain=en_yuksek_alan,
        confidence=round(guven, 3),
        scores={k: round(v, 3) for k, v in puanlar.items()},
        evidence=tuple(kanitlar.get(en_yuksek_alan, ())),
        is_ambiguous=belirsiz,
        runner_up=ikinci_alan if belirsiz else None,
    )


def resolve_source_domain(
    katlanmis: str,
    *,
    intent: str,
    rate_type: str | None,
    axis_filters: dict[str, tuple[str, ...]],
) -> str:
    """Geriye dönük sarmalayıcı — yalnızca alan dizesini döndürür."""
    return score_domains(
        katlanmis,
        intent=intent,
        rate_type=rate_type,
        axis_filters=axis_filters,
    ).domain


__all__ = [
    "AMBIGUITY_GAP",
    "LOW_CONFIDENCE",
    "DomainDecision",
    "DomainScore",
    "resolve_source_domain",
    "score_domains",
]
