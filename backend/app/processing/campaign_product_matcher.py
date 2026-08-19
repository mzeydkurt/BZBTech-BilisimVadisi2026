"""Kampanya ↔ ürün eşleştirmesi (ağa çıkmaz).

⚠️ BAĞ ÜRÜN TÜRÜNDEN KURULMAZ. "Kampanyanın türü taşıt finansmanı, bankanın
taşıt finansmanı ürününe bağla" demek, ürünün oran tablosunu aynı türdeki HER
kampanyaya kopyalamak olurdu: kampanyanın kendi oranı varsa onunla çelişir,
yoksa sahip olmadığımız bir bilgi iddia edilmiş olur. Bağ yalnızca kampanya
metninde ürünün ADI ya da ADRESİ geçtiğinde kurulur.

⚠️ ÜRÜN ADI KISAYSA EŞLEŞTİRİLMEZ. "Kart", "Hesap" gibi adlar her metinde
geçer ve her kampanyayı her ürüne bağlar. Asgari uzunluk eşiği bunu keser.

Ölçüldü (19 Ağustos 2026, 602 kampanya / 234 ürün):

    finansman kampanyası    13/16   (%81)
    diğer (kart, alışveriş) 115/586 (%20)

Finansman tarafındaki kapsama yüksek. Diğer tarafta ürün adının metinde
geçmesi çoğu zaman geçerken anılmasıdır ("Bankkart ile alışveriş"); bu yüzden
`body` yöntemiyle kurulan bağın güveni düşük tutulur ve tüketen taraf eşiğe
göre süzer.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from app.core.normalization.text import ascii_fold_tr, lower_tr
from app.core.vocab import CAMPAIGN_PRODUCT_CONFIDENCE

# ⚠️ Bu uzunluğun altındaki ürün adı eşleştirmeye GİRMEZ. "Kart" (4),
# "Hesap" (5), "Biz Kart" (8) gibi adlar metinlerde serbestçe geçiyor;
# eşiksiz çalıştırıldığında 602 kampanyanın çoğu birden çok ürüne
# bağlanıyordu.
ASGARI_AD_UZUNLUGU: Final[int] = 10

# Gövde metninde aranan pencere. Kampanya metinlerinin sonu banka geneli
# yasal uyarı ve menü metnidir; orada geçen ürün adı kampanyaya ait değildir.
GOVDE_PENCERESI: Final[int] = 2500


@dataclass(frozen=True)
class UrunAdayi:
    """Eşleştirmeye giren ürün."""

    product_id: int
    name: str
    url_slug: str


@dataclass(frozen=True)
class Eslesme:
    """Kurulan bağ ve dayanağı."""

    product_id: int
    match_method: str
    confidence: Decimal
    evidence: str


def _katla(metin: str | None) -> str:
    """Karşılaştırma için metni katlar (küçük harf + ASCII)."""
    return ascii_fold_tr(lower_tr(metin or ""))


def _ad_cekirdegi(ad: str) -> str:
    """Ürün adını eşleştirilebilir çekirdeğe indirger.

    Bankalar ürün adına yıldız ve parantezli açıklama ekliyor:
    `"Taşıt Finansmanı (Taşıt Kredisi)*"`. Bu ek kampanya metninde geçmez;
    çıkarılmazsa hiçbir eşleşme kurulmaz.
    """
    cekirdek = _katla(ad)
    if "(" in cekirdek:
        cekirdek = cekirdek.split("(", 1)[0]
    return cekirdek.replace("*", "").strip()


def esles(
    *,
    title: str,
    campaign_slug: str,
    source_url: str,
    clean_text: str | None,
    adaylar: list[UrunAdayi],
) -> list[Eslesme]:
    """Bir kampanyayı aynı bankanın ürünleriyle eşleştirir.

    Sinyaller güç sırasına göre denenir; bir ürün için EN GÜÇLÜ sinyal
    kaydedilir. Aynı ürün iki kez bağlanmaz.

    Args:
        title: Kampanya başlığı.
        campaign_slug: Kampanyanın `external_slug` değeri.
        source_url: Kampanyanın kaynak adresi.
        clean_text: Kampanyanın temiz metni.
        adaylar: AYNI BANKANIN ürünleri.

    Returns:
        Kurulan bağlar; hiçbiri eşleşmezse boş liste.

    """
    kat_baslik = _katla(title)
    kat_adres = _katla(campaign_slug) + " " + _katla(source_url)
    kat_govde = _katla(clean_text)[:GOVDE_PENCERESI]

    eslesmeler: list[Eslesme] = []
    for aday in adaylar:
        cekirdek = _ad_cekirdegi(aday.name)
        if len(cekirdek) < ASGARI_AD_UZUNLUGU:
            continue

        yontem: str | None = None
        kanit = ""
        if cekirdek in kat_baslik:
            yontem, kanit = "title", title
        elif len(aday.url_slug) >= ASGARI_AD_UZUNLUGU and _katla(aday.url_slug) in kat_adres:
            yontem, kanit = "slug", aday.url_slug
        elif cekirdek in kat_govde:
            yontem, kanit = "body", _baglam(kat_govde, cekirdek, clean_text or "")

        if yontem is None:
            continue

        eslesmeler.append(
            Eslesme(
                product_id=aday.product_id,
                match_method=yontem,
                confidence=CAMPAIGN_PRODUCT_CONFIDENCE[yontem],
                evidence=kanit[:300],
            )
        )
    return eslesmeler


def _baglam(kat_govde: str, cekirdek: str, ham: str) -> str:
    """Eşleşen ürün adının çevresindeki cümle parçasını döndürür.

    ⚠️ Kanıt KATLANMIŞ metinden değil HAM metinden alınır: katlanmış metin
    Türkçe harfleri bozar ve gösterildiğinde kaynakla uyuşmaz. Katlama
    uzunluğu değiştirmediği için ofset ham metinde de geçerlidir.
    """
    yer = kat_govde.find(cekirdek)
    if yer < 0:
        return ham[:120]
    bas = max(0, yer - 40)
    son = min(len(ham), yer + len(cekirdek) + 40)
    return " ".join(ham[bas:son].split())
