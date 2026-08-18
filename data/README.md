# Veri Seti

Türkiye'deki 10 katılım bankasının kamuya açık kampanya ve ürün sayfalarından
toplanmış veri. Bu dosya veri setinin **ne içerdiğini, neyi içermediğini ve
hangi kararların bilinçli alındığını** anlatır.

## İçerik

| Tablo | Kayıt | Not |
|---|---|---|
| `banks` | 10 | Kapsamdaki tüm katılım bankaları |
| `campaigns` | 602 | |
| `campaign_categories` | 2364 | 4 eksen: sektör · ürün türü · hedef kitle · fayda |
| `campaign_extractions` | 4107 | Kural tabanlı çıkarım, kanıtlı |
| `campaign_metrics` | 602 | Yalnızca guard'ı geçen değerler |
| `products` | 222 | |
| `product_rates` | 253 | 5 bankadan yapısal oran |
| `calculator_inventory` | 10 | 6 bankanın hesaplayıcı form envanteri |
| `calculator_probes` | **0** | Hesaplayıcılar SORGULANMADI |
| `source_documents` | 2981 | Her çekimin indeksi |
| `gold_annotations` | 1100 | 50 kampanya, elle etiketlenmiş cevap anahtarı |
| `entity_cards` | 608 | |
| `glossary` | 18 | |

Ham HTML arşivi: `backend/data/raw_html/` — **690 MB**, 10 banka klasörü.
**Asla silinmez.** Biten kampanyalar bankaların sitesinden kalkıyor; arşiv
kanıt zinciridir. Ürün kazıması öncesinde 531 MB'tı; artış ürün sayfalarının
ve hesaplayıcı envanteri sırasında çekilen sitemap'lerin arşivlenmesinden.

Dosya adı içerik adreslidir (`{url_özeti}_{içerik_özeti}.html`), bu yüzden aynı
adresin farklı zamanlardaki hâlleri birbirini EZMEZ — her anlık görüntü
`source_documents.raw_html_sha256` ile eşleşir.

## Veri kalitesi

### Tarih

| `date_precision` | Kampanya |
|---|---|
| `exact` | 291 |
| `partial` | 152 |
| `inferred` | 105 |
| `unknown` | **54** |

⚠️ `unknown` bir eksiklik değil, bir **bulgudur**. Tarihi bulunamayan kampanya
"süresi dolmuş" işaretlenmez; `status='unknown'` ayrı bir durumdur. Bazı
bankalar (ör. Türkiye Finans) yapısal tarih alanı yayımlamıyor.

⚠️ `date_precision='exact'` **kanıt metni olmadan geçersizdir** — veritabanı
düzeyinde CHECK ile zorlanır. Kanıtsız `exact` sayısı: **0**.

### Ürün limitleri

| `limits_source` | Ürün |
|---|---|
| `html_attr` (form envanteri) | 14 |
| `text` (metinden çıkarım) | 55 |
| `none` (bulunamadı) | **153** |

⚠️ `Product.limits_source` doldurulan alanlar arasındaki **EN ZAYIF** kaynağı
bildirir. Tutar formdan gelse de LTV metinden geldiyse `text` yazılır; "en
güçlü" yazmak veriyi olduğundan sağlam gösterirdi.

⚠️ `none` = limit bulunamadı, uydurulmadı. 153 üründe bankanın sayfasında
yapısal limit yok.

### Oranlar

| `rate_source` | Satır | Güven |
|---|---|---|
| `html_table` | 247 | 1.000 |
| `payment_plan_derived` | 6 | 0.950 |

`payment_plan_derived` Albaraka'ya ait: banka oranı yazmıyor, 23 satırlık ödeme
planı yayımlıyor. Oran annüite denkleminden geri hesaplanıyor ve bir kademe
düşük güvenle kaydediliyor.

⚠️ Bu oran sayfadaki **"Yıllık Maliyet Oranı" ile aynı şey değildir.** Albaraka
%82,39 yazıyor; o değer ücretler düşüldükten sonra net ele geçen tutar
üzerinden bileşik yıllık maliyet (bağımsız doğrulandı: %82,73). Bizim
kaydettiğimiz ücretsiz, aylık kâr payı oranıdır.

