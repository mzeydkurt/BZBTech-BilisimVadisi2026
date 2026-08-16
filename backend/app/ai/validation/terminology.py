"""Katman 6 — katılım bankacılığı terminoloji koruması.

⚠️ YALNIZCA BİZİM ÜRETTİĞİMİZ METİN DENETLENİR. Bankanın kendi sayfasında
"kredi" yazıyorsa bu bizim hatamız değildir ve CLAUDE.md'nin tek istisnası
gereği ham veri değiştirilmez. Uyarı, modelin ürettiği özet ya da
sınıflandırma çıktısında konvansiyonel terim belirdiğinde anlamlıdır.

⚠️ KAYNAKTA GEÇEN TERİM UYARI ÜRETMEZ. `check_terminology(metin, kaynak)`
çağrısında kaynak verilirse, orada da geçen terimler elenir; aksi hâlde
"kredi kartı" yazan her banka sayfası yüzlerce yanlış uyarı üretirdi.

Yasaklı terimler `glossary` tablosundan (`is_forbidden_conventional=True`)
okunur; kod içine gömülmez ki sözlük genişledikçe davranış kendiliğinden
güncellensin.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.normalization.text import ascii_fold_tr, lower_tr
from app.db.models import GlossaryTerm

# Sözlük okunamazsa kullanılan asgari liste (şartname §4).
FALLBACK_FORBIDDEN: Final[tuple[str, ...]] = (
    "faiz",
    "faiz oranı",
    "kredi",
    "kredi faizi",
    "mevduat",
    "vadeli mevduat",
    "interest",
    "loan",
    "deposit",
)

# ⚠️ "kredi kartı" YASAK DEĞİLDİR: ürünün resmî adı budur ve bankalar da
# böyle yazar. "kredi" kökünü ararken bu ifadeyi elemezsek her kart
# kampanyası yanlış uyarı üretir.
ALLOWED_PHRASES: Final[tuple[str, ...]] = (
    "kredi kartı",
    "kredi karti",
    "kredi kartları",
    "kredi kartlari",
)


@dataclass(frozen=True)
class TerminologyWarning:
    """Üretilen metinde bulunan konvansiyonel terim."""

    term: str
    position: int
    suggestion: str | None = None


def load_forbidden_terms(session: Session) -> dict[str, str | None]:
    """Sözlükten yasaklı terimleri okur.

    Args:
        session: Veritabanı oturumu.

    Returns:
        Terim → önerilen katılım karşılığı.
    """
    kayitlar = session.scalars(
        select(GlossaryTerm).where(GlossaryTerm.is_forbidden_conventional.is_(True))
    ).all()
    if not kayitlar:
        return dict.fromkeys(FALLBACK_FORBIDDEN)

    terimler: dict[str, str | None] = {}
    for kayit in kayitlar:
        terimler[kayit.term] = kayit.conventional_equivalent
        for takma in kayit.aliases or []:
            terimler.setdefault(takma, kayit.conventional_equivalent)
    return terimler


def _mask_allowed(folded: str) -> str:
    """İzinli ifadeleri maskeler ki içlerindeki kök terim eşleşmesin."""
    for ifade in ALLOWED_PHRASES:
        folded = folded.replace(ifade, "#" * len(ifade))
    return folded


def check_terminology(
    text: str | None,
    forbidden: dict[str, str | None],
    *,
    source_text: str | None = None,
) -> list[TerminologyWarning]:
    """Üretilen metinde konvansiyonel terim arar.

    Args:
        text: BİZİM ürettiğimiz metin (özet, sınıflandırma çıktısı).
        forbidden: `load_forbidden_terms()` çıktısı.
        source_text: Kaynak metin; verilirse orada da geçen terimler elenir.

    Returns:
        Bulunan uyarılar; temizse boş liste.
    """
    if not text:
        return []

    hedef = _mask_allowed(ascii_fold_tr(lower_tr(text)))
    kaynak = _mask_allowed(ascii_fold_tr(lower_tr(source_text or "")))

    uyarilar: list[TerminologyWarning] = []
    for terim, karsilik in forbidden.items():
        katlanmis = ascii_fold_tr(lower_tr(terim))
        if not katlanmis:
            continue
        # ⚠️ KELİME SINIRI ŞART. Sınırsız arama "kredi" için "kredibilite"yi,
        # "loan" için "sloan"ı yakalar ve uyarıyı gürültüye boğar.
        kalip = re.compile(rf"\b{re.escape(katlanmis)}\b")

        eslesme = kalip.search(hedef)
        if eslesme is None:
            continue
        # Kaynakta da geçiyorsa bankanın ifadesidir, bizim hatamız değil.
        if kaynak and kalip.search(kaynak):
            continue
        uyarilar.append(TerminologyWarning(terim, eslesme.start(), karsilik))

    return uyarilar
