"""`source_documents.clean_text` alanını HAM HTML ARŞİVİNDEN yeniden üretir.

⚠️ AĞA ÇIKMAZ. Kaynak `data/raw_html/` altındaki, daha önce çekilmiş
sayfalardır. Bankalara tek bir yeni istek gitmez.

NEDEN GEREKLİ: Ön işlemede yabancı kampanya blokları (§6.1) ayıklanmıyordu;
`app/processing/boilerplate.py` bu sprint'te yazıldı. Arşivdeki HTML
değişmediği için metin, siteye dönmeden yeniden üretilebilir.

ÖLÇÜLEN ETKİ (495 kampanya):
    Metninde 4+ farklı tarih bulunan       56 → 2
    Ziraat Katılım temiz/eski metin oranı  0.63
    Kuveyt Türk temiz/eski metin oranı     0.53

DOĞRULAMA: Ham HTML'in sha256 özeti `raw_html_sha256` ile karşılaştırılır;
tutmayan dosya İŞLENMEZ ve raporlanır. Böylece arşiv bozulmuşsa sessizce
yanlış metin üretilmez.

KAPSAM DOĞRULAMASI (RAG için kritik): Kampanyanın `conditions_text` ve
`description` alanları yeni metnin İÇİNDE olmalıdır. Ayıklama bunları
kesmişse kayıt `kapsam_kaybi` olarak raporlanır — arama ve gömme (SPRINT 5)
eksik metin üzerinde çalışamaz.

Çalıştırma:
    python dev.py yeniden-isle
    python dev.py yeniden-isle --kuru            # yazmaz, yalnızca raporlar
    python dev.py yeniden-isle --banka ziraat_katilim
    python dev.py yeniden-isle --ornek 10        # gözle denetim için örnek bas
"""

from __future__ import annotations

import argparse
import hashlib
import random
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Bank, Campaign, SourceDocument
from app.db.session import SessionLocal
from app.logging_config import configure_logging, get_logger
from app.processing.cleaner import clean_html
from app.processing.dates import find_campaign_period
from app.scrapers.base import BaseScraper
from app.scrapers.models import DiscoveredUrl
from app.scrapers.registry import get_scraper
from app.services.campaign_service import compute_status
from app.utils.hashing import sha256_text

logger = get_logger(__name__)

