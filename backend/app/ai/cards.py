"""Varlık kartları — yapısal alanlardan doğal Türkçe metin (KAPI A9).

SPRINT 5'te gömülecek (embedding) metin budur. Bir kampanyanın veritabanı
satırları arama motoruna doğrudan verilemez; `profit_rate_pct=2.05` ifadesi
"kâr payı oranı yüzde 2,05" sorgusuyla eşleşmez. Kart, yapısal veriyi
aranabilir cümlelere çevirir.

⚠️ SADECE DOĞRULANMIŞ ALANLAR. `is_validated=True` VE `confidence >= 0.60`
olmayan hiçbir değer karta girmez. Kart, sistemin kullanıcıya gösterdiği
en özet biçimdir; guard'ın elediği ya da mantık ihlali taşıyan bir değerin
buraya sızması, halüsinasyonu en görünür yere koymak olurdu.

⚠️ REDDEDİLEN KAYITLAR ZATEN DIŞARIDADIR (`rejected_reason IS NULL`).

⚠️ HESAPLAYICI KAYNAKLI DEĞER İŞARETLENİR. `is_binding=False` olan bir
ürün oranı bankanın bağlayıcı beyanı değildir; kartta bu ibare olmadan
görünmesi yanıltıcı olurdu (§10.3).

⚠️ `card_hash` DEĞİŞMEDİYSE KART YENİDEN ÜRETİLMEZ. Gömme (SPRINT 5)
pahalıdır; değişmeyen metni yeniden gömmek boşa maliyettir.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Bank,
    Campaign,
    CampaignCategory,
    CampaignExtraction,
    GlossaryTerm,
    Product,
    ProductRate,
)
from app.utils.hashing import sha256_text

# Karta girebilmek için gereken en düşük güven.
MIN_CARD_CONFIDENCE: Final[Decimal] = Decimal("0.60")

# Bağlayıcı olmayan değerlere eklenen ibare (§10.3).
NON_BINDING_NOTICE: Final[str] = (
    "(bankanın hesaplama aracından alınan tahmini değer, bağlayıcı değildir)"
)

# Alan adı → kartta kullanılacak Türkçe ifade kalıbı.
# ⚠️ Katılım terminolojisi: "kâr payı", "finansman" — asla "faiz"/"kredi".
FIELD_PHRASES: Final[dict[str, str]] = {
    "profit_rate_pct": "kâr payı oranı %{deger}",
    "profit_share_rate_pct": "katılma hesabı kâr payı oranı %{deger}",
    "installment_count": "{deger} taksit",
    "term_months_min": "en az {deger} ay vade",
    "term_months_max": "{deger} aya kadar vade",
    "min_spend_try": "asgari {deger} TL harcama",
    "max_spend_try": "azami {deger} TL harcama",
    "reward_amount_try": "{deger} TL ödül",
    "cashback_pct": "%{deger} nakit iade",
    "discount_pct": "%{deger} indirim",
    "financing_amount_max": "{deger} TL'ye kadar finansman",
    "allocation_fee_pct": "tahsis ücreti %{deger}",
    "file_fee_try": "dosya masrafı {deger} TL",
}

# Ay adları — tarih aralığını doğal dile çevirmek için.
_MONTHS: Final[tuple[str, ...]] = (
    "Ocak",
    "Şubat",
    "Mart",
    "Nisan",
    "Mayıs",
    "Haziran",
    "Temmuz",
    "Ağustos",
    "Eylül",
    "Ekim",
    "Kasım",
    "Aralık",
)


def _bas_harf_buyut(metin: str) -> str:
    """Yalnızca İLK harfi büyütür, gerisine dokunmaz.

    ⚠️ `str.capitalize()` KULLANILMAZ: tüm dizeyi küçültür ve
    `"5.000 TL ödül"` ifadesini `"5.000 tl ödül"` yapar. Para birimi
    kısaltmasının küçülmesi finansal bir metinde kabul edilemez.

    ⚠️ Türkçe büyütme: `"indirim"` → `"İndirim"` (`"Indirim"` değil).
    """
    if not metin:
        return metin
    ilk = "İ" if metin[0] == "i" else metin[0].upper()
    return ilk + metin[1:]


def _sayi_metni(deger: str) -> str:
    """Sayıyı kartta okunur biçimde yazar: `2.0500` → `2,05`, `5000.00` → `5.000`."""
    try:
        sayi = Decimal(deger)
    except Exception:
        return deger

    if sayi == sayi.to_integral_value():
        return f"{int(sayi):,}".replace(",", ".")
    # Ondalıkta Türkçe virgül; anlamsız sıfırlar atılır.
    return format(sayi.normalize(), "f").rstrip("0").rstrip(".").replace(".", ",")


def _tarih_metni(deger: object) -> str | None:
    """`date` nesnesini `31 Aralık 2026` biçimine çevirir."""
    gun = getattr(deger, "day", None)
    ay = getattr(deger, "month", None)
    yil = getattr(deger, "year", None)
    if gun is None or ay is None or yil is None:
        return None
    return f"{gun} {_MONTHS[ay - 1]} {yil}"


def _validated_fields(session: Session, campaign_id: int) -> dict[str, str]:
    """Kampanyanın karta girebilecek alanlarını döndürür.

    ⚠️ Üç koşul birden aranır: reddedilmemiş, doğrulanmış, güveni yeterli.
    """
    secilen: dict[str, tuple[Decimal, str]] = {}
    for kayit in session.scalars(
        select(CampaignExtraction).where(
            CampaignExtraction.campaign_id == campaign_id,
            CampaignExtraction.rejected_reason.is_(None),
            CampaignExtraction.is_validated.is_(True),
            CampaignExtraction.confidence >= MIN_CARD_CONFIDENCE,
        )
    ):
        if kayit.value_normalized is None:
            continue
        guven = kayit.confidence or Decimal("0")
        mevcut = secilen.get(kayit.field_name)
        if mevcut is None or guven > mevcut[0]:
            secilen[kayit.field_name] = (guven, kayit.value_normalized)

    return {ad: deger for ad, (_, deger) in secilen.items()}


def _labels(session: Session, campaign_id: int) -> dict[str, list[str]]:
    """Kampanyanın etiketlerini eksen bazında döndürür."""
    gruplar: dict[str, list[str]] = {}
    for kayit in session.scalars(
        select(CampaignCategory)
        .where(
            CampaignCategory.campaign_id == campaign_id,
            CampaignCategory.confidence >= MIN_CARD_CONFIDENCE,
        )
        .order_by(CampaignCategory.confidence.desc())
    ):
        gruplar.setdefault(kayit.axis, []).append(kayit.value)
    return gruplar


def build_campaign_card(session: Session, campaign: Campaign) -> str:
    """Kampanyayı doğal Türkçe bir karta çevirir.

    Args:
        session: Veritabanı oturumu.
        campaign: Kartı üretilecek kampanya.

    Returns:
        Kart metni.
    """
    banka = session.get(Bank, campaign.bank_id)
    banka_adi = banka.name if banka else "Bilinmeyen banka"

    satirlar = [f"{banka_adi} — {campaign.title}"]

    if campaign.description:
        satirlar.append(campaign.description.strip())

    etiketler = _labels(session, campaign.id)
    etiket_parcalari = []
    for eksen, baslik in (
        ("sector", "Sektör"),
        ("product_type", "Ürün"),
        ("audience", "Hedef kitle"),
        ("benefit", "Fayda"),
    ):
        degerler = etiketler.get(eksen)
        if degerler:
            # Kontrollü sözlük değerleri alt çizgili; kartta okunur hâle getirilir.
            okunur = ", ".join(d.replace("_", " ") for d in degerler[:3])
            etiket_parcalari.append(f"{baslik}: {okunur}.")
    if etiket_parcalari:
        satirlar.append(" ".join(etiket_parcalari))

    alanlar = _validated_fields(session, campaign.id)
    olcum_parcalari = [
        kalip.format(deger=_sayi_metni(alanlar[ad]))
        for ad, kalip in FIELD_PHRASES.items()
        if ad in alanlar
    ]
    if olcum_parcalari:
        satirlar.append(_bas_harf_buyut(", ".join(olcum_parcalari)) + ".")

    # ⚠️ Tarih `campaigns` tablosundan okunur; guard'dan geçmiş `campaign_metrics`
    # değil. Tarih zaten kendi doğrulamasından geçiyor (`date_precision`).
    baslangic = _tarih_metni(campaign.start_date)
    bitis = _tarih_metni(campaign.end_date)
    if baslangic and bitis:
        satirlar.append(f"Geçerlilik: {baslangic} – {bitis}.")
    elif bitis:
        satirlar.append(f"Geçerlilik: {bitis} tarihine kadar.")
    elif baslangic:
        satirlar.append(f"Başlangıç: {baslangic}.")
    else:
        # ⚠️ Tarihsizlik GİZLENMEZ. "Süresi dolmuş" ile "tarihi bilinmiyor"
        # ayrı şeylerdir (CLAUDE.md).
        satirlar.append("Geçerlilik tarihi kaynakta belirtilmemiş.")

    if campaign.summary_ai:
        satirlar.append(campaign.summary_ai.strip())

    return "\n".join(satirlar)


def build_bank_card(session: Session, bank: Bank) -> str:
    """Bankayı ve veri durumunu karta çevirir."""
    kampanya_sayisi = len(
        session.scalars(select(Campaign.id).where(Campaign.bank_id == bank.id)).all()
    )
    satirlar = [f"{bank.name} — katılım bankası", f"Adres: {bank.website}"]
    if kampanya_sayisi:
        satirlar.append(f"Veri setinde {kampanya_sayisi} kampanyası bulunuyor.")
    else:
        # ⚠️ "Veri yok" bilgisi de bir bulgudur, gizlenmez (CLAUDE.md).
        satirlar.append("Yayımlanmış kampanya sayfası bulunamadı.")
    if bank.notes:
        satirlar.append(bank.notes.strip())
    return "\n".join(satirlar)


def build_glossary_card(term: GlossaryTerm) -> str:
    """Sözlük terimini karta çevirir."""
    satirlar = [f"{term.term} — katılım bankacılığı terimi"]
    if term.definition:
        satirlar.append(term.definition.strip())
    if term.is_forbidden_conventional and term.conventional_equivalent:
        satirlar.append(
            f"Konvansiyonel bankacılıktaki karşılığı: {term.conventional_equivalent}. "
            "Katılım bankacılığında bu terim kullanılmaz."
        )
    elif term.conventional_equivalent:
        satirlar.append(f"Konvansiyonel karşılığı: {term.conventional_equivalent}.")
    return "\n".join(satirlar)


def build_product_card(session: Session, product: Product) -> str:
    """Ürünü karta çevirir — açıklama, oran bantları, BDDK tavanı dahil."""
    from app.services.bddk_limits_service import get_canonical_limits

    banka = session.get(Bank, product.bank_id)
    banka_adi = banka.name if banka else "Bilinmeyen banka"

    satirlar = [f"{banka_adi} — {product.name}"]
    if product.product_type:
        satirlar.append(f"Finansman türü: {product.product_type.replace('_', ' ')}.")
    if product.description:
        satirlar.append(product.description.strip()[:800])

    sinirlar = []
    if product.amount_min is not None and product.amount_max is not None:
        sinirlar.append(
            f"{_sayi_metni(str(product.amount_min))} - "
            f"{_sayi_metni(str(product.amount_max))} TL finansman"
        )
    if product.term_months_max is not None:
        sinirlar.append(f"{product.term_months_max} aya kadar vade")
    if sinirlar:
        satirlar.append(_bas_harf_buyut(", ".join(sinirlar)) + ".")

    # Oran özetleri (en fazla 3 satır)
    oran_ozetleri: list[str] = []
    for oran in list(product.rates)[:3]:
        if oran.profit_rate_pct is None:
            continue
        parca = f"kâr payı %{_sayi_metni(str(oran.profit_rate_pct))}"
        if oran.term_months is not None:
            parca = f"{oran.term_months} ay · {parca}"
        if oran.allocation_fee_pct is not None:
            parca += f", tahsis %{_sayi_metni(str(oran.allocation_fee_pct))}"
        if oran.annual_cost_pct is not None:
            parca += f", yıllık maliyet %{_sayi_metni(str(oran.annual_cost_pct))}"
        if not oran.is_binding:
            parca += " (hesaplayıcı tahmini)"
        oran_ozetleri.append(parca)
    if oran_ozetleri:
        satirlar.append("Oranlar: " + "; ".join(oran_ozetleri) + ".")

    bddk = get_canonical_limits(product_type=product.product_type)
    if bddk is not None:
        satirlar.append(
            f"BDDK yasal tavan ({bddk.family}): {bddk.legal_reference}."
        )
        if bddk.family == "ihtiyac" and bddk.bands:
            ozet = ", ".join(
                f"{b.label} → {b.max_term_months} ay" for b in bddk.bands if b.max_term_months
            )
            if ozet:
                satirlar.append(f"İhtiyaç vade tavanları: {ozet}.")
        if bddk.second_home_note:
            satirlar.append(bddk.second_home_note)

    if not product.is_binding:
        satirlar.append(NON_BINDING_NOTICE)

    return "\n".join(satirlar)


def build_product_rate_card(session: Session, rate: ProductRate) -> str:
    """Ürün oranını karta çevirir."""
    urun = session.get(Product, rate.product_id)
    urun_adi = urun.name if urun else "Bilinmeyen ürün"
    banka = session.get(Bank, urun.bank_id) if urun else None
    banka_adi = banka.name if banka else "Bilinmeyen banka"

    satirlar = [f"{banka_adi} — {urun_adi} kâr payı oranı"]

    parcalar = []
    if rate.term_months is not None:
        parcalar.append(f"{rate.term_months} ay vade")
    if rate.profit_rate_pct is not None:
        parcalar.append(f"kâr payı oranı %{_sayi_metni(str(rate.profit_rate_pct))}")
    if rate.allocation_fee_pct is not None:
        parcalar.append(f"tahsis ücreti %{_sayi_metni(str(rate.allocation_fee_pct))}")
    if rate.annual_cost_pct is not None:
        parcalar.append(f"yıllık maliyet oranı %{_sayi_metni(str(rate.annual_cost_pct))}")
    if rate.amount_min is not None or rate.amount_max is not None:
        parcalar.append(
            f"tutar {_sayi_metni(str(rate.amount_min or ''))}-"
            f"{_sayi_metni(str(rate.amount_max or ''))} TL"
        )
    if parcalar:
        satirlar.append(_bas_harf_buyut(", ".join(parcalar)) + ".")

    if rate.variant:
        satirlar.append(f"Varyant: {rate.variant}.")
    if rate.rate_source:
        satirlar.append(f"Kaynak: {rate.rate_source}.")

    # ⚠️ Hesaplayıcıdan türetilmiş oran bağlayıcı değildir.
    if (urun is not None and not urun.is_binding) or not rate.is_binding:
        satirlar.append(NON_BINDING_NOTICE)

    return "\n".join(satirlar)


def card_hash(card_text: str) -> str:
    """Kart metninin sha256 özeti.

    Değişmeyen kart yeniden üretilmez; gömme (SPRINT 5) pahalıdır.
    """
    return sha256_text(card_text)
