#!/usr/bin/env python
"""Proje görev betiği — `make` gerektirmez.

Kurulum, veritabanı, sunucu, kazıma ve test görevlerinin tek giriş noktasıdır.
`make` gerektirmez (Windows'ta çoğu zaman kurulu değildir) ve ek bağımlılık
kullanmaz; yalnızca Python standart kütüphanesiyle çalışır.

Kullanım:
    python dev.py kur          # bağımlılıkları kur (backend + frontend)
    python dev.py kur --playwright   # ek olarak tarayıcıyı da indir (~400 MB)
    python dev.py migrate      # veritabanı şemasını oluştur
    python dev.py seed         # 10 banka + terminoloji sözlüğü
    python dev.py api          # backend'i başlat  -> http://localhost:8000
    python dev.py web          # arayüzü başlat    -> http://localhost:5173
    python dev.py scrape       # tüm scraper'ları çalıştır
    python dev.py test         # testler + kapsam
    python dev.py lint         # ruff + mypy + tsc
    python dev.py baslat       # migrate + seed + api  (ilk kurulumdan sonra tek komut)

Keşif komutları (gerçek banka sitelerine istek atar, Playwright ister):
    python dev.py kesif-endpoint                      # kampanya listesi JSON uçları
    python dev.py kesif-hesaplayici                   # hesaplayıcı form envanteri
    python dev.py kesif-hesaplayici --banka ziraat_katilim --kuru
    python dev.py kesif-hesaplayici-api               # XHR/fetch endpoint keşfi (tüm bankalar)
    python dev.py kesif-hesaplayici-api --banka kuveyt_turk

Komut listesi için:
    python dev.py
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

KOK = Path(__file__).resolve().parent
BACKEND = KOK / "backend"
FRONTEND = KOK / "frontend"

VENV = BACKEND / ".venv"

WINDOWS = platform.system() == "Windows"
VENV_PYTHON = VENV / ("Scripts/python.exe" if WINDOWS else "bin/python")


def _python() -> str:
    """Sanal ortamdaki Python'u döndürür; yoksa çalışan yorumlayıcıyı kullanır."""
    if VENV_PYTHON.is_file():
        return str(VENV_PYTHON)
    return sys.executable


def _npm() -> str:
    """npm çalıştırılabilirinin adını döndürür."""
    return "npm.cmd" if WINDOWS else "npm"


def _calistir(komut: list[str], *, cwd: Path = KOK) -> int:
    """Komutu çalıştırır ve çıkış kodunu döndürür."""
    yazdir = " ".join(komut)
    print(f"\n\033[36m$ {yazdir}\033[0m  (dizin: {cwd.relative_to(KOK) if cwd != KOK else '.'})")
    try:
        return subprocess.call(komut, cwd=cwd)
    except FileNotFoundError:
        print(f"\033[31mKomut bulunamadı: {komut[0]}\033[0m")
        return 127


def _zincir(*adimlar: Callable[[], int]) -> int:
    """Adımları sırayla çalıştırır; ilk hatada durur."""
    for adim in adimlar:
        kod = adim()
        if kod != 0:
            return kod
    return 0


# ── Görevler ──────────────────────────────────────────────


def kur() -> int:
    """Backend sanal ortamını ve frontend paketlerini kurar.

    `--playwright` verilirse tarayıcı da indirilir. Varsayılan kurulumda
    İNDİRİLMEZ: ~400 MB'lık indirme kapalı ağ (on-premise) kurulumunu
    zorlaştırır ve yalnızca keşif adımlarında gereklidir.
    """
    if not VENV_PYTHON.is_file():
        print("Sanal ortam oluşturuluyor...")
        kod = _calistir([sys.executable, "-m", "venv", str(VENV)])
        if kod != 0:
            return kod

    kod = _calistir([_python(), "-m", "pip", "install", "--upgrade", "pip", "--quiet"])
    if kod != 0:
        return kod

    kod = _calistir([_python(), "-m", "pip", "install", "-e", ".[dev]"], cwd=BACKEND)
    if kod != 0:
        return kod

    if "--playwright" in sys.argv[1:]:
        kod = _playwright_kur()
        if kod != 0:
            return kod

    if shutil.which(_npm()) is None:
        print("\033[33mnpm bulunamadı; frontend kurulumu atlandı.\033[0m")
        print("Node.js 20+ kurup 'python dev.py kur' komutunu tekrar çalıştırın.")
        return 0

    kod = _calistir([_npm(), "install"], cwd=FRONTEND)
    if kod != 0:
        return kod

    _env_dosyasi_olustur()
    print("\n\033[32mKurulum tamam.\033[0m Sıradaki: python dev.py baslat")
    if "--playwright" not in sys.argv[1:]:
        print(
            "\033[2mKeşif adımları (kesif-endpoint / kesif-hesaplayici) tarayıcı ister:"
            "  python dev.py kur --playwright\033[0m"
        )
    return 0


def _playwright_kur() -> int:
    """Playwright'ı ve Chromium'u indirir.

    Ayrı tutulmasının nedeni ~400 MB'lık tarayıcı indirmesidir; kapalı ağ
    kurulumunda gereksiz yere zorunlu bağımlılık olmamalıdır. Yalnızca
    yalnızca keşif betikleri kullanır.
    """
    print("\nPlaywright kuruluyor (~400 MB tarayıcı indirmesi)...")
    kod = _calistir([_python(), "-m", "pip", "install", "playwright"])
    if kod != 0:
        return kod
    return _calistir([_python(), "-m", "playwright", "install", "chromium"])


