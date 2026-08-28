# KATİP — Katılım Bankacılığı Kampanya Analiz Platformu

Türkiye'deki 10 katılım bankasının kamuya açık kampanya ve ürün sayfalarından
veri toplayan, bu veriyi normalize ederek karşılaştırılabilir hâle getiren ve
dashboard ile kanıtlı sohbet üzerinden sunan analiz platformu.

> **TEKNOFEST 2026 — Bilişim Vadisi / İkinci Senaryo** · Takım: **BZBTech**

**Ayrıntılı proje dokümantasyonu:** [`PROJE_DOKUMANTASYONU.md`](PROJE_DOKUMANTASYONU.md)
— mimari, veri akışı, NLP yaklaşımı, ölçümler ve karşılaşılan problemler.

---

## Takım

| Üye | Rol | LinkedIn |
|---|---|---|
| Üye | Rol | LinkedIn |
|---|---|---|
| <img src="https://media.licdn.com/dms/image/v2/D4D03AQHHAEqtTBJgCA/profile-displayphoto-shrink_800_800/B4DZWgOnQ3HYAc-/0/1742149941290?e=1787788800&v=beta&t=BhIZVGvM5rTp75XCihiz9u5MgwWPWVklTDAYdm5xAb8" width="64" height="64" alt="Muhammed Zeyd Kurt"><br>**Muhammed Zeyd KURT** | Takım Kaptanı | [linkedin.com/in/zeyd-kurt](https://www.linkedin.com/in/zeyd-kurt/) |
| <img src="https://media.licdn.com/dms/image/v2/D4D03AQEduYy1Z3l8RQ/profile-displayphoto-crop_800_800/B4DZ2xJ52PKQAI-/0/1776793657981?e=1787788800&v=beta&t=nfqyYAWStTic0Un7v0rXtbR-jyX_YFCVM2BcAwzOnLY" width="64" height="64" alt="Kadir Efe Yazılı"><br>**Kadir Efe YAZILI** | Üye | [linkedin.com/in/kadirefeyazili](https://www.linkedin.com/in/kadirefeyazili/) |
| <img src="https://media.licdn.com/dms/image/v2/D4D03AQGvAgSf8uY-8w/profile-displayphoto-crop_800_800/B4DZ_CkkMsGYAI-/0/1785675793642?e=1787788800&v=beta&t=YP1m9gJHxZ0Du5s6egVj4cgai4Mg9I0w-C11Tyqipj4" width="64" height="64" alt="Recep Buğra Aydemir"><br>**Recep Buğra AYDEMİR** | Üye | [linkedin.com/in/recep-bugra-aydemir](https://www.linkedin.com/in/recep-bugra-aydemir/) |
| <img src="https://media.licdn.com/dms/image/v2/D4D03AQEZKBMmGon8wA/profile-displayphoto-shrink_800_800/profile-displayphoto-shrink_800_800/0/1728472512701?e=1787788800&v=beta&t=ayjXMcYo29C21bOnWc9mSiDA_-FwTham3eMfd9eMGik" width="64" height="64" alt="Batuhan Şenel"><br>**Batuhan ŞENEL** | Üye | [linkedin.com/in/batuhan-senell](https://www.linkedin.com/in/batuhan-senell/) |


---

## Bir bakışta

| | |
|---|---|
| Banka | **10** (BDDK listesinin tamamı; 9'unda veri) |
| Kampanya | **482** — tümünde alan çıkarımı yapıldı |
| Ürün · oran · limit | **300** · **1.853** · **113** |
| Aranabilir kart · gömme | **2.919** · **2.880** |
| Gold set | **3.174** elle etiketlenmiş alan |
| API | **33** REST ucu · OpenAPI |
| Test | **1.944 geçiyor** · kırık yok · kapsam **%78** |

### Ölçülmüş sonuçlar

| Ölçüm | Değer | Rapor |
|---|---|---|
| Alan çıkarımı mikro F1 (`rule_only`) | **0,834** | [`ablation.md`](docs/ablation.md) |
| Geri çağırma (doğru payda, 502 alan) | **%83,1** | [`kapsama_ve_geri_cagirma.md`](docs/kapsama_ve_geri_cagirma.md) |
| Uydurma oranı | **%5,4** | aynı rapor |
| Doğru susma (950 alan) | **%97,2** | aynı rapor |
| Paraf değişmezliği (87 yazım) | **%98,9** | [`paraf_degismezlik.md`](docs/paraf_degismezlik.md) |
| Şartname örnek senaryosu | **9/9** doldurma · **7/7** susma | [`sartname_senaryolari.md`](docs/sartname_senaryolari.md) |
| Erişim isabeti (hibrit) | R@5 **0,780** · MRR 0,826 | [`erisim_recall.md`](docs/erisim_recall.md) |
| Sohbet halüsinasyon oranı | **0,000** | [`sprint5_evaluation.md`](docs/sprint5_evaluation.md) |

---

## Kurulum

### Gereksinimler

| Bileşen | Sürüm |
|---|---|
| Python | 3.11+ (3.12 önerilir) |
| Node.js | 20+ (yalnızca arayüz derlemesi için) |

Harici servis gerekmez: PostgreSQL, Redis veya mesaj kuyruğu yoktur.
Geliştirme veritabanı SQLite'tır ve depoda Git LFS ile paylaşılır — kazıma
yapmadan çalıştırabilirsiniz.

### Hızlı başlangıç

```bash
git clone https://github.com/mzeydkurt/BZBTech-BilisimVadisi2026.git
cd BZBTech-BilisimVadisi2026

python dev.py kur        # sanal ortam + bağımlılıklar + .env
python dev.py baslat     # migrate + seed + backend → http://localhost:8000
python dev.py web        # ayrı terminalde arayüz → http://localhost:5173
```

API dokümanı: `http://localhost:8000/docs`

### Docker ile

```bash
docker build -t katip:latest .
docker run --rm -p 8000:8000 katip:latest        # → http://localhost:8000
```

Tek imaj, tek port; backend derlenmiş arayüzü kendisi servis eder.

**Kapalı ağ gösterimi** — konteynerin ağ arayüzü tamamen kaldırılır:

```bash
docker compose --profile airgap up katip-airgap
```

⚠️ `AIRGAP_MODE=true` iken dış servise bağlı yapılandırma **açılışta
reddedilir**; sistem sessizce dışarı çıkmaz.

---

## Komutlar

Tüm görevler `dev.py` üzerinden yürür; `make` gerekmez. Tam liste:
`python dev.py`

| Komut | Ne yapar | Ağa çıkar |
|---|---|---|
| `kur` | Bağımlılıklar, sanal ortam, `.env` | ✓ |
| `baslat` | migrate + seed + backend | — |
| `web` | Arayüzü başlatır | — |
| `test` | Testler + kapsam raporu | — |
| `lint` | ruff · format · mypy · tsc | — |
| `scrape` | 10 bankadan kampanya verisi | ✓ |
| `urun-kazi` | Ürün / oran / limit sayfaları | ✓ |
| `cikarim` | Metinden alan çıkarımı | LLM katmanı için ✓ |
| `siniflandir` | Dört eksende taksonomi | — |
| `kart-uret` | Aranabilir varlık kartları | — |
| `gomme-uret` | Gömme vektörleri | ✓ |
| `degerlendir` | Gold set'e karşı F1 | — |
| `ablation` | Üç kipi karşılaştırır | — |
| `boru-hatti` | Sekiz adımın tamamı sırayla | ✓ (`--agsiz` ile hayır) |

⚠️ Boru hattı sırası **bağımlılık zinciridir**: her adım bir öncekinin
çıktısını okur. Bozulursa hata *vermez*, sessizce eski veriyle çalışır.

⚠️ Kazıma komutları gerçek banka sitelerine istek atar. `robots.txt`
kurallarına uyulur, host başına 1,5 saniye beklenir, her yanıt ham HTML olarak
arşivlenir.

---

## Yapılandırma

Varsayılan olarak sistem **model olmadan da tam çalışır**: kural tabanlı
çıkarım, taksonomi, erişim ve toplama yanıtları modelden bağımsızdır.

### Yerel model (kapalı ağ yolu)

```bash
ollama pull qwen3:8b          # yanıt üretimi · Apache-2.0
ollama pull nomic-embed-text  # gömme · Apache-2.0
```

```env
LLM_PROVIDER=local
LOCAL_LLM_MODEL=qwen3:8b
EMBEDDING_MODEL=nomic-embed-text
```

### EVREN (üretim sağlayıcısı)

```env
LLM_PROVIDER=evren
EVREN_BASE_URL=https://evren-llmapi.ssyz.org.tr/v1
EVREN_API_KEY=<takım anahtarınız>
EVREN_MODEL=llm-fast
EVREN_EMBEDDING_MODEL=bge-m3-embed
CHAT_TIMEOUT_SECONDS=25
VECTOR_BACKEND=qdrant
QDRANT_URL=<takım örneğiniz>
```

Doğrulama: `python dev.py llm-saglik`

⚠️ Anahtarlar `.gitignore`'dadır, koda gömülmez.

---

## Geliştirme geçmişi

Beş sprintin kapsamı, sahada ölçülen bulgular ve alınan kararlar. Her bölüm
kapalı gelir; başlığa tıklayınca açılır.

<details>
<summary><b>Problem — sahada ölçülen veri düzensizliği</b></summary>

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

</details>

<details>
<summary><b>SPRINT 1 — şema, normalizasyon kütüphanesi, kazıma altyapısı, ilk iki banka</b></summary>

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

#### Toplanan veri

| | |
|---|---|
| Kampanya | 76 (Emlak Katılım 65 · Hayat Finans 11) |
| Tarihi çıkarılan | 66 / 76 |
| Durum dağılımı | 63 aktif · 3 süresi dolmuş · 10 tarih belirtilmemiş |

> "Tarih belirtilmemiş" ile "süresi dolmuş" **ayrı** tutulur. Kaynak sayfada
> tarih yoksa kampanya bitmiş sayılmaz; bunu "süresi dolmuş" göstermek yanlış
> bilgi üretirdi.

</details>

<details>
<summary><b>SPRINT 2 — kalan 8 banka, taksonomi, ürün ve oran verisi, sahada bulunan veri hataları</b></summary>

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

#### Toplanan veri

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

> **Bu tablo Sprint 2'nin kapanış anını gösterir, güncel veritabanını değil.**
> Sonraki sprintlerde süresi kesin dolmuş kampanyalar temizlendi ve ürün/oran
> verisi genişledi. Güncel sayılar: **482 kampanya · 285 ürün · 1.396 oran ·
> 2.441 varlık kartı · 2.402 gömme**. Tarihsel sayı silinmiyor — hangi
> sprintte neyin üretildiği izlenebilir kalıyor.

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

#### Kampanya taksonomisi

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

#### Sahada doğrulanan ve önlenen veri hataları

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

#### Analiz dokümanıyla çelişen, sahada düzeltilen varsayımlar

Planlama dokümanındaki dört varsayım canlı ölçümde tutmadı; kod ölçüme göre
yazıldı.

| Doküman | Ölçüm (Ağustos 2026) |
|---|---|
| Ziraat: `/kampanyalar/{kategori}` gezilecek | O adres **HTTP 404**; tek giriş `/kart-kampanyalari` (209 kampanya, tek istek) |
| Albaraka: liste rotasyonlu, 12-15 kez çek | Rotasyon **yok** — 3 çekimde de aynı 12 slug |
| Vakıf: liste JS, httpx ile 0 kampanya | Sunucu HTML'inde kampanyalar **var**; geçersiz slug gerçek 404 döndürüyor |
| Dünya: sitemap gzip | Düz XML — ama 46 kampanya adresi veriyor; liste sayfası gerçekten JS |

#### Yapısal oran verisi

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

#### Bilinçli kırpmalar — sessiz değil

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

</details>

<details>
<summary><b>SPRINT 3 — yapay zekâ katmanı, gold set, kanıta dayalı sorgulama, yerel model</b></summary>

Yapay zekâ katmanı: yerel model entegrasyonu, kural tabanlı çıkarım ve kanıta
dayalı doğal dil sorgulamanın temeli. Sohbet asistanı ve TEKNOFEST çıkarım
servisi **Sprint 5**'te eklendi.

| Alan | Durum | Sonuç |
|---|---|---|
| Gold set (cevap anahtarı) | ✅ | **2.360 elle etiketlenmiş alan** |
| Kural tabanlı çıkarım | ✅ | **4.508 çıkarım**, kanıt metniyle |
| Değerlendirme ve ablasyon altyapısı | ✅ | Üç kip karşılaştırmalı ölçülüyor |
| Varlık kartı üretimi | ✅ | 1.253 kart |
| Yerel LLM'in sağlayıcıya bağlanması | ✅ | Ollama · `qwen3:8b` · Apache-2.0 · **bulut yok** |
| Gömme sağlayıcısı | ✅ | `nomic-embed-text` · 768 boyut · Apache-2.0 |
| Sorgu anlama katmanı | ✅ | **30 soruluk sorgu kümesi** · kural katmanı **30/30** |
| Hibrit erişim (BM25 + gömme + RRF) | ✅ | Sorgu başına **3-5 ms** · FTS5 kullanılmadı |
| Toplama sorularının SQL yanıtı | ✅ | Üstünlük ve sayma; **model çağrılmaz** |
| Cevap üretimi ve kanıt guard'ı | ✅ | Doğrulanamayan sayı işaretlenir |
| Kanıtlı Arama arayüzü | ✅ | İki bölmeli çalışma alanı · Sprint 5'te sohbete dönüştü |

`rule_only` kipinin gold set'e karşı ölçülmüş temel çizgisi:
**kör alt küme F1 0,785** · mikro F1 0,809 · makro F1 0,773 ·
halüsinasyon oranı 0,171 · doğru susma oranı 0,913.

#### Yerel model — kapalı ağ yolu

Sprint 3'te seçilen yerel yığın. **Üretim sağlayıcısı Sprint 5'te EVREN'e
taşındı**; bu yol kaldırılmadı ve on-prem / kapalı ağ gösteriminin dayanağı
olarak duruyor. Geçiş tek `.env` satırıdır (`LLM_PROVIDER=local`).

| | |
|---|---|
| Çalışma ortamı | Ollama (MIT) |
| Yerel üretim modeli | `qwen3:8b` — Apache-2.0 |
| Yerel gömme modeli | `nomic-embed-text` — Apache-2.0 |
| Ölçülen hız | 7,5 tok/s (GTX 1650, 4 GB VRAM · %57 CPU offload) |

Model seçimi ölçümle yapıldı: iki Apache-2.0 aday aynı Türkçe kampanya
metniyle karşılaştırıldı. İkisi de **sıfır Çince karakter** üretti, ikisi de
doğru kartı gösterdi, ikisi de uydurma sayı yazmadı; `qwen3:8b` kart metnini
kopyalamak yerine gerçekten sentezlediği için seçildi.

> **Qwen2.5-14B bilinçli olarak kullanılmadı.** Gerekçe donanım değil mimari:
> aşağıdaki tasarımda model hiçbir sayı üretmiyor. Doğruluk deterministik
> erişimden, kural tabanlı çıkarıcıdan ve kanıt guard'ından geliyor; model
> büyüklüğü yalnızca cümlenin akıcılığını etkiliyor. Model `.env` içinde tek
> satırla değişir.

⚠️ **Sessiz bir hata bulundu ve düzeltildi.** Sağlayıcı OpenAI uyumlu
`/v1/chat/completions` ucunu kullanıyordu. Düşünen modellerde bu uç, düşünme
çıktısını `content` alanına koymuyor: HTTP 200 dönüyor, `content` **boş**
geliyor ve hiçbir alan çıkarılamıyor — hata mesajı yok, yalnızca F1 sıfıra
düşüyor. Üretim çağrısı Ollama'nın `/api/chat` ucuna, `think: false`
parametresiyle taşındı; boş yanıt artık hata fırlatıyor.

#### Kanıta dayalı sorgulama — model sayı üretmez

Tasarımın çekirdek kuralı: **kullanıcıya gösterilen her rakam
`campaign_metrics` satırından gelir.** Model yalnızca yönlendirme yapar ve
cümle kurar.

| Katman | Yöntem | Model kullanır mı? |
|---|---|---|
| Sorgu anlama | Taksonomi sözlüğü + sayı/karşılaştırma kalıpları | Hayır (son çare) |
| Erişim | BM25 + gömme, Reciprocal Rank Fusion | Yalnızca sorgu vektörü |
| Sert süzgeç | Banka · durum · 4 eksen · sayısal eşik | Hayır |
| Toplama (en düşük / kaç tane) | SQL | **Hayır** |
| Cevap cümlesi | Yerel model | Evet |
| Denetim | Sayı doğrulama · terim guard'ı | Hayır |

**Toplama soruları erişime hiç girmez.** "En düşük kâr payı hangi bankada?"
sorusunda en benzer 8 kart getirilip modele okutulsaydı, model yalnızca o 8
kartın en küçüğünü söylerdi — 608 kampanyanın gerçek en küçüğünü değil. Yanıt
makul görünür, kaynak da gösterir, ama yanlıştır ve yanlışlığı hiçbir yerde
bildirilmez. Hesap tüm kayıtlar üzerinde SQL ile yapılır:

> Kâr payı oranı bakımından uç değer **%0** ve Dünya Katılım bankasının
> "PttAVM.com'da Peşin Fiyatına 3 Taksit Fırsatı!" kampanyasına ait. Aynı
> değeri taşıyan **135 kampanya** daha var. Hesap, bu alanda değeri bulunan
> **148 kampanya** üzerinden yapıldı; **460 kampanyada** alan çıkarılamadığı
> için hesaba katılmadı.

Üç şey cümlede bilinçli olarak duruyor: beraberlik sayısı, hesaba giren kayıt
sayısı, hesaba **girmeyen** kayıt sayısı. "En düşük oran %0" ifadesi, 148 kayıt
üzerinden mi 608 kayıt üzerinden mi söylendiği bilinmeden değersizdir.
`NULL` sıfır sayılmaz.

**Sert süzgeç bir kapıdır, puan değil.** "Kâr payı %2'nin altında" diyen bir
sorguda %4,20'lik kampanya, metni ne kadar benzerse benzesin listeye girmez.

#### Sorgu kümesi — 30 soru, gerçek veride ölçüldü

Kümedeki her soru için beklenen süzgeçler elle yazıldı; sorular
**gold set'ten türetilmedi** (sızıntı olurdu). Kural katmanı beklenen
süzgeçlerin **30/30**'unu çıkarıyor.

| | |
|---|---|
| Gövde kurulumu | 205 ms (süreç başına bir kez) |
| Sorgu başına süre | **3-5 ms** |
| Arama gövdesi | 608 kart |

⚠️ **FTS5 kullanılmadı.** SQLite'a özgüdür ve "PostgreSQL'e geçişte yalnızca
`DATABASE_URL` değişir" kuralını bozar. Saf Python BM25 bu boyutta
milisaniyenin altında çalışıyor.

#### Sorgu katmanında yakalanan sessiz hatalar

Dördü de hata fırlatmadan yanlış sonuç üretiyordu; her biri için regresyon
testi var.

| Bulgu | Etki | Önlem |
|---|---|---|
| `term_months_max` işaretçisi `" ay"`, `normalize_text()` baştaki boşluğu siliyor | Kalan `"ay"` **"kâr p-ay-ı"** içine uyuyor; "en düşük kâr payı" sorusu vade üzerinden yanıtlanıp **"en düşük kâr payı 1"** diyordu | İşaretçiler kelime sınırında aranıyor |
| Taksonomi anahtarı `altın`, `altında` sözcüğüne uyuyor | "%2'nin **altında**" ifadesi sektör süzgeci ekliyor, 7 finansman kampanyasının tamamı eleniyor, **0 sonuç** | Karşılaştırma işaretçileri taksonomi eşleşmesinden önce maskeleniyor — bir simgenin iki rolü olamaz |
| Sert süzgeç, en ilgili 120 adaya uygulanıyordu | Seçici süzgeç havuzu boşaltıyor; "Kuveyt Türk'te market kampanyası" **0 sonuç** dönüyordu | Süzgeç gövdenin tamamına uygulanıyor, sıralama sonra yapılıyor |
| Arama gövdesi önbelleği hiç geçersizleşmiyordu | `kart-uret` sonrası arama ESKİ metinlerle çalışmaya devam ediyordu | Üç sayaçlık parmak izi denetimi |

#### Boş sonuç sessizce gevşetilmez

Bir sorgunun süzgeçleri kesişmiyorsa sonuç boş kalır — ama **hangi süzgecin
kaldırılmasıyla kaç sonuç çıkacağı** yanıtta döner:

```
"KT'de akaryakıt indirimi olan kampanyalar"  ->  0 sonuç
   Sektör: akaryakıt  süzgecini kaldır  ->  11 sonuç
   Fayda:  indirim    süzgecini kaldır  ->   3 sonuç
```

Sonucu kendi başına gevşetmek, kullanıcının sormadığı soruyu yanıtlamak
olurdu; boş göstermek ise "banka bunu yapmıyor" izlenimi verirdi. Karar
kullanıcıya bırakılır.

#### Kanıtlı Arama arayüzü

Sekmenin adı **"Akıllı Arama" değil "Kanıtlı Arama"**: bu sekme arama değil,
kaynağı gösterilebilir yanıt üretiyor.

Yerleşim iki bölmeli — solda soru, yorum ve yanıt; sağda kanıt. Dört unsur:

1. **"Anladığım" çipleri.** Sistem soruyu hangi süzgeçlere çevirdiğini gösterir
   (`Banka: Kuveyt Türk ×` `Sektör: Market ×`); her çipin ipucunda sorgunun o
   süzgeci üreten parçası yazar ve çip kaldırılınca sorgu yeniden çalışır.
   Yanlış anlaşılma görünür ve düzeltilebilir hâle gelir.
2. **Tıklanabilir atıf.** Yanıttaki `[496]` sağdaki ilgili satırı vurgular.
3. **Erişim şeffaflık şeridi.** `608 karttan 5 getirildi · sözcüksel ·
   584 kayıt süzgeçlere takıldı · 5 ms`
4. **Gerçek veriden seçilmiş örnek sorular.** Hepsi bu veri setinde
   yanıtlanabiliyor; boş ekran yerine çalışan bir başlangıç.

Yanıtın kaynağı her zaman yazılı: `yerel model` · `hesaplanmış` (SQL) ·
`model kapalı` (şablon) · `kanıt yok` (reddetme). Model erişilemediğinde
sistem çökmez, sıralı kanıtlar gösterilmeye devam eder.

#### Sahada düzeltilen altyapı hataları

| Bulgu | Etki | Önlem |
|---|---|---|
| Göç `0011` kısıt adını sabit yazıyordu | Ad veritabanına göre 3 ya da 5 kat önek taşıyor; **boş veritabanında `migrate` hiç tamamlanmıyordu** | Ad çalışma anında `sqlite_master`'dan okunuyor |
| `conftest.py`'de ortam bloğu `app.*` içe aktarmalarının altındaydı | `get_settings()` içe aktarma sırasında önbelleğe giriyor; `LLM_PROVIDER=mock` ataması etkisiz kalıyor ve 3 test gerçek modele çıkmaya çalışıyordu | Blok içe aktarmaların üstüne alındı |
| `frontend/package.json`'da `typecheck` betiği yoktu | `dev.py lint` onu çağırıyor; **arayüz tip denetimi hiç çalışmıyormuş** | Betik eklendi |
| `.env`'deki model adı kurulu değildi, gömme modeli bir Hugging Face adıydı | `llm-saglik` False dönüyor, gömme çağrısı 404 verirdi | İkisi de kurulu Ollama modellerine çevrildi |

#### Veri bulgusu — `konut_finansmani` etiketi sıfır

482 kampanyanın **hiçbiri** `konut_finansmani` etiketi taşımıyor. Şartnamenin
8 zorunlu ürün türünden tek sıfır olan bu (ölçüm: 25 Ağustos 2026):

| Tür | Etiket | | Tür | Etiket |
|---|---|---|---|---|
| `kart` | 378 | | `ihtiyac_finansmani` | 9 |
| `alisveris_puani` | 56 | | `tasit_finansmani` | 6 |
| `finansman` | 49 | | `yatirim_urunu` | 5 |
| `yeni_musteri` | 42 | | **`konut_finansmani`** | **0** |

> Bu bir erişim hatası **değil**, sınıflandırma kapsamı boşluğudur. Erişim
> katmanı doğru davranıyor; eksik olan `taxonomy.py` sözlüğü. Sözlük
> genişletildikten sonra `python dev.py siniflandir` **ağa çıkmadan**
> yeniden çalıştırılabilir. Sorgu kümesindeki üç `konut_finansmani` sorusu
> kümede **kalıyor**: boş-sonuç yolunu doğru sınıyorlar.

İkinci bulgu, sözlük genişletmesiyle **kısmen kapandı**: Kuveyt Türk'ün
`market_gida` etiketi 0'dan **1**'e çıktı. Veri setindeki toplam `market_gida`
etiketi 44'ten 22'ye düştü — bu bir gerileme değil, süresi kesin dolmuş
kampanyaların temizlenmesinin sonucu.

</details>

<details>
<summary><b>SPRINT 4 — dashboard, kampanya kataloğu, karşılaştırma arayüzü, simülatör</b></summary>

Sprint 4, biriken kampanya / ürün / oran verisini **rekabet istihbaratı
arayüzüne** dönüştürür. Amaç: banka analistinin 10 katılım bankasını tek
ekranda izlemesi, filtrelemesi, karşılaştırması ve simüle etmesi.

Yapılanlar: genel bakış dashboard'u, kampanya kataloğu ve detay (kanıt
çekmecesi), finansman/ürün listesi ve detay, karşılaştırma, finansman–getiri
simülatörü, katılma hesabı görünümü, CSV/Excel dışa aktarma ve kurumsal
AppShell iskeleti. Eksik veri `null` olarak gösterilir; sıfırla karıştırılmaz.

| Alan | Durum | Sonuç |
|---|---|---|
| Genel bakış (dashboard) | ✅ | KPI kartları · banka kapsama · sektör / durum / taksonomi grafikleri |
| Kampanya kataloğu | ✅ | Chip filtre · sayfalama · durum rozetleri (`unknown` ≠ `expired`) |
| Kampanya detayı + kanıt çekmecesi | ✅ | Çıkarım alanı · `evidence_text` · güven · kaynak URL |
| Finansman / ürün listesi | ✅ | Oranı olan / yalnızca limit / veri yok grupları ayrı |
| Ürün detayı | ✅ | Oran tablosu · limit · BDDK sapması · masraf alanları |
| Karşılaştırma motoru arayüzü | ✅ | Kampanya ve ürün sıralama · kriter · banka seçimi |
| Finansman / getiri simülatörü | ✅ | Tutar–vade senaryosu · ödeme planı satırları |
| Katılma hesabı görünümü | ✅ | TKBB / katılma getirisi odaklı tablo |
| Dışa aktarma | ✅ | Karşılaştırma ve simülasyon için CSV / Excel |
| Kurumsal UI iskeleti | ✅ | AppShell · sidebar · StatCard · Empty / Error / Loading |

</details>

<details>
<summary><b>SPRINT 5 — sohbet asistanı, hibrit RAG, EVREN entegrasyonu, ölçümler</b></summary>

Sohbet asistanı, hibrit RAG ve TEKNOFEST çıkarım servisi entegrasyonu.

| Alan | Durum | Sonuç |
|---|---|---|
| EVREN çıkarım servisi | ✅ | `llm-fast` · 1,6 sn · yerel yol korundu |
| Gömme ve vektör deposu | ✅ | `bge-m3-embed` 1024 boyut · Qdrant **2.402 nokta** |
| Hibrit erişim (BM25 + anlamsal + RRF) | ✅ | Sert süzgeç kapısı Python tarafında |
| Toplama sorularının SQL yanıtı | ✅ | Model çağrılmaz |
| Çok turlu sohbet + oturum kalıcılığı | ✅ | `chat_sessions` / `chat_messages` |
| Sohbet geçmişi listesi ve erişimi | ✅ | `GET /chat/sessions` |
| Model seçimi (istek başına, canlı keşif) | ✅ | `GET /chat/models` |
| Kapsam dışı soru reddi | ✅ | Ölçülmüş 8 vaka |
| Kanıt ve erişim şeffaflığı | ✅ | Kanıt metni · süzgeç çipleri · erişim şeridi |
| Yeniden sıralama | ⛔ | Ölçüldü, **isabeti düşürdü**, açılmadı |

---

#### EVREN — TEKNOFEST çıkarım servisi

TEKNOFEST 2026 kapsamında T.C. Cumhurbaşkanlığı Savunma Sanayii Başkanlığı
tarafından yarışmacı takımlara tahsis edilen **EVREN** servisi (8 × NVIDIA
H200 · vLLM · BF16 · kuantizasyon yok) üretim sağlayıcısı olarak bağlandı.

> **Bu ücretli bir bulut servisi değildir.** Şartnamenin madde 8 (ücretli
> hizmet) ve 5.9 (dış bağımlılık) kısıtları, üçüncü taraf ticari servisleri
> hedefliyor; EVREN yarışmanın kendi altyapısıdır, kotasız ve ücretsizdir.

**Yerel yol kaldırılmadı.** `LLM_PROVIDER=evren` ↔ `local` geçişi tek `.env`
satırıdır; on-prem / kapalı ağ gösterimi Ollama üzerinden yapılmaya devam
eder. Kodda hiçbir yer EVREN'e mahkûm değildir.

Model seçimi ölçümle yapıldı — aynı Türkçe konut finansmanı metni, aynı beş
alan:

| Model | Süre | Doğru alan | Not |
|---|---|---|---|
| **`llm-fast` (EVREN)** | **1,6 sn** | **5/5** | tarihi ISO'ya normalize etti (`2026-12-31`) |
| `llm-large` (EVREN) | 4,7 sn | 5/5 | tarihi ham bıraktı, kanıt alıntıları zayıf |
| `qwen3:8b` (yerel) | 70,0 sn | 4/5 | "masraf **alınmaz**" ifadesini `50.000` yazdı |

`llm-fast` hem **44 kat hızlı** hem daha doğru: `file_fee_try=0` tuzağını iki
yerel model de kaçırdı.

#### RAG — hibrit erişim, kanıtlı yanıt

| Katman | Yöntem | Model kullanır mı? |
|---|---|---|
| Sorgu anlama | Taksonomi sözlüğü + sayı/karşılaştırma kalıpları | Hayır (son çare) |
| Sözcüksel erişim | BM25, saf Python | Hayır |
| Anlamsal erişim | `bge-m3-embed` (1024 boyut) + Qdrant | Yalnızca sorgu vektörü |
| Birleştirme | Reciprocal Rank Fusion | Hayır |
| Sert süzgeç | Banka · durum · 4 eksen · sayısal eşik | Hayır |
| Toplama (en düşük / kaç tane) | SQL | **Hayır** |
| Cevap cümlesi | Yerel/EVREN modeli | Evet |
| Denetim | Sayı doğrulama · terim guard'ı · yön denetimi | Hayır |

**Kullanıcıya gösterilen her rakam `campaign_metrics` satırından gelir.**
Model yalnızca yönlendirme yapar ve cümle kurar.

| Gövde | Sayı |
|---|---|
| `entity_cards` | **2.441** (kampanya 482 · oran 1.635 · ürün 285 · terim 29 · banka 10) |
| `embeddings` | **2.402** · `bge-m3-embed` · 1024 boyut |
| Qdrant noktası | **2.402** · Cosine · durum `green` |

⚠️ 39 kart bilinçli olarak gömülmedi: `bank` (10) üstveri kartıdır,
`glossary` (29) terime göre birebir aranıyor — anlamsal aramaya girmiyor.

**Qdrant birincil, yerel `embeddings` tablosu yedek.** Qdrant erişilemediğinde
arama yerel tabloya düşer ve **nedenini yanıtta yazar**; kapalı ağ gösterimi
bu yüzden Qdrant olmadan da çalışır. Süzgeçleme Qdrant'a devredilmedi:
"değeri yok" ile "eşiği geçmedi" ayrımını yapan tek uygulama Python
tarafındadır ve aynı mantığı iki yerde tutmak ikisinin sessizce ıraksaması
demektir.

`qdrant-client` bağımlılığı **eklenmedi** — REST arayüzü yeterli, `httpx`
projede zaten var ve `LICENSES.md`'ye yeni bir satır girmedi.

#### Sohbet — Katibim-AI

| Yetenek | Durum |
|---|---|
| Çok turlu sohbet + oturum kalıcılığı | ✅ `chat_sessions` / `chat_messages` |
| Tur zinciri — bağlam hangi cevaptan devralınıyor | ✅ `completion_id` / `parent_completion_id` |
| Sohbet geçmişi listesi ve erişimi | ✅ `GET /chat/sessions` |
| Model seçimi (istek başına) | ✅ `GET /chat/models` — canlı keşif |
| Hazır örnek sorular | ✅ gerçek veriden seçilmiş |
| Kapsam dışı soru reddi | ✅ `kapsam_disi` niyeti |
| Kanıt gösterimi | ✅ katlanabilir kanıt metni (kampanya + ürün) |
| Süzgeç şeffaflığı | ✅ "Anladığım" çipleri, kaldırılabilir |
| Erişim şeffaflığı | ✅ kaç karttan kaçı, hangi kanal, ne elendi, kaç ms |
| Boş sonuçta gevşetme önerisi | ✅ hangi süzgeç kaldırılsa kaç sonuç |
| Kampanya odağı — "bu kampanyanın…" | ✅ önceki yanıttaki tek kayda bağlanır |
| Banka kümesi soruları — "hangi bankada X yok" | ✅ `absence` toplaması |
| Banka sayımı — "kaç banka X veriyor" | ✅ `count_banks`, sayı SQL'den |
| Sözlük zenginleştirmesi | ✅ olgusal yanıta tanım eklenir, niyet değişmez |
| Uç değer — "en düşük X oranı hangi bankada" | ✅ ürün oranı tablosundan |
| Toplama görünümü | ✅ banka bazlı döküm + yokluk kümeleri (arayüz) |
| Kapsam sorusu — "hangi bankalar var" | ✅ `bank_roster`, evrenden yanıtlanır |
| Yanıtlanamayan soru | ✅ kanıt kartı gösterilmez |

**Yönetişim — ölçülmüş davranış:**

| Soru | Niyet | Yanıt |
|---|---|---|
| "Yarın hava nasıl olacak?" | `kapsam_disi` | reddetme |
| "Bana bir yemek tarifi ver" | `kapsam_disi` | reddetme |
| "Galatasaray maç sonucu ne?" | `kapsam_disi` | reddetme |
| "Bitcoin alsam mı?" | `kapsam_disi` | reddetme |
| "Merhaba" / "Sen kimsin?" | `sohbet` | şablon tanıtım |
| "asdkjhaskjdh" | `search` | **uydurmuyor** — "veriyle yanıt verilemiyor" |
| "Bana 10 milyon TL kredi ver" | `search` | reddediyor |
| "Hangi bankaya para yatırırsam en çok kazanırım, kesin söyle" | `search` | **yatırım tavsiyesi vermiyor** |

⚠️ Kripto ve borsa soruları kapsam dışına alındı: bir finansal kurum aracının
yatırım tavsiyesi vermesi hem kapsam hem uyum sorunudur. **`döviz` bilinçli
olarak eklenmedi** — `yatirim_birikim` sektörünün gerçek anahtar kelimesi ve
meşru kampanya sorgularında geçiyor.

**Model seçimi** `GET /chat/models` ile canlı keşfedilir (EVREN `/v1/models`,
Ollama `/api/tags`); elle yazılmış bir liste servis değiştiğinde sessizce
yalan söyler.

- Seçim **istek başınadır**, `.env` yazılmaz — bir kullanıcının tercihi tüm
  kurumun yapılandırmasını değiştirmemeli.
- Gömme ve yeniden sıralama modelleri listeye **girmez**: sohbet yanıtı
  üretemezler.
- Yerel modeller **lisans havuzuna göre süzülür**. Ollama'da kurulu olsa bile
  Llama türevi ya da "Research License" taşıyan model seçenek olarak
  sunulmaz; beyaz liste kullanılır, siyah liste değil.
- Erişilemeyen sağlayıcı listeden **gizlenmez**, devre dışı gösterilir —
  gizlemek "böyle bir seçenek yok" izlenimi verir ve kapalı ağ yeteneğini
  görünmez kılar.

**Sohbet zaman aşımı toplu çıkarımdan ayrıldı.** `LLM_TIMEOUT_SECONDS=180`
gece çalışan toplu çıkarım için doğru; sohbette 180 saniye bekleyen bir
arayüz ölmüş görünür. EVREN tüm takımlarca paylaşıldığı için gecikme
dalgalanıyor — ölçüldü: aynı sorgu **4,1 sn · 4,9 sn · 30,5 sn**.
`CHAT_TIMEOUT_SECONDS=25` aşılınca şablon yanıta düşülür ve **kanıtlar yine
gösterilir**.

#### Gerçek soru havuzu ölçümü (100 soru · 42 oturum)

Ekipten gelen `docs/Katilim_Bankaciligi_Test_Sorulari.xlsx` havuzu, güncel
veritabanına göre hazırlanmış **100 soru / 42 oturum** içerir. `Oturum No` ve
`Sıra No` kolonlarıyla **çok turlu**: 58 soru bir takip sorusudur. 92 soru
müşteri, 8 soru banka çalışanı rolünde.

Havuz `session_id` + `parent_completion_id` zinciriyle sırasıyla çalıştırıldı
ve geliştirmeler bu ölçümün üzerine yapıldı.

**Bulgu 1 — "nedir" tanım sorusu sanılıyordu.** `intent=tanim` **49/100**
çıktı; havuzda gerçekten terim sorusu olan kategori ise ~8. Türkçede olgusal
sorular da "nedir" ile biter:

> *"Kuveyt Türk'te aylık vadeli TL katılma hesabının kâr payı oranı nedir?"*

Bunların 16'sı kullanıcıya *"sözlükte tanım bulunamadı"* döndürüyordu — oysa
yanıt kampanya/ürün gövdesinde vardı. Aday kural 100 soruda ölçüldü:

| | doğru tanım | **yanlış tanım** | kaçırılan |
|---|---|---|---|
| eski kural (yalnızca işaretçi) | 7 | **42** | 2 |
| yeni kural (banka adı / sayı varsa tanım değil) | 5 | **3** | 4 |

⚠️ Kalan 3'ün 2'si aslında gerçek tanım sorusu (kategori etiketi eksikti).
4 "kaçırılan"ın 3'ü de doğru davranıştır: *"konut kredisinin faiz oranı
nedir"* olgusal bir sorudur, terim uyarısıyla yanıtlanır.

Tanım yine kaybolmaz: sözlük ıskası **aramaya düşer** ("bulunamadı" denmez) ve
olgusal yanıta tanım **zenginleştirme** olarak eklenir.

**Bulgu 2 — banka kümesi soruları yanıtlanamıyordu.**

| soru | eski davranış | gerçek |
|---|---|---|
| kaç banka taşıt finansmanı veriyor | toplama kurulmuyor, **model sayıyı kendi üretti**: *"iki banka"* | **7** |
| hangi bankada taşıt kampanyası **yok** | olumsuzlama yok sayılıp taşıt **oranları** listelendi | — |
| `by_bank` dökümü | sıfır kampanyalı banka görünmüyordu | `adil_katilim = 0` |

İlki *"model sayı üretmez"* güvencesinin doğrudan ihlaliydi. Üçü de aynı
eksikten doğuyordu: toplama **banka evrenini** görmüyordu; kaydı olmayan banka
`docs` içinde hiç bulunmadığı için yokluk sorusu yapısal olarak
yanıtlanamazdı. `Corpus.banks` eklendi, `count_banks` / `absence` toplamaları
ve `banks_with` / `banks_without` alanları geldi.

⚠️ Alan ayrımı korunur: "kaç banka taşıt finansmanı **veriyor**" ürünü sorar
(7), "hangi bankada taşıt **kampanyası** yok" kampanyayı sorar (3). Aynı sayıyı
iki soruya da vermek, birinde yanlış yanıt demektir.

**Bulgu 3 — "Bu kampanyanın bitiş tarihi ne zaman?"** 58 takip sorusunun
yalnızca 4'ünde bağlam devri oluyordu. Oturum S3 · 3. turda devir
gerçekleşiyor, çip görünüyor, ama sonuç **0** dönüyordu. Üç ayrı neden:

1. Odak yalnızca **bankayı** taşıyordu, kampanyayı değil.
2. Devralınan 5 eksen süzgeci odak kaydı eliyordu.
3. Sert süzgeç kapısı yetmiyordu — **erişim ondan önce çalışıyor** ve sorguda
   içerik terimi olmadığı için BM25 o kaydı hiç getirmiyordu.

Odak varken erişim **tamamen atlanır**, kayıt doğrudan okunur. Birden çok sonuç
varsa odak en üst sıralı kayıttır: "belirsizse bağlamama" kuralı burada
**garanti başarısızlık** üretiyordu. Bağ çip olarak görünür ("önceki yanıttaki
kampanya"), kullanıcı yanlışsa düzeltebilir.

**Sonuç — havuz öncesi/sonrası (100 soru, aynı zincirle):**

| ölçüt | önce | sonra |
|---|---|---|
| `intent=tanim` (havuzda ~8 gerçek) | 49 | **7** |
| *"sözlükte tanım bulunamadı"* yanıtı | 16 | **0** |
| kanıt taşımayan yanıt | 22 | **5** |

⚠️ Kalan 5'in 3'ü **doğru davranıştır**: iki kapsam dışı reddi ve bir sohbet
tanıtımı. Dördüncüsü *"Adil Katılım'da aktif kampanya var mı?"* — yanıt
belirsiz kalıyor, oysa doğru yanıt "0 kampanya" bulgusunu **söylemektir**;
açık iş olarak duruyor.

⚠️ Havuz `count_banks` / `absence` toplamalarını **hiç tetiklemiyor** — "kaç
banka" ya da "hangi bankada … yok" ifadesi içeren soru yok. O yetenekler birim
testleri ve canlı sorgularla doğrulandı, bu havuzla değil.

**Bulgu 4 — uç değer soruları ürün oranlarını görmüyordu.**
*"En düşük konut finansmanı kâr payı oranı hangi katılım bankasında?"* —
rekabet analizinin en klasik sorusu — *"uygun teklif bulunmamaktadır"* yanıtı
dönüyordu. `aggregate.compute` yalnızca **kampanya** metriklerine bakıyor; oran
verisi `product_rates` tablosunda. `count_banks` / `absence` için çözülen alan
ayrımı `extremum`'a uygulanmamıştı. Beraberlik ve kapsam ("kaç kayıtta oran
yok") aynı kuralla bildirilir.

**Bulgu 5 — anlatıcı güvenlik bildirimini düşürüyordu.** Uç değer `%0` çıktığında
eklenen belirsizlik uyarısı, anlatıcı katmanı (`_anlat_computed`) metni yeniden
yazarken **kayboluyordu**. Güvenlik bildirimi modelin üslup kararına
bırakılamaz: uyarı artık yanıt metnine değil `direction_note` yapısal alanına
yazılıyor ve arayüz onu ayrı gösteriyor.

⚠️ `%0` iki anlama gelir ve kuralla ayırt edilemez — gerçek bedelsiz kampanya
(Albaraka Togg: 10-12 ay %0, 36 ay %3,05) ya da kaynakta oranın yayımlanmamış
olması. Veri **değiştirilmiyor**, belirsizlik söyleniyor.

#### Canlı kullanımdan bildirilen üç sorun

Gerçek bir sohbet oturumundan geldi; üçü de aynı sınıftan — **kanıt/kapsam
uyumsuzluğu**: yanıt metni doğru olduğu hâlde ekranda gösterilen dayanak
yanlış ya da eksikti.

| soru | önce | sonra |
|---|---|---|
| "hangi bankalar var" | **3 banka** — rastgele 3 kampanya kartından okunmuş | **10 banka**, Adil Katılım dahil |
| "ben kimim" | doğru reddetme, ama kanıt olarak süresi dolmuş bir Hac/Umre kampanyası | reddetme, **kanıt kartı yok** |
| "en uygun kredi hangisinde konut için" | Enerya İhtiyaç + Araç Finansmanı gösteriliyordu | **4 kanıtın 4'ü `konut_finansmani`** |

**Kapsam sorusunun yanıtı örneklem olamaz.** İlk sorun aynı oturumda daha da
görünür oluyordu: hemen ardından "başka banka yok mu?" sorulduğunda doğru yanıt
(10 banka) geliyordu — aynı bilgi bir soruda yanlış, diğerinde doğru.
`bank_roster` toplaması eklendi; yanıt banka evreninden gelir.

**"Yanıtın dayandığı kanıt" başlığı bir iddiadır.** Yanıt "elimizdeki veriyle
yanıtlanamıyor" ise hiçbir kayıt onun dayanağı değildir. Tek kapı eklendi;
erişim şeffaflığı şeridi (kaç karttan kaçı getirildi) **korunur** — gizleme
değil, yanlış etiketlemenin düzeltilmesi.

**Sektör ekseni ürün süzgecine bağlanmamıştı.** "Konut için" sorgusundan çıkan
tek süzgeç `sector=konut_gayrimenkul`; ürün süzgeci yalnızca `product_type`a
bakıyordu. ⚠️ Yalnızca kesin karşılığı olan sektörler eşlenir — "giyim"
sektörünün finansman ürünü karşılığı yoktur ve uydurulmaz.

#### Sohbet ölçümü (35 soruluk gold set)

| Metrik | Değer |
|---|---|
| Doğru niyet oranı | **0,971** |
| Halüsinasyon oranı | **0,000** |
| Doğru susma oranı (5 vaka) | **1,000** |
| Netleştirme isabeti (1 vaka) | **1,000** |
| Ortalama gecikme | 1.746 ms |

Ayrıntı: [`docs/sprint5_evaluation.md`](docs/sprint5_evaluation.md)

#### Yeniden sıralama ölçüldü — AÇILMADI

EVREN `rerank` modeli çalışıyor ama bu veri setinde **isabeti düşürüyor**:

| | İlk sonuç isabeti |
|---|---|
| RRF (mevcut) | **4/8** |
| `rerank` | **3/8** |

İlk sonucu 8 vakanın 6'sında değiştirdi: 1 iyileştirme, **2 bariz bozma**
("Evlenecek çiftlere" ve "Emeklilere" sorularının doğru sonuçları kayboldu).
Kısa metinlerde belirgin biçimde yanılıyor — "market hediye çekli kampanya"
sorgusunda *"Akaryakıt indirimi"* **0,999** ile birinci çıktı.

Devir rehberinin kendi kuralı uygulandı: *"hibrit, `rule_only`'den kötüyse
LLM katmanı açılmaz."* Yetenek `EvrenProvider.rerank()` olarak duruyor ve
`EVREN_RERANK_MODEL` ayarı mevcut; erişim yoluna **bağlanmadı**.

#### Sprint 5'te yakalanan sessiz hatalar

Sprint 3'te bulunanlar yukarıda; aşağıdakiler bu sprintte ortaya çıktı.
Hepsi hata fırlatmadan yanlış sonuç üretiyordu ve her biri için regresyon
testi var.

| Bulgu | Etki | Önlem |
|---|---|---|
| Gömme etiketi, vektörü üreten modelden bağımsızdı | `bge-m3-embed` ile üretilmiş **1.519 vektör** `nomic-embed-text` etiketiyle kaydedildi (1024 boyut; oysa nomic 768 üretir). Yazan ve okuyan aynı yanlış etiketi kullandığı için hata görünmüyordu; airgap'te `LLM_PROVIDER=local` yapıldığı anda sorgu 768, saklanan 1024 olur ve `cosine()` uzunluk uyuşmazlığında `0.0` döndürdüğü için **anlamsal kanal sessizce ölürdü** | Tek doğruluk kaynağı `active_embedding_model()`; boyut uyuşmazlığı artık yanıtta bildiriliyor ve loglanıyor |
| Model seçimi yalnızca sağlayıcıyı değiştiriyordu | `evren:llm-large` seçmek sağlayıcıyı EVREN'de tutuyor ama modeli `.env`'deki `llm-fast` olarak bırakıyordu — kullanıcı seçim yaptığını sanıyor, **hiçbir şey değişmiyordu** ve hata da verilmiyordu | Seçim sağlayıcıyı **ve** model adını birlikte günceller; model listesi servisten canlı keşfedilir |
| Değerlendirme raporu yanlış gömme modelini beyan ediyordu | `docs/sprint5_evaluation.md` `nomic-embed-text` yazıyordu, oysa vektörler `bge-m3-embed`'den geliyordu — jüriye sunulan bir çıktıda yanlış model adı | Rapor da tek kaynaktan okuyor |
| Qdrant hata mesajı boş geliyordu | `httpx.ReadTimeout`'un `str()` çıktısı boş; mesaj "Qdrant'a ulaşılamıyor: " diye yarım kalıyor ve sorunun zaman aşımı mı ağ mı olduğunu gizliyordu (2.402 noktalık yüklemede ölçüldü) | İstisna türü mesaja giriyor; yükleme partisi 128→64 ve upsert için aramadan ayrı 120 sn zaman aşımı |
| WAL etkinken kopyalanan SQLite dosyası bayat görüntü veriyor | Kart sayımı canlı dosyada **482**, kopyada **377** çıktı; "105 kampanya aranamıyor" şeklinde yanlış bir bulgu raporlanmasına yol açtı | Sayım canlı dosyadan `mode=ro` ile yapılıyor |
| Bağlam devri süzgecin **yokluğuna** bağlıydı, kanıta değil | Yeni soru kendi konusunu getirdiği hâlde önceki turun banka/eksen süzgeci taşınıyordu. Ölçüldü, 5 senaryonun **4'ü yanlış**: "Kuveyt Türk alışveriş puanı" → "taşıt finansmanında en uzun vade **hangi bankada**" sorusu Kuveyt Türk'e kilitleniyor; "Albaraka yeni müşteri" → "**tüm bankalarda** kaç kampanya var" sorusu Albaraka'ya kilitleniyordu. Kullanıcı bankalar arası sordu, tek banka yanıtı aldı | Devir artık kanıta bağlı: sorgu kendi ekseni/oranı/toplamasıyla ayakta durabiliyorsa ve önceki tura açık atıf yapmıyorsa **hiçbir şey** devralınmaz. `opens_scope()` — "hangi banka", "tüm bankalar", "bankalar arası" — banka devrini her koşulda veto eder |
| "Onun" önceki **soruya** bağlanıyordu, önceki **cevaba** değil | "en uzun vade hangi bankada" → *"Vakıf Katılım"* cevabından sonra "peki onun koşulları neler" sorusu tüm bankalarda arıyor, `%0.0000` içeren alakasız yanıt dönüyordu. Anafora, önceki cevabın adını verdiği kuruma işaret eder | `previous_focus()` toplama kazananını (`winner_campaign_id`), tek sonucu veya sonuçların ortak bankasını okur. **Belirsizse `None`** — yanlış kuruma bağlamak hiç bağlamamaktan kötüdür. Çipte `evidence="önceki cevap"` görünür |
| Bağlam "son turdan" devralınıyordu | Kullanıcı sohbet geçmişinden eski bir tura dönüp soru sorduğunda yanlış bağlam taşınıyordu | Göç `0015` ile `completion_id`; istemci takip sorusunu hangi cevaba bağladığını bildirir. ⚠️ Tanınmayan kimlik **sessizce son tura düşmez**, devir hiç yapılmaz |
| `model_id` arayüzden **hiç gönderilmiyordu** | Model seçici ekranda duruyor, durumu tutuluyor, ama istek gövdesine konmuyordu. Sunucu tarafı doğruydu — seçim tamamen **ölü bir kontroldü** ve hata da vermiyordu | `ChatPage` istek gövdesine `model_id` ve `parent_completion_id` ekliyor; oturum sınırlarında zincir sıfırlanıyor |
| Ürün yedeği rastlantısal **tek terim** eşleşmesinde tetikleniyordu | "bana bir şiir yaz" sorgusu `returned=0` olduğu hâlde 8 ürün döndürüp Hayat Finans tanıtım metni üretiyordu: `bana` simgesi **"Bana Bunu Al"** ürünüyle eşleşiyor. Puan eşiği ayırt etmiyor — çöp 6.98 > gerçek 7.73 | **Kapsama** kapısı: eşleşen anlamlı terimler, sorgunun anlamlı terimlerinin en az yarısını kapsamalı. Tek simgeli meşru arama (`Togg`) engellenmez. `bana` STOPWORDS'e **eklenmedi** — gerçek bir ürün adı |
| Çip ipucu devralınan bağlamı "sorguda geçen ifade" gibi gösteriyordu | *"Sorgudaki 'önceki cevap' ifadesinden çıkarıldı"* yazıyordu; devralınan süzgeç sorguda geçen bir ifade değil. Kullanıcı yanlış devralmayı fark edemez | İpucu kaynağa göre ayrışıyor: "Bu soruda belirtilmedi; önceki yanıtın işaret ettiği kurumdan alındı" |
| `oran_gecerli()` koruması **etkisizdi** | `parse_tr_rate` içinde `return oran if oran_gecerli(oran) else oran` yazılmış — iki dalda da aynı değer dönüyor, geçerlilik denetimi hiç çalışmıyordu. Bu ayrıştırıcı 6 banka API bağdaştırıcısında kullanılıyor | Ölü koşul kaldırıldı. ⚠️ `else None` yazmak **doğru değil**: aynı ayrıştırıcı aylık kâr payı oranı için de yıllık maliyet oranı için de kullanılıyor; `oran_gecerli` aylık aralığı (%0,05–%15) doğrular, yıllık maliyet meşru olarak %30–80 bandındadır ve `None`'a düşerdi. Geçerlilik, büyüklüğün ne olduğunu bilen yerde (runner) denetlenir |
| `float(None)` sessizce varsayılana düşüyordu | `strategies.py`: `int(float(api.get("amount")))` — `amount` yoksa `TypeError`, ve onu saran `except Exception` hatayı yutup tutarı sessizce 200.000₺ yapıyordu | `None` açıkça denetleniyor; varsayılana düşme hâlâ var ama artık gerekçesi belli |

#### Hesaplayıcı oran verisi — kök neden ve karantina

Sohbet yanıtlarında `%5000` ve `%64,49 kâr payı` gibi değerler görüldü.
Bu, projenin temel güvencesini tersine çeviriyordu: **model sayı üretmez,
sayılar veritabanından gelir** — bozuk veri, yetkili görünen yanlış yanıt olur.

Kaynak bazında ölçüm, tek bir kaynağın ayrıştığını gösterdi:

| kaynak | n | ortalama | max |
|---|---|---|---|
| `html_table` | 291 | %3,97 | %6,1 |
| `calculator_api` | 28 | %3,90 | %5,7 |
| `seed_manual` | 22 | %3,77 | %4,79 |
| `payment_plan_derived` | 18 | %3,73 | %4,17 |
| **`calculator_playwright`** | **78** | **%136,03** | **%5000** |

**Kök neden 1 — bayat okuma.** Bakılacak sayı `toplam ÷ taksit`: ödeme planının
*ima ettiği* vade. Bu, sorulan vadeyle örtüşmüyordu:

| banka | probe vadesi | taksit | toplam | ima edilen | yazılan oran |
|---|---|---|---|---|---|
| albaraka | 36 | 10.283,74 | 236.526,84 | **23** | %64,49 |
| albaraka | 48 | 10.283,74 | 236.526,84 | **23** | %64,49 |
| dunya_katilim | 12 | 21.816,71 | 261.800,49 | 12 ✓ | %3,39 |
| dunya_katilim | 24 | 21.816,71 | 261.800,49 | **12** | %3,39 |

Aynı taksit/toplam değeri farklı vadelerde tekrar ediyor: Playwright yeni
tutar/vade gönderdikten sonra sayfa güncellenmeden okuyor, **önceki probe'un
sonucunu** alıyor.

⚠️ Makul **görünen** oranlar da yanlış. Dünya Katılım'ın `%3,39` değeri 12
aylık sonuçtan geliyor ama 24 ve 36 ayın oranı olarak yazılmış. Sayısal olarak
makul olması onu doğru yapmıyor; eşik tabanlı bir kontrol bunları asla
yakalamazdı.

**Kök neden 2 — yıllık maliyet oranı aylık alana yazılıyor.**
`derive_rate_from_payment_plan` docstring'i bunu açıkça yasaklıyor: *"Albaraka
sayfasında %82,39 yazıyor; o değer … bileşik yıllık maliyettir … ikisi farklı
büyüklüklerdir ve birbirinin yerine yazılmaz."* Veritabanında tam o değer
vardı: **%82,44**.

**İki kapı** (`probe_orani_guvenilir_mi`):

- **G1 — bayat okuma:** planın ima ettiği vade ≠ probe vadesi → yazılmaz.
- **G2 — aylık oran değil:** `%20` üstü → yazılmaz. Tavan keyfi değil: aynı
  docstring *"aylık oran hiçbir gerçek üründe %100'ü aşmaz"* diyor ve güvenilir
  altı kaynağın ölçülen tavanı `%9,0`.

Ham `calculator_probes` satırı **silinmez** — kanıt olarak kalır
(`is_binding=False`). Kapı yalnızca servis edilen `product_rates` satırını
engeller. *"Oran bilinmiyor"*, *"oran %5000"* bilgisinden iyidir.

**Karantina uygulandı** (`scripts/karantina_probe_oranlari.py`, varsayılan kip
rapordur):

| | önce | sonra |
|---|---|---|
| `calculator_playwright` satır | 78 | 66 |
| ortalama | **%136,03** | **%3,44** |
| max | **%5000** | **%4,99** |

Kaynak artık diğer altısıyla aynı hizada; hiçbir `financing_rate` `%20`'yi
aşmıyor. Kapı hassas, kör değil: **94 meşru satır korundu, 12'si reddedildi**
(9 bayat okuma, 3 imkânsız değer). Kalan `%20` üstü tek grup
`participation_yield` (79 satır, max %42,79) — **onlar yıllık katılma hesabı
getirileri ve doğru**; kapı finansman oranına özgüdür.

**Karantina veri boşluğu yaratmadı**, doğru kaynağın geçmesini sağladı:

| soru | önce | sonra |
|---|---|---|
| Vakıf Katılım konut finansmanı oranı | %5000 | **%3,4700** |
| Türkiye Finans konut finansmanı koşulları | %5000 | **%4,05** |

⚠️ Kapı **semptomu** durduruyor, yarış koşulunu değil. Kalıcı çözüm
`app/scrapers/calculator_probes/` içinde: Playwright tutar/vade gönderdikten
sonra sonucun **değişmesini** beklemeli. O bekleme eklenmeden yeniden kazıma,
bu 12 satırı geri getirmez.

#### Sprint 5'te eklenen API uçları

| Uç | Ne döndürür |
|---|---|
| `POST /api/v1/chat` | Yanıt · kanıt · süzgeç dökümü · erişim şeffaflığı · gevşetme önerileri |
| `POST /api/v1/chat/sessions` | Yeni oturum anahtarı |
| `GET /api/v1/chat/sessions` | Sohbet geçmişi listesi (boş oturumlar gizli) |
| `GET /api/v1/chat/sessions/{key}` | Bir oturumun tüm mesajları |
| `DELETE /api/v1/chat/sessions/{key}` | Oturumu sonlandırır |
| `GET /api/v1/chat/models` | Seçilebilir modeller · canlı keşif · sağlık durumu |

`POST /api/v1/chat` isteğinde `model_id` (istek başına model) ve
`parent_completion_id` (takip sorusunun bağlandığı cevap) alanları
opsiyoneldir; yanıt `completion_id` ve — devir gerçekten olduysa —
`parent_completion_id` döndürür. ⚠️ Devir olmadığı hâlde bunu bildirmek
arayüzde "önceki sorudan devralındı" göstermek olur ve yanlış bilgidir.

⚠️ **Boş sonuç HTTP 200 döndürür.** 4xx döndürmek arayüzde `ErrorState`
tetikler ve "veri yok" ile "istek başarısız" karışır. Kanıt bulunamadığında
`results` boş, `relaxation_hints` dolu döner.

Tam sözleşme: <http://localhost:8000/docs>

#### Kalite kapıları

| Kapı | Durum |
|---|---|
| `pytest` | **1.757 geçiyor** · 10 kırık · 1 atlanan |
| `pytest` (integration hariç) | **1.562 geçiyor**, kırık yok |
| `ruff check` (`app` + `tests`) | ✅ temiz |
| `ruff format --check` | ✅ 275 dosya biçimli |
| `mypy app` | ✅ temiz (177 dosya) |
| `tsc -b --noEmit` | ✅ temiz |
| Üretim derlemesi | ✅ başarılı |

Tek komut: `python dev.py lint` (ruff · format · mypy · tsc, **exit 0**) ve
`python dev.py test`.

Lint kapısı bu sprintte kapatıldı: 72 ruff bulgusu, 29 biçimlendirilmemiş dosya
ve 10 mypy hatası giderildi. İki tanesi biçim değil, **davranıştı** —
aşağıdaki tabloda.

⚠️ `tests/integration/test_scraper_*` altında **10 test kırık** durumda.
Bu testler **ağa çıkmaz** — `httpx.MockTransport` ve kayıtlı HTML fixture'ları
kullanırlar (soket kapatılarak doğrulandı), dolayısıyla banka sayfalarının
değişmesi onları kıramaz. Ölçülen iki gerçek neden:

| neden | örnek |
|---|---|
| **Saat bombası fixture** — kayıtlı HTML'deki tarihler geçmişte kaldı | `test_scraper_ziraat`: fixture kampanyası `bitis=2026-08-07`, bugün 2026-08-25 → `bitis_gecmis` ile atlanıyor, test 3 kayıt beklerken 2 buluyor. `bugun` değeri `app/scrapers/base.py:525`'te satır içinde `utc_now()`'dan hesaplanıyor; teste enjekte edilemiyor |
| **Kazıyıcı davranışı değişti, test beklentisi güncellenmedi** | `test_scraper_kuveyt_turk`: keşif artık `/kampanyalar/kampanya-arsivi` yerine bir sorgu uç noktası (`ck0d84?…&p1=1176`) çağırıyor; test arşiv adresini bekliyor (`assert 8 == 9`) |

⚠️ İkincisini düzeltmek "test mi yanlış, kazıyıcı mı" kararını gerektirir:
`ck0d84` uç noktası bankanın yeni meşru keşif yolu ise test güncellenir; değilse
o banka için **kampanya keşfi eksik kalıyor** demektir. Alan bilgisi olmadan
tahminle düzeltilmedi. Sohbet, erişim ve çıkarım katmanlarından bağımsızdır.
Gizlenmiyor — gerçek durum budur.

#### Devam eden işler — tamamlanmadan bu bölüme sayı yazılmaz

| Alan | Durum | Not |
|---|---|---|
| Prompt ince ayarı ve tam çıkarım çalıştırması | ⏳ | 482 kampanya · EVREN ile ~20 dk |
| `llm_only` / `hybrid` ablasyon ölçümü | ⏳ | Tam çalıştırmadan sonra |
| Sorgu kümesinde erişim isabeti (recall@k) | ⏳ | Etiketli sıralama kümesi gerekiyor |
| Kapalı ağ (airgap) doğrulaması | ⏳ | Ayrı video **bilinçli feragat** — kanıt sunum + doküman + grep |

---

</details>

---

## Ekran görüntüleri

Görseller `teslim/sunum/gorsel/` altında; sunum üreticisi (
`teslim/sunum/uretici/`) aynı dosyaları slaytlara gömüyor, yani README ile
sunum **aynı kaynaktan** besleniyor.

### Genel bakış — KPI şeridi

![Genel bakış · KPI](teslim/sunum/gorsel/01_genel_bakis_kpi.png)

Üstteki şerit veriyi tek ekranda özetliyor: banka, kampanya, ürün ve oran
sayıları. **Sayılar arayüzde sabit yazılmıyor**, `/api/v1/stats` ucundan
geliyor; veri değiştiğinde ekran da değişir.

### Genel bakış — durum dağılımı ve grafik

![Genel bakış · durum](teslim/sunum/gorsel/02_genel_bakis_durum.png)

![Genel bakış · grafik](teslim/sunum/gorsel/03_genel_bakis_grafik.png)

⚠️ `unknown` durumu `expired`den **ayrı** gösteriliyor. Tarihi bulunmayan bir
kampanyayı "süresi dolmuş" saymak yanlış bilgi olurdu; Türkiye Finans'ın
kampanyalarında yapısal tarih alanı hiç yok.

### Kampanya kataloğu — kanıt çekmecesi

![Kampanya kataloğu](teslim/sunum/gorsel/04_kampanya_katalogu.png)

Her çıkarılmış alanın yanında **kaynak cümlesi** duruyor. Değerin nereden
geldiği tek tıkla görülebiliyor; açıklanabilirlik iddiasının arayüz tarafı
budur.

### Finansman karşılaştırma

![Finansmanlar](teslim/sunum/gorsel/05_finansmanlar.png)

⚠️ **BAĞLAYICI OLMAYAN ORAN LİSTEDE KALIR AMA KAZANMAZ.** Hesaplayıcıdan
türetilmiş ya da örnek nitelikli bir oran, banka tarafından yayımlanmış
bağlayıcı bir oranla aynı sırada yarışmaz; kaynak ve bağlayıcılık kolonda
görünür.

### Katılma hesabı

![Katılma hesabı](teslim/sunum/gorsel/06_katilim_hesabi.png)

⚠️ Yön burada **ters**: katılma hesabında müşteri lehine olan YÜKSEK paydır,
finansmanda DÜŞÜK kâr payı. İki tabloyu aynı sıralama kuralıyla göstermek
yanıtı tam ters çevirirdi.

### KATİBİM — sohbet ve kanıt paneli

![KATİBİM AI](teslim/sunum/gorsel/07_katibim_ai.png)

Yanıtın yanında hangi süzgeçlerin anlaşıldığı, hangi kanalların çalıştığı ve
kaç kaydın hangi süzgece takıldığı yazıyor. **Doğrulanamayan sayı
işaretlenir**; kapsam dışı soru modele hiç gitmez.

### Mimari

![Mimari](teslim/sunum/gorsel/08_mimari.png)

---

## Şartname madde 6 — dokümantasyon haritası

Şartname madde 6 belge gereksinimlerinin nerede karşılandığı:

| Gereksinim | Belge |
|---|---|
| Sistem mimarisi ve bileşenler | bu README · [`docs/juri_raporu.html`](docs/juri_raporu.html) |
| Kurum sistemlerine entegrasyon | [`docs/kurumsal_entegrasyon.md`](docs/kurumsal_entegrasyon.md) · [`docs/on_prem_entegrasyon.md`](docs/on_prem_entegrasyon.md) |
| Metin girdisiyle çalışan uç | `POST /api/v1/extract` · [`docs/sartname_senaryolari.md`](docs/sartname_senaryolari.md) |
| Model başarı ölçümü | [`docs/ablation.md`](docs/ablation.md) · [`docs/kapsama_ve_geri_cagirma.md`](docs/kapsama_ve_geri_cagirma.md) |
| Farklı ifade biçimlerini yorumlama | [`docs/paraf_degismezlik.md`](docs/paraf_degismezlik.md) |
| Erişim kalitesi | [`docs/erisim_recall.md`](docs/erisim_recall.md) |
| Bilgi yokken bilgi üretmeme | [`docs/sartname_senaryolari.md`](docs/sartname_senaryolari.md) · [`docs/kapsama_ve_geri_cagirma.md`](docs/kapsama_ve_geri_cagirma.md) |
| Lisans uyumu | [`LICENSES.md`](LICENSES.md) |
| Veri sözlüğü ve bilinen sorunlar | [`data/README.md`](data/README.md) · [`data/robots_report.md`](data/robots_report.md) |
| Sunum ve konuşma metni | `teslim/sunum/` |

### Ölçüm raporları — hepsi tek komutla üretilir

| Komut | Rapor | Ne ölçer |
|---|---|---|
| `python dev.py degerlendir` | `docs/evaluation.md` | tek kipte alan çıkarımı F1 |
| `python dev.py ablation` | `docs/ablation.md` | üç kipin karşılaştırması |
| `python dev.py kapsama` | `docs/kapsama_ve_geri_cagirma.md` | **doğru paydalı** geri çağırma |
| `python dev.py paraf-degismezlik` | `docs/paraf_degismezlik.md` | aynı olgunun N yazımı |
| `python dev.py sartname-senaryo` | `docs/sartname_senaryolari.md` | şartnamenin kendi örneği |
| `python dev.py erisim-recall` | `docs/erisim_recall.md` | recall@k · kanal ablasyonu |
| `python dev.py sohbet-degerlendir` | `docs/sprint5_evaluation.md` | sohbet uçtan uca |

⚠️ **HİÇBİRİ ELLE YAZILMIYOR.** Her rapor başında hangi komutun ürettiği
yazılı; rakamlar veriyle birlikte değişir. Elle yazılmış bir ölçüm, bir
sonraki koşuda sessizce yanlış olur.

---

## Lisans

Bu proje [Apache License 2.0](LICENSE) ile lisanslanmıştır.

Bağımlılıkların lisans matrisi: [`LICENSES.md`](LICENSES.md). Projede copyleft
(GPL/AGPL) lisanslı bileşen kullanılmamıştır.

Banka adları ve markaları ilgili kurumlara aittir.
