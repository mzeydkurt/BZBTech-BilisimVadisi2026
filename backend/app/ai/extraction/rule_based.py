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

import json
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from app.ai.extraction import patterns as p
from app.ai.fields import unit_of
from app.core.normalization.date_tr import parse_date_range_tr
from app.core.normalization.money import parse_money
from app.core.normalization.rate import parse_rate
from app.core.normalization.term import parse_installment_count, parse_term_months
from app.processing.dates import find_campaign_period_detailed

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
    # ⚠️ Kural ve tablo katmanında DAİMA doludur. LLM katmanında (KAPI A6)
    # None olabilir: model, kaynakta bulunmayan bir kanıt üretmiş demektir ve
    # ofset hesaplanamaz. Bu kayıt SİLİNMEZ — halüsinasyon guard'ı (KAPI A7)
    # onu reddedecek ve `rejected_reason` ile saklayacak; halüsinasyon oranı
    # ancak reddedilenler kayıtlıysa raporlanabilir.
    evidence_char_start: int | None
    evidence_char_end: int | None
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


def _oran_tuzak(metin: str, bas: int, son: int) -> bool:
    """Eşleşme indirim / iade / LTV ise kâr payı sayılmaz.

    Pencere `PROXIMITY_CHARS` ile aynı: sayı komşu kelimeyle bağlanır.
    Pencere içinde 'kâr payı' geçiyorsa tuzak yutulur — cümle gerçekten
    oranı anlatıyordur.
    """
    pencere = metin[max(0, bas - p.PROXIMITY_CHARS) : son + p.PROXIMITY_CHARS]
    if p.RATE_TRAP.search(pencere) is None:
        return False
    return not _yakinda(metin, bas, son, kelimeler=("kâr payı", "kar payi", "kâr payi"))


def _rate_fields(metin: str) -> list[ExtractedField]:
    """Kâr payı oranını çıkarır."""
    bulunan: list[ExtractedField] = []

    for eslesme in p.PROFIT_RATE.finditer(metin):
        if _oran_tuzak(metin, eslesme.start(), eslesme.end()):
            continue
        oran = parse_rate(eslesme.group())
        if oran is None:
            continue
        # LTV / teminat payı (tipik %70–90) kâr payı gibi yazılırdı.
        if oran >= 50 and not _yakinda(
            metin, eslesme.start(), eslesme.end(), kelimeler=("kâr payı", "kar payi", "kâr payi")
        ):
            continue
        bulunan.append(_field("profit_rate_pct", oran, metin, eslesme.start(), eslesme.end()))

    # ⚠️ İki FARKLI oran varsa hangisinin kâr payı olduğu belirsizdir.
    # İkisini de yazmak merger'ın birini seçmesine bırakır ve gold'da
    # 10 FP üretiyordu (7.5 vs 12.5). Tek değer 'kâr payı' kanıtlıysa o kalır.
    degerler = {alan.value_normalized for alan in bulunan}
    if len(degerler) > 1:
        kar_payili = [
            alan
            for alan in bulunan
            if "kâr payı" in alan.evidence_text.casefold()
            or "kar payi" in alan.evidence_text.casefold()
        ]
        kar_deger = {alan.value_normalized for alan in kar_payili}
        bulunan = kar_payili[:1] if len(kar_deger) == 1 else []

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