def _env_dosyasi_olustur() -> None:
    """`.env` yoksa örnekten kopyalar."""
    env = KOK / ".env"
    ornek = KOK / ".env.example"
    if not env.exists() and ornek.exists():
        env.write_text(ornek.read_text(encoding="utf-8"), encoding="utf-8")
        print(".env dosyası .env.example'dan oluşturuldu.")


def migrate() -> int:
    """Veritabanı şemasını en son sürüme getirir."""
    return _calistir([_python(), "-m", "alembic", "upgrade", "head"], cwd=BACKEND)


def migrate_geri() -> int:
    """Son göçü geri alır.

    ⚠️ VERİ SİLER: ilk göç geri alındığında tablolar düşürülür ve toplanmış
    kampanya verisi kaybolur. Ham HTML arşivi (`backend/data/raw_html`)
    korunur; veri `seed` + `scrape` ile yeniden üretilebilir.
    """
    print(
        "\033[33mUYARI: Bu işlem tabloları düşürür ve kampanya verisini siler.\n"
        "Ham HTML arşivi korunur; veriyi 'python dev.py seed' ve "
        "'python dev.py scrape' ile geri yükleyebilirsiniz.\033[0m"
    )
    cevap = input("Devam edilsin mi? [e/H] ").strip().lower()
    if cevap not in ("e", "evet", "y", "yes"):
        print("İptal edildi.")
        return 0
    return _calistir([_python(), "-m", "alembic", "downgrade", "-1"], cwd=BACKEND)


def seed() -> int:
    """10 bankayı ve terminoloji sözlüğünü yükler (tekrar çalıştırılabilir)."""
    return _calistir([_python(), "-m", "app.db.seed"], cwd=BACKEND)


def api() -> int:
    """Backend'i geliştirme kipinde başlatır."""
    print("\nBackend: http://localhost:8000  ·  API dokümanı: http://localhost:8000/docs")
    return _calistir(
        [_python(), "-m", "uvicorn", "app.main:app", "--reload", "--port", "8000"],
        cwd=BACKEND,
    )


def web() -> int:
    """Arayüz geliştirme sunucusunu başlatır."""
    print("\nArayüz: http://localhost:5173")
    return _calistir([_npm(), "run", "dev"], cwd=FRONTEND)


def scrape() -> int:
    """Kayıtlı scraper'ları çalıştırır.

    Argümansız çağrıldığında tümünü çalıştırır. Tek banka veya pilot
    doğrulama için argümanlar alt komuta olduğu gibi aktarılır:

        python dev.py scrape --banka ziraat_katilim --kategori kart-kampanyalari --limit 5
    """
    ekler = _ek_argumanlar() or ["--tumu"]
    return _calistir([_python(), "-m", "app.scrapers.run", *ekler], cwd=BACKEND)


def scrape_js() -> int:
    """JS \"Daha fazla\" listelerini Playwright ile genişletir; detay httpx.

    Banka scraper dosyalarına Playwright gömülmez. Öncelik: Kuveyt, Dünya,
    Albaraka, Vakıf.
    """
    return _calistir(
        [_python(), "-m", "scripts.scrape_js_campaigns", *_ek_argumanlar()], cwd=BACKEND
    )


def scrape_deneme() -> int:
    """Kazımayı veritabanına yazmadan dener."""
    return _calistir(
        [_python(), "-m", "app.scrapers.run", "--all", "--dry-run"], cwd=BACKEND
    )


def urun_esle() -> int:
    """Kampanyaları ürünlerle eşleştirir (ağa çıkmaz).

    ⚠️ Bağ ÜRÜN TÜRÜNDEN kurulmaz; kampanya metninde ürünün ADI ya da
    ADRESİ geçmelidir. Tür eşlemesi, ürünün oran tablosunu aynı türdeki her
    kampanyaya kopyalamak olurdu.

    `--kuru` yazmadan raporlar, `--banka` tek bankayla sınırlar.
    """
    return _calistir(
        [_python(), "-m", "scripts.match_campaign_products", *_ek_argumanlar()], cwd=BACKEND
    )


def urun_dogrula() -> int:
    """Ürün ve oran kapsamasını doğrular ve rapor üretir."""
    return _calistir([_python(), "-m", "scripts.verify_products"], cwd=BACKEND)


def kesif_endpoint() -> int:
    """Kampanya listesi JSON uçlarını arar.

    ⚠️ Gerçek banka sitelerine istek atar. Playwright gerektirir; kurulu
    değilse keşif yapılmadan rapor üretilir.
    """
    return _calistir(
        [_python(), "-m", "scripts.discover_endpoints", *_ek_argumanlar()], cwd=BACKEND
    )


def kesif_hesaplayici_api() -> int:
    """Hesaplayıcı sayfalarında XHR/fetch endpoint keşfi (tüm bankalar).

    Config: `backend/data/config/calculator_banks.json`
    Ham kayıt: `backend/data/debug/network/<bank>/<tarih>/`
    """
    return _calistir(
        [_python(), "-m", "scripts.discover_calculator_apis", *_ek_argumanlar()],
        cwd=BACKEND,
    )


