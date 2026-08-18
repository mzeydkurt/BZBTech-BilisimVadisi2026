"""Hesaplayıcı formunun envanterini çıkaran SAF fonksiyonlar.

Bu modülde ağ, veritabanı veya tarayıcı yoktur: girdi HTML, çıktı yapıdır.
Tarayıcıyı sürmek `scripts/inventory_calculators.py`'nin işidir. Ayrım bilinçli
— envanter mantığının testleri ağa çıkmadan, kaydedilmiş HTML üzerinde
çalışabilmelidir (§13).

ENVANTERİN ASIL DEĞERİ: Ziraat'te kâr payı oranı statik HTML'de yok, yalnızca
bir hesaplama aracında. O aracın finansman tipi dropdown'ındaki 16 seçenek
ASLINDA 16 ÜRÜN VARYANTIDIR. Yani hesaplayıcı hiç sorgulanmasa bile, formun
kendisi ürün varyantlarını, tutar limitlerini ve izinli vadeleri veriyor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Final

from bs4 import BeautifulSoup, Tag

from app.core.normalization.money import parse_decimal_tr
from app.core.normalization.text import ascii_fold_tr, collapse_whitespace, lower_tr
from app.core.vocab import VARIANT_VOCAB

# Vade seçeneği gibi görünen etiketler. Vakıf Katılım vadeyi kelimeyle
# yazıyor ("Aylık", "1 Yıl Üzeri", "Kırık Vade"); bunlar varyant değildir.
_TERM_LABEL_RE: Final[re.Pattern[str]] = re.compile(r"\b(aylik|yillik|yil|vade|ay)\b")

# Para birimi seçicisi de varyant değildir: Vakıf Katılım hesaplama
# sayfasında TL/USD/EURO/ALTIN seçtiriyor, bu ürün varyantı değil işlem
# para birimi.
_CURRENCY_LABEL_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(tl|try|usd|eur|euro|gbp|altin|gumus|xau)\b"
)

# ── Varyant etiketi → kanonik anahtar eşlemesi ────────────
#
# Anahtar sırası ÖNEMLİDİR: daha özgül kalıplar önce denenir. "2. el konut"
# hem "konut" hem "2. el" içeriyor; önce birleşik kalıba bakılmazsa yanlış
# boyuta düşer.
#
# ⚠️ Eşleşme bulunamazsa UYDURULMAZ: `variant_key=None` döner, ham etiket
# `variant_label`'da saklanır ve `docs/variant_mapping.md`'ye "eşlenmedi"
# olarak yazılır.
VARIANT_PATTERNS: Final[tuple[tuple[str, str, tuple[str, ...]], ...]] = (
    # (boyut, kanonik anahtar, aranacak kalıplar — ASCII katlanmış küçük harf)
    ("konut_durumu", "kentsel_donusum", ("kentsel donusum",)),
    ("konut_durumu", "tamamlayici_konut", ("tamamlayici konut", "tamamlayici")),
    ("konut_durumu", "toki", ("toki",)),
    ("konut_durumu", "arsa", ("arsa",)),
    ("konut_durumu", "isyeri", ("isyeri", "is yeri", "ticari gayrimenkul")),
    ("konut_durumu", "ikinci_el_konut", ("2. el konut", "2.el konut", "ikinci el konut")),
    ("konut_durumu", "sifir_konut", ("sifir konut", "0 km konut", "yeni konut")),
    ("arac_durumu", "elektrikli_arac", ("elektrikli",)),
    ("arac_durumu", "hibrit_arac", ("hibrit", "hybrid")),
    ("arac_durumu", "ticari_arac", ("ticari arac", "ticari tasit")),
    (
        "arac_durumu",
        "ikinci_el_arac",
        ("2. el arac", "2.el arac", "ikinci el arac", "2. el tasit", "ikinci el tasit"),
    ),
    ("arac_durumu", "sifir_arac", ("sifir arac", "0 km arac", "sifir km", "sifir tasit")),
    ("sigorta", "sigortasiz", ("sigortasiz", "sigortasi olmayan")),
    ("sigorta", "sigortali", ("sigortali",)),
    ("enerji_sinifi", "enerji_a", ("enerji sinifi a", "a sinifi", "a enerji")),
    ("enerji_sinifi", "enerji_b", ("enerji sinifi b", "b sinifi", "b enerji")),
    ("enerji_sinifi", "enerji_diger", ("diger enerji", "enerji sinifi diger")),
    ("musteri_tipi", "maas_musterisi", ("maas musteri", "maasini", "maas alan")),
    ("musteri_tipi", "kamu_calisani", ("kamu calisani", "memur")),
    ("musteri_tipi", "banka_calisani", ("banka calisani", "personel")),
    ("musteri_tipi", "yeni_musteri", ("yeni musteri", "ilk kez")),
    ("musteri_tipi", "esnaf", ("esnaf",)),
    ("musteri_tipi", "ciftci", ("ciftci", "tarim")),
    ("ozel", "karz_i_hasen", ("karz-i hasen", "karz i hasen", "karzi hasen")),
    ("ozel", "cevre_dostu", ("cevre dostu", "cevreci")),
    ("ozel", "surdurulebilirlik", ("surdurulebilir",)),
)

# Metin taşımayan, envanterde anlamı olmayan form kontrolleri.
IGNORED_INPUT_TYPES: Final[frozenset[str]] = frozenset(
    {"hidden", "submit", "button", "reset", "image", "file", "password"}
)

# Sayfadaki yasal uyarıyı yakalayan ipuçları. Bankalar hesaplayıcı
# çıktısının bağlayıcı olmadığını buralarda belirtiyor.
LEGAL_NOTICE_HINTS: Final[tuple[str, ...]] = (
    "bilgi amaclidir",
    "bilgilendirme amaclidir",
    "baglayici",
    "temsili",
    "ornek niteligindedir",
    "kesin fiyat",
)

# Kombinasyon sayısı bu eşiğin altındaysa tam tarama makul sayılır.
FULL_SAMPLING_LIMIT: Final[int] = 60
# Bu eşiğin altındaysa ızgara (grid) örneklemesi yapılır; üstündeyse yalnızca pilot.
GRID_SAMPLING_LIMIT: Final[int] = 2_000

# Izgara örneklemesinde tutar ekseninden alınacak nokta sayısı.
GRID_AMOUNT_POINTS: Final[int] = 4


@dataclass
class VariantCandidate:
    """Hesaplayıcı dropdown'ından çıkarılmış aday ürün varyantı."""

    label: str
    """Kaynaktaki insan okunur etiket — BİREBİR saklanır."""

    value: str | None
    """Formdaki `<option value>` — sorgu şablonunda kullanılır."""

    variant_key: str | None = None
    """Kanonik anahtar; eşleşme bulunamadıysa None."""

    variant_dimension: str | None = None
    """Anahtarın ait olduğu boyut; eşleşme bulunamadıysa None."""

    @property
    def is_mapped(self) -> bool:
        """Kanonik sözlüğe eşlenebildi mi?"""
        return self.variant_key is not None


