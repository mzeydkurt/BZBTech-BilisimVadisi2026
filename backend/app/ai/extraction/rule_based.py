"""Katman 2 — kural tabanlı çıkarım.

Şartname 5.6'daki `%2,05` = `% 2.05` = `2.05 %` dönüşümü regex ile %100
doğrulukla çözülür. Bunu modele sormak yavaş, pahalı ve hatalıdır. LLM
(Katman 3) YALNIZCA buranın çözemediği alanlar için çalışır.

⚠️ HER BULGUNUN KARAKTER ARALIĞI ZORUNLUDUR ve şu değişmez kural geçerlidir:

    clean_text[evidence_char_start:evidence_char_end] == evidence_text

Kanıt, kaynağın HAM DİLİMİDİR; normalize edilmiş bir kopya değildir. Aksi
hâlde arayüzde "bu değer nereden geldi?" sorusuna verilen yanıt metnin
yanlış yerini gösterir ve açıklanabilirlik iddiası çöker.

⚠️ SPRINT 1'İN NORMALİZASYON KÜTÜPHANESİ KULLANILIR, yeniden yazılmaz.
Türkçe sayı biçimi (`5.000` = beş bin, `5,000` = beş) orada çözülmüş ve
%96 test kapsamıyla doğrulanmış durumda.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from app.ai.extraction import patterns as p
from app.ai.fields import unit_of
from app.core.normalization.date_tr import parse_date_range_tr
from app.core.normalization.money import parse_money
from app.core.normalization.rate import parse_rate
from app.core.normalization.term import parse_installment_count, parse_term_months

# Kural tabanlı çıkarımın taban güveni. Tablo katmanı 1.00, LLM 0.70.
RULE_CONFIDENCE: Final[Decimal] = Decimal("0.90")
# Aynı alan için birden çok eşleşme varsa güven düşer; kararı merger verir.
AMBIGUOUS_CONFIDENCE: Final[Decimal] = Decimal("0.60")


@dataclass(frozen=True)
class ExtractedField:
    """Tek bir alanın çıkarım sonucu, kanıtıyla birlikte."""

    field_name: str
    value_raw: str
    value_normalized: str
    unit: str
    evidence_text: str
    evidence_char_start: int
    evidence_char_end: int
    confidence: Decimal
    method: str = "rule"
    validation_note: str | None = None


def _field(
    name: str,
    value: object,
    metin: str,
    bas: int,
    son: int,
    *,
    confidence: Decimal = RULE_CONFIDENCE,
    note: str | None = None,
) -> ExtractedField:
    """Ham dilimden `ExtractedField` üretir.

    ⚠️ `evidence_text` DAİMA `metin[bas:son]` dilimidir. Elle yazılmış ya da
    normalize edilmiş bir kanıt, ofset doğrulamasını (KAPI A4 geçiş koşulu)
    sessizce bozar.
    """
    dilim = metin[bas:son]
    return ExtractedField(
        field_name=name,
        value_raw=dilim,
        value_normalized=str(value),
        unit=unit_of(name),
        evidence_text=dilim,
        evidence_char_start=bas,
        evidence_char_end=son,
        confidence=confidence,
        validation_note=note,
    )


def _yakinda(metin: str, bas: int, son: int, *, kelimeler: tuple[str, ...]) -> bool:
    """Eşleşmenin çevresinde beklenen kavram geçiyor mu?

    ⚠️ YAKINLIK KURALI. Sayının hangi kavrama ait olduğu komşu kelimeyle
    doğrulanmazsa, metindeki herhangi bir sayı herhangi bir alana atanır.
    """
    pencere = metin[max(0, bas - p.PROXIMITY_CHARS) : son + p.PROXIMITY_CHARS].casefold()
    return any(kelime in pencere for kelime in kelimeler)


def _rate_fields(metin: str) -> list[ExtractedField]:
    """Kâr payı oranını çıkarır."""
    bulunan: list[ExtractedField] = []

    for eslesme in p.PROFIT_RATE.finditer(metin):
        oran = parse_rate(eslesme.group())
        if oran is not None:
            bulunan.append(_field("profit_rate_pct", oran, metin, eslesme.start(), eslesme.end()))

    # ⚠️ "vade farksız" oranın SIFIR olduğunu söyler; bilinmeyen değildir.
    if not bulunan:
        sifir = p.ZERO_RATE.search(metin)
        if sifir:
            bulunan.append(
                _field(
                    "profit_rate_pct",
                    0,
                    metin,
                    sifir.start(),
                    sifir.end(),
                    note="vade farksız → oran 0",
                )
            )

    return _coklu_isaretle(bulunan)


def _coklu_isaretle(bulunan: list[ExtractedField]) -> list[ExtractedField]:
    """Aynı alanda birden çok eşleşme varsa güveni düşürür.

    ⚠️ Eşleşmeler SİLİNMEZ, hepsi kaydedilir: hangisinin doğru olduğuna
    merger (KAPI A7) karar verecek. Burada susmak, bilgiyi kaybetmek olurdu.
    """
    if len(bulunan) <= 1:
        return bulunan
    return [
        ExtractedField(
            **{**alan.__dict__, "confidence": AMBIGUOUS_CONFIDENCE},
        )
        if alan.validation_note is None
        else alan
        for alan in bulunan
    ]


def _installment(metin: str) -> list[ExtractedField]:
    """Taksit sayısını çıkarır.

    ⚠️ "4 aya varan TAKSİT" → taksit 4, VADE DEĞİL.
    """
    eslesme = p.INSTALLMENT.search(metin)
    if eslesme is None:
        return []
    sayi = parse_installment_count(eslesme.group())
    if sayi is None:
        return []
    return [_field("installment_count", sayi, metin, eslesme.start(), eslesme.end())]


def _term(metin: str) -> list[ExtractedField]:
    """Vadeyi çıkarır.

    ⚠️ İçinde "taksit" geçen eşleşme vade sayılmaz; o taksit sayısıdır.
    """
    bulunan: list[ExtractedField] = []

    for eslesme in p.TERM.finditer(metin):
        pencere = metin[max(0, eslesme.start() - 15) : eslesme.end() + 15].casefold()
        if "taksit" in pencere:
            continue

        alt, ust = parse_term_months(eslesme.group())
        if alt is not None:
            bulunan.append(_field("term_months_min", alt, metin, eslesme.start(), eslesme.end()))
        if ust is not None:
            bulunan.append(_field("term_months_max", ust, metin, eslesme.start(), eslesme.end()))
        if bulunan:
            break  # İlk geçerli vade ifadesi esas alınır.

    return bulunan


def _amounts(metin: str) -> list[ExtractedField]:
    """Harcama eşiği, ödül tutarı ve finansman tutarını çıkarır."""
    bulunan: list[ExtractedField] = []

    esik = p.MIN_SPEND.search(metin)
    if esik is not None:
        tutar, _ = parse_money(esik.group())
        if tutar is not None:
            bulunan.append(_field("min_spend_try", tutar, metin, esik.start(), esik.end()))

    # ⚠️ Kademeli ödülde EN YÜKSEK ödül alınır (kılavuz kuralı): "5.000→250,
    # 10.000→500" metninde kampanyanın vaat ettiği üst değer 500'dür.
    en_yuksek: tuple[Decimal, int, int] | None = None
    for eslesme in p.REWARD_AMOUNT.finditer(metin):
        tutar, _ = parse_money(eslesme.group())
        if tutar is None:
            continue
        if en_yuksek is None or tutar > en_yuksek[0]:
            en_yuksek = (tutar, eslesme.start(), eslesme.end())
    if en_yuksek is not None:
        bulunan.append(_field("reward_amount_try", en_yuksek[0], metin, en_yuksek[1], en_yuksek[2]))

    finansman = p.FINANCING_AMOUNT.search(metin)
    if finansman is not None:
        tutar, _ = parse_money(finansman.group())
        if tutar is not None:
            bulunan.append(
                _field("financing_amount_max", tutar, metin, finansman.start(), finansman.end())
            )

    return bulunan


def _percent_rewards(metin: str) -> list[ExtractedField]:
    """Yüzde iade ve indirim oranlarını çıkarır."""
    bulunan: list[ExtractedField] = []

    for alan, kalip in (("cashback_pct", p.CASHBACK_PCT), ("discount_pct", p.DISCOUNT_PCT)):
        eslesme = kalip.search(metin)
        if eslesme is None:
            continue
        oran = parse_rate(eslesme.group())
        if oran is not None:
            bulunan.append(_field(alan, oran, metin, eslesme.start(), eslesme.end()))

    return bulunan


def _fees(metin: str) -> list[ExtractedField]:
    """Tahsis ücreti, dosya masrafı ve masrafsızlık bilgisini çıkarır."""
    bulunan: list[ExtractedField] = []

    tahsis = p.ALLOCATION_FEE.search(metin)
    if tahsis is not None:
        oran = parse_rate(tahsis.group())
        if oran is not None:
            bulunan.append(_field("allocation_fee_pct", oran, metin, tahsis.start(), tahsis.end()))

    masraf = p.FILE_FEE.search(metin)
    if masraf is not None:
        tutar, _ = parse_money(masraf.group())
        if tutar is not None:
            bulunan.append(_field("file_fee_try", tutar, metin, masraf.start(), masraf.end()))

    # ⚠️ "masrafsız" hem `has_no_fee=true` hem `file_fee_try=0` demektir
    # (etiketleme kılavuzu kuralı); ikisi ayrı ayrı çıkarılır.
    muaf = p.NO_FEE.search(metin)
    if muaf is not None:
        bulunan.append(_field("has_no_fee", "true", metin, muaf.start(), muaf.end()))
        if masraf is None:
            bulunan.append(_field("file_fee_try", 0, metin, muaf.start(), muaf.end()))

    return bulunan


def _dates(metin: str) -> list[ExtractedField]:
    """Başlangıç ve bitiş tarihlerini çıkarır.

    ⚠️ AYRIŞTIRMA `parse_date_range_tr`E DEVREDİLİR — 7 tarih biçimi orada
    çözülmüş durumda. Buradaki kalıp yalnızca KANIT ARALIĞINI bulur;
    scraper'da olduğu gibi burada da tarih regex'i yeniden yazılmaz.

    ⚠️ Tarih bulunamazsa alan ÇIKARILMAZ. Türkiye Finans'ın tüm kampanyaları
    böyle olacak; yokluk "süresi dolmuş" DEĞİLDİR.
    """
    eslesme = p.DATE_SPAN.search(metin)
    if eslesme is None:
        return []

    baslangic, bitis, kesinlik = parse_date_range_tr(eslesme.group())
    if kesinlik == "unknown":
        return []

    bulunan: list[ExtractedField] = []
    if baslangic is not None:
        bulunan.append(
            _field("start_date", baslangic.isoformat(), metin, eslesme.start(), eslesme.end())
        )
    if bitis is not None:
        bulunan.append(_field("end_date", bitis.isoformat(), metin, eslesme.start(), eslesme.end()))
    return bulunan


def _reward_type(metin: str) -> list[ExtractedField]:
    """Ödülün türünü belirler (kontrollü sözlükten)."""
    for tur, kalip in p.REWARD_TYPE_MARKERS:
        eslesme = kalip.search(metin)
        if eslesme is not None:
            return [_field("reward_type", tur, metin, eslesme.start(), eslesme.end())]
    return []


def extract_rule_based(clean_text: str | None) -> list[ExtractedField]:
    """Metinden kural tabanlı olarak çıkarılabilen tüm alanları toplar.

    Args:
        clean_text: Kampanyanın temizlenmiş metni.

    Returns:
        Bulunan alanlar; hiçbiri bulunamazsa boş liste.

        ⚠️ BULUNAMAYAN ALAN İÇİN KAYIT ÜRETİLMEZ. "Bilgi yok" durumu
        kaydın YOKLUĞUYLA temsil edilir; sıfır ya da boş dize yazmak
        halüsinasyonun ta kendisidir.
    """
    metin = clean_text or ""
    if not metin.strip():
        return []

    bulunan: list[ExtractedField] = []
    for cikarici in (
        _rate_fields,
        _installment,
        _term,
        _amounts,
        _percent_rewards,
        _fees,
        _dates,
        _reward_type,
    ):
        bulunan.extend(cikarici(metin))

    return bulunan


def solved_fields(bulunan: list[ExtractedField]) -> set[str]:
    """Kuralın çözdüğü alan adları.

    KAPI A6'da `already_found` filtresi bunu kullanır: çözülen alanlar
    LLM'e HİÇ SORULMAZ — hem hız hem doğruluk kazancı.
    """
    return {alan.field_name for alan in bulunan}