def kesif_hesaplayici() -> int:
    """Hesaplayıcı formlarını envanterler.

    ⚠️ Gerçek banka sitelerine istek atar. Banka başına en fazla 3 deneme
    yapılır; sonuçlar `calculator_inventory` tablosuna ve
    `docs/calculator_inventory.md` dosyasına yazılır.
    """
    return _calistir(
        [_python(), "-m", "scripts.inventory_calculators", *_ek_argumanlar()], cwd=BACKEND
    )


def envanter_uygula() -> int:
    """Hesaplayıcı envanterini ürün limitlerine uygular (ağa çıkmaz).

    `kesif-hesaplayici` sayfanın ne sunduğunu tabloya yazar; bu komut o
    envanteri `products` satırlarına bağlar. Ortak hesaplayıcının BİRLEŞİK
    vade listesi değil, seçenek etiketindeki ürüne özel sınır esas alınır.
    """
    return _calistir([_python(), "-m", "scripts.apply_inventory", *_ek_argumanlar()], cwd=BACKEND)


def hesaplayici_sorgula() -> int:
    """Oranı boş finansman ürünlerinde hesaplayıcıya örnek tutar sorar.

    ⚠️ AĞA ÇIKAR (Playwright). Çıktılar `is_binding=False`; bağlayıcı teklif
    sanılmaz. Banka başına sınırlı sorgu.
    """
    return _calistir(
        [_python(), "-m", "scripts.probe_calculators", *_ek_argumanlar()], cwd=BACKEND
    )


def hesaplayici_api_sorgula() -> int:
    """Doğrulanmış banka hesaplama API'lerini httpx ile sorgular.

    ⚠️ AĞA ÇIKAR. Playwright gerekmez.
    Albaraka, Vakıf, Hayat, Emlak, Kuveyt, Türkiye Finans.
    Çıktılar `is_binding=False`.
    """
    return _calistir(
        [_python(), "-m", "scripts.probe_calculator_apis", *_ek_argumanlar()],
        cwd=BACKEND,
    )


def hesaplayici_hedef_sorgula() -> int:
    """Belirli banka hesaplayıcı URL'lerinden tüm ürün varyantlarını sorgular.

    ⚠️ AĞA ÇIKAR (Playwright). Kuveyt/Albaraka/TF/Vakıf vb. dropdown'daki
    her finansman türü max tutar/vade ile denenir; `is_binding=False` yazar.
    """
    return _calistir(
        [_python(), "-m", "scripts.probe_calculator_targets", *_ek_argumanlar()],
        cwd=BACKEND,
    )


def geri_doldur() -> int:
    """Bankanın kendi kategori etiketini arşivlenmiş HTML'den geri doldurur.

    AĞA ÇIKMAZ. `bank_category` sütunu sonradan eklendiği için ondan önce
    çekilmiş kayıtlarda boş; arşivdeki liste sayfaları o etiketi taşıyor.
    """
    return _calistir(
        [_python(), "-m", "scripts.backfill_bank_category", *_ek_argumanlar()], cwd=BACKEND
    )


def yeniden_isle() -> int:
    """Temiz metni ham HTML arşivinden yeniden üretir (ağa çıkmaz).

    Ön işlemede yabancı kampanya blokları (§6.1) ayıklanmıyordu; kural
    eklendikten sonra metin, bankalara yeni istek atmadan tazelenir.
    Tarihi hiç olmayan kampanyaların dönemi de metinden geri doldurulur.
    """
    return _calistir(
        [_python(), "-m", "scripts.reprocess_clean_text", *_ek_argumanlar()], cwd=BACKEND
    )


def urun_aciklama_doldur() -> int:
    """Finansman ürün açıklamalarını arşiv clean_text'ten doldurur (ağa çıkmaz)."""
    return _calistir(
        [_python(), "-m", "scripts.backfill_product_descriptions", *_ek_argumanlar()],
        cwd=BACKEND,
    )


def urun_tekilestir() -> int:
    """Aynı banka+ad+tür ürünlerini birleştirir; kopyayı pasife alır."""
    return _calistir(
        [_python(), "-m", "scripts.dedupe_products", *_ek_argumanlar()],
        cwd=BACKEND,
    )


def urun_js_aciklama() -> int:
    """Playwright ile ürün sayfasındaki Nedir?/tanıtım bloğunu doldurur."""
    return _calistir(
        [_python(), "-m", "scripts.scrape_product_descriptions_js", *_ek_argumanlar()],
        cwd=BACKEND,
    )


def finansman_metin_zenginlestir() -> int:
    """Oranı/limiti boş finansmanları metinden doldurur veya pasife alır (ağa çıkmaz)."""
    return _calistir(
        [_python(), "-m", "scripts.enrich_no_data_financing", *_ek_argumanlar()],
        cwd=BACKEND,
    )


def finansman_aile_orani() -> int:
    """Partner/niş ürünlere aile oranını miras bırakır (ağa çıkmaz, bağlayıcı değil)."""
    return _calistir(
        [_python(), "-m", "scripts.inherit_family_rates", *_ek_argumanlar()],
        cwd=BACKEND,
    )


