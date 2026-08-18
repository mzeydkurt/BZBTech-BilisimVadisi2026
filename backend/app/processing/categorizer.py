"""Kural tabanlı kampanya sınıflandırması — LLM YOK.

Bu sprintteki sınıflandırmanın tamamı deterministiktir: aynı girdi daima aynı
etiketleri üretir. Yapay zekâ çıkarımı sonraki sprintte gelecek ve bu katmanın
ürettiği etiketler onun karşılaştırma tabanı (ablation çalışmasının "kural
tabanlı" kolonu) olacak.

KANIT ÖNCELİĞİ — güçlüden zayıfa:

    url            adres yolundaki kategori          güven 1.00
    bank_category  bankanın kendi etiketi            güven 1.00
    merchant       marka sözlüğü eşleşmesi           güven 0.90
    keyword        anahtar kelime eşleşmesi          güven 0.70

İlk ikisi ÇIKARIM DEĞİLDİR: bankanın kendi yayımladığı veridir. Ziraat
kampanya kartında sektörü kendisi yazıyor, Kuveyt Türk adres yolunda taşıyor.
Bu yüzden güvenleri tamdır.

⚠️ UYDURMA ETİKET YOK. Kaynak yoksa etiket yazılmaz. Tek istisna: hiçbir
sektör sinyali bulunmayan kampanyalara `sector='genel'` düşük güvenle
(0.30) yazılır — çünkü şema her kampanyada en az bir sektör etiketi bekliyor
ve "sınıflandırılamadı" bilgisinin kendisi de bir bulgudur. Düşük güven,
sonraki sprintte hangi kayıtların önce ele alınacağını gösterir.

⚠️ Aynı eksende birden fazla etiket serbesttir: "Trendyol'da kredi kartına
taksit" kampanyası hem `kart` hem `alisveris_puani` olabilir.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Final
from urllib.parse import urlsplit

from app.core.normalization.text import ascii_fold_tr, lower_tr, normalize_text
from app.core.taxonomy import (
    AMBIGUOUS_MERCHANTS,
    AUDIENCE_KEYWORDS,
    BANK_CATEGORY_PRODUCT_TYPE,
    BANK_CATEGORY_SECTOR,
    BENEFIT_KEYWORDS,
    FALLBACK_CONFIDENCE,
    FALLBACK_SECTOR,
    MERCHANT_SECTOR,
    PRODUCT_TYPE_KEYWORDS,
    SECTOR_KEYWORDS,
    SOURCE_CONFIDENCE,
)

# Belirsiz marka adında güven bu kadar düşürülür.
AMBIGUOUS_PENALTY: Final[Decimal] = Decimal("0.200")

# Kanıt metni bu uzunlukta kırpılır: `campaign_categories.evidence` alanı
# gerekçeyi göstermek içindir, tüm sayfayı saklamak için değil.
EVIDENCE_MAX_LENGTH: Final[int] = 160

# Kampanyadan yararlanmak için ürüne SAHİP OLMAK gerektiğini gösteren iyelik
# ekleri: "Kartınızla", "kartlarınız ile", "hesabınıza". Bu ekler müşterinin
# ürünü halihazırda taşıdığının METİNDEKİ kanıtıdır.
#
# ⚠️ "Müşteri Ol" DÜĞMESİ buraya GİRMEZ. O bir gezinti öğesidir ve
# kampanyanın yalnızca yeni müşteriye ait olduğunu göstermez — çoğu kampanya
# hem mevcut hem yeni müşteriye açıktır ("Müşteri Ol, 4 taksit" kampanyası
# mevcut müşteride de geçerli olabilir).
OWNERSHIP_RE: Final[re.Pattern[str]] = re.compile(
    r"kart\w*n\w{0,3}z\w*|hesab\w*n\w{0,3}z\w*|müşterilerimiz|kart sahi",
    re.IGNORECASE,
)

# Açık işaretçi yokken varsayılan hedef kitle.
DEFAULT_AUDIENCE: Final[str] = "mevcut_musteri"


@dataclass(frozen=True)
class CategoryLabel:
    """Tek bir eksende üretilmiş tek bir etiket.

    `campaign_categories` satırına birebir karşılık gelir.
    """

    axis: str
    value: str
    source: str
    confidence: Decimal
    evidence: str | None = None


def _fold(text: str | None) -> str:
    """Karşılaştırma için metni sadeleştirir (küçük harf + ASCII katlama).

    ⚠️ Yalnızca EŞLEŞTİRME için kullanılır. Saklanan kanıt metni ham hâliyle
    kalır: Türkçe karakterler veri setinde korunur.
    """
    return ascii_fold_tr(lower_tr(normalize_text(text or "")))


def _kirp(text: str) -> str:
    """Kanıt metnini okunur uzunlukta kırpar."""
    temiz = normalize_text(text)
    return temiz[:EVIDENCE_MAX_LENGTH]


def _kelime_var(hedef_katlanmis: str, aranan: str) -> bool:
    """Aranan ifadeyi kelime sınırına duyarlı biçimde arar.

    ⚠️ Ham `in` araması yanlış eşleşme üretiyor: "gain" kelimesi "kazangain"
    gibi bir dizide veya "tod" kelimesi "metod" içinde geçebilir. Türkçe ekler
    (-de, -da, -ta, 'nin) serbest bırakılır; bunun için sağ sınır aranmaz,
    yalnızca SOL sınır zorunlu tutulur ve sağda harf devam ederse kabul edilir.
    """
    kalip = re.escape(_fold(aranan))
    # Sol sınır: dize başı veya harf/rakam olmayan bir karakter.
    return re.search(rf"(?<![a-z0-9]){kalip}", hedef_katlanmis) is not None


def _url_kategorisi(source_url: str) -> str | None:
    """Adres yolundaki kategori parçasını döndürür.

    Kuveyt Türk'te yol `/kampanyalar/{segment}/{kategori}/{slug}` biçiminde ve
    kategori doğrudan okunabiliyor.
    """
    parcalar = [p for p in urlsplit(source_url).path.split("/") if p]
    for parca in parcalar:
        if parca in BANK_CATEGORY_PRODUCT_TYPE or parca in BANK_CATEGORY_SECTOR:
            return parca
    return None


def _banka_etiketinden(etiket: str | None, source_url: str) -> list[CategoryLabel]:
    """Bankanın kendi kategorisinden etiket üretir.

    Args:
        etiket: Keşifte taşınan kategori bilgisi (`DiscoveredUrl.category_hint`).
        source_url: Kampanyanın adresi; etiket yoksa yoldan aranır.

    Returns:
        Bulunan etiketler; kaynak yoksa boş liste.
    """
    sonuc: list[CategoryLabel] = []

    # Adres yolu, elle taşınan etiketten daha kesindir: kaynağı doğrudan URL.
    yol_kategorisi = _url_kategorisi(source_url)
    adaylar: list[tuple[str, str]] = []
    if yol_kategorisi:
        adaylar.append(("url", yol_kategorisi))
    if etiket:
        adaylar.append(("bank_category", etiket))

    for kaynak, ham in adaylar:
        anahtar = _fold(ham)
        # Sözlük anahtarları da katlanarak karşılaştırılır.
        sektor = _sozlukten(BANK_CATEGORY_SECTOR, anahtar)
        if sektor:
            sonuc.append(
                CategoryLabel(
                    axis="sector",
                    value=sektor,
                    source=kaynak,
                    confidence=SOURCE_CONFIDENCE[kaynak],
                    evidence=_kirp(str(ham)),
                )
            )
        urun = _sozlukten(BANK_CATEGORY_PRODUCT_TYPE, anahtar)
        if urun:
            sonuc.append(
                CategoryLabel(
                    axis="product_type",
                    value=urun,
                    source=kaynak,
                    confidence=SOURCE_CONFIDENCE[kaynak],
                    evidence=_kirp(str(ham)),
                )
            )

    return sonuc


def _sozlukten(sozluk: dict[str, str], katlanmis_anahtar: str) -> str | None:
    """Katlanmış anahtarla sözlükte arama yapar."""
    for ham_anahtar, deger in sozluk.items():
        if _fold(ham_anahtar) == katlanmis_anahtar:
            return deger
    return None


def _markadan(metin_katlanmis: str, ham_metin: str) -> list[CategoryLabel]:
    """Marka sözlüğünden sektör etiketi üretir."""
    sonuc: list[CategoryLabel] = []
    gorulen: set[str] = set()

    for marka, sektor in MERCHANT_SECTOR.items():
        if not _kelime_var(metin_katlanmis, marka):
            continue
        if sektor in gorulen:
            continue
        gorulen.add(sektor)

        guven = SOURCE_CONFIDENCE["merchant"]
        if marka in AMBIGUOUS_MERCHANTS:
            # ⚠️ Kısa marka adları sıradan kelimeyle karışabiliyor.
            guven -= AMBIGUOUS_PENALTY

        sonuc.append(
            CategoryLabel(
                axis="sector",
                value=sektor,
                source="merchant",
                confidence=guven,
                evidence=_kirp(_baglam(ham_metin, marka) or marka),
            )
        )

    return sonuc


def _baglam(ham_metin: str, aranan: str) -> str | None:
    """Eşleşen ifadenin geçtiği kısa bağlamı döndürür (kanıt için)."""
    katlanmis = _fold(ham_metin)
    yer = katlanmis.find(_fold(aranan))
    if yer < 0:
        return None
    bas = max(0, yer - 40)
    return ham_metin[bas : yer + len(aranan) + 60]


def _anahtar_kelimeden(
    metin_katlanmis: str, ham_metin: str, axis: str, sozluk: dict[str, tuple[str, ...]]
) -> list[CategoryLabel]:
    """Anahtar kelime sözlüğünden etiket üretir (en zayıf sinyal)."""
    sonuc: list[CategoryLabel] = []

    for deger, kelimeler in sozluk.items():
        for kelime in kelimeler:
            if not _kelime_var(metin_katlanmis, kelime):
                continue
            sonuc.append(
                CategoryLabel(
                    axis=axis,
                    value=deger,
                    source="keyword",
                    confidence=SOURCE_CONFIDENCE["keyword"],
                    evidence=_kirp(_baglam(ham_metin, kelime) or kelime),
                )
            )
            break  # Aynı değer için ilk eşleşme yeterli.

    return sonuc


def _tekillestir(etiketler: list[CategoryLabel]) -> list[CategoryLabel]:
    """Aynı (eksen, değer) için EN GÜÇLÜ kanıtı tutar.

    Bir kampanya hem bankanın kategorisinden hem anahtar kelimeden aynı
    sektöre işaret edebiliyor; şemadaki tekillik kısıtı (`campaign_id`, `axis`,
    `value`) tek satır bekliyor. Güçlü kanıt korunur, zayıfı atılır.
    """
    en_iyi: dict[tuple[str, str], CategoryLabel] = {}
    for etiket in etiketler:
        anahtar = (etiket.axis, etiket.value)
        mevcut = en_iyi.get(anahtar)
        if mevcut is None or etiket.confidence > mevcut.confidence:
            en_iyi[anahtar] = etiket
    # Eksen, sonra güven (azalan), sonra değer: çıktı kararlı sıralanır.
    return sorted(en_iyi.values(), key=lambda e: (e.axis, -e.confidence, e.value))


def categorize(
    *,
    title: str,
    description: str | None = None,
    conditions_text: str | None = None,
    source_url: str = "",
    bank_category: str | None = None,
) -> list[CategoryLabel]:
    """Bir kampanyayı dört eksende sınıflandırır.

    Args:
        title: Kampanya başlığı.
        description: Kısa açıklama.
        conditions_text: Koşul metni.
        source_url: Kampanyanın adresi (yol kategorisi buradan okunur).
        bank_category: Bankanın kendi kategori etiketi.

    Returns:
        Üretilen etiketler; her (eksen, değer) çifti en fazla bir kez.
    """
    # Başlık ve açıklama sinyal bakımından en yoğun kısım; koşul metni uzun ve
    # gürültülü olduğu için yalnızca fayda/hedef kitle aramasına katılır.
    baslik_alani = " ".join(filter(None, (title, description)))
    tum_metin = " ".join(filter(None, (title, description, conditions_text)))

    baslik_katlanmis = _fold(baslik_alani)
    tum_katlanmis = _fold(tum_metin)

    etiketler: list[CategoryLabel] = []

    # 1-2. Bankanın kendi verisi (url + bank_category)
    etiketler += _banka_etiketinden(bank_category, source_url)

    # 3. Marka sözlüğü — yalnızca başlık ve açıklamada aranır; koşul metninde
    #    geçen "kampanya dışıdır" cümleleri yanlış sektör üretiyordu.
    etiketler += _markadan(baslik_katlanmis, baslik_alani)

    # 4. Anahtar kelimeler
    etiketler += _anahtar_kelimeden(
        baslik_katlanmis, baslik_alani, "product_type", PRODUCT_TYPE_KEYWORDS
    )
    etiketler += _anahtar_kelimeden(baslik_katlanmis, baslik_alani, "sector", SECTOR_KEYWORDS)
    # ⚠️ HEDEF KİTLE TÜM METİNDE ARANIR — koşul metni dahil. "Kampanya
    # yalnızca emekli müşterilerimiz için geçerlidir" gibi ifadeler yalnızca
    # orada geçiyor (`test_hedef_kitle_kosul_metninden_de_okunur`).
    #
    # Gürültü kaynağı olan "Müşteri Ol" DÜĞMESİ metinden değil SÖZLÜKTEN
    # elendi (bkz. `AUDIENCE_KEYWORDS`), böylece koşul metni okunmaya
    # devam ediyor.
    etiketler += _anahtar_kelimeden(tum_katlanmis, tum_metin, "audience", AUDIENCE_KEYWORDS)
    etiketler += _anahtar_kelimeden(tum_katlanmis, tum_metin, "benefit", BENEFIT_KEYWORDS)

    etiketler = _tekillestir(etiketler)

    # ⚠️ Şema her kampanyada en az bir sektör bekliyor. Sinyal yoksa uydurmak
    # yerine "genel" düşük güvenle yazılır; bu kayıtlar sonraki sprintte
    # önceliklendirilecek.
    if not any(e.axis == "sector" for e in etiketler):
        etiketler.append(
            CategoryLabel(
                axis="sector",
                value=FALLBACK_SECTOR,
                source="keyword",
                confidence=FALLBACK_CONFIDENCE,
                evidence=None,
            )
        )

    # ⚠️ HEDEF KİTLE VARSAYILANI: SAHİPLİK KANITI VARSA "mevcut müşteri".
    #
    # Alan bilgisi: bir kampanyadan yararlanmak için kart ya da hesap
    # gerekiyorsa, hedef kitle zaten mevcut müşteridir. Bunu METİN SÖYLÜYOR —
    # "Kartınızla", "kartlarınız ile", "hesabınıza" ifadelerindeki İYELİK EKİ
    # müşterinin ürüne halihazırda sahip olduğunun kanıtıdır. Uydurma değil,
    # kanıtı gösterilebilir bir çıkarımdır; bu yüzden kanıt metni saklanır.
    #
    # ⚠️ YALNIZCA AÇIK İŞARETÇİ YOKKEN çalışır. "Yeni müşterilere özel",
    # "gençlere özel", "emekli" gibi bir ifade varsa yukarıdaki anahtar
    # kelime katmanı zaten etiketi üretmiştir ve buraya hiç girilmez.
    #
    # ⚠️ Güven DÜŞÜK (`FALLBACK_CONFIDENCE`): bu bir varsayılan, bankanın
    # açık beyanı değil.
    if not any(e.axis == "audience" for e in etiketler):
        sahiplik = OWNERSHIP_RE.search(tum_metin)
        if sahiplik is not None:
            etiketler.append(
                CategoryLabel(
                    axis="audience",
                    value=DEFAULT_AUDIENCE,
                    source="keyword",
                    confidence=FALLBACK_CONFIDENCE,
                    evidence=_kirp(_baglam(tum_metin, sahiplik.group(0)) or sahiplik.group(0)),
                )
            )

    return etiketler
