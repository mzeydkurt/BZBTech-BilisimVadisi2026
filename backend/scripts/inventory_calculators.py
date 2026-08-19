"""Hesaplayıcı envanteri.

AMAÇ: Hesaplayıcının hangi girdileri kabul ettiğini ve ne kadar veri
alınabileceğini SİSTEMATİK çıkarmak. Rastgele değer girip "acaba çalıştı mı"
demek yerine formu envanterleyip maliyeti önceden hesaplamak.

Envanterin asıl değeri sorgu sonuçları değil, FORMUN KENDİSİ: Ziraat'te
finansman tipi dropdown'ındaki 16 seçenek aslında 16 ürün varyantıdır; tutar
slider'ının `min`/`max` değerleri ürün limitidir; vade seçicisi izinli vadeleri
verir. Hesaplayıcı hiç sorgulanmasa bile bu veri elde edilir.

⚠️ ETİK KURALLAR
  - Banka başına EN FAZLA 3 deneme isteği. Amaç mekanizmayı anlamak, veri
    toplamak değil. Yapılan deneme sayısı loglanır ve rapora yazılır.
  - İstekler arasında en az 2 saniye bekleme.
  - Kimliğimiz gizlenmez; gerçek User-Agent kullanılır.
  - Sayfadaki yasal uyarı birebir kaydedilir; hesaplayıcı çıktısı bankanın
    taahhüdü DEĞİLDİR.

Çalıştırma:
    python dev.py kesif-hesaplayici
    python dev.py kesif-hesaplayici --banka ziraat_katilim
    python dev.py kesif-hesaplayici --kuru      # DB'ye yazmaz
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.config import get_settings
from app.db.base import utc_now
from app.db.models import Bank, CalculatorInventory
from app.db.session import SessionLocal
from app.logging_config import configure_logging, get_logger
from app.scrapers.browser import (
    NETWORK_IDLE_MS,
    browser_page,
    is_playwright_available,
    playwright_kurulum_mesaji,
)
from app.scrapers.calculator_inventory import (
    CalculatorForm,
    allowed_terms,
    amount_bounds,
    count_combinations,
    parse_form_controls,
    suggest_sampling,
    variant_candidates,
)

logger = get_logger(__name__)

# backend/scripts/ -> backend/ -> depo kökü
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RAPOR_YOLU = REPO_ROOT / "docs" / "calculator_inventory.md"

# ⚠️ Banka başına 3'ten fazla deneme isteği atılmaz.
MAX_DENEME = 3

# İstekler arası bekleme. Hesaplayıcıda ≥2 sn (normal kazımada ≥1.5 sn).
DENEME_BEKLEMESI = 2.0


@dataclass
class Hedef:
    """Envanterlenecek tek bir hesaplayıcı sayfası."""

    bank_code: str
    bank_name: str
    url: str
    calculator_name: str
    beklenen: str
    """Analizde öngörülen yapı — rapora yazılır, doğrulama için."""


HEDEFLER: tuple[Hedef, ...] = (
    Hedef(
        bank_code="ziraat_katilim",
        bank_name="Ziraat Katılım",
        url="https://www.ziraatkatilim.com.tr/bireysel/finansman-urunleri/konut-gayrimenkul-finansmani",
        calculator_name="Konut / Gayrimenkul Finansmanı Hesaplama",
        beklenen="16 seçenekli dropdown + tutar slider + vade 1-60",
    ),
    Hedef(
        bank_code="ziraat_katilim",
        bank_name="Ziraat Katılım",
        url="https://www.ziraatkatilim.com.tr/bireysel/finansman-urunleri/tasit-finansmani",
        calculator_name="Taşıt Finansmanı Hesaplama",
        beklenen="Sıfır / 2. el araç ayrımı",
    ),
    Hedef(
        bank_code="ziraat_katilim",
        bank_name="Ziraat Katılım",
        url="https://www.ziraatkatilim.com.tr/bireysel/finansman-urunleri/ihtiyac-finansmani",
        calculator_name="İhtiyaç Finansmanı Hesaplama",
        beklenen="—",
    ),
    Hedef(
        bank_code="vakif_katilim",
        bank_name="Vakıf Katılım",
        url="https://www.vakifkatilim.com.tr/tr/yardimci-sayfalar/hesaplama-araclari/finansman-hesaplama",
        calculator_name="Finansman Hesaplama",
        beklenen="Ayrı hesaplama sayfası — endpoint ihtimali en yüksek",
    ),
    Hedef(
        bank_code="albaraka",
        bank_name="Albaraka Türk",
        url="https://www.albaraka.com.tr/tr/bireysel/finansmanlar/konut-finansmani",
        calculator_name="Konut Finansmanı",
        beklenen="23 satırlık ödeme planı sunucudan mı geliyor",
    ),
    Hedef(
        bank_code="albaraka",
        bank_name="Albaraka Türk",
        url="https://www.albaraka.com.tr/tr/bireysel/finansmanlar/tasit-finansmani",
        calculator_name="Taşıt Finansmanı",
        beklenen="Ödeme planı tablosu",
    ),
    Hedef(
        bank_code="dunya_katilim",
        bank_name="Dünya Katılım",
        url="https://www.dunyakatilim.com.tr/kendim-icin/finansmanlar/ihtiyac-finansmani",
        calculator_name="İhtiyaç Finansmanı Taksit Hesaplama",
        beklenen="Taksit hesaplayıcı",
    ),
    Hedef(
        bank_code="dunya_katilim",
        bank_name="Dünya Katılım",
        url="https://www.dunyakatilim.com.tr/kendim-icin/arac-finansmanlari/arac-finansmani",
        calculator_name="Araç Finansmanı Taksit Hesaplama",
        beklenen="arac / cevre-dostu-arac varyant ayrımı",
    ),
    Hedef(
        bank_code="kuveyt_turk",
        bank_name="Kuveyt Türk",
        url="https://www.kuveytturk.com.tr/kendim-icin/finansmanlar",
        calculator_name="Finansman Hesaplama",
        beklenen="Oran hangi çağrıdan geliyor",
    ),
    Hedef(
        bank_code="turkiye_finans",
        bank_name="Türkiye Finans",
        url="https://www.turkiyefinans.com.tr/tr-tr/bireysel/ihtiyac-finansmani/Sayfalar/ihtiyac-finansmani.aspx",
        calculator_name="İhtiyaç Finansmanı",
        beklenen="Tablo zaten var; hesaplayıcı varsa çapraz doğrulama için",
    ),
)


@dataclass
class EnvanterSonucu:
    """Tek bir hedefin envanter sonucu."""

    hedef: Hedef
    form: CalculatorForm = field(default_factory=CalculatorForm)
    mechanism: str = "unknown"
    endpoint_url: str | None = None
    endpoint_method: str | None = None
    response_fields: dict[str, Any] | None = None
    deneme_sayisi: int = 0
    hata: str | None = None

    @property
    def total_combinations(self) -> int:
        """Sorgulanabilecek kombinasyon sayısı."""
        return count_combinations(self.form.input_fields)

    @property
    def sampling_decision(self) -> str:
        """Önerilen örnekleme kararı."""
        return suggest_sampling(self.total_combinations, self.mechanism)

    @property
    def feasible(self) -> bool:
        """Örnekleme uygulanabilir mi?"""
        return self.sampling_decision not in ("skip",)

    @property
    def variant_count(self) -> int:
        """Keşfedilen ürün varyantı sayısı."""
        return len(variant_candidates(self.form))


def _hedefi_envanterle(hedef: Hedef) -> EnvanterSonucu:
    """Sayfayı açar, formu envanterler ve mekanizmayı tespit eder."""
    sonuc = EnvanterSonucu(hedef=hedef)
    xhr_kayitlari: list[dict[str, Any]] = []

    def _yanit_dinleyici(response: Any) -> None:
        try:
            content_type = response.headers.get("content-type", "")
            if "application/json" not in content_type.lower():
                return
            xhr_kayitlari.append(
                {
                    "url": response.url,
                    "method": response.request.method,
                    "status": response.status,
                }
            )
        except Exception as exc:
            logger.warning("yanit_dinleyici_hatasi", url=hedef.url, hata=str(exc))

    try:
        with browser_page(on_response=_yanit_dinleyici) as page:
            logger.info("hesaplayici_aciliyor", banka=hedef.bank_code, url=hedef.url)
            page.goto(hedef.url, wait_until="domcontentloaded")
            page.wait_for_timeout(NETWORK_IDLE_MS)

            sonuc.form = parse_form_controls(page.content())
            if not sonuc.form.input_fields:
                sonuc.mechanism = "none"
                logger.info("hesaplayici_yok", banka=hedef.bank_code, url=hedef.url)
                return sonuc

            acilis_xhr = len(xhr_kayitlari)
            sonuc.deneme_sayisi = _mekanizmayi_dene(page, sonuc.form)
            sonuc.mechanism = _mekanizmayi_belirle(
                xhr_kayitlari, acilis_xhr, denendi=sonuc.deneme_sayisi > 0
            )

            if xhr_kayitlari:
                son = xhr_kayitlari[-1]
                sonuc.endpoint_url = son["url"]
                sonuc.endpoint_method = son["method"]
                sonuc.response_fields = {"gozlemlenen_cagrilar": len(xhr_kayitlari)}
    except Exception as exc:
        sonuc.hata = f"{type(exc).__name__}: {exc}"
        logger.warning("envanter_basarisiz", banka=hedef.bank_code, hata=sonuc.hata)

    return sonuc


def _mekanizmayi_dene(page: Any, form: CalculatorForm) -> int:
    """Girdileri değiştirip XHR tetiklenip tetiklenmediğine bakar.

    ⚠️ EN FAZLA `MAX_DENEME` etkileşim. Amaç mekanizmayı anlamak, veri toplamak
    değil; bu siteler gerçek bankalara ait.

    Returns:
        Yapılan deneme sayısı.
    """
    yapilan = 0

    for ad, tanim in form.input_fields.items():
        if yapilan >= MAX_DENEME:
            break
        try:
            if tanim.get("type") == "select" and tanim.get("options"):
                # İlk gerçek seçeneği seç.
                deger = str(tanim["options"][0]["value"])
                page.select_option(f"[name='{ad}'], #{ad}", deger, timeout=5_000)
            elif tanim.get("type") in ("range", "number"):
                orta = _orta_deger(tanim)
                if orta is None:
                    continue
                page.fill(f"[name='{ad}'], #{ad}", str(orta), timeout=5_000)
            else:
                continue
        except Exception:
            continue

        yapilan += 1
        page.wait_for_timeout(NETWORK_IDLE_MS)
        time.sleep(DENEME_BEKLEMESI)

    return yapilan


def _orta_deger(tanim: dict[str, Any]) -> int | float | None:
    """Sayısal alan için aralığın ortasındaki değeri üretir."""
    en_az, en_cok = tanim.get("min"), tanim.get("max")
    if en_az is None or en_cok is None:
        return tanim.get("value")
    return (en_az + en_cok) // 2 if isinstance(en_az, int) else (en_az + en_cok) / 2


def _mekanizmayi_belirle(
    xhr_kayitlari: list[dict[str, Any]], acilis_xhr: int, *, denendi: bool
) -> str:
    """Gözlenen ağ trafiğinden hesaplama mekanizmasını çıkarır."""
    if not denendi:
        return "unknown"

    deneme_sonrasi = len(xhr_kayitlari) - acilis_xhr
    if deneme_sonrasi > 0:
        # Girdi değişince sunucuya gidiyor: sorgulanabilir bir uç var.
        return "api"
    if acilis_xhr > 0:
        # Açılışta veri çekmiş ama girdi değişince gitmiyor: oran önden
        # alınıp hesap tarayıcıda yapılıyor.
        return "js_with_rate_fetch"
    return "js_client_side"


def _kaydet(sonuclar: list[EnvanterSonucu]) -> int:
    """Envanteri `calculator_inventory` tablosuna yazar (upsert).

    Returns:
        Yazılan/güncellenen kayıt sayısı.
    """
    yazilan = 0
    with SessionLocal() as session:
        for sonuc in sonuclar:
            bank = session.scalar(select(Bank).where(Bank.code == sonuc.hedef.bank_code))
            if bank is None:
                logger.warning("banka_yok", banka=sonuc.hedef.bank_code)
                continue

            en_az, en_cok = amount_bounds(sonuc.form.input_fields)
            kayit = session.scalar(
                select(CalculatorInventory).where(
                    CalculatorInventory.bank_id == bank.id,
                    CalculatorInventory.page_url == sonuc.hedef.url,
                )
            )
            if kayit is None:
                kayit = CalculatorInventory(bank_id=bank.id, page_url=sonuc.hedef.url)
                session.add(kayit)

            kayit.calculator_name = sonuc.hedef.calculator_name
            kayit.input_fields = sonuc.form.input_fields
            kayit.variant_count = sonuc.variant_count or None
            kayit.amount_min = en_az
            kayit.amount_max = en_cok
            kayit.allowed_terms = allowed_terms(sonuc.form.input_fields)
            kayit.mechanism = sonuc.mechanism
            kayit.endpoint_url = sonuc.endpoint_url
            kayit.endpoint_method = sonuc.endpoint_method
            kayit.response_fields = sonuc.response_fields
            kayit.total_combinations = sonuc.total_combinations or None
            kayit.sampling_decision = sonuc.sampling_decision
            kayit.feasible = sonuc.feasible
            kayit.non_binding_notice = sonuc.form.legal_notice
            kayit.notes = sonuc.hata or sonuc.hedef.beklenen
            kayit.inspected_at = utc_now()
            yazilan += 1

        session.commit()
    return yazilan


def _rapor_yaz(sonuclar: list[EnvanterSonucu], *, playwright_var: bool) -> None:
    """`docs/calculator_inventory.md` raporunu üretir."""
    satirlar: list[str] = [
        "# Hesaplayıcı Envanteri",
        "",
        "> `python dev.py kesif-hesaplayici` ile üretilir.",
        "",
        "⚠️ Bu sayfalardan alınan değerler bankaların **taahhüdü değildir**; her kaydın",
        "`non_binding_notice` alanında sayfadaki yasal uyarı birebir saklanır.",
        "",
    ]

    if not playwright_var:
        satirlar += [
            "## ⚠️ Playwright kurulu değil",
            "",
            "Envanter ÇIKARILAMADI. Tüm hedefler `mechanism='unknown'`,",
            "`sampling_decision='skip'`, `feasible=false` ile kaydedilir.",
            "",
            "```",
            "python dev.py kur --playwright",
            "```",
            "",
        ]

    satirlar += [
        "## Özet",
        "",
        "| Banka | Hesaplayıcı | Mekanizma | Varyant | Kombinasyon | Karar | Deneme |",
        "|---|---|---|---|---|---|---|",
    ]
    for sonuc in sonuclar:
        satirlar.append(
            f"| {sonuc.hedef.bank_name} | {sonuc.hedef.calculator_name} "
            f"| `{sonuc.mechanism}` | {sonuc.variant_count} | {sonuc.total_combinations} "
            f"| `{sonuc.sampling_decision}` | {sonuc.deneme_sayisi}/{MAX_DENEME} |"
        )
    satirlar.append("")

    for sonuc in sonuclar:
        satirlar += _hedef_bolumu(sonuc)

    RAPOR_YOLU.parent.mkdir(parents=True, exist_ok=True)
    RAPOR_YOLU.write_text("\n".join(satirlar), encoding="utf-8")


def _hedef_bolumu(sonuc: EnvanterSonucu) -> list[str]:
    """Tek bir hedefin rapor bölümünü üretir."""
    satirlar = [
        f"## {sonuc.hedef.bank_name} — {sonuc.hedef.calculator_name}",
        "",
        f"- Sayfa: {sonuc.hedef.url}",
        f"- Mekanizma: `{sonuc.mechanism}`",
        f"- Beklenen yapı: {sonuc.hedef.beklenen}",
        f"- Yapılan deneme: {sonuc.deneme_sayisi} (üst sınır {MAX_DENEME})",
    ]
    if sonuc.endpoint_url:
        satirlar.append(f"- Endpoint: `{sonuc.endpoint_method} {sonuc.endpoint_url}`")
    if sonuc.hata:
        satirlar.append(f"- ⚠️ Hata: `{sonuc.hata}`")
    satirlar.append("")

    if not sonuc.form.input_fields:
        satirlar += ["**Hesaplayıcı bulunamadı.** Sayfada form kontrolü yok.", ""]
        return satirlar

    satirlar += ["### Girdi boyutları", "", "| Alan | Tip | Değerler |", "|---|---|---|"]
    for ad, tanim in sonuc.form.input_fields.items():
        satirlar.append(f"| `{ad}` | {tanim.get('type')} | {_deger_ozeti(tanim)} |")
    satirlar.append("")

    adaylar = variant_candidates(sonuc.form)
    if adaylar:
        satirlar += [
            "### Ürün varyantı adayları",
            "",
            "| Etiket | Değer | Kanonik anahtar |",
            "|---|---|---|",
        ]
        for aday in adaylar:
            anahtar = f"`{aday.variant_key}`" if aday.is_mapped else "**eşlenmedi**"
            satirlar.append(f"| {aday.label} | `{aday.value}` | {anahtar} |")
        eslenmeyen = [a.label for a in adaylar if not a.is_mapped]
        satirlar.append("")
        if eslenmeyen:
            satirlar += [
                f"⚠️ {len(eslenmeyen)} etiket `VARIANT_VOCAB`'a eşlenemedi ve "
                "`variant_key=None` ile kaydedilecek: " + ", ".join(eslenmeyen),
                "",
            ]

    en_az, en_cok = amount_bounds(sonuc.form.input_fields)
    satirlar += [
        f"- Tutar aralığı: {_tutar(en_az)} – {_tutar(en_cok)}",
        f"- İzinli vadeler: {allowed_terms(sonuc.form.input_fields) or '—'}",
        f"- Toplam kombinasyon: {sonuc.total_combinations}",
        f"- Örnekleme kararı: `{sonuc.sampling_decision}`",
        f"- Uygulanabilir: {'EVET' if sonuc.feasible else 'HAYIR'}",
        f"- Yasal uyarı: {sonuc.form.legal_notice or '— (sayfada bulunamadı)'}",
        "",
    ]
    return satirlar


def _deger_ozeti(tanim: dict[str, Any]) -> str:
    """Bir girdi alanının değerlerini tek satırda özetler."""
    tip = tanim.get("type")
    if tip in ("select", "radio"):
        secenekler = tanim.get("options", [])
        etiketler = ", ".join(f'"{s["label"]}"' for s in secenekler[:4])
        if len(secenekler) > 4:
            etiketler += f", … ({len(secenekler)} seçenek)"
        return etiketler
    if tip in ("range", "number"):
        return f"{tanim.get('min')} – {tanim.get('max')}, adım {tanim.get('step')}"
    return str(tanim.get("placeholder") or tanim.get("label") or "—")


def _tutar(value: Decimal | None) -> str:
    """Tutarı okunur biçimde yazar."""
    return f"{value:,.0f}".replace(",", ".") if value is not None else "—"


def main(argv: list[str] | None = None) -> int:
    """Betiğin giriş noktası."""
    ayristirici = argparse.ArgumentParser(description="Hesaplayıcı envanteri")
    ayristirici.add_argument("--banka", help="Yalnızca bu banka kodunu incele")
    ayristirici.add_argument(
        "--kuru", action="store_true", help="Veritabanına yazmaz, yalnızca rapor üretir"
    )
    argumanlar = ayristirici.parse_args(argv)

    configure_logging()
    settings = get_settings()

    if settings.airgap_mode:
        print("AIRGAP_MODE açık; envanter dışarıya istek atamaz. .env dosyasını kontrol edin.")
        return 2

    hedefler = [h for h in HEDEFLER if not argumanlar.banka or h.bank_code == argumanlar.banka]
    if not hedefler:
        print(f"Bilinmeyen banka: {argumanlar.banka}")
        print("Seçenekler: " + ", ".join(sorted({h.bank_code for h in HEDEFLER})))
        return 2

    playwright_var = is_playwright_available()
    if not playwright_var:
        print(playwright_kurulum_mesaji())
        sonuclar = [EnvanterSonucu(hedef=h, hata="Playwright kurulu değil") for h in hedefler]
        _rapor_yaz(sonuclar, playwright_var=False)
        if not argumanlar.kuru:
            _kaydet(sonuclar)
        print(f"\nRapor yazıldı (envanter çıkarılmadan): {RAPOR_YOLU}")
        return 1

    print(f"{len(hedefler)} hesaplayıcı incelenecek. Bu işlem gerçek banka sitelerine istek atar.")
    print(f"Banka başına en fazla {MAX_DENEME} deneme, istekler arası {DENEME_BEKLEMESI} sn.\n")

    sonuclar: list[EnvanterSonucu] = []
    for sira, hedef in enumerate(hedefler, start=1):
        print(f"[{sira}/{len(hedefler)}] {hedef.bank_name} — {hedef.calculator_name}")
        sonuc = _hedefi_envanterle(hedef)
        sonuclar.append(sonuc)
        print(
            f"    -> mekanizma={sonuc.mechanism} varyant={sonuc.variant_count} "
            f"kombinasyon={sonuc.total_combinations} karar={sonuc.sampling_decision}"
        )
        if sira < len(hedefler):
            time.sleep(DENEME_BEKLEMESI)

    _rapor_yaz(sonuclar, playwright_var=True)
    if argumanlar.kuru:
        print("\n--kuru: veritabanına yazılmadı.")
    else:
        print(f"\n{_kaydet(sonuclar)} envanter kaydı yazıldı.")

    bulunan = sum(1 for s in sonuclar if s.form.input_fields)
    print(f"{bulunan}/{len(sonuclar)} sayfada hesaplayıcı bulundu.")
    print(f"Rapor: {RAPOR_YOLU}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