def urun_kazi() -> int:
    """Ürün/finansman sayfalarından limit, varyant ve oran çıkarır.

    ⚠️ AĞA ÇIKAR. Hesaplayıcılar SORGULANMAZ; yalnızca form nitelikleri
    (dropdown seçenekleri, tutar sınırları, izinli vadeler) okunur.
    """
    return _calistir([_python(), "-m", "scripts.scrape_products", *_ek_argumanlar()], cwd=BACKEND)


def urun_kazi_deneme() -> int:
    """Ürün kazımasını veritabanına yazmadan dener (ağa çıkar)."""
    ek = _ek_argumanlar() or ["--tumu"]
    return _calistir(
        [_python(), "-m", "scripts.scrape_products", *ek, "--kuru"], cwd=BACKEND
    )


def siniflandir() -> int:
    """Kampanyaları dört eksende sınıflandırır ve raporu üretir.

    Kayıtlı veriden çalışır, AĞA ÇIKMAZ. Sözlük genişletildikçe yeniden
    çalıştırılabilir; bankalara yeni istek gitmez.
    """
    return _calistir([_python(), "-m", "scripts.categorize", *_ek_argumanlar()], cwd=BACKEND)


def llm_saglik() -> int:
    """Yapılandırılmış LLM sağlayıcısına ulaşılıp ulaşılamadığını söyler.

    SPRINT 3A'da `local` için "servis yok" çıktısı BEKLENEN sonuçtur: model
    SPRINT 3B'de kurulacak.
    """
    return _calistir([_python(), "-m", "scripts.llm_health", *_ek_argumanlar()], cwd=BACKEND)


def gold_ornek() -> int:
    """Gold set örneklemi seçer (ağa çıkmaz).

    Dengeli ve zor vaka ağırlıklı 100 kampanya seçip
    `data/gold/gold_sample.jsonl` dosyasına yazar.
    """
    return _calistir([_python(), "-m", "scripts.sample_gold", *_ek_argumanlar()], cwd=BACKEND)


def etiketle() -> int:
    """Gold set etiketleme arayüzünü açar.

    Backend'i başlatır; arayüz http://localhost:8000/api/v1/annotate/ui
    adresinde çalışır. AĞA ÇIKMAZ, yalnızca yerel veritabanını okur.
    """
    print("")
    print("Etiketleme arayüzü: http://localhost:8000/api/v1/annotate/ui")
    print("Kılavuz: docs/gold_annotation_guide.md")
    print("Durdurmak için Ctrl+C")
    print("")
    return _calistir(
        [_python(), "-m", "uvicorn", "app.main:app", "--reload", "--port", "8000"],
        cwd=BACKEND,
    )


def gold_durum() -> int:
    """Etiketleme ilerlemesini yazar (ağa çıkmaz)."""
    return _calistir([_python(), "-m", "scripts.gold_status", *_ek_argumanlar()], cwd=BACKEND)


def tkbb_yukle() -> int:
    """TKBB Veri Peteği'nin elle doğrulanmış verisini yükler (ağa çıkmaz).

    `tkbb-cek` bu ortamda çalışmadığında/çalıştırılmadığında kullanılan
    fallback — KAPI 4.4.
    """
    return _calistir([_python(), "-m", "scripts.load_tkbb_seed"], cwd=BACKEND)


def tkbb_cek() -> int:
    """TKBB Veri Peteği'ni Playwright ile canlı sitesinden çeker.

    ⚠️ Gerçek ağa çıkar, Playwright/Chromium ister. Başarısız olursa
    `tkbb-yukle` fallback'ine düşün — KAPI 4.3/4.4.
    """
    return _calistir([_python(), "-m", "scripts.scrape_tkbb", *_ek_argumanlar()], cwd=BACKEND)


def kanit_bagla() -> int:
    """Kanıtı boş gold etiketlerine metinden bağlamlı kanıt bağlar (ağa çıkmaz).

    ⚠️ İNSAN DOĞRULAMASI DEĞİLDİR. Etiketin DEĞERİNİ metinde arar ve
    çevresindeki cümle parçasını kanıt yazar; değerin doğruluğunu denetlemez.
    Yazılan kanıtlar `oto-kanit` ile işaretlenir ve `gold-durum` bunları
    insan seçimlerinden AYRI sayar.

    Sınıflandırma alanları (`sector`, `product_type`, `target_customer`,
    `reward_type`) bağlanmaz: metin kategori adını yazmaz, hangi ifadenin o
    kategoriyi doğurduğu insan yargısıdır.

    `--kuru` ile yazmadan kaç etiketin bağlanacağı raporlanır.
    """
    return _calistir(
        [_python(), "-m", "scripts.anchor_gold_evidence", *_ek_argumanlar()], cwd=BACKEND
    )


def cikarim() -> int:
    """Kampanya metinlerinden bilgi çıkarır (ağa çıkmaz).

    SPRINT 3A'da yalnızca kural tabanlı katman çalışır; LLM katmanı
    KAPI A6'da eklenecek.
    """
    return _calistir([_python(), "-m", "scripts.extract", *_ek_argumanlar()], cwd=BACKEND)


def kart_uret() -> int:
    """Varlık kartlarını üretir (ağa çıkmaz).

    Kartlar SPRINT 5'te gömülecek metinlerdir; yalnızca DOĞRULANMIŞ
    alanları içerir.
    """
    return _calistir([_python(), "-m", "scripts.build_cards", *_ek_argumanlar()], cwd=BACKEND)


