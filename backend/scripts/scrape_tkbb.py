"""TKBB Veri Peteği'nin 4 veri setini doğrudan API'sinden çeker (KATİP KAPI 4.3).

`python dev.py tkbb-cek` ile çalıştırılır.

✅ YÖNTEM DEĞİŞTİ (21 Ağustos 2026) — ÖNCEKİ NOT YANLIŞTI. Bu modül daha önce
"düz HTTP güvenilir değil, Playwright ile network interception gerekir"
diyordu ve 4 veri setinden yalnızca görüntülenen sayfadaki 1'ini
yakalayabiliyordu. Kullanıcı gerçek uç noktayı bizzat paylaştı; dört widget
ID'nin dördü de düz `httpx` isteğiyle DOĞRU ve GÜNCEL veri dönüyor (ölçüldü,
dördü de tek tek doğrulandı):

    https://veri-petegi.tkbb.org.tr/api/v1/data/?id={WIDGET_ID}&type=pivot
    &refresh_cache=false&dashboard=db-fyfb30he1txl19b&date_aggregate=auto
    &dashboard_date_aggregate=auto&rowLevel=0&ordering=

Playwright/tarayıcı oturumu artık GEREKMİYOR — CLAUDE.md'nin "Playwright
yalnızca keşifte, üretim hattı Playwright'sız çalışır" kuralına da bu hâli
uygundur. İstek `settings.scraper_user_agent` kimliğiyle atılır (§8.2:
kimliğimizi gizlemiyoruz).

⚠️ ÖLÇÜ KODU → PARA BİRİMİ. TKBB pivot'unda her vade için dört ölçü var:

    m0 = TL (TRY)   m1 = USD   m2 = EUR   m3 = Altın (XAU)

⚠️ KÂR PAYLAŞIM ORANLARINDA YALNIZCA TL YAZILIR (`yalnizca_try=True`).
Kullanıcının açık isteği: bölüşüm oranı karşılaştırmasında TL dışındaki
para birimleri istenmiyor. Dağıtılan kâr payı (getiri) tablolarında dört
para biriminin hepsi yazılır.

⚠️ BAYAT SATIR TEMİZLİĞİ ZORUNLU (`_bayatlari_sil`). `load_tkbb_seed` yalnızca
ekliyor/güncelliyordu, hiç SİLMİYORDU; TKBB bir hücreyi boşalttığında eski
değer veritabanında kalıyordu. Ölçüldü: Albaraka'nın ara ödemeli XAU hücreleri
canlı API'de BOŞ olduğu hâlde veritabanında 9,17 ve 2,79 olarak duruyordu
(eski dokümandan gelen değerler). Bu yüzden her widget yazılmadan ÖNCE o
ürün+oran türü için mevcut TKBB satırları silinir — veri %100 API'den
yeniden üretilebilir olduğu için bu güvenlidir.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

import httpx

from app.config import get_settings
from app.core.exceptions import NotFoundError
from app.logging_config import get_logger

logger = get_logger(__name__)

TKBB_API_BASE: Final[str] = "https://veri-petegi.tkbb.org.tr/api/v1/data/"
TKBB_DASHBOARD_ID: Final[str] = "db-fyfb30he1txl19b"

# Kullanıcıya/jüriye gösterilecek insan-okunur kaynak sayfası. Veri yukarıdaki
# API'den gelir; bu adres o verinin TKBB'deki yayın yeridir.
TKBB_KAYNAK_SAYFASI: Final[str] = "https://tkbb.org.tr/veripetegi-detay/40"

# ⛔ BU PARAMETRE DÜŞÜRÜLEMEZ — DÜŞÜRÜLDÜĞÜNDE SESSİZCE YANLIŞ VERİ GELİR.
#
# Çift URL-kodlanmış hâliyle çözümü:
#   dbfl-5amu0677cd7d07a={"anchor":"now","unit":"week","move":0,"behavior":"snap_beginning"}
#   dbfl-5amu0677cd7d07a={"anchor":"now","unit":"week","move":0,"behavior":"snap_ending"}
#
# Yani dashboard'ın tarih filtresi: İÇİNDE BULUNULAN HAFTAYA sabitlenir
# (haftanın başı → haftanın sonu). TKBB dashboard'ı bu filtreyle çalışıyor.
#
# ⚠️ ÖLÇÜLDÜ (21 Ağustos 2026) — bu parametre olmadan API HATA VERMEZ,
# 200 döner ama TÜM ZAMANLARIN ORTALAMASINI hesaplar:
#
#     filters ile   : Albaraka Aylık TL = %31,35   (dashboard'da görünen değer)
#     filters'sız   : Albaraka Aylık TL = %14,4689 (tüm zamanların ortalaması)
#
# İlk yazımda bu parametre "gereksiz görünüyor" diye çıkarılmıştı ve
# veritabanına 4 veri setinin TAMAMI yanlış (ortalama) değerlerle yazıldı;
# hata yalnızca kullanıcı kendi tarayıcı çıktısını paylaştığında görüldü.
# Sadeleştirmek için TEKRAR ÇIKARILMAMALIDIR.
TKBB_FILTERS: Final[str] = (
    "dbfl-5amu0677cd7d07a%3D%257B%2522anchor%2522%253A%2522now%2522%252C%2522unit%2522%253A"
    "%2522week%2522%252C%2522move%2522%253A0%252C%2522behavior%2522%253A%2522snap_beginning"
    "%2522%257D%26dbfl-5amu0677cd7d07a%3D%257B%2522anchor%2522%253A%2522now%2522%252C%2522"
    "unit%2522%253A%2522week%2522%252C%2522move%2522%253A0%252C%2522behavior%2522%253A%2522"
    "snap_ending%2522%257D"
)


class WidgetTanimi:
    """Bir TKBB veri setinin KATİP karşılığı."""

    def __init__(
        self, *, rate_type: str, variant: str | None, aciklama: str, yalnizca_try: bool
    ) -> None:
        self.rate_type = rate_type
        self.variant = variant
        self.aciklama = aciklama
        # True ise yalnızca m0 (TL) hücreleri yazılır.
        self.yalnizca_try = yalnizca_try


# widget ID -> tanım. Dördü de kullanıcının paylaştığı API adresleriyle
# doğrulandı (21 Ağustos 2026).
WIDGET_ESLEMESI: Final[dict[str, WidgetTanimi]] = {
    "DL-FFC6K484A682B8I": WidgetTanimi(
        rate_type="participation_yield",
        variant=None,
        aciklama="Dağıtılan Kâr Payı Oranları",
        yalnizca_try=False,
    ),
    "DL-0M0C2ABB615D062": WidgetTanimi(
        rate_type="profit_sharing_ratio",
        variant=None,
        aciklama="Kâr Paylaşım Oranları",
        # ⚠️ Kullanıcının açık isteği: bölüşüm oranında yalnızca TL.
        yalnizca_try=True,
    ),
    "DL-AU9W2TC6C9C60B8": WidgetTanimi(
        rate_type="participation_yield",
        variant="ara_odemeli",
        aciklama="Ara Ödemeli Katılma Hesabı Dağıtılan Kâr Payı Oranları",
        yalnizca_try=False,
    ),
    "DL-2036D46O0D6U0CF": WidgetTanimi(
        rate_type="profit_sharing_ratio",
        variant="ara_odemeli",
        aciklama="Ara Ödemeli Katılma Hesabı Kâr Paylaşım Oranları",
        yalnizca_try=True,
    ),
}

# TKBB'nin ölçü kodu → para birimi. m0 TL'dir; sıra arayüzde de korunur.
OLCU_KODU_PARA_BIRIMI: Final[dict[str, str]] = {
    "m0": "TRY",
    "m1": "USD",
    "m2": "EUR",
    "m3": "XAU",
}

# TKBB vade etiketi → KATİP'in kanonik etiketi.
VADE_ETIKETI: Final[dict[str, str]] = {
    "Aylık": "aylik",
    "3 Aylık": "3_aylik",
    "6 Aylık": "6_aylik",
    "Yıllık": "yillik",
}

# TKBB'nin tam banka adı → KATİP banka kodu (BANK_SEED ile eşleşir).
BANKA_ADI_KODU: Final[dict[str, str]] = {
    "Albaraka Türk Katılım Bankası A.Ş.": "albaraka",
    "Dünya Katılım Bankası A.Ş.": "dunya_katilim",
    "Türkiye Emlak Katılım Bankası A.Ş.": "emlak_katilim",
    "Hayat Finans Katılım Bankası A.Ş.": "hayat_finans",
    "Kuveyt Türk Katılım Bankası A.Ş.": "kuveyt_turk",
    "T.O.M. Katılım Bankası A.Ş.": "tom_bank",
    "Türkiye Finans Katılım Bankası A.Ş.": "turkiye_finans",
    "Vakıf Katılım Bankası A.Ş.": "vakif_katilim",
    "Ziraat Katılım Bankası A.Ş.": "ziraat_katilim",
}

RAW_ARSIV_DIZINI = Path(__file__).resolve().parent.parent / "data" / "raw_html" / "tkbb"


def widget_url(widget_id: str) -> str:
    """Bir widget'ın pivot API adresini üretir.

    ⚠️ `filters` ZORUNLU — gerekçesi `TKBB_FILTERS` yorumunda. Kaldırılırsa
    istek başarılı görünür ama tüm zamanların ortalaması döner.
    """
    return (
        f"{TKBB_API_BASE}?id={widget_id}&type=pivot&refresh_cache=false"
        f"&dashboard={TKBB_DASHBOARD_ID}&filters={TKBB_FILTERS}"
        f"&date_aggregate=auto&dashboard_date_aggregate=auto&rowLevel=0&ordering="
    )


def _parse_widget_json(gövde: dict[str, Any], *, yalnizca_try: bool) -> dict[str, dict[str, str]]:
    """TKBB pivot JSON'unu `{banka_kodu: {"vade|para": deger}}` biçimine çevirir.

    ⚠️ Değer BOZULMAZ: API'nin döndürdüğü sayı `str()` ile olduğu gibi taşınır,
    yuvarlanmaz. Boş hücre (`""`) ATLANIR — sıfır ile karıştırılmaz.

    Args:
        gövde: `{"data": [{"attributes": {"rows": [...]}}]}` biçiminde ham gövde.
        yalnizca_try: True ise yalnızca m0 (TL) ölçüsü alınır.

    Returns:
        Banka kodu → hücreler sözlüğü. Tanınmayan banka adı atlanır (loglanır).
    """
    sonuc: dict[str, dict[str, str]] = {}
    satirlar = gövde["data"][0]["attributes"]["rows"]

    for satir in satirlar:
        banka_adi = satir.get("banka")
        banka_kodu = BANKA_ADI_KODU.get(banka_adi or "")
        if banka_kodu is None:
            logger.warning("tkbb_bilinmeyen_banka_adi", ad=banka_adi)
            continue

        hucreler: dict[str, str] = {}
        for anahtar, deger in satir.items():
            if anahtar == "banka" or "|" not in anahtar:
                continue
            ham_vade, olcu_kodu = anahtar.split("|")
            if yalnizca_try and olcu_kodu != "m0":
                continue
            vade = VADE_ETIKETI.get(ham_vade)
            para = OLCU_KODU_PARA_BIRIMI.get(olcu_kodu)
            # ⚠️ `""` (boş hücre) veri YOK demektir; 0 ile karıştırılmaz.
            if vade is None or para is None or deger is None or deger == "":
                continue
            hucreler[f"{vade}|{para}"] = str(deger)

        sonuc[banka_kodu] = hucreler

    return sonuc


def cek_widgetlari() -> dict[str, dict[str, Any]]:
    """Dört widget'ı doğrudan TKBB pivot API'sinden çeker.

    Returns:
        widget_id → {"gövde": dict, "kaynak_url": str} — yalnızca gerçekten
        alınabilenler; başarısız olanlar sözlükte HİÇ YER ALMAZ (uydurulmaz).
    """
    ayarlar = get_settings()
    yakalanan: dict[str, dict[str, Any]] = {}

    with httpx.Client(
        timeout=30.0,
        follow_redirects=True,
        headers={"User-Agent": ayarlar.scraper_user_agent},
    ) as client:
        for widget_id in WIDGET_ESLEMESI:
            url = widget_url(widget_id)
            try:
                yanit = client.get(url)
                yanit.raise_for_status()
                gövde = yanit.json()
            except (httpx.HTTPError, json.JSONDecodeError) as exc:
                logger.warning("tkbb_widget_alinamadi", widget=widget_id, hata=str(exc))
                continue

            # Yapı beklendiği gibi mi? Değilse sessizce yanlış veri yazmaktan
            # vazgeçilir.
            try:
                gövde["data"][0]["attributes"]["rows"]
            except (KeyError, IndexError, TypeError):
                logger.warning("tkbb_widget_beklenmeyen_yapi", widget=widget_id)
                continue

            yakalanan[widget_id] = {"gövde": gövde, "kaynak_url": url}
            logger.info(
                "tkbb_widget_alindi",
                widget=widget_id,
                aciklama=WIDGET_ESLEMESI[widget_id].aciklama,
            )

    return yakalanan


def _bayatlari_sil(session: Any, urun_id: int, rate_type: str) -> int:
    """Bir ürünün TKBB kaynaklı mevcut oran satırlarını siler.

    ⚠️ NEDEN GEREKLİ. TKBB bir hücreyi boşalttığında (ör. Albaraka'nın ara
    ödemeli altın hesabı artık yayımlanmıyor) yalnızca upsert yapan bir
    yükleyici eski değeri veritabanında BIRAKIR ve arayüz kalkmış bir ürünü
    canlı gibi gösterir. Veri %100 API'den yeniden üretildiği için silmek
    güvenlidir — kayıp yoktur, yalnızca kaynakla birebir eşitlenir.

    Returns:
        Silinen satır sayısı.
    """
    from sqlalchemy import delete

    from app.db.models import ProductRate

    sonuc = session.execute(
        delete(ProductRate).where(
            ProductRate.product_id == urun_id,
            ProductRate.data_source == "tkbb_veripetegi",
            ProductRate.rate_type == rate_type,
        )
    )
    return int(sonuc.rowcount or 0)


def cekilen_veriyi_yukle(session: Any, yakalanan: dict[str, dict[str, Any]]) -> dict[str, int]:
    """Ham JSON'ları arşivler ve veritabanına birebir işler."""
    from sqlalchemy import select

    from app.db.models import Bank
    from scripts.load_tkbb_seed import _urun_bul_veya_olustur, _yaz_oranlar

    ozet = {
        "urun": 0,
        "oran": 0,
        "silinen_bayat": 0,
        "not_offered": 0,
        "widget_bulunamadi": len(WIDGET_ESLEMESI) - len(yakalanan),
    }
    bankalar = {b.code: b for b in session.scalars(select(Bank))}

    RAW_ARSIV_DIZINI.mkdir(parents=True, exist_ok=True)
    for widget_id, veri in yakalanan.items():
        # ⚠️ Ham yanıt ASLA silinmez (CLAUDE.md): kaynağı yeniden çekmeden
        # yeniden işleyebilmenin tek yolu.
        (RAW_ARSIV_DIZINI / f"{widget_id}.json").write_text(
            json.dumps(veri["gövde"], ensure_ascii=False, indent=2), encoding="utf-8"
        )

        tanim = WIDGET_ESLEMESI[widget_id]
        product_type = (
            "ara_donem_kar_odemeli" if tanim.variant == "ara_odemeli" else "birikim_katilma_hesabi"
        )
        satirlar = _parse_widget_json(veri["gövde"], yalnizca_try=tanim.yalnizca_try)

        for bank_code, hucreler in satirlar.items():
            bank = bankalar.get(bank_code)
            if bank is None or not hucreler:
                continue
            urun = _urun_bul_veya_olustur(
                session,
                bank,
                variant=tanim.variant,
                product_type=product_type,
                availability_status="offered",
            )
            ozet["urun"] += 1
            # Kaynakla birebir eşitle: önce bayatları sil, sonra yaz.
            ozet["silinen_bayat"] += _bayatlari_sil(session, urun.id, tanim.rate_type)
            session.flush()
            ozet["oran"] += _yaz_oranlar(
                session,
                urun,
                rate_type=tanim.rate_type,
                values=hucreler,
                evidence_text=(
                    f"TKBB Veri Peteği — {tanim.aciklama}. "
                    f"Kaynak: {TKBB_KAYNAK_SAYFASI}"
                ),
            )

        # ⚠️ "ÜRÜN YOK" API'DEN TÜRETİLİR, ELLE LİSTE TUTULMAZ. Ara ödemeli
        # uçları yalnızca o ürünü sunan bankaları döndürüyor (5 banka);
        # yanıtta HİÇ görünmeyen banka o ürünü sunmuyor demektir
        # (`not_offered`) — bu "veri eksik" (`unknown`) ile AYNI ŞEY DEĞİL,
        # bkz. `core/vocab.py::AVAILABILITY_STATUSES`. Elle bakımı gereken
        # `not_offered_banks` seed listesinin kaynakla ıraksama riski böylece
        # tamamen ortadan kalkar.
        if tanim.variant == "ara_odemeli":
            sunmayanlar = set(BANKA_ADI_KODU.values()) - set(satirlar)
            for bank_code in sorted(sunmayanlar):
                bank = bankalar.get(bank_code)
                if bank is None:
                    continue
                _urun_bul_veya_olustur(
                    session,
                    bank,
                    variant=tanim.variant,
                    product_type=product_type,
                    availability_status="not_offered",
                )
                ozet["not_offered"] += 1

    session.commit()
    return ozet


