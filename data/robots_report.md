# robots.txt Uyum Raporu

> Şartname madde 15 (Etik Kurallar). Bu rapor `source_documents.robots_allowed`
> kolonundan üretilir; her istek denetlenir ve sonucu kayıt altına alınır.

## Özet

| | Adet |
|---|---|
| Toplam belge kaydı | **2981** |
| `robots_allowed = true` (çekildi) | **2923** |
| `robots_allowed = false` (**çekilmedi**) | **58** |

⚠️ **Engellenen adrese istek YAPILMAZ.** Kayıt, "bu adres keşfedildi ama
robots.txt izin vermediği için çekilmedi" bilgisini saklar. Kaydın kendisi bir
bulgudur: veri setindeki boşluğun sebebi belgelenmiş olur, "bu banka az
kampanya yayımlıyor" gibi yanlış bir sonuca varılmaz.

## Engellenen adresler

> ⚠️ **19 Ağustos 2026 güncellemesi — aşağıdaki iki engel ARTIK YOK.**
> Bankaların `robots.txt` dosyaları yeniden okundu; ikisi de bu adresleri
> bugün açıyor. 58 engelli kayıt 16-17 Ağustos'tan kalma **bayat kayıttır**.
> Veriler `SCRAPER_ROBOTS_OVERRIDE` **kapalıyken**, yani tam uyumla çekildi.

### Dünya Katılım — 48 kampanya → çözüldü

16 Ağustos'ta keşif 48 kampanya adresi buldu, hiçbirine istek atılmadı.

**19 Ağustos'ta yeniden okunan `robots.txt`:**
```
User-agent: *
Allow: /
Disallow: *search=
```

Kampanya yolu açık. Yeniden kazımada **44 kampanya `robots_allowed=true`
ile çekildi**; geçersiz kılma anahtarı KULLANILMADI. Eski 48 kayıt tarihsel
iz olarak duruyor.

Kalan 4 adres (`dsdamat`, `lc-waikiki`, `pttavm`, `vakkorama`) canlıda 200
dönüyor ve robots izinli; sitemap'te artık listelenmedikleri için keşfe
girmiyorlar. Bu bir **robots kısıtı değil, keşif boşluğudur**.

### Türkiye Finans — 10 liste sayfası → çözüldü

**19 Ağustos'ta okunan `robots.txt` tam içeriği** `/tr-tr/kampanyalar/Sayfalar/`
kalıbını içermiyor; yalnızca TEK bir kampanya sayfası adıyla kapalı:

```
Disallow: /tr-tr/kampanyalar/Sayfalar/edenred-tanisma-paketi-kampanyasi.aspx
Disallow: /*pdf$
```

Kayıtlı 10 kategori sayfasının hiçbiri bu listede değil. Yeniden kazımada
22 sayfa uyumla çekildi.

> **Ders:** `robots.txt` bir anlık görüntüdür, değişir. Engel kaydı
> "kalıcı yasak" değil, "o tarihte yasaktı" demektir; kazıma yenilenirken
> yeniden okunmalıdır.

## Aşılmayan JSON uçları

`kesif-endpoint` iki bankada kampanya listesi JSON ucu buldu. İkisi de
robots.txt ile kapalı ve **kullanılmadı**:

| Banka | Uç | Kural |
|---|---|---|
| Vakıf Katılım | `/plugins/CampaignListJson?...page=N` | `Disallow: /plugins/` |
| Albaraka | `/plugins/GetCampaigns?...PageIndex=N` | `Disallow: /plugins/` |

Bu uçların yerine **sitemap** kullanıldı ve daha fazla veri verdi: Vakıf 99,
Albaraka 40 adres — uçlar sayfa başına yalnızca 9 kayıt döndürüyordu.

⚠️ Yarışma kapsamında çalışıyor olmak, üçüncü tarafın `robots.txt`
direktifini kaldırmaz. Bu karar oturumlar arası tartışıldı ve korundu;
pratikte bir maliyeti de olmadı, izinli yol daha zengin çıktı.

## Ürün sayfalarında durum

Ürün/finansman kazımasında (`urun-kazi`, 222 ürün / 10 banka)
**hiçbir adres robots.txt ile engellenmedi**. Engellenen yollar yalnızca
yukarıdaki `/plugins/` uçları ve Dünya/TF'nin kampanya yollarıydı.

## Uygulanan diğer etik kurallar

| Kural | Uygulama |
|---|---|
| İstekler arası gecikme | `scraper_request_delay_seconds` (varsayılan 2.0 sn) |
| Kimliğini açık eden User-Agent | `Fetcher` gerçek ve izlenebilir UA gönderir, gizlemez |
| Hesaplayıcı sorgulama | **YAPILMADI** — `calculator_probes` tablosu boş (0 kayıt) |
| Hesaplayıcı envanteri deneme sınırı | Banka başına en fazla 3 (`docs/calculator_inventory.md`'de her kayıtta yazılı) |
| Tarayıcı (Playwright) | Yalnızca keşifte; üretim hattı httpx ile çalışır |
| `AIRGAP_MODE` | Açıkken hiçbir dış istek yapılmaz |

## Yeniden üretim

```bash
python dev.py scrape          # kampanya tarafı
python dev.py urun-kazi       # ürün tarafı
```

Sayılar `source_documents` tablosundan doğrulanabilir:

```sql
SELECT robots_allowed, COUNT(*) FROM source_documents GROUP BY robots_allowed;
```