def ablation() -> int:
    """Üç konfigürasyonu karşılaştırır ve ablasyon tablosunu üretir.

    ⚠️ Bu sprint'te yalnızca `rule_only` gerçek sayı üretir; diğer ikisi
    MockProvider ile çalışır ve anlamlı değildir (tablo iskeleti kurulur).
    """
    return _calistir([_python(), "-m", "scripts.ablation", *_ek_argumanlar()], cwd=BACKEND)


def degerlendir() -> int:
    """Gold set'e karşı çıkarım kalitesini ölçer (ağa çıkmaz)."""
    return _calistir([_python(), "-m", "scripts.evaluate", *_ek_argumanlar()], cwd=BACKEND)


# ── Sprint 5 (sohbet) ─────────────────────────────────────
# ⚠️ 3B komutlarından AYRI bölüm. Merge conflict'i azaltmak için
# sohbet-degerlendir / gomme-uret burada toplanır.


def sohbet_degerlendir() -> int:
    """Sohbet gold set'ine karşı uçtan uca ölçüm (ağa çıkmaz).

    Çıktı: docs/sprint5_evaluation.md — docs/evaluation.md (çıkarım F1) ile karıştırılmaz.
    """
    return _calistir(
        [_python(), "-m", "scripts.evaluate_chat", *_ek_argumanlar()], cwd=BACKEND
    )


def gomme_uret() -> int:
    """entity_cards → embeddings (mevcut semantic kanalı doldurur).

    FAISS/vektör DB yok. source_hash=card_hash iken atlar.
    LocalProvider.embed yoksa lexical-only devam eder.
    """
    return _calistir(
        [_python(), "-m", "scripts.build_embeddings", *_ek_argumanlar()], cwd=BACKEND
    )


def _ek_argumanlar() -> list[str]:
    """Komut adından sonraki argümanları alt betiğe geçirir.

    `python dev.py kesif-hesaplayici --banka ziraat_katilim` çağrısında
    `--banka ziraat_katilim` kısmını taşır.
    """
    return sys.argv[2:]


def disa_aktar() -> int:
    """Veri setini kararlı anahtarlarla dışa aktarır (ağa çıkmaz).

    Kampanya verisi silinmeden önce ZORUNLUDUR: gold etiketleri autoincrement
    `campaign_id`'ye bağlı ve yeniden kazımada o id'ler değişiyor.
    """
    return _calistir([_python(), "-m", "scripts.export_dataset", *_ek_argumanlar()], cwd=BACKEND)


def disa_aktar_dogrula() -> int:
    """Dışa aktarmayı doğrular ve damga basar (ağa çıkmaz).

    Damga olmadan `sifirla` çalışmayı reddeder.
    """
    return _calistir([_python(), "-m", "scripts.verify_export", *_ek_argumanlar()], cwd=BACKEND)


def sifirla() -> int:
    """Kampanya verisini sıfırlar. VERİ SİLER.

    Doğrulanmış dışa aktarma ve `--onay SIL` gerektirir; SQLite dosyası önce
    `data/backups/` altına kopyalanır. `source_documents` korunur.
    """
    return _calistir(
        [_python(), "-m", "scripts.reset_campaign_data", *_ek_argumanlar()], cwd=BACKEND
    )


def suresi_dolanlari_temizle() -> int:
    """Süresi KESİN OLARAK dolmuş kampanyaları kalıcı siler. VERİ SİLER.

    `sifirla` ile aynı güvenlik desenini (doğrulanmış dışa aktarma +
    `--onay SIL` + SQLite yedeği) izler ama TÜMÜNÜ değil, yalnızca
    `status='expired'` olan kampanyaları siler — tarihi bilinmeyen
    (`unknown`) kampanyalar etkilenmez. `source_documents` korunur.
    """
    return _calistir(
        [_python(), "-m", "scripts.delete_expired_campaigns", *_ek_argumanlar()], cwd=BACKEND
    )


def gold_yeniden_bagla() -> int:
    """Gold etiketlerini yeniden kazınmış kampanyalara bağlar (ağa çıkmaz)."""
    return _calistir([_python(), "-m", "scripts.reanchor_gold", *_ek_argumanlar()], cwd=BACKEND)


def gold_denetle() -> int:
    """Kanıtı doğrulanamayan gold etiketlerini raporlar (ağa çıkmaz)."""
    return _calistir([_python(), "-m", "scripts.gold_recheck", *_ek_argumanlar()], cwd=BACKEND)


def test() -> int:
    """Testleri kapsam raporuyla çalıştırır."""
    return _calistir(
        [
            _python(),
            "-m",
            "pytest",
            "tests",
            "--cov=app",
            "--cov-report=term-missing",
            "--cov-fail-under=60",
        ],
        cwd=BACKEND,
    )


def lint() -> int:
    """Biçim, kural ve tip denetimi yapar."""
    kod = _zincir(
        lambda: _calistir([_python(), "-m", "ruff", "check", "app", "tests"], cwd=BACKEND),
        lambda: _calistir(
            [_python(), "-m", "ruff", "format", "--check", "app", "tests"], cwd=BACKEND
        ),
        lambda: _calistir([_python(), "-m", "mypy", "app"], cwd=BACKEND),
    )
    if kod != 0:
        return kod

    if shutil.which(_npm()) is None:
        print("\033[33mnpm bulunamadı; arayüz tip denetimi atlandı.\033[0m")
        return 0
    return _calistir([_npm(), "run", "typecheck"], cwd=FRONTEND)