def _ilk_odul(metin: str, kalip: re.Pattern[str]) -> tuple[Decimal, int, int] | None:
    """Metindeki İLK geçerli ödül tutarını, toplu üst sınırları eleyerek bulur.

    ⚠️ SEÇİM STRATEJİSİ ÖLÇÜLEREK BELİRLENDİ (50 kampanyalık gold set):

        A en yüksek (eski)                 reward 19/25 · loyalty 13/14
        B ilk                              reward 23/25 · loyalty 14/14
        C toplu-hariç + en yüksek          reward 20/25 · loyalty 13/14
        D toplu-hariç + ilk                reward 23/25 · loyalty 14/14  ✓
        E başlık öncelikli + en yüksek     reward 22/25 · loyalty 14/14

    "En yüksek" kuralı iki yerde bozuluyordu: (1) Ziraat sayfalarının sonuna
    KOMŞU KAMPANYA KARTI sızıyor ve onun tutarı daha büyük olabiliyor,
    (2) "toplamda 50 kişi için maksimum 25.000 TL" toplu tavanı tek ödülden
    büyük. `AGGREGATE_CAP` ikincisini eliyor, "ilk" olma koşulu birincisini.

    ⚠️ "İlk" seçimi kılavuzun "kademelide EN YÜKSEK" kuralını BOZMAZ:
    `clean_text` kampanya BAŞLIĞIYLA başlıyor ve başlık kademenin üst
    değerini duyuruyor ("3.500 TL'ye varan ParafPara"). Başlığında tutar
    olmayan kademeli bir kampanya çıkarsa bu strateji alt kademeyi seçer;
    o gün geldiğinde ölçüm yeniden yapılmalı.
    """
    for eslesme in kalip.finditer(metin):
        onek = metin[max(0, eslesme.start() - p.PROXIMITY_CHARS) : eslesme.start()]
        if p.AGGREGATE_CAP.search(onek):
            continue
        tutar, _ = parse_money(eslesme.group())
        if tutar is not None:
            return tutar, eslesme.start(), eslesme.end()
    return None


def _amounts(metin: str) -> list[ExtractedField]:
    """Harcama eşiği, ödül tutarı ve finansman tutarını çıkarır."""
    bulunan: list[ExtractedField] = []
    kademe = _kademe_sinirlari(metin)

    acik_asgari: Decimal | None = None
    esik = p.MIN_SPEND.search(metin)
    if esik is not None:
        tutar, _ = parse_money(esik.group())
        # ⚠️ Kademe sınırı asgari eşik DEĞİLDİR (bkz. `_kademe_sinirlari`).
        if tutar is not None and tutar not in kademe:
            acik_asgari = tutar
            bulunan.append(_field("min_spend_try", tutar, metin, esik.start(), esik.end()))

    odul = _ilk_odul(metin, p.REWARD_AMOUNT)
    if odul is not None:
        bulunan.append(_field("reward_amount_try", odul[0], metin, odul[1], odul[2]))

    finansman = p.FINANCING_AMOUNT.search(metin)
    if finansman is not None:
        tutar, _ = parse_money(finansman.group())
        if tutar is not None:
            bulunan.append(
                _field("financing_amount_max", tutar, metin, finansman.start(), finansman.end())
            )

    bulunan.extend(_limits(metin, acik_asgari=acik_asgari, kademe=kademe))
    return bulunan


def _kademe_sinirlari(metin: str) -> frozenset[Decimal]:
    """Hem "…'ye kadar" hem "…üzeri" biçiminde geçen tutarları döndürür.

    Bir tutar aynı metinde İKİ YÖNDE de işaretlenmişse o tutar bir sınır
    değil, iki kademeyi ayıran ÇİZGİDİR. Kampanyanın tavanı ya da tabanı
    olarak yazılamaz.

    Args:
        metin: Kampanyanın temizlenmiş metni.

    Returns:
        Kademe sınırı olan tutarlar; yoksa boş küme.
    """

    def _tutarlar(kalip: re.Pattern[str]) -> set[Decimal]:
        bulunan: set[Decimal] = set()
        for eslesme in kalip.finditer(metin):
            ham = next((g for g in eslesme.groups() if g), None) or eslesme.group()
            tutar, _ = parse_money(ham)
            if tutar is not None:
                bulunan.add(tutar)
        return bulunan

    return frozenset(_tutarlar(p.MAX_SPEND) & _tutarlar(p.MIN_SPEND))