## Bilinçli kırpmalar — sessiz değil

Şartname "sessiz kırpma yapma" diyor. Aşağıdakiler ölçülmüş kararlardır:

**1. `products` varyant satırı = 0.** Hesaplayıcı dropdown'larının tamamı,
ölçüldüğünde ürüne değil SİTEYE ait çıktı (Ziraat'in tek seçicisi 17 finansman
türünü birden sunuyor ve üç sayfada aynı). Filtresiz çalıştırmada 42 sahte
varyant üretiyordu. Gerekçe ve eleme yöntemi `docs/variant_mapping.md`'de.

**2. `allowed_terms` neredeyse boş.** 10 hesaplayıcı envanterinin yalnızca
birinde vade seçici var, o da birleşik bir liste (1-60) — hiçbir ürünün gerçek
sınırı değil. Bunun yerine seçenek etiketlerindeki ürüne özel sınırlar
`term_months_min/max` alanlarına yazıldı (`TAŞIT FINANSMANI(1-48 AY)` → 48).

**3. Hesaplayıcılar sorgulanmadı.** `calculator_probes` = 0. Form envanteri
bankanın yayımladığı yapısal limittir ve tek istek atmadan okunur; bu yüzden
`is_binding=True` kalır.

**4. Dünya Katılım'ın 48 kampanyası çekilmedi.** `robots.txt` engelliyor.
Ayrıntı: [`robots_report.md`](robots_report.md).

**5. 2025 öncesinde BİTMİŞ kampanyalar yazılmadı** (`min_campaign_year`).
Eşik BİTİŞ tarihine uygulanır, başlangıca değil — uzun vadeli kampanyalar
yıllar önce başlayıp hâlâ sürüyor olabiliyor.

## Bilinen sorunlar

- **Albaraka'da 9 içeriksiz kampanya.** `clean_text`'leri birebir aynı ve
  tamamen site menüsünden oluşuyor; sayfaların gövdesi JS ile yükleniyor.
  Çıkarım için işe yaramazlar.
- **Emlak Katılım'ın taşıt LTV matrisi okunmuyor.** Tablo başlığı "Enerji
  Sınıfı" olmadığı için matris ayrıştırıcısı görmüyor. Ayrıca Emlak bu tabloda
  ABD biçimi virgül kullanmış (`400,000`), Türkçe ayrıştırıcı bunu 400 okuyor.
- **Hayat Finans'ın paylaşım oranı tablosu okunmuyor.** Tablo devrik: vadeler
  sütunda, değerler `%90 - %10` (müşteri–banka payı) biçiminde.
- **Kampanya "tekrarları" gerçektir, silinmemelidir.** 30 grup aynı başlığı
  taşıyor ama **hepsi farklı dönemli** (aylık yinelenen kampanyalar). Aynı
  başlık VE aynı dönem taşıyan grup sayısı: 0.

## Klasörler

| Yol | İçerik | Depoya girer mi |
|---|---|---|
| `backend/data/raw_html/` | Ham HTML arşivi, içerik adresli | ❌ |
| `backend/data/exports/` | `disa-aktar` çıktıları, kararlı anahtarlı | ❌ |
| `backend/data/backups/` | Sıfırlama öncesi yedekler | ❌ |
| `data/gold/` | Gold set örneklemi | ✅ |
| `data/eval/` | Değerlendirme sonuçları (JSON) | ✅ |

## Yeniden üretim

```bash
python dev.py baslat            # migrate + seed
python dev.py scrape            # kampanyalar (AĞA ÇIKAR)
python dev.py urun-kazi         # ürün/finansman (AĞA ÇIKAR)
python dev.py kesif-hesaplayici # hesaplayıcı envanteri (AĞA ÇIKAR, Playwright)
python dev.py envanter-uygula   # envanteri ürün limitlerine bağla
python dev.py siniflandir       # taksonomi
python dev.py cikarim --sadece-kural
python dev.py degerlendir --mod rule_only
```

Veri silinmeden önce `disa-aktar` + `disa-aktar-dogrula` **zorunludur**;
doğrulama damgası olmayan dışa aktarma ile silme reddedilir.