def bicimle() -> int:
    """Kodu biçimlendirir."""
    return _zincir(
        lambda: _calistir([_python(), "-m", "ruff", "format", "app", "tests"], cwd=BACKEND),
        lambda: _calistir(
            [_python(), "-m", "ruff", "check", "--fix", "app", "tests"], cwd=BACKEND
        ),
    )


# ── Boru hattı ────────────────────────────────────────────
#
# ⚠️ ADIM SIRASI KEYFİ DEĞİL, BAĞIMLILIK ZİNCİRİDİR. Her adım bir
# öncekinin çıktısını okur:
#
#     kazı → ham HTML + clean_text
#       └─ ön işleme → clean_text tazelenir (ayrıştırıcı değiştiyse)
#            └─ çıkarım → alanlar (clean_text'ten)
#                 └─ sınıflandırma → kategoriler (clean_text + alanlar)
#                      └─ kart üretimi → varlık kartları (kategoriler)
#                           └─ değerlendirme → F1 (çıkarım vs gold)
#
# Sıra bozulursa hata VERMEZ, sessizce eski veriyle çalışır: kalıp
# düzeltildikten sonra `cikarim` çalıştırılmazsa `degerlendir` bir gün
# önceki çıkarımı ölçer ve düzeltmenin etkisi hiç görünmez. Ölçüldü:
# 19 Ağustos'ta kalıplar düzeltildi, çıkarım 18 Ağustos'tan kalmıştı;
# yapılan iyileştirmeler F1'e yansımıyordu.

# ⚠️ KISMİ BAŞARI HATTI DURDURMAZ. `app.scrapers.run` çıkış kodunu ikiye
# ayırıyor: 1 = bazı adresler alınamadı ama çalıştırma tamamlandı,
# 2 = gerçek hata (banka koduna erişilemedi, yapılandırma bozuk).
#
# Bankalar biten kampanyayı siteden KALDIRIYOR; detay adresi 404 dönüyor ve
# bu README'de de yazılı, beklenen bir durum. Kısmi başarıyı hata sayan bir
# hat pratikte hiç çalışmaz: 602 kampanyanın 3'ü bayatladığı anda zincir
# duruyor ve ondan sonraki yedi adım hiç yürütülmüyordu.
_KISMI_BASARI_TOLERE_EDILEN: frozenset[str] = frozenset({"scrape", "urun-kazi"})

_HAT_ADIMLARI: dict[str, tuple[str, bool]] = {
    # ad: (açıklama, ağa çıkar mı)
    "scrape": ("Kampanya sayfalarını çeker", True),
    "urun-kazi": ("Ürün/oran/limit sayfalarını çeker", True),
    "tkbb-cek": ("TKBB katılma oranlarını çeker", True),
    "yeniden-isle": ("Temiz metni arşivden tazeler", False),
    "cikarim": ("Metinlerden alanları çıkarır", False),
    "siniflandir": ("Dört eksende sınıflandırır", False),
    "kart-uret": ("Varlık kartlarını üretir", False),
    "urun-esle": ("Kampanyaları ürünlerle eşleştirir", False),
    "urun-dogrula": ("Ürün/oran kapsamasını denetler", False),
    "degerlendir": ("Gold set'e karşı F1 ölçer", False),
}


def boru_hatti() -> int:
    """Veri hattını uçtan uca çalıştırır.

    Günlük kullanımda tek komut yeterlidir; alt adımlar tek tek de
    çağrılabilir (hepsi `python dev.py <adım>` olarak durmaya devam eder).

        python dev.py boru-hatti              # tam hat (AĞA ÇIKAR)
        python dev.py boru-hatti --agsiz      # yalnızca yeniden işleme
        python dev.py boru-hatti --kuru       # ne çalışacağını yaz, çalıştırma
        python dev.py boru-hatti --banka albaraka

    ⚠️ `--agsiz` KAZIMA ADIMLARINI ATLAR. Ayrıştırıcı ya da kalıp kodu
    değiştiğinde doğru seçenek budur: ham HTML arşivi (`data/raw_html`) hiç
    silinmediği için tüm veri bankalara yeni istek atmadan yeniden üretilir.
    Bankaya istek atmak yalnızca sayfaların KENDİSİ değiştiyse gerekir.
    """
    ekler = _ek_argumanlar()
    agsiz = "--agsiz" in ekler
    kuru = "--kuru" in ekler
    banka = ""
    if "--banka" in ekler:
        yer = ekler.index("--banka")
        if yer + 1 < len(ekler):
            banka = ekler[yer + 1]

    secilen = [
        (ad, aciklama, agli)
        for ad, (aciklama, agli) in _HAT_ADIMLARI.items()
        if not (agsiz and agli)
    ]

    print("\n\033[1mBORU HATTI\033[0m")
    for sira, (ad, aciklama, agli) in enumerate(secilen, start=1):
        isaret = "\033[33mAĞ\033[0m" if agli else "  "
        print(f"  {sira}. {isaret} {ad:16} {aciklama}")
    if banka:
        print(f"\n  banka süzgeci: {banka}")
    if kuru:
        print("\n\033[36mKURU ÇALIŞMA — hiçbir adım yürütülmedi.\033[0m")
        return 0

    # ⚠️ Banka süzgeci YALNIZCA kazıma adımlarına geçer. `cikarim` ve
    # `degerlendir` tüm veri kümesi üzerinde çalışır; süzgeç geçirilirse
    # F1 tek bankanın alt kümesinde ölçülür ve rapor yanıltıcı olur.
    suzgecli = {"scrape", "urun-kazi"}

    uyarilar: list[str] = []
    for sira, (ad, _, _) in enumerate(secilen, start=1):
        print(f"\n\033[1m[{sira}/{len(secilen)}] {ad}\033[0m")
        modul, varsayilan = _HAT_MODULLERI[ad]
        argumanlar = list(varsayilan)
        if ad in suzgecli:
            argumanlar += ["--banka", banka] if banka else ["--tumu"]
        kod = _calistir([_python(), "-m", modul, *argumanlar], cwd=BACKEND)
        if kod == 1 and ad in _KISMI_BASARI_TOLERE_EDILEN:
            print(
                f"\n\033[33m'{ad}' kısmi başarıyla bitti — bazı adresler alınamadı. "
                "Hat devam ediyor.\033[0m"
            )
            uyarilar.append(ad)
            continue
        if kod != 0:
            print(f"\n\033[31mHat '{ad}' adımında durdu (çıkış {kod}).\033[0m")
            print("Sonraki adımlar bu adımın çıktısını okuyacaktı; yürütülmedi.")
            return kod

    print("\n\033[32mBoru hattı tamamlandı.\033[0m")
    return 0