def _limits(
    metin: str, *, acik_asgari: Decimal | None, kademe: frozenset[Decimal]
) -> list[ExtractedField]:
    """Harcama/finansman alt ve üst sınırlarını çıkarır.

    İki kaynak var: `2.000 TL - 300.000 TL arası` biçimindeki ARALIK ve
    `100.000 TL'ye kadar` biçimindeki TEK ÜST SINIR.

    ⚠️ Aralık her iki uca da yazılır; üst sınır tek başına ALT SINIR ÜRETMEZ.
    Kılavuz kuralı ("120 aya kadar" → min ∅, max 120) tutarlar için de
    geçerli: alt sınır belirtilmemişse sıfır YAZILMAZ, alan boş bırakılır.

    ⚠️ `financing_amount_*` yalnızca finansman bağlamı varsa doldurulur;
    her harcama eşiği bir finansman limiti değildir.

    ⚠️ AÇIK İŞARETÇİ ARALIĞI YENER. Metinde hem "6.000 TL ve üzeri" hem
    "100 TL - 1.000 TL arası" geçebiliyor ve bunlar FARKLI şeyleri anlatıyor
    (biri kampanya eşiği, diğeri ör. taksit tutarı). İkisi birden
    `min_spend_try` yazılınca 17 kampanyada çelişkili çift kayıt üretiliyordu.

    ⚠️ KADEMELİ TABLO ÜST SINIR DEĞİLDİR. Emekli maaşı kademeleri
    ("9.999 TL'ye kadarsa 5.000 TL; 10.000 TL - 14.999 TL arası ...;
    20.000 TL ve Üzeri ...") metninde ARA kademenin üst ucu kampanyanın
    tavanı değil. Açık asgari eşikten KÜÇÜK bir üst sınır bu durumun
    imzasıdır ve yazılmaz — 16 kampanyada ölçüldü. Üst sınır uydurmak
    yerine alan boş bırakılır; en üst kademe zaten açık uçlu.

    ⚠️ AYNI TUTARIN İKİ YÖNDE GEÇMESİ KADEME SINIRIDIR. "20 bin TL'ye kadar
    harcamalara 12 taksit, 20 bin TL üzerindeki harcamalara 3 taksit"
    cümlesinde 20.000 ne kampanyanın tavanı ne tabanı — iki taksit
    kademesini AYIRAN çizgi. Bu imza (`_kademe_sinirlari`) yakalanmazsa
    aynı sayı hem `min_spend_try` hem `max_spend_try` olarak yazılıyor ve
    ikisi de yanlış oluyor; gold set'te iki kampanyada ölçüldü.

    Args:
        metin: Kampanyanın temizlenmiş metni.
        acik_asgari: `MIN_SPEND` açık işaretçisinin değeri; yoksa None.
        kademe: Kademe sınırı olan tutarlar (`_kademe_sinirlari`).
    """
    bulunan: list[ExtractedField] = []
    finansman_baglami = p.FINANCING_CONTEXT.search(metin) is not None

    def tutarli(ust: Decimal) -> bool:
        if ust in kademe:
            return False
        return acik_asgari is None or ust > acik_asgari

    aralik = p.SPEND_RANGE.search(metin)
    if aralik is not None:
        alt, _ = parse_money(aralik.group(1))
        ust, _ = parse_money(aralik.group(2))
        bas, son = aralik.start(), aralik.end()
        if alt is not None and acik_asgari is None:
            bulunan.append(_field("min_spend_try", alt, metin, bas, son))
            if finansman_baglami:
                bulunan.append(_field("financing_amount_min", alt, metin, bas, son))
        if ust is not None and tutarli(ust):
            bulunan.append(_field("max_spend_try", ust, metin, bas, son))
            if finansman_baglami:
                bulunan.append(_field("financing_amount_max", ust, metin, bas, son))
        return bulunan

    # ⚠️ Kademeli üst sınırda EN YÜKSEK alınır: "75.000 TL'ye ulaşan ...,
    # 150.000 TL'ye ulaşan ..." metninde kampanyanın tavanı 150.000'dir.
    # Burada "ilk" DEĞİL "en yüksek" doğru: üst sınır bir ödül değil, sınır.
    en_yuksek: tuple[Decimal, int, int] | None = None
    for eslesme in p.MAX_SPEND.finditer(metin):
        ham = eslesme.group(1) or eslesme.group(2)
        tutar, _ = parse_money(ham)
        if tutar is None:
            continue
        if en_yuksek is None or tutar > en_yuksek[0]:
            en_yuksek = (tutar, eslesme.start(), eslesme.end())
    if en_yuksek is not None and tutarli(en_yuksek[0]):
        bulunan.append(_field("max_spend_try", en_yuksek[0], metin, en_yuksek[1], en_yuksek[2]))
        if finansman_baglami:
            bulunan.append(
                _field("financing_amount_max", en_yuksek[0], metin, en_yuksek[1], en_yuksek[2])
            )

    return bulunan


