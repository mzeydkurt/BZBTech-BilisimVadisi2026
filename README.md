# KATİP — Katılım Bankacılığı Kampanya Analiz Platformu

BZB Tech tarafından geliştirilen KATİP (Katılım Bankacılığı Kampanya Analiz
Platformu), Türkiye'deki katılım bankalarının kamuya açık kampanya
sayfalarından veri toplayan, bu veriyi normalize ederek karşılaştırılabilir
hâle getiren ve web arayüzü üzerinden sunan analiz platformudur.

> **TEKNOFEST 2026 — Bilişim Vadisi / İkinci Senaryo** · Takım: **BZBTech**

---

## Takım

| Üye | Rol | LinkedIn |
|---|---|---|
| <img src="https://media.licdn.com/dms/image/v2/D4D03AQHHAEqtTBJgCA/profile-displayphoto-shrink_800_800/B4DZWgOnQ3HYAc-/0/1742149941290?e=1787788800&v=beta&t=BhIZVGvM5rTp75XCihiz9u5MgwWPWVklTDAYdm5xAb8" width="64" height="64" alt="Muhammed Zeyd Kurt"><br>**Muhammed Zeyd KURT** | Takım Kaptanı | [linkedin.com/in/zeyd-kurt](https://www.linkedin.com/in/zeyd-kurt/) |
| <img src="https://media.licdn.com/dms/image/v2/D4D03AQEduYy1Z3l8RQ/profile-displayphoto-crop_800_800/B4DZ2xJ52PKQAI-/0/1776793657981?e=1787788800&v=beta&t=nfqyYAWStTic0Un7v0rXtbR-jyX_YFCVM2BcAwzOnLY" width="64" height="64" alt="Kadir Efe Yazılı"><br>**Kadir Efe YAZILI** | Üye | [linkedin.com/in/kadirefeyazili](https://www.linkedin.com/in/kadirefeyazili/) |
| <img src="https://media.licdn.com/dms/image/v2/D4D03AQGvAgSf8uY-8w/profile-displayphoto-crop_800_800/B4DZ_CkkMsGYAI-/0/1785675793642?e=1787788800&v=beta&t=YP1m9gJHxZ0Du5s6egVj4cgai4Mg9I0w-C11Tyqipj4" width="64" height="64" alt="Recep Buğra Aydemir"><br>**Recep Buğra AYDEMİR** | Üye | [linkedin.com/in/recep-bugra-aydemir](https://www.linkedin.com/in/recep-bugra-aydemir/) |
| <img src="https://media.licdn.com/dms/image/v2/D4D03AQEZKBMmGon8wA/profile-displayphoto-shrink_800_800/profile-displayphoto-shrink_800_800/0/1728472512701?e=1787788800&v=beta&t=ayjXMcYo29C21bOnWc9mSiDA_-FwTham3eMfd9eMGik" width="64" height="64" alt="Batuhan Şenel"><br>**Batuhan ŞENEL** | Üye | [linkedin.com/in/batuhan-senell](https://www.linkedin.com/in/batuhan-senell/) |

---

## Problem

Katılım bankalarının kampanya bilgileri her kurumda farklı biçimde
yayımlanıyor. Analizimizde doğrulanan bazı örnekler:

- **Tarih yapısal bir alanda durmuyor.** Kampanya süresi, koşul metninin içinde
  serbest cümle olarak geçiyor ve en az **7 farklı biçimde** yazılıyor
  (`01.01.2026 - 31.12.2026`, `1-31 Ağustos 2026`, `10 Temmuz – 7 Ağustos 2026`,
  `Son Gün 31.12.2026` …). Bir bankada ise hiçbir kampanyada tarih bulunmuyor.
- **Sayı biçimi Türkçe.** `5.000` beş bin, `5,000` ise beştir — İngilizce
  konvansiyonun tersi.
- **Görünmez karakterler var.** Bir bankanın oran tablosu başlıklarında
  zero-width space ve non-breaking space bulunuyor; temizlenmezse kolon
  eşleştirmesi *sessizce* başarısız oluyor.
- **Biten kampanyalar siteden kalkıyor.** Kimi bankada sert HTTP 404 dönüyor,
  arşiv bulunmuyor. Ham veri saklanmazsa geri getirilemiyor.

Bu proje, dağınık ve kırılgan bu veriyi tek bir düzenli modele indirger;
her değerin **kaynağını** ve **çıkarım güvenilirliğini** kayıt altına alır.

## SPRINT 1 kapsamı

| Alan | Durum | Sonuç |
|---|---|---|
| Veritabanı şeması + Alembic göçleri | ✅ | 9 tablo · `upgrade` ve `downgrade` doğrulandı |
| 10 katılım bankası + terminoloji sözlüğü (seed) | ✅ | 10 banka · 18 terim · tekrar çalıştırılabilir |
| Türkçe finansal metin normalizasyon kütüphanesi | ✅ | 7 tarih formatı · tutar, oran, vade · **%96 test kapsamı** |
| Kazıma altyapısı (robots, soft-404, yeniden deneme, ham HTML arşivi) | ✅ | 101 arşiv dosyası · özet doğrulaması tam |
| İki banka scraper'ı (Emlak Katılım, Hayat Finans) | ✅ | **76 kampanya** gerçek veriyle toplandı |
| REST API (`/health`, `/banks`, `/campaigns`, `/stats`) | ✅ | Filtreleme, sayfalama, sıralama · OpenAPI dokümanı |
| Web arayüzü (genel bakış + kampanya tablosu) | ✅ | Yükleniyor / hata / sonuç yok durumları ayrı |

**Kapsam dışı (sonraki sprintler):** yapay zekâ / LLM entegrasyonu, sohbet
arayüzü, kalan 8 bankanın scraper'ı, kampanya karşılaştırma motoru.

### Toplanan veri

| | |
|---|---|
| Kampanya | 76 (Emlak Katılım 65 · Hayat Finans 11) |
| Tarihi çıkarılan | 66 / 76 |
| Durum dağılımı | 63 aktif · 3 süresi dolmuş · 10 tarih belirtilmemiş |

> "Tarih belirtilmemiş" ile "süresi dolmuş" **ayrı** tutulur. Kaynak sayfada
> tarih yoksa kampanya bitmiş sayılmaz; bunu "süresi dolmuş" göstermek yanlış
> bilgi üretirdi.

## SPRINT 2 kapsamı

| Alan | Durum | Sonuç |
|---|---|---|
| Şema genişletmesi (ürün varyantı, taksonomi, hesaplayıcı envanteri) | ✅ | 5 yeni tablo · `downgrade` turu sınandı |
| Kalan 8 bankanın scraper'ı | ✅ | **10 bankanın tamamı** · sitemap, JSON ucu ve liste sayfası yolları |
| Kampanya taksonomisi (4 dik eksen) | ✅ | **3.000 etiket** · her kampanyada en az 2 |
| Ürün / finansman verisi | ✅ | **234 ürün** · varyant, limit ve teminat türü |
| Yapısal oran tabloları | ✅ | **373 oran** · LTV matrisi ve ödeme planı dahil |
| Hesaplayıcı form envanteri | ✅ | 10 envanter / 6 banka · **hiçbir hesaplayıcı sorgulanmadı** |
| Veri sıfırlama ve dışa aktarma zinciri | ✅ | Kararlı anahtarlı dışa aktarma + doğrulama damgası |

**Kapsam dışı (sonraki sprintler):** sohbet arayüzü, kampanya karşılaştırma
motoru, yerel LLM ile çalıştırma.

### Toplanan veri

| Tablo | Kayıt | Not |
|---|---|---|
| `campaigns` | 608 | 10 bankanın tamamı |
| `campaign_categories` | 3.000 | 4 eksen · her kampanyada en az 2 etiket |
| `campaign_extractions` | 4.508 | Kural tabanlı çıkarım, kanıtlı |
| `campaign_metrics` | 608 | Yalnızca guard'ı geçen değerler |
| `campaign_products` | 216 | Kampanya–ürün bağı, yöntem ve güvenle |
| `products` | 234 | Limit kaynağı etiketli |
| `product_rates` | 373 | Yapısal oran satırı |
| `product_limits` | 108 | Tutar/vade/LTV matrisi |
| `calculator_inventory` | 10 | 6 bankanın hesaplayıcı form envanteri |
| `calculator_probes` | **0** | Hesaplayıcılar bilinçli olarak **sorgulanmadı** |
| `entity_cards` | 1.253 | Varlık kartları |
| `gold_annotations` | 2.360 | Elle etiketlenmiş cevap anahtarı |

Banka bazında kampanya:

| Banka | Kampanya | | Banka | Kampanya |
|---|---|---|---|---|
| Ziraat Katılım | 210 | | Kuveyt Türk | 47 |
| Vakıf Katılım | 92 | | Albaraka Türk | 40 |
| T.O.M. Katılım | 71 | | Türkiye Finans | 22 |
| Türkiye Emlak Katılım | 68 | | Hayat Finans | 10 |
| Dünya Katılım | 48 | | Adil Katılım | 0 |

| `date_precision` | Kampanya |
|---|---|
| `exact` | 293 |
| `partial` | 155 |
| `inferred` | 106 |
| `unknown` | **54** |

> `unknown` bir eksiklik değil **bulgudur**. Tarihi bulunamayan kampanya
> "süresi dolmuş" işaretlenmez; `status='unknown'` ayrı bir durumdur.
> `date_precision='exact'` kanıt metni olmadan geçersizdir — veritabanı
> düzeyinde CHECK ile zorlanır, kanıtsız `exact` sayısı **0**.

> **Adil Katılım'ın 0 kampanyası bir eksiklik değil, bulgudur.** Bankanın kamuya
> açık kampanya sayfası yok; 9 aday adres denetlendi ve hepsi belgelendi. Site
> var olmayan her adres için ana sayfayı HTTP 200 ile döndürdüğünden, içerik
> özeti karşılaştırması yapılmasaydı 9 uydurma kayıt oluşacaktı.

Ham HTML arşivi **690 MB** ve asla silinmez: biten kampanyalar bankaların
sitesinden kalkıyor, arşiv kanıt zinciridir. Dosya adı içerik adreslidir, bu
yüzden aynı adresin farklı zamanlardaki hâlleri birbirini **ezmez**.

Ayrıntılı veri sözlüğü, kalite ölçümleri ve bilinen sorunlar:
[`data/README.md`](data/README.md) · robots kapsam gerekçeleri:
[`data/robots_report.md`](data/robots_report.md)

### Kampanya taksonomisi

Dört **dik** eksen; bir kampanya her eksende birden fazla etiket alabilir:

| Eksen | Değer sayısı | Kaynak |
|---|---|---|
| `product_type` | 15 | Şartnamenin 8 zorunlu türü + 7 ek tür |
| `sector` | 22 | Ziraat'in 14 gerçek kategorisi temel alındı |
| `audience` | 14 | Şartname 5.3 "Hedef Kitle Bilgileri" |
| `benefit` | 11 | Fayda türü |

Kanıt önceliği — güçlüden zayıfa:

| Kaynak | Güven | Açıklama |
|---|---|---|
| `url` | 1.00 | Adres yolundaki kategori (Kuveyt Türk) |
| `bank_category` | 1.00 | Bankanın kendi etiketi (Ziraat'in 14 kategorisi) |
| `merchant` | 0.90 | Marka sözlüğü |
| `keyword` | 0.70 | Anahtar kelime sözlüğü |

İlk ikisi **çıkarım değil kaynak veridir**: banka sektörü kendi sayfasında
yazıyor. Bankanın liste kartlarındaki etiket `campaigns.bank_category`
sütununa taşındığında sektörü çıkarılamayan kampanya oranı %44,2'den
**%30,5**'e indi.

> **Uydurma etiket yok.** Kaynak yoksa etiket yazılmaz. Sektör sinyali
> bulunmayan kampanyalara `genel` yazılır ama **0.30 güvenle** — düşük güven,
> sonraki sprintte hangi kayıtların önce ele alınacağını gösterir.

Sınıflandırma deterministiktir ve **ağa çıkmadan** yeniden çalıştırılabilir;
sözlük genişletildiğinde bankalara yeni istek gitmez. Etiketler her
çalıştırmada silinip yeniden yazılır, böylece sözlükten çıkarılan bir
kelimenin ürettiği etiket veritabanında kalmaz.

Arayüzde kampanya tablosunda **Sektör** ve **Ürün Türü** kolonları rozet
olarak gösterilir; her rozetin ipucunda etiketin hangi kaynaktan ve hangi
metinden çıkarıldığı yazar. Düşük güvenli etiketler kesikli çerçeveyle
ayırt edilir — gizlenmez, çünkü "sınıflandırılamadı" bilgisi de bir bulgudur.

### Sahada doğrulanan ve önlenen veri hataları

Aşağıdakilerin tamamı **canlı sitelerde ölçüldü**. Ortak özellikleri hata
fırlatmadan sessizce yanlış veri üretmeleri; her biri için regresyon testi var.

| Bulgu | Etki | Önlem |
|---|---|---|
| Ziraat detay sayfalarında ilk `<h1>` logo metni | 209 kampanyanın 209'u "Ziraat Katılım Bankası" adıyla kaydedildi | `extract_title(ignore_headings=...)` |
| Aynı `<h1>` sorunu soft-404'ü de gizliyordu | 2 "sayfa yok" yanıtı kampanya sanıldı | `is_soft_404` ham `<title>` etiketine de bakıyor |
| Bölüm başlığı `<p><strong>` içinde | Ziraat 209/209, Emlak 66/66 kayıtta koşul metni boş kaldı | Satır içi başlıkta blok atasına çıkılıyor |
| T.O.M.'da aynı kampanya iki yol önekinde | 76 kampanya 157 kayda çıkıyordu | Slug bazında tekilleştirme |
| Türkiye Finans başlıklarında kelime içi zero-width space | Kolon eşleştirmesi sessizce boş dönüyordu | `normalize_text()` zorunlu |
| Göç sırasında SQLite FK denetimi açık | Tablo yeniden kurulurken `product_rates` satırları siliniyordu | Göç boyunca denetim kapatılıyor |
| Sayfanın tamamında çıplak sayı tutar sayılıyordu | "36 ay" ve "%80" ifadeleri `amount_max` olarak yazılmıştı | Tutarda para birimi işareti zorunlu |
| Paylaşım oranı ve vade aralıkları tutar sanılıyordu | "40-60" ve "1-30 gün" ürün limitine yazılıyordu | Aralıkta en az bir uçta para birimi aranıyor |

### Analiz dokümanıyla çelişen, sahada düzeltilen varsayımlar

Planlama dokümanındaki dört varsayım canlı ölçümde tutmadı; kod ölçüme göre
yazıldı.

| Doküman | Ölçüm (Ağustos 2026) |
|---|---|
| Ziraat: `/kampanyalar/{kategori}` gezilecek | O adres **HTTP 404**; tek giriş `/kart-kampanyalari` (209 kampanya, tek istek) |
| Albaraka: liste rotasyonlu, 12-15 kez çek | Rotasyon **yok** — 3 çekimde de aynı 12 slug |
| Vakıf: liste JS, httpx ile 0 kampanya | Sunucu HTML'inde kampanyalar **var**; geçersiz slug gerçek 404 döndürüyor |
| Dünya: sitemap gzip | Düz XML — ama 46 kampanya adresi veriyor; liste sayfası gerçekten JS |

### Yapısal oran verisi

| `rate_source` | Satır | Güven |
|---|---|---|
| `html_table` | 367 | 1.00 |
| `payment_plan_derived` | 6 | 0.95 |

Türkiye Finans oranı serbest metinde değil gerçek bir HTML tablosunda
yayımlıyor — veri setinin en güvenilir parçası. Aynı ürün için sigortalı ve
sigortasız olmak üzere iki ayrı tablo veriyor.

> **Varyant boyutu tablonun dışındadır.** Hangi tablonun sigortalı hangisinin
> sigortasız olduğu yalnızca üstteki başlıkta yazılı. Başlık okunmazsa iki
> tablo tek ürüne ait sanılır ve "en düşük kâr payı" karşılaştırması bir
> bankanın sigortalı oranını başka bankanın sigortasız oranıyla kıyaslar.

Albaraka oranı hiç yayımlamıyor, 23 satırlık ödeme planı veriyor; oran annüite
denkleminden geri hesaplanıp bir kademe düşük güvenle kaydediliyor.

### Bilinçli kırpmalar — sessiz değil

Şartname sessiz kapsam daraltmayı yasaklıyor. Aşağıdakiler **ölçülmüş
kararlardır**, gerekçeleri belgelidir:

1. **Ürün varyant satırı yazılmadı.** Hesaplayıcı dropdown'ları ölçüldüğünde
   ürüne değil **siteye** ait çıktı (Ziraat'in tek seçicisi 17 finansman
   türünü birden sunuyor ve üç sayfada aynı). Filtresiz çalıştırma 42 sahte
   varyant üretiyordu.
2. **Hesaplayıcılar sorgulanmadı** (`calculator_probes` = 0). Form envanteri
   bankanın yayımladığı yapısal limittir ve tek istek atmadan okunur.
3. **Dünya Katılım'ın 48 kampanyası çekilmedi** — `robots.txt` engelliyor.
4. **2025 öncesinde bitmiş kampanyalar yazılmadı.** Eşik bitiş tarihine
   uygulanır, başlangıca değil: uzun vadeli kampanyalar yıllar önce başlayıp
   hâlâ sürüyor olabiliyor.

Bilinen ayrıştırma sorunları (Emlak'ın taşıt LTV matrisi, Hayat Finans'ın
devrik paylaşım tablosu, Albaraka'da JS ile yüklenen 9 kampanya)
[`data/README.md`](data/README.md) içinde tek tek listelidir.

---

## SPRINT 3 — devam ediyor

Yapay zekâ çıkarım katmanı. Şimdiye kadar tamamlananlar:

| Alan | Durum | Sonuç |
|---|---|---|
| Gold set (cevap anahtarı) | ✅ | **2.360 elle etiketlenmiş alan** |
| Kural tabanlı çıkarım | ✅ | **4.508 çıkarım**, kanıt metniyle |
| Değerlendirme ve ablasyon altyapısı | ✅ | Üç kip karşılaştırmalı ölçülüyor |
| Varlık kartı üretimi | ✅ | 1.253 kart |

`rule_only` kipinin gold set'e karşı ölçülmüş temel çizgisi:
**kör alt küme F1 0,785** · mikro F1 0,809 · makro F1 0,773 ·
halüsinasyon oranı 0,171 · doğru susma oranı 0,913.

Devam eden işler — **tamamlanmadan bu bölüme sayı yazılmaz:**

| Alan | Durum |
|---|---|
| Yerel LLM'in (Ollama) sağlayıcıya bağlanması | ⏳ |
| Prompt ince ayarı ve tam çıkarım çalıştırması | ⏳ |
| `llm_only` / `hybrid` ablasyon ölçümü | ⏳ |
| Kanıta dayalı doğal dil sorgulama (RAG) | ⏳ |
| Kapalı ağ (airgap) doğrulaması | ⏳ |


---

## Kurulum

### Gereksinimler

| Bileşen | Sürüm | Not |
|---|---|---|
| Python | 3.11 veya üzeri | 3.12 önerilir |
| Node.js | 20 veya üzeri | yalnızca arayüz derlemesi için |
| npm | 10 veya üzeri | Node ile birlikte gelir |

Harici servis gerekmez: PostgreSQL, Redis veya mesaj kuyruğu yoktur.
Geliştirme veritabanı SQLite'tır ve dosya olarak tutulur.

Tüm bağımlılıkların tam listesi ve lisansları için:
[`LICENSES.md`](LICENSES.md) ·
[`backend/requirements.txt`](backend/requirements.txt) ·
[`frontend/package.json`](frontend/package.json)

### Adım adım çalıştırma

Tüm görevler `dev.py` üzerinden çalışır; **`make` kurmanıza gerek yoktur.**
Betik yalnızca Python standart kütüphanesini kullanır.

```bash
# 1. Depoyu klonlayın
git clone https://github.com/mzeydkurt/BZBTech-BilisimVadisi2026.git
cd BZBTech-BilisimVadisi2026

# 2. Bağımlılıkları kurun (sanal ortam + frontend paketleri + .env dosyası)
python dev.py kur

# 3. Veritabanını hazırlayıp backend'i başlatın → http://localhost:8000
python dev.py baslat

# 4. Ayrı bir terminalde arayüzü başlatın → http://localhost:5173
python dev.py web
```

`baslat` komutu sırasıyla şemayı oluşturur, 10 bankayı yükler ve sunucuyu
başlatır. Adımları ayrı ayrı çalıştırmak için:

```bash
python dev.py migrate        # veritabanı şemasını oluştur
python dev.py seed           # 10 banka + terminoloji sözlüğü
python dev.py api            # backend'i başlat
python dev.py test           # testler + kapsam raporu
python dev.py lint           # ruff + mypy + tsc
python dev.py                # tüm komutları listeler
```

API dokümanı: `http://localhost:8000/docs`

### Veri toplama

⚠️ Bu komutlar gerçek banka sitelerine istek atar. `robots.txt` kurallarına
uyulur, host başına 1,5 saniye bekleme uygulanır ve her yanıt ham HTML olarak
arşivlenir.

```bash
python dev.py scrape                    # 10 bankadan kampanya verisi
python dev.py scrape --banka ziraat_katilim
python dev.py scrape-deneme             # veritabanına yazmadan dene
python dev.py urun-kazi                 # ürün/finansman limit, varyant ve oranları
python dev.py urun-kazi-deneme          # veritabanına yazmadan dene
python dev.py tkbb-cek                  # TKBB Veri Peteği (Playwright gerektirir)
```

Kazımadan sonra kapsama denetlenir (ağa çıkmaz):

```bash
python dev.py urun-dogrula              # banka × oran türü kapsaması, rapor üretir
```

Rapor `docs/urun_dogrulama_raporu.md` dosyasına yazılır: banka başına ürün,
oran ve limit sayısı ile `rate_type` dağılımı. Üç oran türünden birinin sıfır
kalması ayrıştırıcıda bir kopukluk olduğunu gösterir.

Hesaplayıcılar **sorgulanmaz**: yalnızca form nitelikleri okunur (dropdown
seçenekleri = ürün varyantları, tutar sınırları, izinli vadeler). Bankaya ek
yük binmez ve değerler bankanın yayımladığı yapısal limit olduğu için
bağlayıcı kalır.

### Ağa çıkmayan işlemler

Toplanmış veriyle çalışır; bankalara yeni istek gitmez.

```bash
python dev.py yeniden-isle       # temiz metni ham HTML arşivinden yeniden üret
python dev.py geri-doldur        # banka kategorisini arşivden doldur
python dev.py siniflandir        # dört eksenli taksonomi
python dev.py urun-esle          # kampanyaları ürünlerle eşleştirir
python dev.py tkbb-yukle         # TKBB'nin elle doğrulanmış verisini yükler
python dev.py cikarim            # metinden bilgi çıkarımı
python dev.py degerlendir        # gold set'e karşı F1
python dev.py ablation           # rule_only / llm_only / hybrid karşılaştırması
python dev.py kart-uret          # varlık kartları (SPRINT 5 gömme girdisi)
```

### Gold set (cevap anahtarı)

```bash
python dev.py gold-ornek         # örneklem seç
python dev.py etiketle           # etiketleme arayüzü → /api/v1/annotate/ui
python dev.py gold-durum         # ilerleme + kanıt + öz-tutarlılık
python dev.py gold-denetle       # kanıtı doğrulanamayan etiketleri raporla
python dev.py kanit-bagla --kuru # kanıtı boş etiketleri metne bağla (önce dene)
```

**Kanıt bağlama.** `kanit-bagla`, kanıtı boş kalmış etiketlerin DEĞERİNİ
metinde arar ve çevresindeki cümle parçasını kanıt yazar. Çıplak rakam kanıt
sayılmaz: her alan için yakınında bir birim/bağlam aranır (`TL`, `%`,
`taksit`, `vade`). Sınıflandırma alanları (`sector`, `product_type`,
`target_customer`, `reward_type`) bağlanmaz — metin kategori adını yazmaz,
hangi ifadenin o kategoriyi doğurduğu insan yargısıdır.

> ⚠️ Otomatik bağlama **insan doğrulaması değildir**. Yazılan kanıtlar
> `oto-kanit` ile işaretlenir ve `gold-durum` bunları insan seçimlerinden
> ayrı sayar. Tek bir "kanıtlı etiket" sayısı verilseydi rapor, sahip
> olmadığımız bir titizliği iddia ederdi.



### Boru hattı — günlük kullanımda tek komut

Sekiz adımın tamamı sırayla:

```bash
python dev.py boru-hatti           # tam hat (AĞA ÇIKAR)
python dev.py boru-hatti --agsiz   # yalnızca yeniden işleme (ağa çıkmaz)
python dev.py boru-hatti --kuru    # ne çalışacağını yazar, çalıştırmaz
python dev.py boru-hatti --banka albaraka
```

| # | Adım | Ağ |
|---|---|---|
| 1 | `scrape` — kampanya sayfaları | ✓ |
| 2 | `urun-kazi` — ürün/oran/limit sayfaları | ✓ |
| 3 | `yeniden-isle` — temiz metni arşivden tazeler | — |
| 4 | `cikarim` — alanları çıkarır | — |
| 5 | `siniflandir` — dört eksende sınıflandırır | — |
| 6 | `kart-uret` — varlık kartları | — |
| 7 | `urun-dogrula` — kapsama denetimi | — |
| 8 | `degerlendir` — gold set'e karşı F1 | — |

Adımların hepsi tek tek de çağrılabilir; boru hattı onları değiştirmez,
doğru sırayla çalıştırır.

> ⚠️ **Sıra bağımlılık zinciridir, tercih değil.** Her adım bir öncekinin
> çıktısını okur. Bozulursa hata VERMEZ — sessizce eski veriyle çalışır.
> Ölçüldü: 19 Ağustos'ta kalıplar düzeltildi ama `cikarim` çalıştırılmadı;
> `degerlendir` bir gün önceki çıkarımı ölçtü ve yapılan iyileştirmeler
> F1'e hiç yansımadı.

> ⚠️ **Ayrıştırıcı ya da kalıp kodu değiştiyse `--agsiz` yeterlidir.** Ham
> HTML arşivi hiç silinmediği için tüm veri bankalara yeni istek atmadan
> yeniden üretilir. Bankaya istek atmak yalnızca sayfaların KENDİSİ
> değiştiyse gereklidir.

### Veri yenileme zinciri

Kazıma mantığı değiştiğinde veri sıfırdan toplanır. Adımlar sırayla yürür ve
her biri bir öncekine bağlıdır.

```bash
# 1. Kararlı anahtarlarla dışa aktar (campaign_id yerine bank_code:slug)
python dev.py disa-aktar
#    -> "Dışa aktarıldı: data/exports/20260817T161318"
#    Komut bu yolu ekrana yazar; sonraki adımlara olduğu gibi kopyalayın.
#    Ayrıca data/gold/gold_set.jsonl dosyasını SABİT yola yazar (şartname
#    §4.6 biçimi); o dosya dışa aktarma dizinine girmez.

# 2. Doğrula ve damgala — damga olmadan silme REDDEDİLİR
python dev.py disa-aktar-dogrula --dizin data/exports/20260817T161318

# 3. Ne silineceğini gör (hiçbir şey silmez)
python dev.py sifirla --export data/exports/20260817T161318 --kuru

# 4. Kampanya verisini sıfırla — BANKA BANKA önerilir
python dev.py sifirla --export data/exports/20260817T161318 --banka vakif_katilim --onay SIL

# 5. Yeniden kaz ve sonucu gör
python dev.py scrape --banka vakif_katilim

# 6. Gold etiketlerini yeni kimliklere bağla
python dev.py gold-yeniden-bagla
```

Gold etiketlerini de silmek için `--gold-sil` eklenir; varsayılan olarak
korunurlar. Dizin yolu `backend/` önekiyle de kabul edilir.

⚠️ Örneklem dosyası (`data/gold/gold_sample.jsonl`) `campaign_id` de taşır.
Sıfırlamadan sonra `python dev.py gold-ornek` yeniden çalıştırılmalıdır;
aksi hâlde eski örneklem güncel olmayan kimliklere işaret eder.

Ne silinir, ne kalır:

| Silinir | Kalır |
|---|---|
| `campaigns`, `campaign_metrics`, `campaign_categories`, `campaign_extractions` | **`gold_annotations`** — kimlik `campaign_key`'de, bağ NULL'a düşer |
| `entity_cards` (kampanya türü), `scrape_runs` | `source_documents` — ham arşiv indeksi |
| | **`data/raw_html/`** — ham HTML asla silinmez |

⚠️ `app.db` dosyasını **elle silmek** başka bir şeydir: gold set de o dosyanın
içinde olduğu için tamamen kaybedilir. `sifirla` komutu dosyaya dokunmaz,
yalnızca kampanya satırlarını boşaltır ve öncesinde `data/backups/` altına
kopya alır.

Sıfırlamadan önce ne gideceğini görmek için:

```bash
python dev.py sifirla --export <dizin> --kuru
```

### Keşif (Playwright gerektirir)

Bankaların JavaScript ile doldurduğu kampanya listelerinin JSON uçlarını ve
hesaplayıcı formlarını bir kez envanterler. Sonuç veritabanına yazılır;
üretim hattı Playwright'sız çalışır.

```bash
python dev.py kur --playwright   # tek seferlik, ~400 MB
python dev.py kesif-endpoint     # → docs/endpoint_discovery.md
python dev.py kesif-hesaplayici  # → docs/calculator_inventory.md
python dev.py envanter-uygula    # envanteri ürün limitlerine bağlar (ağa çıkmaz)
```

⚠️ `envanter-uygula`, ORTAK hesaplayıcının birleşik vade listesini değil,
seçenek etiketindeki ürüne özel sınırı yazar. Ziraat'in tek dropdown'ı 17
finansman türünü sunuyor ve vade seçicisi 1-60 listeliyor; gerçek sınır
etikette: `TAŞIT FINANSMANI(1-48 AY)`, `KONUT FINANSMANI (…/1-120 AY)`.

### Diğer

```bash
python dev.py llm-saglik     # LLM sağlayıcısının durumu (SPRINT 3A: mock)
python dev.py bicimle        # kodu biçimlendir (ruff format + fix)
python dev.py derle-web      # arayüzü üretim için derle
python dev.py migrate-geri   # son göçü geri al (VERİ SİLEBİLİR, onay ister)
python dev.py suresi-dolanlari-temizle   # süresi kesin dolmuş kampanyaları
                                         # kalıcı siler (VERİ SİLER, onay ister)
```

### dev.py kullanmadan

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate                # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python -m alembic upgrade head
python -m app.db.seed
python -m uvicorn app.main:app --reload --port 8000
```

Komutların tamamı [`dev.py`](dev.py) içinde okunabilir durumdadır.

### Kapalı ağ (on-premise) kurulumu

`.env` içinde `AIRGAP_MODE=true` yapıldığında sistem **hiçbir dış HTTP isteği
yapmaz**; kazıma denemesi hata ile durur. API ve arayüz, daha önce toplanmış
veriyle çalışmaya devam eder.

---

## Ekran görüntüleri

_(Arayüz görselleri eklenecek)_

---

## Lisans

Bu proje [Apache License 2.0](LICENSE) ile lisanslanmıştır.

Bağımlılıkların lisans matrisi: [`LICENSES.md`](LICENSES.md). Projede copyleft
(GPL/AGPL) lisanslı bileşen kullanılmamıştır.

Banka adları ve markaları ilgili kurumlara aittir.