@dataclass
class CalculatorForm:
    """Bir hesaplayıcı sayfasının envanteri."""

    input_fields: dict[str, Any] = field(default_factory=dict)
    legal_notice: str | None = None

    @property
    def variant_field_name(self) -> str | None:
        """Varyant taşıyan alanın adı (en çok seçeneği olan `select`).

        Ziraat'te tutar ve vade de `select` olabiliyor; varyant listesi
        bunların arasında en kalabalık olanıdır.
        """
        adaylar = [
            (ad, tanim)
            for ad, tanim in self.input_fields.items()
            if tanim.get("type") == "select" and self._is_variant_like(tanim)
        ]
        if not adaylar:
            return None
        return max(adaylar, key=lambda item: len(item[1].get("options", [])))[0]

    @staticmethod
    def _is_variant_like(tanim: dict[str, Any]) -> bool:
        """Seçenekleri sayı değil metin olan alanları varyant adayı sayar.

        Vade seçicisi (12, 24, 36) varyant değildir; finansman tipi seçicisi
        ("Sıfır Konut", "2. El Konut") varyanttır.
        """
        secenekler = tanim.get("options", [])
        if len(secenekler) < 2:
            return False

        etiketler = [str(secenek.get("label", "")).strip() for secenek in secenekler]
        metinli = [e for e in etiketler if not e.replace(".", "").isdigit()]
        if len(metinli) < 2:
            return False

        # ⚠️ VADE SEÇENEKLERİ HER ZAMAN SAYI DEĞİL. Vakıf Katılım vadeyi
        # kelimeyle yazıyor: "Aylık", "3 Aylık", "6 Aylık", "Yıllık",
        # "1 Yıl Üzeri", "Kırık Vade". Yalnızca salt sayılar elendiğinde bu
        # liste VARYANT sanılıyor ve altı sahte ürün varyantı üretiyordu.
        def _eksen_gibi(etiket: str) -> bool:
            katlanmis = ascii_fold_tr(lower_tr(etiket))
            return bool(_TERM_LABEL_RE.search(katlanmis) or _CURRENCY_LABEL_RE.search(katlanmis))

        eksen_gibi = sum(1 for e in etiketler if _eksen_gibi(e))
        return eksen_gibi < len(etiketler) / 2


