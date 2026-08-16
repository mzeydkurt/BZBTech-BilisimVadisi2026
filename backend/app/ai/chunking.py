"""Uzun metinlerin model bağlamına sığacak parçalara bölünmesi.

⚠️ NEDEN GEREKLİ: Dünya Katılım ve T.O.M. Bank sayfalarında gövde 1.500 kelimeyi
aşıyor. Bağlam penceresini aşan bir istem sessizce KIRPILIR — model metnin
sonunu hiç görmez ve oradaki tarihi "bulunamadı" olarak döndürür. Hata mesajı
çıkmaz; yalnızca F1 düşer ve nedeni anlaşılmaz.

⚠️ BÖLÜM BAŞLIĞI HER PARÇAYA EKLENİR. "Kampanya Şartları" başlığı olmadan
gelen bir madde listesi, modelin hangi bağlamda okuduğunu bilmemesine yol açar;
hariç tutma listesindeki bir tutar kampanya ödülü sanılabilir.
"""

from __future__ import annotations

import re
from typing import Final

from app.ai.fields import MAX_PROMPT_CHARS

# Paragraf sınırı: bir ya da daha fazla boş satır.
PARAGRAF_AYRACI: Final[re.Pattern[str]] = re.compile(r"\n\s*\n")

# Paragraf tek başına sınırı aşarsa cümle sınırından bölünür.
CUMLE_AYRACI: Final[re.Pattern[str]] = re.compile(r"(?<=[.!?])\s+")


def _hard_split(text: str, limit: int) -> list[str]:
    """Hiçbir doğal sınır bulunamayan metni sabit uzunlukta keser.

    Son çare: tek bir dev paragraf ya da boşluksuz tablo dökümü. Bilgi
    kaybetmemek için kesilir, ATILMAZ.
    """
    return [text[i : i + limit] for i in range(0, len(text), limit)]


def _split_paragraph(paragraf: str, limit: int) -> list[str]:
    """Sınırı aşan tek bir paragrafı cümlelerine böler."""
    if len(paragraf) <= limit:
        return [paragraf]

    parcalar: list[str] = []
    birikim = ""
    for cumle in CUMLE_AYRACI.split(paragraf):
        if len(cumle) > limit:
            # Cümle bile sığmıyor: önce biriken yazılır, sonra sert kesim.
            if birikim:
                parcalar.append(birikim)
                birikim = ""
            parcalar.extend(_hard_split(cumle, limit))
            continue

        aday = f"{birikim} {cumle}".strip() if birikim else cumle
        if len(aday) <= limit:
            birikim = aday
        else:
            parcalar.append(birikim)
            birikim = cumle

    if birikim:
        parcalar.append(birikim)
    return parcalar


def _pack(bloklar: list[str], limit: int) -> list[str]:
    """Blokları sınırı aşmayacak şekilde parçalara doldurur."""
    parcalar: list[str] = []
    birikim = ""

    for blok in bloklar:
        temiz = blok.strip()
        if not temiz:
            continue

        for parca in _split_paragraph(temiz, limit):
            aday = f"{birikim}\n\n{parca}" if birikim else parca
            if len(aday) <= limit:
                birikim = aday
            else:
                if birikim:
                    parcalar.append(birikim)
                birikim = parca

    if birikim:
        parcalar.append(birikim)
    return parcalar


def chunk_for_llm(
    clean_text: str | None,
    segments: dict[str, str] | None = None,
    *,
    max_chars: int = MAX_PROMPT_CHARS,
) -> list[str]:
    """Metni modele gönderilebilecek parçalara böler.

    Kısa metinler BÖLÜNMEZ: tek parça hâlinde döner ve tek çağrı yapılır.
    Bölünen metinlerde her parça ayrı çağrıdır; sonuçlar birleştirilirken aynı
    alan için İLK DOLU değer kullanılır (bkz. KAPI A6).

    Args:
        clean_text: Temizlenmiş kampanya metni.
        segments: Bölüm başlığı → metin eşlemesi (SPRINT 2 segmenter çıktısı).
            ⚠️ Şu an tüm bankalarda üretilmiyor; verilmezse paragraf sınırına
            göre bölünür. Segmenter geldiğinde davranış kendiliğinden iyileşir.
        max_chars: Bir parçanın en fazla uzunluğu.

    Returns:
        En az bir parça; boş metinde boş liste.

    Raises:
        ValueError: `max_chars` pozitif değilse.
    """
    if max_chars <= 0:
        raise ValueError(f"max_chars pozitif olmalı: {max_chars}")

    metin = (clean_text or "").strip()
    if not metin:
        return []
    if len(metin) <= max_chars:
        return [metin]

    if segments:
        # ⚠️ Başlık parçanın İÇİNE yazılır: bağlam olmadan gelen madde listesi
        # yanlış alana eşlenir.
        bloklar = [f"[{baslik}]\n{icerik.strip()}" for baslik, icerik in segments.items() if icerik]
    else:
        bloklar = PARAGRAF_AYRACI.split(metin)

    parcalar = _pack(bloklar, max_chars)
    # Bölümler verildiği hâlde hepsi boşsa ham metne düşülür: sessizce boş
    # liste döndürmek, kampanyanın hiç işlenmemesi demek olurdu.
    return parcalar or _pack(PARAGRAF_AYRACI.split(metin), max_chars)
