"""Sohbet sonuçlarında alaka süzgeci — dolgu / yan konu kampanya eleme."""

from __future__ import annotations

import re
from typing import Final

from app.core.normalization.text import ascii_fold_tr, lower_tr
from app.retrieval.query import QueryPlan
from app.retrieval.search import SearchHit

# Sektör → başlıkta aranan anahtarlar (marka etiketinden gelen sahte eşleşmeyi ezer).
_SEKTOR_BASLIK: Final[dict[str, tuple[str, ...]]] = {
    "egitim_kitap": ("egitim", "okul", "universite", "ogrenci", "kurs", "kitap", "kirtasiye"),
    "market_gida": ("market", "gida", "migros", "a101", "bim", "sok"),
    "seyahat_konaklama": ("seyahat", "otel", "ucak", "tatil", "tur"),
    "akaryakit": ("akaryakit", "benzin", "motorin", "petrol"),
    "eticaret_pazaryeri": ("eticaret", "pazaryeri", "trendyol", "hepsiburada", "n11"),
}

_ATIF_TEMIZ: Final[re.Pattern[str]] = re.compile(r"\s*\[(?:\d+|N)\]", re.IGNORECASE)


def _fold(text: str) -> str:
    return ascii_fold_tr(lower_tr(text or ""))


def _banka_alias_tokenlari() -> frozenset[str]:
    """Banka adı parçaları başlık alaka anahtarı olmasın (sert bank_code süzgecini boşaltır)."""
    from app.retrieval.query import BANK_ALIASES

    tokenlar: set[str] = set()
    for kod, takma in BANK_ALIASES.items():
        tokenlar.add(_fold(kod.replace("_", " ")))
        for parca in kod.split("_"):
            if len(parca) >= 4:
                tokenlar.add(_fold(parca))
        for ad in takma:
            folded = _fold(ad)
            tokenlar.add(folded)
            for parca in folded.split():
                if len(parca) >= 4:
                    tokenlar.add(parca)
    return frozenset(tokenlar)


def _baslik_anahtarlari(plan: QueryPlan) -> tuple[str, ...]:
    anahtarlar: list[str] = []
    banka_token = _banka_alias_tokenlari()
    for sektor in plan.axis_filters.get("sector", ()):
        anahtarlar.extend(_SEKTOR_BASLIK.get(sektor, ()))
    for terim in plan.free_terms:
        if terim in {"kampanya", "kampanyasi", "kampanyalar", "bahseder", "misin", "bana", "nedir"}:
            continue
        if terim in banka_token or _fold(terim) in banka_token:
            continue
        if len(terim) >= 4:
            anahtarlar.append(terim)
    # Tekrarları koru sırayla.
    gorulen: set[str] = set()
    sonuc: list[str] = []
    for a in anahtarlar:
        if a not in gorulen:
            gorulen.add(a)
            sonuc.append(a)
    return tuple(sonuc)


def filter_relevant_hits(
    hits: tuple[SearchHit, ...],
    plan: QueryPlan,
    *,
    max_n: int = 3,
) -> tuple[SearchHit, ...]:
    """Alakasız dolgu sonuçlarını düşürür; 1 alakalıysa 1, 2 ise 2 döner.

    Marka→sektör sözlüğü (ör. idefix→egitim_kitap) yüzünden süzgeçten geçen
    ama başlığı soruyla ilgisiz kampanyalar elenir: başlıkta sektör anahtarı
    olanlar varsa yalnızca onlar tutulur.
    """
    if not hits:
        return ()

    anahtarlar = _baslik_anahtarlari(plan)
    if not anahtarlar:
        return hits[:max_n]

    puanli: list[tuple[int, float, SearchHit]] = []
    for vurus in hits:
        metin = _fold(f"{vurus.doc.title} {vurus.doc.summary or ''}")
        baslik_eslesme = sum(1 for a in anahtarlar if a in metin)
        puanli.append((baslik_eslesme, vurus.score, vurus))

    # Anahtar varken yalnızca başlık/özette geçenler kalsın; hiçbiri
    # geçmiyorsa dolgu (ör. idefix→egitim_kitap) — boş dön, alakasız gösterme.
    if any(b > 0 for b, _, _ in puanli):
        puanli = [p for p in puanli if p[0] > 0]
    else:
        return ()

    puanli.sort(key=lambda x: (-x[0], -x[1], x[2].doc.campaign_id))
    return tuple(v for _, _, v in puanli[:max_n])


def strip_citation_markers(text: str) -> str:
    """Modelin [N] atıflarını ve sızan DB id ifadelerini kullanıcı metninden temizler."""
    temiz = _ATIF_TEMIZ.sub("", text or "")
    # "ürün id: 12", "kampanya #45", "(id=3)" gibi teknik kimlikler.
    temiz = re.sub(
        r"(?i)\b(?:ürün|kampanya|product|campaign)\s*(?:id|#)\s*[:#]?\s*\d+\b",
        "",
        temiz,
    )
    temiz = re.sub(r"(?i)\(?\bid\s*[=:]\s*\d+\)?", "", temiz)
    return re.sub(r" {2,}", " ", temiz).strip()


def is_follow_up_query(raw: str) -> bool:
    """Kısa devam sorusu mu? (bağlamı önceki turdan devral)."""
    folded = _fold(raw)
    belirtecler = [w for w in re.findall(r"[a-z0-9]+", folded) if w]
    if len(belirtecler) <= 5 and any(
        k in folded
        for k in (
            "peki",
            "onun",
            "bunun",
            "bundan",
            "ondan",
            "ozellik",
            "devam",
            "daha fazla",
            "anlat",
            "detay",
            "hangisi",
            "ne kadar",
            "ya o",
            "ya bu",
        )
    ):
        return True
    return len(belirtecler) <= 3 and bool(belirtecler)


__all__ = [
    "filter_relevant_hits",
    "is_follow_up_query",
    "strip_citation_markers",
]