# Metindeki sayısal tarihler — kirlilik göstergesi olarak sayılır.
DATE_RE = re.compile(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{4}\b")

# Bu sayıdan fazla FARKLI tarih taşıyan metin, birden çok kampanya içeriyor
# demektir (§ kök neden analizi).
COKLU_TARIH_ESIGI = 4

# Kapsam doğrulamasında karşılaştırılan en az uzunluk. Daha kısa alanlarda
# alt dize kontrolü anlamlı değildir.
KAPSAM_MIN_UZUNLUK = 80


@dataclass
class BankaOzeti:
    """Tek bankanın yeniden işleme sonucu."""

    islenen: int = 0
    guncellenen: int = 0
    eski_uzunluk: int = 0
    yeni_uzunluk: int = 0
    coklu_tarih_once: int = 0
    coklu_tarih_sonra: int = 0
    bosalan: int = 0
    kapsam_kaybi: list[int] = field(default_factory=list)
    hash_uyusmazligi: int = 0
    dosya_yok: int = 0
    tarih_kazanildi: int = 0
    tarih_tazelendi: int = 0

    @property
    def oran(self) -> float:
        """Yeni metnin eskisine oranı."""
        return self.yeni_uzunluk / self.eski_uzunluk if self.eski_uzunluk else 1.0


def _sikistir(value: str) -> str:
    """Tüm boşluk dizilerini tek boşluğa indirger.

    Karşılaştırma bunun üzerinden yapılır: `conditions_text` bölüm
    ayrıştırıcısından boş satırlı (`\\n\\n`) gelirken gövde metni tek satır
    sonu kullanıyor. Ham karşılaştırma bu farkı içerik kaybı sanıyordu.
    """
    return " ".join(value.split())


def _kapsam_kaybi(campaign: Campaign | None, eski: str, yeni: str) -> bool:
    """Yeniden işleme, ESKİ metinde bulunan kampanya içeriğini sildi mi?

    RAG ve gömme katmanı (SPRINT 5) `clean_text` üzerinden çalışacağı için
    kampanyanın koşul ve açıklama metni eksiksiz kalmalıdır; başlık tek
    başına yeterli değildir.

    ⚠️ Ölçüt bir FARKTIR, mutlak bir kapsam değil. "Alan yeni metinde yok"
    demek yetmez — bazı alanlar (ör. `description`'ın başındaki bölüm
    başlığı) zaten gövdede bitişik geçmiyor ve ESKİ metinde de yoktu.
    Bunları kayıp saymak 40 yanlış uyarı üretiyordu. Yalnızca eskiden VAR
    olup yenide KAYBOLAN içerik gerileme sayılır.

    Args:
        campaign: Belgeye bağlı kampanya; yoksa denetim yapılmaz.
        eski: Önceki temiz metin.
        yeni: Yeni üretilen temiz metin.

    Returns:
        İçerik kaybedildiyse True.
    """
    if campaign is None:
        return False

    eski_sikisik = _sikistir(eski)
    yeni_sikisik = _sikistir(yeni)

    for alan in (campaign.conditions_text, campaign.description):
        deger = _sikistir(alan or "")
        if len(deger) < KAPSAM_MIN_UZUNLUK:
            continue
        parca = deger[:KAPSAM_MIN_UZUNLUK]
        if parca in eski_sikisik and parca not in yeni_sikisik:
            return True
    return False


def _belge_kampanyasi(document: SourceDocument) -> Campaign | None:
    """Belgeye bağlı kampanyayı döndürür (varsa)."""
    return document.campaigns[0] if document.campaigns else None


def _tarih_tazele(
    campaign: Campaign | None,
    html: str,
    clean_text: str,
    scraper: BaseScraper | None,
    *,
    kuru: bool,
) -> tuple[int, int] | None:
    """Kampanya tarihlerini arşivdeki HTML'den YENİDEN türetir.

    ⚠️ `--tarihleri-tazele` ile açılır; varsayılan DEĞİLDİR çünkü mevcut
    değerlerin üzerine yazar.

    NEDEN GEREKLİ: `parse_detail()` gövdeyi `clean_html()`'den okuyor. Ön
    işleme düzeltilmeden önce bu gövde komşu kampanya kartlarını da
    içeriyordu ve Ziraat'te tarih bölümü kartlardaki "Son Gün" satırından
    okunabiliyordu. Ölçüldü: 20 kampanyanın `end_date` değeri komşu
    kampanyadan gelmiş (ör. #195 sayfada 09-02-2026 diyor, veritabanında
    31-08-2026 yazıyordu). Scraper'da hata YOK — kayıtlar düzeltme öncesi
    kazımadan kalma. Aynı HTML bugün ayrıştırılınca doğru tarih çıkıyor.

    YALNIZCA tarih alanları güncellenir. `parse_detail()` başlık, açıklama
    ve koşul metnini de üretir ama onlara dokunulmaz: bu betiğin işi metin
    tazelemektir, kampanya kaydını yeniden yazmak değil.

    Args:
        campaign: Belgeye bağlı kampanya.
        html: Arşivden okunan ham HTML.
        clean_text: Yeniden üretilmiş temiz metin (tarih geri dolgusu için).
        scraper: Bankanın scraper örneği.
        kuru: True ise yalnızca sayar, yazmaz.

    Returns:
        Değişiklik varsa (eski, yeni) tarih çifti yerine basit bir işaret
        olarak `(1, 1)`; değişiklik yoksa None.
    """
    if campaign is None or scraper is None:
        return None

    hint = DiscoveredUrl(url=campaign.source_url, doc_type="campaign", discovery_method="listing")
    try:
        raw = scraper.parse_detail(html, campaign.source_url, hint)
    except Exception as hata:  # pragma: no cover - tek kaydın hatası akışı durdurmaz
        logger.warning("tarih_tazeleme_basarisiz", kampanya_id=campaign.id, hata=str(hata))
        return None

    if raw is None:
        return None

    # ⚠️ Scraper'ın kazıma akışındaki SON adımı burada da uygulanmalı.
    # `_fill_missing_dates()` `_process_url()` içinde çağrılıyor, `parse_detail()`
    # içinde değil. Atlanınca Türkiye Finans'ın metinden çıkarılmış 16 tarihi
    # `None`'a geri dönüyordu: tazeleme, kazımanın ürettiğinden DAHA AZ veri
    # üretmiş oluyordu.
    BaseScraper._fill_missing_dates(raw, clean_text)

    if raw.start_date == campaign.start_date and raw.end_date == campaign.end_date:
        return None

    # ⚠️ Dolu bir tarih BOŞALTILMAZ. Tazelemenin işi yanlış değeri düzeltmek;
    # veriyi silmek değil. Ayrıştırma bir gerileme yaşarsa bu koruma, sessiz
    # veri kaybını engeller.
    if raw.start_date is None and raw.end_date is None:
        logger.warning(
            "tarih_tazeleme_bos_dondu",
            kampanya_id=campaign.id,
            mevcut_bitis=str(campaign.end_date),
        )
        return None

    if not kuru:
        campaign.start_date = raw.start_date
        campaign.end_date = raw.end_date
        campaign.date_precision = raw.date_precision
        campaign.status = compute_status(raw.start_date, raw.end_date)
    return (1, 1)


def _tarih_geri_doldur(campaign: Campaign | None, yeni: str, *, kuru: bool) -> bool:
    """Tarihi hiç olmayan kampanyanın dönemini temiz metinden geri doldurur.

    ⚠️ Yalnızca HER İKİ tarih de boşsa çalışır; mevcut bir tarihin üzerine
    ASLA yazmaz. Scraper'ın yapısal alandan okuduğu değer her zaman önceliklidir.

    Kazanım ölçüldü: Türkiye Finans'ın 22 kampanyasının tamamı `unknown`
    kayıtlıydı; 16'sının dönemi metinden güvenilir biçimde çıkarılabiliyor.
    Kalan 6'sı `unknown` KALIR — metinlerinde yalnızca uygunluk koşulu tarihi
    ya da yılsız aralık var; tarih uydurulmaz.

    Args:
        campaign: Belgeye bağlı kampanya.
        yeni: Yeniden üretilmiş temiz metin.
        kuru: True ise yalnızca sayar, yazmaz.

    Returns:
        Tarih kazanıldıysa True.
    """
    if campaign is None:
        return False
    if campaign.start_date is not None or campaign.end_date is not None:
        return False

    start, end, precision = find_campaign_period(yeni)
    if precision == "unknown":
        return False

    if not kuru:
        campaign.start_date = start
        campaign.end_date = end
        campaign.date_precision = precision
        # `status` tek doğruluk kaynağı `compute_status`'tır; tarih değişince
        # yeniden hesaplanmalıdır (bkz. CLAUDE.md).
        campaign.status = compute_status(start, end)
    return True


def _isle(
    session: Session,
    *,
    banka_kodu: str | None,
    kuru: bool,
    ornek_sayisi: int,
    tarihleri_tazele: bool = False,
) -> dict[str, BankaOzeti]:
    """Arşivi tarar, temiz metni yeniden üretir ve özet döndürür."""
    kok = get_settings().raw_html_path
    ozet: dict[str, BankaOzeti] = defaultdict(BankaOzeti)
    ornek_havuzu: list[tuple[str, int, str, str]] = []
    # Scraper örnekleri banka başına bir kez kurulur; ağ kullanılmaz,
    # yalnızca `parse_detail()` çağrılır.
    scraperlar: dict[str, BaseScraper | None] = {}

    sorgu = (
        select(SourceDocument, Bank.code)
        .join(Bank, SourceDocument.bank_id == Bank.id)
        .where(SourceDocument.raw_html_path.isnot(None))
        .where(SourceDocument.doc_type == "campaign")
    )
    if banka_kodu:
        sorgu = sorgu.where(Bank.code == banka_kodu)

    for document, kod in session.execute(sorgu):
        istatistik = ozet[kod]
        if tarihleri_tazele and kod not in scraperlar:
            try:
                scraperlar[kod] = get_scraper(kod)
            except Exception:
                # Scraper'ı olmayan banka (ör. arşiv artığı) akışı durdurmaz.
                scraperlar[kod] = None
        dosya = kok / str(document.raw_html_path)

        if not dosya.is_file():
            istatistik.dosya_yok += 1
            continue

        ham = dosya.read_bytes()
        if document.raw_html_sha256 and hashlib.sha256(ham).hexdigest() != document.raw_html_sha256:
            # Arşiv bozulmuş; yanlış metin üretmektense kaydı atla.
            istatistik.hash_uyusmazligi += 1
            logger.warning("arsiv_hash_uyusmazligi", belge_id=document.id, yol=str(dosya))
            continue

        campaign = _belge_kampanyasi(document)
        eski = document.clean_text or ""
        yeni = clean_html(
            ham.decode("utf-8", "replace"),
            bank_code=kod,
            title=campaign.title if campaign else None,
        )

        istatistik.islenen += 1
        istatistik.eski_uzunluk += len(eski)
        istatistik.yeni_uzunluk += len(yeni)
        if len(set(DATE_RE.findall(eski))) >= COKLU_TARIH_ESIGI:
            istatistik.coklu_tarih_once += 1
        if len(set(DATE_RE.findall(yeni))) >= COKLU_TARIH_ESIGI:
            istatistik.coklu_tarih_sonra += 1
        if eski and not yeni.strip():
            istatistik.bosalan += 1
        if _kapsam_kaybi(campaign, eski, yeni):
            istatistik.kapsam_kaybi.append(campaign.id if campaign else document.id)

        if tarihleri_tazele:
            if _tarih_tazele(
                campaign, ham.decode("utf-8", "replace"), yeni, scraperlar.get(kod), kuru=kuru
            ):
                istatistik.tarih_tazelendi += 1
        elif _tarih_geri_doldur(campaign, yeni, kuru=kuru):
            istatistik.tarih_kazanildi += 1

        if ornek_sayisi and campaign is not None:
            ornek_havuzu.append((kod, campaign.id, campaign.title, yeni))

        if yeni != eski:
            istatistik.guncellenen += 1
            if not kuru:
                document.clean_text = yeni or None
                document.clean_text_sha256 = sha256_text(yeni) if yeni else None

    if ornek_sayisi and ornek_havuzu:
        _ornek_bas(ornek_havuzu, ornek_sayisi)

    return ozet


def _ornek_bas(havuz: list[tuple[str, int, str, str]], adet: int) -> None:
    """Gözle denetim için rastgele örnek kampanya metni basar.

    §6.1 uyarısı: fazla agresif temizlik gerçek içeriği de siler; 10 rastgele
    kampanya GÖZLE kontrol edilmelidir. Örneklem deterministiktir.
    """
    print("\n" + "=" * 78)
    print(f"GÖZLE DENETİM — {adet} rastgele kampanya")
    print("=" * 78)
    for kod, kampanya_id, baslik, metin in random.Random(42).sample(havuz, min(adet, len(havuz))):
        print(f"\n── {kod} · kampanya {kampanya_id} · {baslik[:60]}")
        print(f"   ({len(metin)} karakter)")
        for satir in metin.split("\n"):
            print(f"   | {satir[:110]}")


def _rapor_bas(ozet: dict[str, BankaOzeti], *, kuru: bool) -> int:
    """Özet tabloyu basar ve süreç çıkış kodunu döndürür."""
    print("\n" + "=" * 92)
    print("YENİDEN İŞLEME ÖZETİ")
    print("=" * 92)
    print(
        f"{'banka':18s} {'işlenen':>8s} {'güncel':>7s} {'oran':>6s} {'4+tarih':>12s} "
        f"{'boşalan':>8s} {'kapsam':>7s} {'hash':>5s} {'+tarih':>7s}"
    )
    print("-" * 92)

    toplam = BankaOzeti()
    for kod in sorted(ozet):
        v = ozet[kod]
        toplam.islenen += v.islenen
        toplam.guncellenen += v.guncellenen
        toplam.eski_uzunluk += v.eski_uzunluk
        toplam.yeni_uzunluk += v.yeni_uzunluk
        toplam.coklu_tarih_once += v.coklu_tarih_once
        toplam.coklu_tarih_sonra += v.coklu_tarih_sonra
        toplam.bosalan += v.bosalan
        toplam.kapsam_kaybi.extend(v.kapsam_kaybi)
        toplam.hash_uyusmazligi += v.hash_uyusmazligi
        toplam.tarih_kazanildi += v.tarih_kazanildi
        toplam.tarih_tazelendi += v.tarih_tazelendi
        v_tarih = v.tarih_kazanildi + v.tarih_tazelendi
        print(
            f"{kod:18s} {v.islenen:8d} {v.guncellenen:7d} {v.oran:6.2f} "
            f"{v.coklu_tarih_once:5d}->{v.coklu_tarih_sonra:<5d} {v.bosalan:8d} "
            f"{len(v.kapsam_kaybi):7d} {v.hash_uyusmazligi:5d} {v_tarih:7d}"
        )

    print("-" * 92)
    t_tarih = toplam.tarih_kazanildi + toplam.tarih_tazelendi
    print(
        f"{'TOPLAM':18s} {toplam.islenen:8d} {toplam.guncellenen:7d} {toplam.oran:6.2f} "
        f"{toplam.coklu_tarih_once:5d}->{toplam.coklu_tarih_sonra:<5d} {toplam.bosalan:8d} "
        f"{len(toplam.kapsam_kaybi):7d} {toplam.hash_uyusmazligi:5d} {t_tarih:7d}"
    )

    if toplam.bosalan:
        print(f"\n⚠️  {toplam.bosalan} kayıtta metin TAMAMEN boşaldı — kural fazla agresif.")
    if toplam.kapsam_kaybi:
        print(
            f"\n⚠️  {len(toplam.kapsam_kaybi)} kayıtta kampanyanın kendi koşul/açıklama "
            f"metni kesildi: {toplam.kapsam_kaybi[:20]}"
        )
    if toplam.hash_uyusmazligi:
        print(f"\n⚠️  {toplam.hash_uyusmazligi} arşiv dosyası sha256 ile eşleşmedi, atlandı.")

    if kuru:
        print("\n--kuru: veritabanına YAZILMADI.")
    else:
        print("\nYazıldı. Sıradaki: python dev.py cikarim --sadece-kural")

    # Boşalan kayıt veya kapsam kaybı varsa sessiz geçilmemeli.
    return 1 if (toplam.bosalan or toplam.kapsam_kaybi) else 0


def main(argv: list[str] | None = None) -> int:
    """Betiğin giriş noktası."""
    ayristirici = argparse.ArgumentParser(
        description="Temiz metni ham HTML arşivinden yeniden üretir (ağa çıkmaz)"
    )
    ayristirici.add_argument("--kuru", action="store_true", help="Veritabanına yazmaz")
    ayristirici.add_argument("--banka", default=None, help="Yalnızca bu banka kodu")
    ayristirici.add_argument(
        "--ornek", type=int, default=0, help="Gözle denetim için N kampanya metni bas"
    )
    ayristirici.add_argument(
        "--tarihleri-tazele",
        dest="tarihleri_tazele",
        action="store_true",
        help="Kampanya tarihlerini arsivden YENIDEN turetir (mevcut degerin uzerine yazar)",
    )
    argumanlar = ayristirici.parse_args(argv)

    configure_logging()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    kok = get_settings().raw_html_path
    if not kok.is_dir():
        print(f"Ham HTML arşivi bulunamadı: {kok}")
        return 1

    with SessionLocal() as session:
        ozet = _isle(
            session,
            banka_kodu=argumanlar.banka,
            kuru=argumanlar.kuru,
            ornek_sayisi=argumanlar.ornek,
            tarihleri_tazele=argumanlar.tarihleri_tazele,
        )
        if argumanlar.kuru:
            session.rollback()
        else:
            session.commit()

    if not ozet:
        print("İşlenecek belge bulunamadı.")
        return 1

    return _rapor_bas(ozet, kuru=argumanlar.kuru)


if __name__ == "__main__":
    sys.exit(main())