def _tiers(metin: str) -> list[ExtractedField]:
    """Kademeli ödül yapısını çıkarır (eşik → ödül).

    ⚠️ TEK KADEME KADEME DEĞİLDİR. Bir eşik ve bir ödül `min_spend_try` +
    `reward_amount_try` ile zaten temsil ediliyor; bu alan ancak İKİ ya da
    daha fazla FARKLI eşik varsa doldurulur. Aksi hâlde aynı bilgi iki
    yerde durur ve hangisinin doğru olduğu belirsizleşir.

    ⚠️ AYNI EŞİĞE İKİ FARKLI ÖDÜL ÇIKARSA ALAN BOŞ BIRAKILIR. Kalıbın
    60 karakterlik penceresi iç içe geçmiş cümlelerde çapraz eşleşme
    üretebiliyor (ölçüldü: bir kampanyada 5.000 → 350 ve 5.000 → 200 aynı
    metinden çıktı). Hangisinin doğru olduğuna karar vermek yerine
    SUSULUR — belirsiz bir kademe tablosu, tablo olmamasından kötüdür.

    Args:
        metin: Kampanyanın temizlenmiş metni.

    Returns:
        En fazla bir `tier_structure` kaydı; kademe yoksa boş liste.
    """
    kademeler: dict[Decimal, set[Decimal]] = {}
    bas: int | None = None
    son = 0

    for eslesme in p.TIER.finditer(metin):
        esik, _ = parse_money(eslesme.group(1))
        odul, _ = parse_money(eslesme.group(2))
        if esik is None or odul is None or esik == odul:
            continue
        kademeler.setdefault(esik, set()).add(odul)
        bas = eslesme.start() if bas is None else bas
        son = max(son, eslesme.end())

    if len(kademeler) < 2 or bas is None:
        return []
    if any(len(oduller) > 1 for oduller in kademeler.values()):
        return []

    yapi = [
        {"threshold": str(esik), "reward": str(next(iter(oduller)))}
        for esik, oduller in sorted(kademeler.items())
    ]
    return [
        _field(
            "tier_structure",
            json.dumps(yapi, ensure_ascii=False),
            metin,
            bas,
            son,
            note=f"{len(yapi)} kademe",
        )
    ]


def _total_benefit(metin: str) -> list[ExtractedField]:
    """Kampanyanın azami toplam faydasını çıkarır.

    ⚠️ TOPLU KİŞİ TAVANI ALINMAZ. "toplamda 5 kişi için maksimum 25.000 TL"
    bir müşterinin alabileceği azami fayda DEĞİL, bütün davetlerin toplam
    tavanıdır. `AGGREGATE_CAP` bu öneki tanıyor ve eşleşme atlanıyor;
    ayrım yapılmazsa alan bir kampanyada 12,5 kat fazla gösteriyordu.

    ⚠️ TEK ÖDÜLDEN KÜÇÜK BİR TOPLAM YAZILMAZ. Toplam, tek seferlik ödüle
    eşit ya da ondan büyük olmak zorunda; küçükse eşleşme kampanyanın
    tavanını değil başka bir tutarı anlatıyor.

    Args:
        metin: Kampanyanın temizlenmiş metni.

    Returns:
        En fazla bir `max_total_benefit_try` kaydı.
    """
    for eslesme in p.TOTAL_BENEFIT.finditer(metin):
        pencere = metin[eslesme.start() : eslesme.end() + p.PROXIMITY_CHARS]
        if p.AGGREGATE_CAP.search(pencere):
            continue
        tutar, _ = parse_money(eslesme.group(1))
        if tutar is None or tutar <= 0:
            continue
        return [_field("max_total_benefit_try", tutar, metin, eslesme.start(), eslesme.end())]
    return []