# Adım adı → (modül, zorunlu varsayılan argümanlar).
#
# ⚠️ `cikarim` KİP SEÇMEDEN ÇALIŞMAZ. Üretim kipi `--sadece-kural`:
# `local` sağlayıcı Sprint 3B'de bağlanacak, o zamana kadar `--tumu`
# MockProvider'ı devreye sokar ve ölçümü sahte veriyle kirletir.
_HAT_MODULLERI: dict[str, tuple[str, list[str]]] = {
    "scrape": ("app.scrapers.run", []),
    "urun-kazi": ("scripts.scrape_products", []),
    "tkbb-cek": ("scripts.scrape_tkbb", []),
    "yeniden-isle": ("scripts.reprocess_clean_text", []),
    "cikarim": ("scripts.extract", ["--sadece-kural"]),
    "siniflandir": ("scripts.categorize", []),
    "kart-uret": ("scripts.build_cards", []),
    "urun-esle": ("scripts.match_campaign_products", []),
    "urun-dogrula": ("scripts.verify_products", []),
    "degerlendir": ("scripts.evaluate", []),
}


def derle_web() -> int:
    """Arayüzü derler; backend bu çıktıyı "/" altından sunar."""
    return _calistir([_npm(), "run", "build"], cwd=FRONTEND)


def baslat() -> int:
    """Şemayı hazırlar, veriyi yükler ve backend'i başlatır."""
    return _zincir(migrate, seed, api)


