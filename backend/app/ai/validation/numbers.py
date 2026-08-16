"""Katman 4 — sayısal doğrulama.

Üretilen her rakam, TÜRKÇE YAZIM VARYANTLARIYLA kaynakta aranır. Kanıt
doğrulaması (katman 3) cümlenin kaynakta olduğunu gösterir ama o cümledeki
sayının doğru okunduğunu göstermez: model doğru cümleyi alıntılayıp
içindeki `%2,05`i `2.50` diye normalize edebilir. Bu katman onu yakalar.

⚠️ TÜRKÇE SAYI BİÇİMİ. `5.000` beş bindir, beş değil; `5,000` beştir.
Varyantlar bu kurala göre üretilir (bkz. SPRINT 1 normalizasyon kütüphanesi).

⚠️ SINIFLANDIRMA ALANLARI MUAFTIR. `has_no_fee=true` ya da
`reward_type=nakit_iade` bir sayı değildir; kaynakta "true" aramak her
doğru çıkarımı reddederdi.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Final

from app.ai.validation.evidence import normalize_for_match

# Sayısal doğrulamaya tabi birimler. Diğerleri (enum, bool, date) muaftır:
# tarih zaten kendi kuralıyla ayrıştırıldı, enum ve bool sayı değildir.
NUMERIC_UNITS: Final[frozenset[str]] = frozenset({"pct", "TRY", "month", "count"})

# "5 bin" gibi yazımlar için çarpanlar.
_SCALE_WORDS: Final[dict[str, int]] = {"bin": 1_000, "milyon": 1_000_000}

_NON_DIGIT_RE: Final[re.Pattern[str]] = re.compile(r"[^\d]")


def _tam_sayi_varyantlari(tam: int) -> set[str]:
    """Tam sayının Türkçe yazım biçimlerini üretir.

    5000 için: `5000` · `5.000` · `5 000` · `5 bin`
    """
    varyant = {str(tam), f"{tam:,}".replace(",", "."), f"{tam:,}".replace(",", " ")}
    for kelime, carpan in _SCALE_WORDS.items():
        if tam >= carpan and tam % carpan == 0:
            varyant.add(f"{tam // carpan} {kelime}")
    return varyant


def number_variants(value: Decimal) -> set[str]:
    """Bir sayının kaynakta aranacak yazım biçimlerini döndürür.

    Args:
        value: Normalize edilmiş değer.

    Returns:
        Aranacak dizeler (küçük harf, normalize edilmiş).
    """
    varyantlar: set[str] = set()
    tam = int(value)

    if value == tam:
        varyantlar |= _tam_sayi_varyantlari(tam)
    else:
        # Ondalıklı: hem nokta hem virgül ayraçlı yazım aranır.
        duz = format(value.normalize(), "f").rstrip("0").rstrip(".")
        varyantlar.add(duz)
        varyantlar.add(duz.replace(".", ","))
        # İki basamağa tamamlanmış hâli de geçerlidir: "2,5" ile "2,50".
        iki_basamak = f"{value:.2f}"
        varyantlar.add(iki_basamak)
        varyantlar.add(iki_basamak.replace(".", ","))

    return {normalize_for_match(v) for v in varyantlar if v}


def validate_number_in_source(
    value: str | Decimal | None, unit: str | None, clean_text: str
) -> bool:
    """Değerin kaynakta geçip geçmediğini doğrular.

    Args:
        value: Çıkarımın normalize edilmiş değeri.
        unit: Alanın birimi.
        clean_text: Kaynak metin.

    Returns:
        Sayı kaynakta bulunduysa ya da alan muafsa True.
    """
    if unit not in NUMERIC_UNITS:
        # ⚠️ Sınıflandırma ve tarih alanları muaf.
        return True
    if value is None or not clean_text:
        return False

    try:
        sayi = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return False

    # ⚠️ SIFIR MUAFTIR. "vade farksız" → profit_rate_pct=0 TÜRETİLMİŞ bir
    # değerdir; kaynakta "0" rakamı geçmez ve geçmesi de beklenmez.
    if sayi == 0:
        return True

    kaynak = normalize_for_match(clean_text)
    # Rakamları da ayrıca çıkar: "5.000" ile "5000" aynı sayıdır ama
    # normalize edilmiş metinde farklı dizelerdir.
    kaynak_rakamlari = _NON_DIGIT_RE.sub(" ", kaynak)

    for varyant in number_variants(sayi):
        if varyant in kaynak:
            return True
        sadece_rakam = _NON_DIGIT_RE.sub("", varyant)
        if sadece_rakam and f" {sadece_rakam} " in f" {kaynak_rakamlari} ":
            return True

    return False


# Metinden sayı yakalayan kalıp: `%2,05` · `5.000` · `120` · `2.05`
_NUMBER_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"\d+(?:[.,]\d+)*")

# ⚠️ TARİHLER SAYI SAYILMAZ ve taramadan ÖNCE maskelenir.
#
# `31.12.2026` üzerinde sayı kuralı çalıştırılırsa iki nokta binlik ayracı
# sanılır ve token `31122026` diye okunur. Bu sayı kaynakta hiçbir zaman
# bulunmaz; sonuç olarak KAYNAKLA BİREBİR AYNI bir özet bile "uydurma sayı
# içeriyor" diye reddedilirdi (ölçüldü).
#
# Tarihin kendisi zaten `date_tr` ile ayrıştırılıyor ve `start_date` /
# `end_date` alanlarında kendi doğrulamasından geçiyor; burada ikinci kez
# denetlenmesi gerekmez.
_DATE_TOKEN_RE: Final[re.Pattern[str]] = re.compile(
    r"\b\d{1,2}\s*[./-]\s*\d{1,2}\s*[./-]\s*\d{2,4}\b"
)


def numbers_in_text(text: str | None) -> list[Decimal]:
    """Metindeki tüm sayıları Türkçe biçimi çözerek döndürür.

    `5.000` beş bin, `2,05` iki virgül sıfır beş olarak okunur.

    Args:
        text: Taranacak metin.

    Returns:
        Bulunan sayılar (yinelenenler ayıklanmış, ilk görülme sırasında).
    """
    if not text:
        return []

    # Tarihler taramadan önce maskelenir (bkz. `_DATE_TOKEN_RE`).
    maskeli = _DATE_TOKEN_RE.sub(" ", text)

    bulunan: list[Decimal] = []
    gorulen: set[Decimal] = set()

    for eslesme in _NUMBER_TOKEN_RE.finditer(maskeli):
        ham = eslesme.group()
        # Türkçe biçim: nokta binlik, virgül ondalık ayracıdır.
        if "," in ham:
            duz = ham.replace(".", "").replace(",", ".")
        elif ham.count(".") == 1 and len(ham.split(".")[1]) != 3:
            # Tek nokta ve ondalık kısmı 3 basamak DEĞİLSE ondalıktır:
            # `2.05` iki virgül sıfır beş, `5.000` ise beş bindir.
            duz = ham
        else:
            duz = ham.replace(".", "")

        try:
            sayi = Decimal(duz)
        except InvalidOperation:
            continue
        if sayi not in gorulen:
            gorulen.add(sayi)
            bulunan.append(sayi)

    return bulunan


def unsupported_numbers(text: str | None, clean_text: str) -> list[Decimal]:
    """Üretilen metinde geçip KAYNAKTA GEÇMEYEN sayıları döndürür.

    Özet doğrulamasının çekirdeği (KAPI A8): kaynağın kısaltılmış hâli olan
    bir özet, kaynakta bulunmayan bir sayı içeremez. İçeriyorsa bu bir
    halüsinasyondur ve özet reddedilir.

    Args:
        text: Modelin ürettiği metin (özet).
        clean_text: Kaynak metin.

    Returns:
        Kaynakta karşılığı bulunamayan sayılar; temizse boş liste.
    """
    return [
        sayi
        for sayi in numbers_in_text(text)
        if not validate_number_in_source(sayi, "TRY", clean_text)
    ]
