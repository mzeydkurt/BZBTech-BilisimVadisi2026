"""Katman 3 — kanıt (evidence) doğrulaması.

⚠️ PROJENİN EN SAVUNULABİLİR TEKNİK FARKI. Modelin ürettiği her değer bir
kanıt cümlesiyle gelir; bu cümle KAYNAK METİNDE FİİLEN GEÇMİYORSA değer
reddedilir. Sayısal halüsinasyonun büyük kısmı bu tek kuralla kesilir:
model bir oran uydurduğunda, onu destekleyen cümleyi de uydurmak zorunda
kalır ve uydurulmuş cümle kaynakta bulunmaz.

KADEMELİ EŞLEŞME — katı olmakla kullanışlı olmak arasındaki denge:

    1. Birebir alt dize                    → kesin
    2. Normalize edilmiş eşleşme           → boşluk/tire/tırnak farkları
    3. %90+ karakter benzerliği            → tek harf düşmesi, ek farkı
    4. Hiçbiri tutmuyorsa                  → REDDEDİLİR

⚠️ 3. kademe olmadan guard AŞIRI KATI olur. Model metni doğru kopyaladığı
hâlde satır sonunu boşluğa çevirdiği ya da bir tireyi kısa çizgiye
dönüştürdüğü için doğru bir çıkarım reddedilirdi; bu, halüsinasyonu değil
kullanılabilirliği ölçmek olurdu.

⚠️ 3. kademe İKİ SIÇRAMAYI birden affetmez. Eşik %90'da tutulur; daha
düşük bir eşikte "kâr payı %2,05" ile "kâr payı %9,95" birbirine benzer
çıkar ve guard sayısal halüsinasyonu kaçırır.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Final

# 3. kademede kabul edilen en düşük benzerlik.
SIMILARITY_THRESHOLD: Final[float] = 0.90

# Bu uzunluğun altındaki kanıt doğrulanmaz ve REDDEDİLİR: birkaç karakterlik
# bir dize metnin her yerinde eşleşir ve doğrulamayı anlamsızlaştırır.
MIN_EVIDENCE_CHARS: Final[int] = 8

# Benzerlik araması için kaynakta taranacak pencere, kanıt uzunluğunun katı.
# Tüm metinde kayan pencere aramak 500 kampanyada gereksiz pahalıdır.
_WINDOW_FACTOR: Final[int] = 2

_WHITESPACE_RE: Final[re.Pattern[str]] = re.compile(r"\s+")

# Tırnak ve tire benzeri karakterler tek biçime indirgenir.
_QUOTE_MAP: Final[dict[int, str]] = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "“": '"',
        "”": '"',
        "«": '"',
        "»": '"',
        "–": "-",
        "—": "-",
        "−": "-",
    }
)

# Sıfır genişlikli karakterler (Türkiye Finans sayfalarında kelime İÇİNDE var).
_ZERO_WIDTH_RE: Final[re.Pattern[str]] = re.compile(r"[​‌‍﻿]")


def normalize_for_match(value: str) -> str:
    """Metni kanıt karşılaştırmasına hazırlar.

    Sıfır genişlikli karakterleri siler, NFKC uygular, tırnak ve tireleri
    tek biçime indirger, boşlukları tek boşluğa çeker ve küçük harfe çevirir.

    Args:
        value: Ham metin.

    Returns:
        Karşılaştırmaya hazır metin.
    """
    temiz = _ZERO_WIDTH_RE.sub("", value)
    temiz = unicodedata.normalize("NFKC", temiz)
    temiz = temiz.translate(_QUOTE_MAP)
    return _WHITESPACE_RE.sub(" ", temiz).strip().casefold()


def _best_window(hedef: str, kaynak: str) -> float:
    """Kaynakta hedefe en çok benzeyen pencerenin benzerlik oranı.

    Kayan pencere, hedef uzunluğunun katı kadar genişlikte gezdirilir.
    Adım, hedefin dörtte biridir: her karakterde kaydırmak 500 kampanyada
    kabul edilemez yavaşlıkta, tam pencere boyu kaydırmak ise sınırdaki
    eşleşmeleri kaçırır.

    Args:
        hedef: Aranan kanıt (normalize edilmiş).
        kaynak: Kaynak metin (normalize edilmiş).

    Returns:
        0.0 - 1.0 arası en yüksek benzerlik.
    """
    pencere = len(hedef) * _WINDOW_FACTOR
    if len(kaynak) <= pencere:
        return SequenceMatcher(None, hedef, kaynak).ratio()

    adim = max(1, len(hedef) // 4)
    en_iyi = 0.0
    for bas in range(0, len(kaynak) - pencere + adim, adim):
        oran = SequenceMatcher(None, hedef, kaynak[bas : bas + pencere]).ratio()
        if oran > en_iyi:
            en_iyi = oran
            if en_iyi >= SIMILARITY_THRESHOLD:
                break
    return en_iyi


def validate_evidence(evidence: str | None, clean_text: str) -> tuple[bool, int, int]:
    """Kanıtın kaynak metinde geçip geçmediğini doğrular.

    Args:
        evidence: Çıkarımın kanıt metni.
        clean_text: Kaynak metin.

    Returns:
        `(geçerli, başlangıç, bitiş)`. Bulunamazsa `(False, -1, -1)`.
        Yaklaşık eşleşmede (3. kademe) ofset `(-1, -1)` döner: benzer ama
        birebir olmayan bir aralığı kaynakta işaretlemek, arayüzde yanlış
        yeri vurgulamak olurdu.
    """
    ham = (evidence or "").strip()
    if len(ham) < MIN_EVIDENCE_CHARS or not clean_text:
        return False, -1, -1

    # 1. Birebir.
    bas = clean_text.find(ham)
    if bas != -1:
        return True, bas, bas + len(ham)

    # 2. Normalize edilmiş.
    hedef = normalize_for_match(ham)
    kaynak = normalize_for_match(clean_text)
    if not hedef:
        return False, -1, -1
    if hedef in kaynak:
        return True, -1, -1

    # 3. Karakter benzerliği.
    if _best_window(hedef, kaynak) >= SIMILARITY_THRESHOLD:
        return True, -1, -1

    # 4. Reddedilir.
    return False, -1, -1
