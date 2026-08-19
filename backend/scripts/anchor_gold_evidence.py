"""Kanıtı boş gold etiketlerine metinden bağlamlı kanıt bağlar (ağa çıkmaz).

⚠️ BU BİR İNSAN DOĞRULAMASI DEĞİLDİR. Betik, etiketin DEĞERİNİ metinde arar ve
çevresindeki cümle parçasını kanıt olarak yazar. Değerin doğruluğunu denetlemez;
yalnızca "bu değer metnin şu yerinde geçiyor" bağını kurar.

Bu ayrımı kaybetmemek için yazılan her kanıt `note='oto-kanit'` ile
işaretlenir ve `gold-durum` raporu insan seçimi ile otomatik bağlamayı AYRI
sayar. Aksi hâlde rapor "kanıt denetimi temiz" der ve sahip olmadığımız bir
titizliği iddia etmiş oluruz.

⚠️ ÇIPLAK RAKAM KANIT DEĞİLDİR. `min_spend_try=5000` için "5000" dizesini
bulmak yetmez; metinde o rakam başka bir şeyi de anlatıyor olabilir. Bu yüzden
her alan için yakınında bulunması ZORUNLU bir birim/bağlam aranır ("TL", "%",
"taksit", "vade"). Bağlam yoksa etiket ELLE bırakılır.

⚠️ Sınıflandırma alanları (`product_type`, `sector`, `target_customer`)
otomatik bağlanmaz. Metin "seyahat_konaklama" yazmaz; hangi ifadenin o
kategoriyi doğurduğu insan yargısıdır.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.vocab import OTO_KANIT_NOTU
from app.db.models.campaign import Campaign
from app.db.models.gold_annotation import GoldAnnotation
from app.db.models.source_document import SourceDocument
from app.db.session import SessionLocal
from app.logging_config import configure_logging, get_logger

logger = get_logger(__name__)

# Otomatik bağlamanın uygulanmayacağı alanlar: değer metinde birebir geçmez.
SINIFLANDIRMA_ALANLARI: frozenset[str] = frozenset(
    {"product_type", "sector", "target_customer", "reward_type", "has_no_fee"}
)

# Alan → kanıt penceresinde bulunması zorunlu bağlam kalıbı.
# Bağlamı olmayan alan otomatik bağlanmaz; çıplak rakam kanıt sayılmaz.
BAGLAM_KALIPLARI: dict[str, str] = {
    "reward_amount_try": r"TL|₺|lira",
    "min_spend_try": r"TL|₺|lira",
    "max_spend_try": r"TL|₺|lira",
    "financing_amount_min": r"TL|₺|lira",
    "financing_amount_max": r"TL|₺|lira",
    "aggregate_cap_try": r"TL|₺|lira",
    "cashback_pct": r"%",
    "discount_pct": r"%",
    "profit_rate_pct": r"%",
    # ⚠️ Bölüşüm oranı "%2" diye YAZILMIYOR: "98/2 paylaşım oranlı" deniyor.
    # Yalnızca "%" arandığında bu satırlar kanıtsız kalıyordu.
    "profit_share_rate_pct": r"%|/\s?\d|paylas|paylaş|bolus|bölüş",
    "installment_count": r"taksit",
    # ⚠️ "6 taksite kadar" bir VADE ifadesidir; banka "6 ay" demiyor.
    "term_months_min": r"ay\b|vade|taksit",
    "term_months_max": r"ay\b|vade|taksit",
    # ⚠️ Bankalar "puan" demiyor, MARKA ADI kullanıyor: "ParafPara",
    # "Bankkart Lira", "WorldPuan". Yalnızca "puan|mil" arandığında bu
    # satırlar kanıtsız kalıyordu.
    "loyalty_points": r"puan|mil|lira|parafpara|paraf para|bankkart|world|maximum",
}

AY_ADLARI: tuple[str, ...] = (
    "",
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

# Kanıt penceresinin değerin iki yanına eklediği karakter sayısı.
_PENCERE = 45

# Bu uzunluğun altındaki kanıt bağlam taşımaz, yazılmaz.
_ASGARI_KANIT = 12

def _sayi_yazimlari(deger: str) -> list[str]:
    """Sayısal değerin metinde geçebileceği yazımlarını üretir.

    `5000` → `"5.000"`, `"5000"`; `2.79` → `"2,79"` (Türkçe ondalık ayracı).
    """
    yazimlar: list[str] = []
    if not re.fullmatch(r"\d+(\.\d+)?", deger):
        return yazimlar

    sayi = float(deger)
    if sayi == int(sayi):
        tam = int(sayi)
        yazimlar += [f"{tam:,}".replace(",", "."), str(tam)]
    if "." in deger:
        yazimlar.append(deger.replace(".", ","))
    return list(dict.fromkeys(yazimlar))


def _tarih_yazimlari(deger: str) -> list[str]:
    """ISO tarihin metinde geçebileceği Türkçe yazımlarını üretir."""
    eslesme = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", deger)
    if not eslesme:
        return []

    yil, ay, gun = eslesme.groups()
    # ⚠️ Bankalar başındaki sıfırı ATIYOR: "1.01.2027", "9 Haziran 2026".
    # Yalnızca sıfır dolgulu biçim arandığında bu tarihler bulunamıyordu.
    g_kisa, ay_kisa = str(int(gun)), str(int(ay))
    return [
        f"{gun}.{ay}.{yil}",
        f"{g_kisa}.{ay}.{yil}",
        f"{g_kisa}.{ay_kisa}.{yil}",
        f"{gun}-{ay}-{yil}",
        f"{g_kisa}-{ay}-{yil}",
        f"{gun}/{ay}/{yil}",
        f"{g_kisa}/{ay}/{yil}",
        f"{g_kisa} {AY_ADLARI[int(ay)]} {yil}",
        f"{gun} {AY_ADLARI[int(ay)]} {yil}",
        # ⚠️ Aralık yazımında YIL YALNIZCA İKİNCİ tarihte olur:
        # "Kampanya, 17 Ağustos - 17 Eylül 2026 tarihleri arasında".
        # Başlangıç tarihi yılsız kaldığı için yıllı biçimlerin hiçbiri
        # tutmuyordu. Yıllı yazımlar önce denenir; bu yalnızca son çare.
        f"{g_kisa} {AY_ADLARI[int(ay)]}",
        f"{gun} {AY_ADLARI[int(ay)]}",
    ]


def _pencere_kirp(metin: str, bas: int, son: int) -> str:
    """Pencereyi kelime sınırlarına hizalayarak kırpar."""
    sol = metin.find(" ", bas) + 1 if bas > 0 else 0
    parca = metin[sol:son]
    if son < len(metin):
        parca = parca.rsplit(" ", 1)[0]
    return parca.strip()


def kanit_bul(field_name: str, gold_value: str, clean_text: str) -> str | None:
    """Değeri metinde arar, bağlamıyla birlikte kanıt parçası döndürür.

    Args:
        field_name: Etiketin alan adı.
        gold_value: Etiketin değeri.
        clean_text: Kampanyanın boşlukları sadeleştirilmiş temiz metni.

    Returns:
        Bağlam taşıyan kanıt parçası; bulunamazsa None.

    """
    if not clean_text or field_name in SINIFLANDIRMA_ALANLARI:
        return None

    # Tarih yazımı kendi başına ayırt edicidir; ek bağlam aranmaz.
    for yazim in _tarih_yazimlari(gold_value):
        yer = clean_text.find(yazim)
        if yer >= 0:
            return _pencere_kirp(
                clean_text, max(0, yer - 30), min(len(clean_text), yer + len(yazim) + 30)
            )

    kalip = BAGLAM_KALIPLARI.get(field_name)
    if kalip is None:
        return None

    for yazim in _sayi_yazimlari(gold_value):
        # ⚠️ Sayı bir başka sayının PARÇASI olmamalı ("75" ile "175 TL"
        # karışmasın) ama ardından gelen NOKTALAMA eşleşmeyi bozmamalı.
        # Önceki sürüm `(?![\d.,])` kullanıyordu; "%10, toplam 500 TL"
        # ifadesindeki virgülü ondalık ayracı sanıp satırı reddediyordu.
        desen = (
            r"(?<!\d)(?<!\d[.,])" + re.escape(yazim) + r"(?!\d)(?![.,]\d)"
        )
        for eslesme in re.finditer(desen, clean_text):
            bas = max(0, eslesme.start() - _PENCERE)
            son = min(len(clean_text), eslesme.end() + _PENCERE)
            if re.search(kalip, clean_text[bas:son], re.IGNORECASE):
                return _pencere_kirp(clean_text, bas, son)
    return None


def _temiz_metinler(session: Session) -> dict[int, str]:
    """Kampanya kimliği → sadeleştirilmiş temiz metin."""
    satirlar = session.execute(
        select(Campaign.id, SourceDocument.clean_text).outerjoin(
            SourceDocument, Campaign.source_document_id == SourceDocument.id
        )
    ).all()
    return {cid: " ".join((metin or "").split()) for cid, metin in satirlar}


def calistir(session: Session, *, kuru: bool) -> Counter[str]:
    """Kanıtı boş etiketleri tarar ve bağlanabilenleri işaretleyerek yazar."""
    metinler = _temiz_metinler(session)
    sayac: Counter[str] = Counter()

    etiketler = list(
        session.scalars(
            select(GoldAnnotation).where(
                GoldAnnotation.gold_value.is_not(None),
                GoldAnnotation.gold_value != "",
            )
        )
    )

    for etiket in etiketler:
        if (etiket.evidence_text or "").strip():
            continue

        if etiket.field_name in SINIFLANDIRMA_ALANLARI:
            sayac["elle: sınıflandırma alanı"] += 1
            continue

        kanit = kanit_bul(
            etiket.field_name, str(etiket.gold_value), metinler.get(etiket.campaign_id, "")
        )
        if kanit is None or len(kanit) < _ASGARI_KANIT:
            sayac["elle: bağlamlı eşleşme yok"] += 1
            continue

        sayac["otomatik bağlandı"] += 1
        if not kuru:
            etiket.evidence_text = kanit
            etiket.note = OTO_KANIT_NOTU

    if not kuru:
        session.commit()
    return sayac


def main(argv: list[str] | None = None) -> int:
    """Komut satırı girişi."""
    ayristirici = argparse.ArgumentParser(
        prog="anchor_gold_evidence",
        description="Kanıtı boş gold etiketlerine metinden bağlamlı kanıt bağlar.",
    )
    ayristirici.add_argument(
        "--kuru", action="store_true", help="Yazma yapma, yalnızca kaç etiket bağlanacağını raporla"
    )
    secenekler = ayristirici.parse_args(argv)

    configure_logging()
    with SessionLocal() as session:
        sayac = calistir(session, kuru=secenekler.kuru)

    logger.info(
        "gold_kanit_baglama_bitti",
        kuru=secenekler.kuru,
        **{k.replace(" ", "_").replace(":", ""): v for k, v in sayac.items()},
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
