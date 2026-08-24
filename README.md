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

Yapay zekâ katmanı: yerel model entegrasyonu ve kanıta dayalı doğal dil
sorgulama.

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
| Kanıtlı Arama arayüzü | ✅ | İki bölmeli çalışma alanı |

`rule_only` kipinin gold set'e karşı ölçülmüş temel çizgisi:
**kör alt küme F1 0,785** · mikro F1 0,809 · makro F1 0,773 ·
halüsinasyon oranı 0,171 · doğru susma oranı 0,913.

### Yerel model — bulut servisi yok

Şartname dış servise bağımlılığı yasaklıyor; çıkarım ve yanıt üretimi
tamamen `localhost`ta çalışıyor.

| | |
|---|---|
| Çalışma ortamı | Ollama (MIT) |
| Üretim modeli | `qwen3:8b` — Apache-2.0 |
| Gömme modeli | `nomic-embed-text` — Apache-2.0 |
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

### Kanıta dayalı sorgulama — model sayı üretmez

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

### Sorgu kümesi — 30 soru, gerçek veride ölçüldü

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

### Sorgu katmanında yakalanan sessiz hatalar

Dördü de hata fırlatmadan yanlış sonuç üretiyordu; her biri için regresyon
testi var.

| Bulgu | Etki | Önlem |
|---|---|---|
| `term_months_max` işaretçisi `" ay"`, `normalize_text()` baştaki boşluğu siliyor | Kalan `"ay"` **"kâr p-ay-ı"** içine uyuyor; "en düşük kâr payı" sorusu vade üzerinden yanıtlanıp **"en düşük kâr payı 1"** diyordu | İşaretçiler kelime sınırında aranıyor |
| Taksonomi anahtarı `altın`, `altında` sözcüğüne uyuyor | "%2'nin **altında**" ifadesi sektör süzgeci ekliyor, 7 finansman kampanyasının tamamı eleniyor, **0 sonuç** | Karşılaştırma işaretçileri taksonomi eşleşmesinden önce maskeleniyor — bir simgenin iki rolü olamaz |
| Sert süzgeç, en ilgili 120 adaya uygulanıyordu | Seçici süzgeç havuzu boşaltıyor; "Kuveyt Türk'te market kampanyası" **0 sonuç** dönüyordu | Süzgeç gövdenin tamamına uygulanıyor, sıralama sonra yapılıyor |
| Arama gövdesi önbelleği hiç geçersizleşmiyordu | `kart-uret` sonrası arama ESKİ metinlerle çalışmaya devam ediyordu | Üç sayaçlık parmak izi denetimi |

### Boş sonuç sessizce gevşetilmez

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

### Kanıtlı Arama arayüzü

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

### Sahada düzeltilen altyapı hataları

| Bulgu | Etki | Önlem |
|---|---|---|
| Göç `0011` kısıt adını sabit yazıyordu | Ad veritabanına göre 3 ya da 5 kat önek taşıyor; **boş veritabanında `migrate` hiç tamamlanmıyordu** | Ad çalışma anında `sqlite_master`'dan okunuyor |
| `conftest.py`'de ortam bloğu `app.*` içe aktarmalarının altındaydı | `get_settings()` içe aktarma sırasında önbelleğe giriyor; `LLM_PROVIDER=mock` ataması etkisiz kalıyor ve 3 test gerçek modele çıkmaya çalışıyordu | Blok içe aktarmaların üstüne alındı |
| `frontend/package.json`'da `typecheck` betiği yoktu | `dev.py lint` onu çağırıyor; **arayüz tip denetimi hiç çalışmıyormuş** | Betik eklendi |
| `.env`'deki model adı kurulu değildi, gömme modeli bir Hugging Face adıydı | `llm-saglik` False dönüyor, gömme çağrısı 404 verirdi | İkisi de kurulu Ollama modellerine çevrildi |