def match_variant(label: str) -> tuple[str | None, str | None]:
    """Kaynaktaki etiketi kanonik varyant anahtarına eşler.

    ⚠️ Eşleşme yoksa UYDURULMAZ. Bir etiketi yanlış anahtara bağlamak,
    karşılaştırmada bir bankanın sigortalı oranını başka bankanın sigortasız
    oranıyla kıyaslamaya yol açar — sessiz ve tespiti zor bir hata.

    Args:
        label: Bankanın sayfasındaki insan okunur etiket ("2. El Konut").

    Returns:
        (boyut, kanonik_anahtar) ikilisi; eşleşme yoksa (None, None).

    """
    if not label:
        return None, None

    aranan = ascii_fold_tr(lower_tr(collapse_whitespace(label)))

    for boyut, anahtar, kaliplar in VARIANT_PATTERNS:
        for kalip in kaliplar:
            if kalip in aranan:
                return boyut, anahtar

    # Etiket zaten kanonik anahtarın kendisi olabilir (ör. API değeri).
    slug = aranan.replace(" ", "_").replace("-", "_")
    for boyut, anahtarlar in VARIANT_VOCAB.items():
        if slug in anahtarlar:
            return boyut, slug

    return None, None


def parse_form_controls(html: str) -> CalculatorForm:
    """Hesaplayıcı sayfasındaki tüm form kontrollerini envanterler.

    Args:
        html: Sayfanın (tarayıcıda render edilmiş) HTML'i.

    Returns:
        Girdi alanları ve yasal uyarıdan oluşan envanter.

    """
    soup = BeautifulSoup(html, "lxml")
    alanlar: dict[str, Any] = {}

    for select in soup.find_all("select"):
        ad = _control_name(select)
        if ad is None:
            continue
        secenekler = [
            secenek for option in select.find_all("option") if (secenek := _option(option))
        ]
        if secenekler:
            alanlar[ad] = {"type": "select", "options": secenekler}

    for element in soup.find_all("input"):
        tip = str(element.get("type", "text")).lower()
        if tip in IGNORED_INPUT_TYPES:
            continue
        ad = _control_name(element)
        if ad is None:
            continue

        if tip in ("range", "number"):
            alanlar[ad] = _numeric_control(element, tip)
        elif tip == "radio":
            grup = alanlar.setdefault(ad, {"type": "radio", "options": []})
            grup["options"].append(
                {
                    "value": element.get("value"),
                    "label": _radio_label(soup, element),
                }
            )
        elif tip == "checkbox":
            alanlar[ad] = {
                "type": "checkbox",
                "label": _radio_label(soup, element),
                "value": element.get("value"),
            }
        else:
            alanlar[ad] = _text_control(element)

    return CalculatorForm(input_fields=alanlar, legal_notice=find_legal_notice(html))