GOREVLER: dict[str, tuple[Callable[[], int], str]] = {
    "kur": (kur, "Bağımlılıkları kurar (backend + frontend)"),
    "baslat": (baslat, "migrate + seed + api — ilk kurulumdan sonra tek komut"),
    "migrate": (migrate, "Veritabanı şemasını oluşturur/günceller"),
    "migrate-geri": (migrate_geri, "Son göçü geri alır"),
    "seed": (seed, "10 banka + terminoloji sözlüğünü yükler"),
    "api": (api, "Backend'i başlatır (http://localhost:8000)"),
    "web": (web, "Arayüzü başlatır (http://localhost:5173)"),
    "scrape": (scrape, "Tüm scraper'ları çalıştırır"),
    "scrape-js": (scrape_js, "JS liste (Daha fazla) + httpx detay — Playwright ayrı"),
    "scrape-deneme": (scrape_deneme, "Kazımayı veritabanına yazmadan dener"),
    "geri-doldur": (geri_doldur, "Banka kategorisini arşivden geri doldurur (ağa çıkmaz)"),
    "yeniden-isle": (yeniden_isle, "Temiz metni arşivden yeniden üretir (ağa çıkmaz)"),
    "urun-kazi": (urun_kazi, "Ürün/finansman limit, varyant ve oranlarını çeker"),
    "urun-kazi-deneme": (urun_kazi_deneme, "Ürün kazımasını yazmadan dener"),
    "urun-aciklama-doldur": (
        urun_aciklama_doldur,
        "Finansman açıklamalarını arşivden doldurur (ağa çıkmaz)",
    ),
    "urun-tekilestir": (urun_tekilestir, "Çoğalan finansman ürünlerini tekilleştirir"),
    "urun-js-aciklama": (
        urun_js_aciklama,
        "Playwright ile ürün Nedir? açıklamasını doldurur",
    ),
    "finansman-metin-zenginlestir": (
        finansman_metin_zenginlestir,
        "Boş finansman limit/oranını metinden doldurur veya pasife alır",
    ),
    "finansman-aile-orani": (
        finansman_aile_orani,
        "Partner/niş ürünlere aile oranını miras bırakır (bağlayıcı değil)",
    ),
    "urun-esle": (urun_esle, "Kampanyaları ürünlerle eşleştirir (ağa çıkmaz)"),
    "urun-dogrula": (urun_dogrula, "Ürün ve oran kapsamasını doğrular ve rapor üretir"),
    "siniflandir": (siniflandir, "Kampanyaları dört eksende sınıflandırır (ağa çıkmaz)"),
    "llm-saglik": (llm_saglik, "LLM sağlayıcısının durumunu kontrol eder"),
    "gold-ornek": (gold_ornek, "Gold set örneklemi seçer (ağa çıkmaz)"),
    "etiketle": (etiketle, "Gold set etiketleme arayüzünü açar"),
    "gold-durum": (gold_durum, "Etiketleme ilerlemesini raporlar"),
    "kanit-bagla": (kanit_bagla, "Kanıtı boş gold etiketlerini metne bağlar"),
    "tkbb-yukle": (tkbb_yukle, "TKBB Veri Peteği'nin elle doğrulanmış verisini yükler"),
    "tkbb-cek": (tkbb_cek, "TKBB Veri Peteği'ni Playwright ile canlı çeker (KAPI 4.3)"),
    "envanter-uygula": (envanter_uygula, "Hesaplayıcı envanterini ürün limitlerine uygular"),
    "hesaplayici-sorgula": (
        hesaplayici_sorgula,
        "Oranı boş ürünlerde hesaplayıcıya örnek tutar sorar (Playwright)",
    ),
    "hesaplayici-hedef-sorgula": (
        hesaplayici_hedef_sorgula,
        "Verilen banka hesaplayıcı URL'lerinden tüm ürün varyantlarını sorgular",
    ),
    "hesaplayici-api-sorgula": (
        hesaplayici_api_sorgula,
        "Doğrulanmış finansman API'lerini httpx ile sorgular (Albaraka/Vakıf)",
    ),
    "cikarim": (cikarim, "Kampanya metinlerinden bilgi çıkarır (ağa çıkmaz)"),
    "degerlendir": (degerlendir, "Gold set'e karşı F1 ölçer (ağa çıkmaz)"),
    "ablation": (ablation, "Üç kipi karşılaştırır, ablasyon tablosunu üretir"),
    "kart-uret": (kart_uret, "Varlık kartlarını üretir (ağa çıkmaz)"),
    # ── Sprint 5 (sohbet) — 3B komutlarından ayrı ──
    "sohbet-degerlendir": (
        sohbet_degerlendir,
        "Sohbet gold set ölçümü → docs/sprint5_evaluation.md",
    ),
    "gomme-uret": (gomme_uret, "Kart gömmelerini üretir (embeddings tablosu)"),
    "kesif-endpoint": (kesif_endpoint, "Kampanya listesi JSON uçlarını arar (Playwright)"),
    "kesif-hesaplayici": (
        kesif_hesaplayici,
        "Hesaplayıcı formlarını envanterler (Playwright)",
    ),
    "kesif-hesaplayici-api": (
        kesif_hesaplayici_api,
        "Hesaplayıcı XHR/fetch endpoint keşfi (tüm bankalar)",
    ),
    "disa-aktar": (disa_aktar, "Veri setini kararlı anahtarlarla dışa aktarır"),
    "disa-aktar-dogrula": (disa_aktar_dogrula, "Dışa aktarmayı doğrular ve damgalar"),
    "sifirla": (sifirla, "Kampanya verisini sıfırlar (VERİ SİLER, onay ister)"),
    "suresi-dolanlari-temizle": (
        suresi_dolanlari_temizle,
        "Süresi kesin dolmuş kampanyaları kalıcı siler (VERİ SİLER, onay ister)",
    ),
    "gold-yeniden-bagla": (gold_yeniden_bagla, "Gold etiketlerini yeniden bağlar"),
    "gold-denetle": (gold_denetle, "Kanıtı doğrulanamayan gold etiketlerini raporlar"),
    "test": (test, "Testleri kapsam raporuyla çalıştırır"),
    "lint": (lint, "ruff + mypy + tsc denetimi"),
    "bicimle": (bicimle, "Kodu biçimlendirir"),
    "boru-hatti": (boru_hatti, "Veri hattını uçtan uca çalıştırır (tek komut)"),
    "derle-web": (derle_web, "Arayüzü üretim için derler"),
}


def _yardim() -> int:
    """Komut listesini yazar."""
    print(__doc__.split("Kullanım:")[0].strip())
    print("\nKomutlar:\n")
    for ad, (_, aciklama) in GOREVLER.items():
        print(f"  \033[36m{ad:16s}\033[0m {aciklama}")
    print("\nÖrnek:  python dev.py baslat\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Betiğin giriş noktası."""
    if WINDOWS:
        # Windows konsolunda ANSI renkleri ve Türkçe karakterler için.
        os.system("")  # noqa: S605  (renk desteğini etkinleştirir)
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")

    argumanlar = argv if argv is not None else sys.argv[1:]
    if not argumanlar or argumanlar[0] in ("-h", "--help", "yardim"):
        return _yardim()

    ad = argumanlar[0]
    gorev = GOREVLER.get(ad)
    if gorev is None:
        print(f"\033[31mBilinmeyen komut: {ad}\033[0m\n")
        return _yardim() or 2

    return gorev[0]()


if __name__ == "__main__":
    raise SystemExit(main())
