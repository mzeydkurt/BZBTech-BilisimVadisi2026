"""Bankanın kendi kategori etiketini ARŞİVLENMİŞ HTML'den geri doldurur.

⚠️ AĞA ÇIKMAZ. Kaynak `data/raw_html/` altındaki, daha önce çekilmiş liste
sayfalarıdır. Bankalara tek bir yeni istek gitmez.

NEDEN GEREKLİ: `campaigns.bank_category` sütunu sonradan eklendi. Ondan önce
çekilmiş kayıtlarda sütun boş ve sınıflandırma bankanın kendi etiketini
kullanamıyor. Ziraat Katılım'da ölçüldü: 209 kampanyanın 153'ü gerçek bir
sektöre eşlenebilecekken hepsi "genel" kalıyor.

Alternatif, bankaları yeniden kazımaktı — ama liste sayfası zaten arşivde
duruyor ve ham HTML asla silinmiyor. Etik kazıma kuralı gereği elde olan
veriyle yapılabilecek işi yeniden istek atarak yapmayız.

Çalıştırma:
    python dev.py geri-doldur
    python dev.py geri-doldur --kuru      # yazmaz, yalnızca raporlar
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bs4 import BeautifulSoup
from sqlalchemy import select

from app.config import get_settings
from app.core.normalization.text import collapse_whitespace
from app.db.models import Bank, Campaign
from app.db.session import SessionLocal
from app.logging_config import configure_logging, get_logger
from app.utils.slugify import slug_from_url_path

logger = get_logger(__name__)

# Banka kodu → (kart bağlantısının CSS sınıfı, kategori etiketinin CSS sınıfı).
# Yalnızca kategori etiketini kartında taşıyan bankalar burada bulunur.
CARD_SELECTORS: dict[str, tuple[str, str]] = {
    "ziraat_katilim": ("item-title", "item-category"),
}


def _slug_to_category(bank_code: str, arsiv_dizini: Path) -> dict[str, str]:
    """Arşivlenmiş liste sayfalarından slug → kategori eşlemesi çıkarır.

    Args:
        bank_code: Banka kodu.
        arsiv_dizini: `data/raw_html/{banka}` dizini.

    Returns:
        Slug → bankanın ham kategori etiketi.
    """
    link_sinifi, kategori_sinifi = CARD_SELECTORS[bank_code]
    esleme: dict[str, str] = {}

    for dosya in arsiv_dizini.glob("*.html"):
        html = dosya.read_bytes().decode("utf-8", "replace")
        # Kart yapısı yalnızca liste sayfalarında var; detay sayfalarında yok.
        if f'class="{link_sinifi}' not in html and f"{link_sinifi} " not in html:
            continue

        soup = BeautifulSoup(html, "lxml")
        for anchor in soup.find_all("a", class_=link_sinifi, href=True):
            kapsayici = anchor.find_parent(class_="item-content") or anchor.parent
            etiket = None
            for _ in range(3):
                if kapsayici is None:
                    break
                bulunan = kapsayici.find("span", class_=kategori_sinifi)
                if bulunan is not None:
                    etiket = collapse_whitespace(bulunan.get_text())
                    break
                kapsayici = kapsayici.parent

            if not etiket:
                continue
            slug = slug_from_url_path(str(anchor["href"]))
            # İlk görülen etiket korunur; aynı kampanya birden çok kartta
            # (çevrilen yüz) tekrarlanıyor.
            esleme.setdefault(slug, etiket)

    return esleme


def main(argv: list[str] | None = None) -> int:
    """Betiğin giriş noktası."""
    ayristirici = argparse.ArgumentParser(description="Banka kategorisini arşivden geri doldur")
    ayristirici.add_argument("--kuru", action="store_true", help="Veritabanına yazmaz")
    argumanlar = ayristirici.parse_args(argv)

    configure_logging()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    arsiv_kok = get_settings().raw_html_path
    if not arsiv_kok.is_dir():
        print(f"Ham HTML arşivi bulunamadı: {arsiv_kok}")
        return 1

    toplam = 0
    with SessionLocal() as session:
        for bank_code in CARD_SELECTORS:
            dizin = arsiv_kok / bank_code
            if not dizin.is_dir():
                print(f"{bank_code}: arşiv dizini yok, atlandı")
                continue

            esleme = _slug_to_category(bank_code, dizin)
            if not esleme:
                print(f"{bank_code}: arşivde kategori etiketi bulunamadı")
                continue

            bank = session.scalar(select(Bank).where(Bank.code == bank_code))
            if bank is None:
                print(f"{bank_code}: banka kaydı yok")
                continue

            guncellenen = 0
            for campaign in session.scalars(select(Campaign).where(Campaign.bank_id == bank.id)):
                etiket = esleme.get(campaign.external_slug)
                if etiket and campaign.bank_category != etiket:
                    campaign.bank_category = etiket
                    guncellenen += 1

            toplam += guncellenen
            print(f"{bank_code}: {len(esleme)} etiket bulundu, {guncellenen} kayıt güncellendi")

        if argumanlar.kuru:
            session.rollback()
            print("\n--kuru: veritabanına yazılmadı.")
        else:
            session.commit()
            print(f"\nToplam {toplam} kayıt güncellendi.")
            print("Sıradaki: python dev.py siniflandir")

    return 0


if __name__ == "__main__":
    sys.exit(main())