def find_legal_notice(html: str) -> str | None:
    """Sayfadaki "bağlayıcı değildir" uyarısını birebir çıkarır.

    Bu metin `calculator_inventory.non_binding_notice`'a olduğu gibi yazılır:
    hesaplayıcıdan alınan değerlerin bankanın taahhüdü olmadığını jüriye ve
    kullanıcıya kanıtlayan şey budur.

    Args:
        html: Sayfa HTML'i.

    Returns:
        Bulunan uyarı cümlesi; yoksa None.

    """
    soup = BeautifulSoup(html, "lxml")
    metin = collapse_whitespace(soup.get_text(separator=" "))

    for cumle in re.split(r"(?<=[.!?])\s+", metin):
        aranan = ascii_fold_tr(lower_tr(cumle))
        if any(ipucu in aranan for ipucu in LEGAL_NOTICE_HINTS):
            return cumle.strip()
    return None


def count_combinations(
    input_fields: dict[str, Any], *, amount_points: int = GRID_AMOUNT_POINTS
) -> int:
    """Sorgulanabilecek toplam kombinasyon sayısını hesaplar.

    varyant × tutar örneklemi × vade. Bu sayı, bankaya kaç istek atılacağını
    ve dolayısıyla örneklemenin etik olarak uygulanabilir olup olmadığını
    belirler.

    Args:
        input_fields: `parse_form_controls` çıktısındaki alanlar.
        amount_points: Sürekli tutar ekseninden alınacak nokta sayısı.

    Returns:
        Kombinasyon sayısı; hiç alan yoksa 0.

    """
    if not input_fields:
        return 0

    toplam = 1
    bulundu = False

    for tanim in input_fields.values():
        tip = tanim.get("type")
        if tip in ("select", "radio"):
            adet = len(tanim.get("options", []))
        elif tip in ("range", "number"):
            # Sürekli eksen: tam tarama anlamsız, sabit sayıda nokta örneklenir.
            adet = amount_points
        else:
            continue
        if adet <= 0:
            continue
        toplam *= adet
        bulundu = True

    return toplam if bulundu else 0


def suggest_sampling(total_combinations: int, mechanism: str) -> str:
    """Kombinasyon sayısına göre örnekleme kararı önerir.

    ⚠️ Bu siteler gerçek bankalara ait. Binlerce sorgu atmak hem etik değil
    hem de yük yaratır; karar sayıya bakılarak önceden verilir.

    Args:
        total_combinations: `count_combinations` çıktısı.
        mechanism: Hesaplayıcının çalışma biçimi (`app/core/vocab.py`).

    Returns:
        "full" | "grid" | "pilot_only" | "skip".

    """
    # Mekanizma çözülemediyse sorgulama yapılamaz; JS varsayılanı ise
    # zaten karşılaştırmaya girmeyen bir değer üretir.
    if mechanism in ("unknown", "none"):
        return "skip"
    if total_combinations <= 0:
        return "skip"
    if total_combinations <= FULL_SAMPLING_LIMIT:
        return "full"
    if total_combinations <= GRID_SAMPLING_LIMIT:
        return "grid"
    return "pilot_only"


def variant_candidates(form: CalculatorForm) -> list[VariantCandidate]:
    """Varyant alanındaki seçenekleri aday ürün varyantlarına çevirir.

    Args:
        form: `parse_form_controls` çıktısı.

    Returns:
        Adaylar; varyant alanı bulunamazsa boş liste.

    """
    alan_adi = form.variant_field_name
    if alan_adi is None:
        return []

    adaylar: list[VariantCandidate] = []
    for secenek in form.input_fields[alan_adi].get("options", []):
        etiket = str(secenek.get("label", "")).strip()
        if not etiket:
            continue
        boyut, anahtar = match_variant(etiket)
        adaylar.append(
            VariantCandidate(
                label=etiket,
                value=secenek.get("value"),
                variant_key=anahtar,
                variant_dimension=boyut,
            )
        )
    return adaylar


def amount_bounds(input_fields: dict[str, Any]) -> tuple[Decimal | None, Decimal | None]:
    """Tutar ekseninin alt ve üst sınırını çıkarır.

    HTML attribute'undan okunan limit, metinden tahmin edilenden çok daha
    güvenilirdir (`limits_source='html_attr'`).

    Args:
        input_fields: `parse_form_controls` çıktısındaki alanlar.

    Returns:
        (en_az, en_cok); bulunamazsa (None, None).

    """
    for ad, tanim in input_fields.items():
        if tanim.get("type") not in ("range", "number"):
            continue
        if not _looks_like_amount(ad):
            continue
        return _as_decimal(tanim.get("min")), _as_decimal(tanim.get("max"))
    return None, None