### Yeni veri bulgusu — `konut_finansmani` etiketi sıfır

608 kampanyanın **hiçbiri** `konut_finansmani` etiketi taşımıyor. Şartnamenin
8 zorunlu ürün türünden tek sıfır olan bu:

| Tür | Etiket | | Tür | Etiket |
|---|---|---|---|---|
| `kart` | 451 | | `finansman` | 7 |
| `alisveris_puani` | 86 | | `yatirim_urunu` | 6 |
| `yeni_musteri` | 45 | | `tasit_finansmani` | 3 |
| `ihtiyac_finansmani` | 9 | | **`konut_finansmani`** | **0** |

İkinci bulgu: Kuveyt Türk'ün 47 kampanyasının hiçbirinde `market_gida`
etiketi yok (veri setinde toplam 44 market etiketi var).

> Bu bir erişim hatası **değil**, sınıflandırma kapsamı boşluğudur. Erişim
> katmanı doğru davranıyor; eksik olan `taxonomy.py` sözlüğü. Sözlük
> genişletilip `python dev.py siniflandir` çalıştırıldığında ağa çıkmadan
> düzelir. Sorgu kümesindeki üç `konut_finansmani` sorusu kümede **kalıyor**:
> boş-sonuç yolunu doğru sınıyorlar.

### Devam eden işler — tamamlanmadan bu bölüme sayı yazılmaz

| Alan | Durum | Not |
|---|---|---|
| Gömme vektörlerinin üretilmesi | ⏳ | `embeddings` tablosu boş; **anlamsal kanal henüz kapalı**, arama sözcüksel kanalla çalışıyor ve bu durum arayüzde bildiriliyor |
| Prompt ince ayarı ve tam çıkarım çalıştırması | ⏳ | 608 kampanya · bu donanımda ~6-8 saat |
| `llm_only` / `hybrid` ablasyon ölçümü | ⏳ | Tam çalıştırmadan sonra |
| Sorgu kümesinde erişim isabeti (recall@k) | ⏳ | |
| Kapalı ağ (airgap) doğrulaması ve videosu | ⏳ | |

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

### Yerel LLM kurulumu — opsiyonel

**Model olmadan da sistem tam çalışır.** Kural tabanlı çıkarım, taksonomi,
erişim ve toplama yanıtları modelden bağımsızdır; Kanıtlı Arama sekmesi de
sıralı kanıtları göstermeye devam eder, yalnızca özet cümle üretilmez ve bu
durum arayüzde açıkça yazar.

1. Ollama'yı kurun: <https://ollama.com/download>
2. İki modeli indirin — üretim ve gömme ayrı modellerdir:

   ```bash
   ollama pull qwen3:8b            # yanıt üretimi   · Apache-2.0 · ~5,2 GB
   ollama pull nomic-embed-text    # gömme (768 boyut) · Apache-2.0 · ~274 MB
   ```

3. `.env` dosyasında sağlayıcıyı açın:

   ```env
   LLM_PROVIDER=local
   LOCAL_LLM_BASE_URL=http://localhost:11434/v1
   LOCAL_LLM_MODEL=qwen3:8b
   EMBEDDING_MODEL=nomic-embed-text
   ```

4. Doğrulayın: `python dev.py llm-saglik`

⚠️ `LOCAL_LLM_MODEL`, `ollama list` çıktısındaki adla **birebir** aynı olmalı.
Kurulu olmayan bir ad yazıldığında `health()` sessizce `False` döner ve
çıkarım hiç çalışmaz.

> **Hiçbir bulut servisi veya ücretli API kullanılmamaktadır.** Model
> `localhost` üzerinde çalışır; veri kurumdan çıkmaz. Çalışma ortamı Ollama
> (MIT), kullanılan modellerin ikisi de Apache License 2.0'dır.

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
python dev.py llm-saglik     # yerel modele ulaşılıyor mu, model yüklü mü
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
