"""Hesaplayıcı envanterini ürün limitlerine uygular (SPRINT 2 §3.4).

`kesif-hesaplayici` sayfanın NE SUNDUĞUNU `calculator_inventory` tablosuna
yazar; bu betik o envanteri `products` satırlarına bağlar. AĞA ÇIKMAZ.

⚠️ VADE SEÇİCİSİ DEĞİL, SEÇENEK ETİKETİ ESAS ALINIR. Ziraat Katılım'ın
hesaplayıcısı sitenin tamamında ortak: tek dropdown 17 finansman türünü
sunuyor ve vade seçicisi 1-60 listeliyor. Bu BİRLEŞİK bir listedir; hiçbir
ürün 60 ay vermiyor. Gerçek sınır etiketin içinde yazılı:

    "TAŞIT FINANSMANI(1-48 AY)"                       -> 48 ay
    "KONUT FINANSMANI (0-10.000.000 TL/1-120 AY))"    -> 120 ay, 10.000.000 TL

Vade seçicisi olduğu gibi yazılsaydı taşıt finansmanı 60 aya kadar
gösterilecekti.

⚠️ EŞLEŞME ZORUNLU, TÜRE GÖRE TOPLU ATAMA YAPILMAZ. "KONUT FINANSMANI"
seçeneğinin 1-120 ay sınırı, aynı türdeki "Kentsel Dönüşüm Finansmanı"
ürününe DE geçerli değildir; o ürünün seçeneği ayrı ve sınırsız. Yalnızca
adı eşleşen ürüne yazılır, gerisi boş kalır.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import select

from app.core.normalization.text import ascii_fold_tr, lower_tr
from app.db.models import Bank, CalculatorInventory, Product
from app.db.session import SessionLocal
from app.logging_config import configure_logging, get_logger
from app.scrapers.calculator_inventory import OptionLimits, parse_option_limits

logger = get_logger(__name__)

# Eşleşme için anlamsız olan, her üründe geçen kelimeler.
DURAK_KELIMELER: frozenset[str] = frozenset(
    {"finansmani", "finansman", "kampanya", "paketi", "bireysel", "ay", "tl"}
)

# Finansman seçeneğinin yazılabileceği ürün türleri. Hesap ve kart ürünleri
# DIŞARIDA: bir birikim hesabına finansman vadesi yazılamaz.
FINANSMAN_TURLERI: frozenset[str] = frozenset(
    {
        "finansman",
        "konut_finansmani",
        "tasit_finansmani",
        "ihtiyac_finansmani",
        "isyeri_finansmani",
        "kobi_ticari",
    }
)


def _tokenlar(text: str) -> set[str]:
    """Metni eşleştirme belirteçlerine ayırır.

    ⚠️ YALNIZCA TEK KELİMELER. Birleşik biçim ("konutfinansmani") belirteç
    listesine EKLENMEZ: eklendiğinde zorunlu koşula dönüşüyor ve
    "KONUT FINANSMANI" seçeneği `konut-gayrimenkul-finansmani` ürününe
    bağlanamıyordu — araya "gayrimenkul" girdiği için birleşik dize
    tutmuyor. Birleşik karşılaştırma HEDEF tarafında yapılır (`_eslesir`).
    """
    katlanmis = ascii_fold_tr(lower_tr(text or "")).replace("-", " ").replace("/", " ")
    return {parca for parca in katlanmis.split() if parca and parca not in DURAK_KELIMELER}


def _eslesir(secenek: OptionLimits, urun: Product) -> bool:
    """Seçenek etiketi bu ürünü mü anlatıyor?

    İki koşul birden aranır:

    1. **Tür uyumu.** "…FİNANSMANI" seçeneği yalnızca finansman ürününe
       yazılır. ⚠️ Bu denetim olmadan "KONUT FINANSMANI" seçeneğinin
       1-120 ay / 10.000.000 TL sınırı `konut-hesabi` (birikim katılma
       hesabı) ürününe de yazılıyordu — tasarruf hesabına finansman vadesi
       yazmak veriyi tamamen yanlış gösterir.

    2. **Ad uyumu.** Ayırt edici belirteçlerin TAMAMI ürünün adında ya da
       anahtarında geçmelidir. Kısmi eşleşme kabul edilseydi "KONUT
       FINANSMANI" seçeneği "Kentsel Dönüşüm Finansmanı"na da yazılırdı.
    """
    if "finansman" in ascii_fold_tr(lower_tr(secenek.product_name)):
        if urun.product_type not in FINANSMAN_TURLERI:
            return False

    aranan = _tokenlar(secenek.product_name)
    ayirt_edici = {t for t in aranan if len(t) > 3}
    if not ayirt_edici:
        return False

    hedef = ascii_fold_tr(lower_tr(f"{urun.name} {urun.external_key}")).replace("-", " ")
    hedef_birlesik = hedef.replace(" ", "")
    return all(t in hedef or t in hedef_birlesik for t in ayirt_edici)


def _birlestir(secenekler: list[OptionLimits]) -> OptionLimits:
    """Aynı ürüne ait birden çok paketi tek limite indirger.

    ⚠️ EN GENİŞ ARALIK ALINIR. Taşıt finansmanının dört paketi var
    (1-12, 1-24, 1-36, 1-48); bankanın sunduğu en uzun vade 48'dir.
    """
    altlar = [s.term_months_min for s in secenekler if s.term_months_min is not None]
    ustler = [s.term_months_max for s in secenekler if s.term_months_max is not None]
    tavanlar = [s.amount_max for s in secenekler if s.amount_max is not None]
    tabanlar = [s.amount_min for s in secenekler if s.amount_min is not None]
    return OptionLimits(
        label=" · ".join(s.label for s in secenekler),
        product_name=secenekler[0].product_name,
        term_months_min=min(altlar) if altlar else None,
        term_months_max=max(ustler) if ustler else None,
        amount_min=min(tabanlar) if tabanlar else None,
        amount_max=max(tavanlar) if tavanlar else None,
    )


def _secenekleri_topla(session: object) -> dict[int, list[OptionLimits]]:
    """Banka kimliği → o bankanın envanterindeki seçenek limitleri."""
    toplanan: dict[int, list[OptionLimits]] = defaultdict(list)
    for envanter in session.scalars(select(CalculatorInventory)):  # type: ignore[attr-defined]
        # ⚠️ JSON kolonu SQLAlchemy tarafından ÇÖZÜLMÜŞ geliyor; dizeyi
        # yeniden çözmeye çalışmak `TypeError` verir. İki biçim de kabul
        # edilir, çünkü dışa aktarma dosyalarında ham dize olarak duruyor.
        ham = envanter.input_fields or {}
        alanlar = json.loads(ham) if isinstance(ham, str) else ham
        for tanim in alanlar.values():
            for secenek in tanim.get("options") or []:
                limit = parse_option_limits(str(secenek.get("label", "")))
                # Sınır taşımayan seçenek bilgi vermez; yazılacak bir şey yok.
                if limit is None or (
                    limit.term_months_max is None and limit.amount_max is None
                ):
                    continue
                toplanan[envanter.bank_id].append(limit)
    return toplanan


def main(argv: list[str] | None = None) -> int:
    """Betiğin giriş noktası."""
    ayristirici = argparse.ArgumentParser(description="Hesaplayıcı envanterini ürünlere uygula")
    ayristirici.add_argument("--banka", help="Yalnızca bu banka kodunu işle")
    ayristirici.add_argument("--kuru", action="store_true", help="Yazma yapma, yalnızca raporla")
    argumanlar = ayristirici.parse_args(argv)

    configure_logging()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    guncellenen = 0
    eslesmeyen: list[str] = []

    with SessionLocal() as session:
        secenekler = _secenekleri_topla(session)
        if not secenekler:
            print("Envanterde sınır taşıyan seçenek yok. Önce `kesif-hesaplayici` çalıştırın.")
            return 1

        for bank_id, liste in secenekler.items():
            bank = session.get(Bank, bank_id)
            if bank is None or (argumanlar.banka and bank.code != argumanlar.banka):
                continue

            urunler = list(
                session.scalars(
                    select(Product).where(
                        Product.bank_id == bank_id, Product.parent_product_id.is_(None)
                    )
                )
            )
            print(f"\n{bank.code}: {len(liste)} sınırlı seçenek, {len(urunler)} ürün")

            # Aynı ürün adına ait paketleri grupla.
            gruplar: dict[str, list[OptionLimits]] = defaultdict(list)
            for secenek in liste:
                gruplar[secenek.product_name].append(secenek)

            for ad, grup in sorted(gruplar.items()):
                limit = _birlestir(grup)
                hedefler = [u for u in urunler if _eslesir(limit, u)]
                if not hedefler:
                    eslesmeyen.append(f"{bank.code}: {ad}")
                    print(f"   ✗ {ad:<38} eşleşen ürün yok")
                    continue

                for urun in hedefler:
                    _uygula(urun, limit, kuru=argumanlar.kuru)
                    guncellenen += 1
                adlar = ", ".join(u.external_key for u in hedefler)
                print(
                    f"   ✓ {ad:<38} vade={limit.term_months_min}-{limit.term_months_max} "
                    f"tavan={limit.amount_max}  -> {adlar}"
                )

        if argumanlar.kuru:
            session.rollback()
            print(f"\nKURU ÇALIŞTIRMA — {guncellenen} ürün güncellenecekti, yazılmadı.")
        else:
            session.commit()
            print(f"\n{guncellenen} ürün güncellendi.")

    if eslesmeyen:
        print(f"\n⚠️ {len(eslesmeyen)} seçenek hiçbir ürüne bağlanamadı:")
        for satir in eslesmeyen:
            print(f"   - {satir}")
        print("   Bunlar whitelist'te olmayan ürünler olabilir; sessizce atlanmadı.")

    return 0


def _uygula(urun: Product, limit: OptionLimits, *, kuru: bool) -> None:
    """Limitleri ürüne yazar.

    ⚠️ ETİKET SINIRI VADE ALANINI KOŞULSUZ EZER.

    Ziraat'in ortak hesaplayıcısı SUNUCU HTML'İNDE bulunuyor ve vade
    seçicisi 1-60 listeliyor. Ürün kazıması bu BİRLEŞİK aralığı her Ziraat
    ürününe `term_months_max=60` olarak yazıyor — taşıt finansmanına da,
    eğitim finansmanına da.

    Birleşik liste HİÇBİR ÜRÜNÜN gerçek sınırı değil; kimi üründen geniş
    (taşıt gerçekte 48), kimi üründen dar (konut gerçekte 120). Bu yüzden
    "boşsa yaz" da "dar olan kazanır" da yanlış sonuç verir — ikisi de
    denendi ve konut 120 yerine 60'ta kaldı.

    Seçenek etiketi ("TAŞIT FINANSMANI(1-48 AY)") ürüne özel, bankanın
    kendi yazdığı bir sınırdır ve birleşik seçiciden HER DURUMDA daha iyi
    kanıttır.

    ⚠️ `amount_max` ezilmez: tutar tavanı statik tablodan da gelebiliyor ve
    o kaynak (`html_table`) daha güçlü.
    """
    if kuru:
        return

    if limit.term_months_min is not None:
        urun.term_months_min = limit.term_months_min
    if limit.term_months_max is not None:
        urun.term_months_max = limit.term_months_max
    if limit.amount_max is not None and urun.amount_max is None:
        urun.amount_max = Decimal(limit.amount_max)

    # Envanter kaynaklı limit `html_attr`; yalnızca daha zayıf kaynağı yükseltir.
    if urun.limits_source in {"none", "text"}:
        urun.limits_source = "html_attr"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