def allowed_terms(input_fields: dict[str, Any]) -> list[int] | None:
    """İzinli vade seçeneklerini çıkarır.

    Args:
        input_fields: `parse_form_controls` çıktısındaki alanlar.

    Returns:
        Ay cinsinden vadeler; bulunamazsa None.

    """
    for ad, tanim in input_fields.items():
        if not _looks_like_term(ad):
            continue
        if tanim.get("type") == "select":
            vadeler = [
                int(sayi)
                for secenek in tanim.get("options", [])
                if (sayi := _first_integer(str(secenek.get("label", "")))) is not None
            ]
            if vadeler:
                return sorted(set(vadeler))
    return None


# ── İç yardımcılar ────────────────────────────────────────


def _option(option: Tag) -> dict[str, Any] | None:
    """Tek bir `<option>`ı envantere çevirir; yer tutucuysa None döner.

    Yer tutucu ayrımı `value` niteliğine göre yapılır:
      - `value=""`      → "Seçiniz" gibi bir yer tutucudur, ATLANIR. Sayılırsa
                          varyant sayısı ve kombinasyon tahmini şişer, örnekleme
                          kararı yanlış verilir.
      - `value` YOK     → etiketin kendisi değerdir; gerçek bir seçenektir.
    """
    etiket = collapse_whitespace(option.get_text())
    if not etiket:
        return None

    if option.has_attr("value"):
        deger = str(option["value"])
        if not deger.strip():
            return None
        return {"value": deger, "label": etiket}

    return {"value": etiket, "label": etiket}


def _control_name(element: Tag) -> str | None:
    """Form kontrolünün kararlı bir adını döndürür."""
    for nitelik in ("name", "id", "data-name"):
        deger = element.get(nitelik)
        if deger:
            return str(deger)
    return None


def _numeric_control(element: Tag, tip: str) -> dict[str, Any]:
    """`range`/`number` girdisinin sınırlarını okur."""
    return {
        "type": tip,
        "min": _as_number(element.get("min")),
        "max": _as_number(element.get("max")),
        "step": _as_number(element.get("step")),
        "value": _as_number(element.get("value")),
    }


def _text_control(element: Tag) -> dict[str, Any]:
    """Serbest metin girdisini envanterler."""
    return {
        "type": "text",
        "placeholder": element.get("placeholder"),
        "value": element.get("value"),
    }


def _radio_label(soup: BeautifulSoup, element: Tag) -> str | None:
    """Radyo/onay kutusunun görünen etiketini bulur."""
    kimlik = element.get("id")
    if kimlik:
        etiket = soup.find("label", attrs={"for": kimlik})
        if etiket:
            return collapse_whitespace(etiket.get_text())
    ebeveyn = element.find_parent("label")
    if ebeveyn:
        return collapse_whitespace(ebeveyn.get_text())
    return None


def _looks_like_amount(name: str) -> bool:
    """Alan adının tutar ekseni olup olmadığını sezer."""
    aranan = ascii_fold_tr(lower_tr(name))
    return any(ipucu in aranan for ipucu in ("tutar", "amount", "miktar", "kredi", "finansman"))


def _looks_like_term(name: str) -> bool:
    """Alan adının vade ekseni olup olmadığını sezer."""
    aranan = ascii_fold_tr(lower_tr(name))
    return any(ipucu in aranan for ipucu in ("vade", "term", "taksit", "ay"))


def _as_number(value: Any) -> float | int | None:
    """HTML attribute değerini sayıya çevirir; çevrilemezse None."""
    if value is None:
        return None
    try:
        sayi = float(str(value).replace(",", "."))
    except ValueError:
        return None
    return int(sayi) if sayi.is_integer() else sayi