def _loyalty(metin: str) -> list[ExtractedField]:
    """Sadakat programı puanını çıkarır (ParafPara, Bankkart Lira, Mil…).

    ⚠️ `reward_amount_try` İLE BİRLİKTE DOLAR ve gold set'te ikisi aynı
    değeri taşır — ödül TL cinsinden bir sadakat birimiyse ("750 TL Bankkart
    Lira") her iki alan da yazılır. Ödül TL cinsinden değilse ("10.000 Mil")
    yalnızca bu alan dolar; ayrımı `REWARD_AMOUNT` kalıbının zorunlu `TL`
    koşulu yapar.
    """
    puan = _ilk_odul(metin, p.LOYALTY_POINTS)
    if puan is None:
        return []
    return [_field("loyalty_points", puan[0], metin, puan[1], puan[2])]


def _profit_share(metin: str) -> list[ExtractedField]:
    """Katılma hesabı paylaşım oranını çıkarır.

    ⚠️ `98/2` biçimindeki oranda MÜŞTERİ PAYI ikinci sayıdır; birinci sayı
    bankada kalan paydır. Yanlış sayı alınırsa katılma hesapları
    karşılaştırması tam ters sıralanır.
    """
    eslesme = p.PROFIT_SHARE_RATIO.search(metin)
    if eslesme is None:
        return []
    ham = eslesme.group(1) or eslesme.group(2)
    if ham is None:
        return []
    return [
        _field(
            "profit_share_rate_pct",
            Decimal(ham),
            metin,
            eslesme.start(),
            eslesme.end(),
        )
    ]


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

    # ⚠️ EKSPERTİZ AYRI ALAN, `has_no_fee` DEĞİL. "Ekspertiz ücretsiz" bir
    # kampanyanın TÜM masraflarını kaldırdığı anlamına gelmez; yalnızca
    # değerleme ücretini söyler. İkisi tek alana toplanırsa "dosya masrafı
    # var, ekspertiz yok" durumundaki kampanya masrafsız görünür.
    ekspertiz = p.APPRAISAL_FEE_COVERED.search(metin)
    if ekspertiz is not None:
        bulunan.append(
            _field("appraisal_fee_covered", "true", metin, ekspertiz.start(), ekspertiz.end())
        )

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

    İKİ AŞAMALI. Önce DÖNEM CÜMLESİ aranır ("... tarihleri arasında
    geçerlidir"), bulunamazsa metindeki ilk tarih aralığına düşülür.

    ⚠️ Sıra bu şekilde olmak zorunda; gold set üzerinde ölçüldü:

        yalnızca ilk aralık        F1 = 0.84   (yakınlık yok, yanlış aralık)
        yalnızca dönem cümlesi     F1 = 0.71   (çok katı, 30 kaçırma)
        önce dönem, sonra aralık   F1 = 0.94   ✓

    Dönem cümlesi yakınlık kuralını uygular (§5.2) ve metinde birden çok
    tarih olduğunda doğru olanı seçer; ama işaretçisiz yazılmış tarihleri
    kaçırır. İkisi birlikte hem kesinliği hem kapsamı verir.

    ⚠️ Tarih bulunamazsa alan ÇIKARILMAZ; yokluk "süresi dolmuş" DEĞİLDİR.
    """
    donem = find_campaign_period_detailed(metin)
    if donem.bulundu:
        bas, son = donem.evidence_start, donem.evidence_end
        baslangic, bitis = donem.start, donem.end
    else:
        eslesme = p.DATE_SPAN.search(metin)
        if eslesme is None:
            return []
        baslangic, bitis, kesinlik = parse_date_range_tr(eslesme.group())
        if kesinlik == "unknown":
            return []
        bas, son = eslesme.start(), eslesme.end()

    bulunan: list[ExtractedField] = []
    if baslangic is not None:
        bulunan.append(_field("start_date", baslangic.isoformat(), metin, bas, son))
    if bitis is not None:
        bulunan.append(_field("end_date", bitis.isoformat(), metin, bas, son))
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
        _profit_share,
        _installment,
        _term,
        _amounts,
        _tiers,
        _total_benefit,
        _loyalty,
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