def main() -> int:
    """CLI girişi: `python dev.py tkbb-cek`."""
    print(f"TKBB Veri Peteği API'si çekiliyor ({len(WIDGET_ESLEMESI)} veri seti)")  # noqa: T201
    yakalanan = cek_widgetlari()

    eksik = set(WIDGET_ESLEMESI) - set(yakalanan)
    print(f"Alınan veri seti: {len(yakalanan)}/{len(WIDGET_ESLEMESI)}")  # noqa: T201
    # ⚠️ ASCII işaret: Windows Türkçe konsolu (cp1254) "✓/✗" basamıyor ve
    # `UnicodeEncodeError` ile çalıştırmayı düşürüyor (ölçüldü).
    for widget_id in yakalanan:
        print(f"  [OK]   {WIDGET_ESLEMESI[widget_id].aciklama}")  # noqa: T201
    for widget_id in sorted(eksik):
        print(f"  [EKSIK] {WIDGET_ESLEMESI[widget_id].aciklama} ({widget_id})")  # noqa: T201

    if not yakalanan:
        print("Hiçbir veri seti alınamadı. Fallback: python dev.py tkbb-yukle")  # noqa: T201
        return 1

    from app.db.session import SessionLocal

    with SessionLocal() as session:
        try:
            ozet = cekilen_veriyi_yukle(session, yakalanan)
        except NotFoundError as exc:
            print(f"Veritabanı hatası: {exc}")  # noqa: T201
            return 1

    print(  # noqa: T201
        f"Yazıldı — ürün: {ozet['urun']}, oran: {ozet['oran']}, "
        f"temizlenen bayat satır: {ozet['silinen_bayat']}"
    )
    if eksik:
        print(f"Eksik {len(eksik)} veri seti için: python dev.py tkbb-yukle")  # noqa: T201
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