def _as_decimal(value: Any) -> Decimal | None:
    """Sayıyı `Decimal`e çevirir — para alanlarında float kullanılmaz."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return parse_decimal_tr(str(value))


def _first_integer(text: str) -> int | None:
    """Metindeki ilk tam sayıyı döndürür ("36 Ay" -> 36)."""
    eslesme = re.search(r"\d+", text)
    return int(eslesme.group()) if eslesme else None


# ── Seçenek etiketinden ürün limiti (§3.4) ────────────────
#
# ⚠️ ORTAK HESAPLAYICI, ÜRÜNE ÖZEL BİLGİ TAŞIYABİLİR. Ziraat Katılım'ın
# finansman hesaplayıcısı sitenin TAMAMINDA aynı: 17 seçenekli tek bir
# dropdown, üç ayrı ürün sayfasında da birebir aynı çıkıyor. Vade seçicisi
# 1-60 listeliyor ama bu BİRLEŞİK bir liste; hiçbir ürün 60 ay vermiyor.
#
# Gerçek sınır SEÇENEK ETİKETİNİN İÇİNDE yazılı:
#
#     "TAŞIT FINANSMANI(1-48 AY)"
#     "İHTIYAÇ FINANSMANI (1-24 AY)"
#     "KONUT FINANSMANI (0-10.000.000 TL/1-120 AY))"
#
# Vade seçicisini olduğu gibi ürüne yazmak taşıt finansmanını 60 aya kadar
# gösterirdi; etiketten okunan 48 doğru değerdir.
_OPTION_TERM_RE: Final[re.Pattern[str]] = re.compile(r"(\d{1,3})\s*-\s*(\d{1,3})\s*ay")
_OPTION_AMOUNT_RE: Final[re.Pattern[str]] = re.compile(
    r"([\d.]+)\s*-\s*([\d.]+)\s*tl", re.IGNORECASE
)


@dataclass(frozen=True)
class OptionLimits:
    """Bir hesaplayıcı seçeneğinden okunan ürün limitleri."""

    label: str
    product_name: str
    term_months_min: int | None = None
    term_months_max: int | None = None
    amount_min: Decimal | None = None
    amount_max: Decimal | None = None


def parse_option_limits(label: str) -> OptionLimits | None:
    """Hesaplayıcı seçenek etiketinden ürün adını ve limitlerini ayırır.

    ⚠️ PARANTEZ İÇİ SINIR, ÜRÜN ADININ PARÇASI DEĞİLDİR. "TAŞIT
    FINANSMANI(1-48 AY)" ile "TAŞIT FINANSMANI (1-36 AY)" AYNI ürünün iki
    paketi; ad ayrılmazsa iki farklı ürün sanılır.

    ⚠️ Parantez bazen bitişik ("FINANSMANI(1-12 AY)"), bazen boşluklu, bazen
    fazladan kapanışlı ("...1-120 AY))") yazılmış. Ayrıştırma bunların
    üçüne de dayanıklı olmalı.

    Args:
        label: Dropdown seçeneğinin görünen metni.

    Returns:
        Ayrıştırılmış limitler; etiket boşsa None.
    """
    temiz = collapse_whitespace(label or "")
    if not temiz:
        return None

    # Parantezli sınır bloğunu addan ayır.
    parantez = re.search(r"\(([^()]*)\)?\)?\s*$", temiz)
    ad = collapse_whitespace(temiz[: parantez.start()] if parantez else temiz)
    icerik = ascii_fold_tr(lower_tr(parantez.group(1))) if parantez else ""

    vade = _OPTION_TERM_RE.search(icerik)
    tutar = _OPTION_AMOUNT_RE.search(icerik)

    alt_tutar = _as_decimal(tutar.group(1)) if tutar else None
    ust_tutar = _as_decimal(tutar.group(2)) if tutar else None

    return OptionLimits(
        label=temiz,
        product_name=ad or temiz,
        term_months_min=int(vade.group(1)) if vade else None,
        term_months_max=int(vade.group(2)) if vade else None,
        # ⚠️ Alt sınır SIFIR limit değildir; "0-10.000.000 TL" ifadesinde
        # anlamlı olan yalnızca tavan.
        amount_min=alt_tutar if alt_tutar and alt_tutar > 0 else None,
        amount_max=ust_tutar,
    )
