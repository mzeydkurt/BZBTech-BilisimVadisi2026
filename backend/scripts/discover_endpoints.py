"""Kampanya listesi endpoint avı.

Dört bankada kampanya listesi sunucu HTML'inde GELMİYOR; sayfa açıldıktan
sonra JavaScript bir uca istek atıp kartları oradan dolduruyor. O ucu bulmak,
o banka için scraper'ı tarayıcı gerektirmeyen basit bir JSON çekimine indirger.

Bu betik ÜRETİM KODU DEĞİLDİR: hiçbir kampanya kaydetmez, yalnızca ağ
trafiğini dinleyip `docs/endpoint_discovery.md` raporunu üretir.

Çalıştırma:
    python dev.py kesif-endpoint
    python dev.py kesif-endpoint --banka vakif_katilim

⚠️ Bu siteler gerçek bankalara ait. Sayfa başına en fazla birkaç etkileşim
yapılır, istekler arasında bekleme uygulanır ve kimliğimiz gizlenmez.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.logging_config import configure_logging, get_logger
from app.scrapers.browser import (
    NETWORK_IDLE_MS,
    browser_page,
    is_playwright_available,
    playwright_kurulum_mesaji,
)

logger = get_logger(__name__)

# backend/scripts/ -> backend/ -> depo kökü
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RAPOR_YOLU = REPO_ROOT / "docs" / "endpoint_discovery.md"

# Bir sayfada denenecek EN FAZLA etkileşim sayısı. Amaç ucu bulmak, veri
# toplamak değil; "Daha Fazla"ya otuz kez basmak gereksiz yük yaratır.
MAX_ETKILESIM = 3

# Etkileşimler arası bekleme (saniye). Rate limit kuralı: ≥1.5 sn.
ETKILESIM_BEKLEMESI = 2.0


@dataclass
class Hedef:
    """Endpoint aranacak tek bir sayfa."""

    bank_code: str
    bank_name: str
    url: str
    tetikleyici: str
    """İnsan okunur açıklama — rapora yazılır."""

    secililer: tuple[str, ...] = ()
    """Tıklanmayı deneyecek CSS seçicileri (sırayla denenir)."""

    metin_ipuclari: tuple[str, ...] = ()
    """Düğme metninden bulma denemesi (seçici tutmazsa)."""


HEDEFLER: tuple[Hedef, ...] = (
    Hedef(
        bank_code="kuveyt_turk",
        bank_name="Kuveyt Türk",
        url="https://www.kuveytturk.com.tr/kampanyalar/kendim-icin/kart-kampanyalari",
        tetikleyici="Daha Fazla Yükle",
        metin_ipuclari=("Daha Fazla Yükle", "Daha Fazla", "Devamı"),
    ),
    Hedef(
        bank_code="vakif_katilim",
        bank_name="Vakıf Katılım",
        url="https://www.vakifkatilim.com.tr/tr/kendim-icin/kampanyalar/mevcut-kampanyalar",
        tetikleyici="Sayfa yüklenmesi + 'İşim İçin' sekmesi",
        metin_ipuclari=("İşim İçin", "Isim Icin"),
    ),
    Hedef(
        bank_code="dunya_katilim",
        bank_name="Dünya Katılım",
        url="https://www.dunyakatilim.com.tr/kampanyalar",
        tetikleyici="Daha Fazla + Geçmiş Kampanyalar",
        metin_ipuclari=("Daha Fazla", "Geçmiş Kampanyalar", "Gecmis Kampanyalar"),
    ),
    Hedef(
        bank_code="albaraka",
        bank_name="Albaraka Türk",
        url="https://www.albaraka.com.tr/tr/kampanyalar",
        tetikleyici="Daha Fazla Kampanya Göster",
        metin_ipuclari=("Daha Fazla Kampanya Göster", "Daha Fazla"),
    ),
)


@dataclass
class YakalananIstek:
    """Sayfanın attığı, JSON dönen bir istek."""

    url: str
    method: str
    status: int
    content_type: str
    ornek_alanlar: list[str] = field(default_factory=list)
    kayit_sayisi: int | None = None


@dataclass
class HedefSonucu:
    """Tek bir hedefin keşif sonucu."""

    hedef: Hedef
    bulundu: bool = False
    istekler: list[YakalananIstek] = field(default_factory=list)
    etkilesim_sayisi: int = 0
    hata: str | None = None


def _json_mu(content_type: str) -> bool:
    """Yanıtın JSON olup olmadığını söyler."""
    return "application/json" in content_type.lower() or "+json" in content_type.lower()


def _govdeyi_ozetle(govde: Any) -> tuple[list[str], int | None]:
    """JSON gövdesinden alan adlarını ve kayıt sayısını çıkarır.

    Args:
        govde: Ayrıştırılmış JSON.

    Returns:
        (alan adları, kayıt sayısı) — kayıt sayısı bulunamazsa None.
    """
    if isinstance(govde, list):
        ilk = govde[0] if govde else None
        alanlar = sorted(ilk.keys()) if isinstance(ilk, dict) else []
        return alanlar, len(govde)

    if isinstance(govde, dict):
        # Kampanya listeleri çoğunlukla bir sarmalayıcı içinde geliyor:
        # {"data": [...]} veya {"items": [...]} gibi.
        for anahtar in ("data", "items", "result", "results", "list", "campaigns"):
            ic = govde.get(anahtar)
            if isinstance(ic, list):
                alanlar, sayi = _govdeyi_ozetle(ic)
                return alanlar or sorted(govde.keys()), sayi
        return sorted(govde.keys()), None

    return [], None


def _hedefi_incele(hedef: Hedef) -> HedefSonucu:
    """Tek bir sayfayı açıp JSON dönen istekleri toplar."""
    sonuc = HedefSonucu(hedef=hedef)
    yakalanan: list[YakalananIstek] = []

    def _yanit_dinleyici(response: Any) -> None:
        try:
            content_type = response.headers.get("content-type", "")
            if not _json_mu(content_type):
                return
            # Aynı uç birden fazla kez çağrılabilir; tekilleştirilir.
            if any(k.url == response.url for k in yakalanan):
                return
            alanlar: list[str] = []
            kayit_sayisi: int | None = None
            try:
                alanlar, kayit_sayisi = _govdeyi_ozetle(response.json())
            except Exception:
                pass
            yakalanan.append(
                YakalananIstek(
                    url=response.url,
                    method=response.request.method,
                    status=response.status,
                    content_type=content_type,
                    ornek_alanlar=alanlar[:15],
                    kayit_sayisi=kayit_sayisi,
                )
            )
        except Exception as exc:
            logger.warning("yanit_dinleyici_hatasi", url=hedef.url, hata=str(exc))

    try:
        with browser_page(on_response=_yanit_dinleyici) as page:
            logger.info("sayfa_aciliyor", banka=hedef.bank_code, url=hedef.url)
            page.goto(hedef.url, wait_until="domcontentloaded")
            page.wait_for_timeout(NETWORK_IDLE_MS)

            sonuc.etkilesim_sayisi = _tetikleyicileri_dene(page, hedef)
    except Exception as exc:
        sonuc.hata = f"{type(exc).__name__}: {exc}"
        logger.warning("kesif_basarisiz", banka=hedef.bank_code, hata=sonuc.hata)

    sonuc.istekler = yakalanan
    sonuc.bulundu = bool(yakalanan)
    return sonuc


def _tetikleyicileri_dene(page: Any, hedef: Hedef) -> int:
    """ "Daha fazla" türü düğmelere basmayı dener.

    Returns:
        Yapılan etkileşim sayısı.
    """
    yapilan = 0

    for secici in hedef.secililer:
        if yapilan >= MAX_ETKILESIM:
            break
        if _tikla(page, page.locator(secici)):
            yapilan += 1
            time.sleep(ETKILESIM_BEKLEMESI)

    for metin in hedef.metin_ipuclari:
        if yapilan >= MAX_ETKILESIM:
            break
        if _tikla(page, page.get_by_text(metin, exact=False).first):
            yapilan += 1
            time.sleep(ETKILESIM_BEKLEMESI)

    return yapilan


def _tikla(page: Any, locator: Any) -> bool:
    """Öğeye tıklamayı dener; bulunamazsa sessizce False döner."""
    try:
        if locator.count() == 0:
            return False
        locator.click(timeout=5_000)
        page.wait_for_timeout(NETWORK_IDLE_MS)
    except Exception:
        return False
    return True


def _rapor_yaz(sonuclar: list[HedefSonucu], *, playwright_var: bool) -> None:
    """`docs/endpoint_discovery.md` raporunu üretir."""
    satirlar: list[str] = [
        "# Kampanya Listesi Endpoint Keşfi",
        "",
        "> `python dev.py kesif-endpoint` ile üretilir.",
        "",
    ]

    if not playwright_var:
        satirlar += [
            "## ⚠️ Playwright kurulu değil",
            "",
            "Keşif YAPILAMADI. Dört banka da `BULUNAMADI` sayılır ve scraper'ları",
            "sunucu HTML'i üzerinden yazılır (Vakıf Katılım'da kampanya listesi",
            "sunucu HTML'inde gelmediği için o banka `status='partial'` kalır).",
            "",
            "```",
            "python dev.py kur --playwright",
            "```",
            "",
        ]

    satirlar += [
        "## Özet",
        "",
        "| Banka | Sonuç | JSON uç sayısı | Etkileşim |",
        "|---|---|---|---|",
    ]
    for sonuc in sonuclar:
        durum = "✅ BULUNDU" if sonuc.bulundu else "❌ BULUNAMADI"
        satirlar.append(
            f"| {sonuc.hedef.bank_name} | {durum} | {len(sonuc.istekler)} "
            f"| {sonuc.etkilesim_sayisi} |"
        )
    satirlar.append("")

    for sonuc in sonuclar:
        satirlar += [
            f"## {sonuc.hedef.bank_name}",
            "",
            f"- Sayfa: {sonuc.hedef.url}",
            f"- Tetikleyici: {sonuc.hedef.tetikleyici}",
            f"- Yapılan etkileşim: {sonuc.etkilesim_sayisi} (üst sınır {MAX_ETKILESIM})",
        ]
        if sonuc.hata:
            satirlar.append(f"- ⚠️ Hata: `{sonuc.hata}`")
        satirlar.append("")

        if not sonuc.istekler:
            satirlar += [
                "**BULUNAMADI.** Sayfa JSON uç kullanmıyor ya da içerik sunucuda",
                "render ediliyor. Bu banka için scraper HTML ayrıştırmasıyla yazılır.",
                "",
            ]
            continue

        for istek in sonuc.istekler:
            satirlar += [
                f"### `{istek.method} {istek.url}`",
                "",
                f"- Durum: {istek.status}",
                f"- İçerik tipi: {istek.content_type}",
            ]
            if istek.kayit_sayisi is not None:
                satirlar.append(f"- Dönen kayıt sayısı: {istek.kayit_sayisi}")
            if istek.ornek_alanlar:
                alanlar = ", ".join(f"`{a}`" for a in istek.ornek_alanlar)
                satirlar.append(f"- Alanlar: {alanlar}")
            satirlar.append("")

    RAPOR_YOLU.parent.mkdir(parents=True, exist_ok=True)
    RAPOR_YOLU.write_text("\n".join(satirlar), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """Betiğin giriş noktası."""
    ayristirici = argparse.ArgumentParser(description="Kampanya listesi endpoint keşfi")
    ayristirici.add_argument("--banka", help="Yalnızca bu banka kodunu incele")
    argumanlar = ayristirici.parse_args(argv)

    configure_logging()
    settings = get_settings()

    if settings.airgap_mode:
        print("AIRGAP_MODE açık; keşif dışarıya istek atamaz. .env dosyasını kontrol edin.")
        return 2

    hedefler = [h for h in HEDEFLER if not argumanlar.banka or h.bank_code == argumanlar.banka]
    if not hedefler:
        print(f"Bilinmeyen banka: {argumanlar.banka}")
        print("Seçenekler: " + ", ".join(h.bank_code for h in HEDEFLER))
        return 2

    playwright_var = is_playwright_available()
    if not playwright_var:
        print(playwright_kurulum_mesaji())
        _rapor_yaz(
            [HedefSonucu(hedef=h, hata="Playwright kurulu değil") for h in hedefler],
            playwright_var=False,
        )
        print(f"\nRapor yazıldı (keşif yapılmadan): {RAPOR_YOLU}")
        return 1

    print(f"{len(hedefler)} sayfa incelenecek. Bu işlem gerçek banka sitelerine istek atar.\n")

    sonuclar: list[HedefSonucu] = []
    for sira, hedef in enumerate(hedefler, start=1):
        print(f"[{sira}/{len(hedefler)}] {hedef.bank_name} — {hedef.url}")
        sonuc = _hedefi_incele(hedef)
        sonuclar.append(sonuc)
        durum = f"{len(sonuc.istekler)} JSON uç" if sonuc.bulundu else "uç bulunamadı"
        print(f"    -> {durum}")
        if sira < len(hedefler):
            time.sleep(ETKILESIM_BEKLEMESI)

    _rapor_yaz(sonuclar, playwright_var=True)
    bulunan = sum(1 for s in sonuclar if s.bulundu)
    print(f"\n{bulunan}/{len(sonuclar)} bankada JSON uç bulundu.")
    print(f"Rapor: {RAPOR_YOLU}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
