# KATİP — Proje Dokümantasyonu

**Katılım Bankacılığı Kampanya Analiz Platformu**
TEKNOFEST 2026 · Yapay Zekâ Dil Ajanları · 2. Senaryo · Takım **BZBTech**

Bu belge şartname madde 6'nın istediği başlıkları tek dosyada toplar: sistem
mimarisi, veri akışı, NLP yaklaşımı, veri seti, ön işleme, model/kural yapısı,
karşılaştırma mantığı, çalıştırma talimatı, karşılaşılan problemler, örnek
çıktılar ve performans değerlendirmesi.

Kurulum ve hızlı başlangıç için [`README.md`](README.md).

---

## İçindekiler

1. [Problem ve çözüm](#1-problem-ve-çözüm)
2. [Sistem mimarisi](#2-sistem-mimarisi)
3. [Veri akışı](#3-veri-akışı)
4. [Veri seti](#4-veri-seti)
5. [Ön işleme](#5-ön-i̇şleme)
6. [Bilgi çıkarımı — üç katman](#6-bilgi-çıkarımı--üç-katman)
7. [Halüsinasyon savunması](#7-halüsinasyon-savunması)
8. [Taksonomi ve sınıflandırma](#8-taksonomi-ve-sınıflandırma)
9. [Karşılaştırma mantığı](#9-karşılaştırma-mantığı)
10. [Sohbet ve erişim (RAG)](#10-sohbet-ve-erişim-rag)
11. [On-premise ve kapalı ağ](#11-on-premise-ve-kapalı-ağ)
12. [Performans değerlendirmesi](#12-performans-değerlendirmesi)
13. [Örnek çıktılar](#13-örnek-çıktılar)
14. [Karşılaşılan problemler ve çözümleri](#14-karşılaşılan-problemler-ve-çözümleri)
15. [Bilinçli kırpmalar ve açık işler](#15-bilinçli-kırpmalar-ve-açık-i̇şler)
16. [Lisans ve etik](#16-lisans-ve-etik)

---

## 1. Problem ve çözüm

Katılım bankaları kampanya ve ürün bilgilerini web sitelerinde **serbest
metin** olarak, kurumdan kuruma farklı terminoloji ve biçimlerle yayımlıyor.
Analizde ölçülen örnekler:

| Bulgu | Ölçüm |
|---|---|
| Tarih yapısal bir alanda durmuyor | En az **7 farklı biçim**: `01.01.2026 - 31.12.2026`, `1-31 Ağustos 2026`, `Son Gün 31.12.2026`… Bir bankada hiçbir kampanyada tarih yok |
| Sayı biçimi Türkçe | `5.000` beş bin, `5,000` beş — İngilizce konvansiyonun tersi |
| Görünmez karakterler | Bir bankanın oran tablosu başlıklarında zero-width space; temizlenmezse kolon eşleştirmesi **sessizce** başarısız |
| Biten kampanya siteden kalkıyor | Sert HTTP 404, arşiv yok. Ham veri saklanmazsa geri getirilemez |
| Terminoloji farkı | Faiz ≠ kâr payı, kredi ≠ finansman, mevduat ≠ katılım fonu |

**Çözüm:** bu dağınık veriyi tek bir düzenli modele indirgeyen, her değerin
**kaynağını** ve **çıkarım güvenilirliğini** kayıt altına alan; dashboard ve
kanıtlı sohbet üzerinden sunan uçtan uca platform.

### Tasarımın çekirdek kuralı

> **Kullanıcıya gösterilen her rakam bir veritabanı satırından gelir.**
> Model yalnızca yönlendirme yapar ve cümle kurar.

Bu kural mimarinin her katmanında zorlanır; §7 ve §10 nasıl olduğunu anlatır.

---

## 2. Sistem mimarisi

Tek süreç, tek port. Backend derlenmiş arayüzü kendisi servis eder; kurum içi
kurulumda ayrı bir Node çalışma zamanı gerekmez.

```
                          ┌──────────────────────────────┐
   Banka web siteleri ───▶│  scrapers/                   │  robots.txt · soft-404
   (10 katılım bankası)   │  fetcher · registry · robots │  içerik adresli arşiv
                          └──────────────┬───────────────┘
                                         ▼
                          ┌──────────────────────────────┐
                          │  processing/                 │  temizleme · boilerplate
                          │  cleaner · dates · rate_tables│ tarih · oran tabloları
                          └──────────────┬───────────────┘
                                         ▼
                          ┌──────────────────────────────┐
                          │  ai/extraction/              │  tablo → kural → LLM
                          │  ai/validation/              │  6 katmanlı guard
                          └──────────────┬───────────────┘
                                         ▼
   ┌─────────────┐        ┌──────────────────────────────┐
   │  SQLite /   │◀──────▶│  db/ · services/             │  campaign_metrics
   │  PostgreSQL │        │  comparison · simulator      │  product_rates
   └─────────────┘        └──────────────┬───────────────┘
                                         ▼
                          ┌──────────────────────────────┐
                          │  retrieval/                  │  BM25 + gömme + RRF
                          │  corpus · query · aggregate  │  sert süzgeç · SQL
                          └──────────────┬───────────────┘
                                         ▼
                          ┌──────────────────────────────┐
                          │  api/v1/  (33 uç)            │  FastAPI
                          │  + frontend/dist  (tek port) │  React 18 + TS
                          └──────────────────────────────┘
```

### Katmanlar

| Katman | Sorumluluk | Modül |
|---|---|---|
| Kazıma | 10 banka scraper'ı, robots denetimi, soft-404, ham arşiv | `app/scrapers/` |
| İşleme | HTML temizleme, boilerplate, tarih çözümü, oran tabloları | `app/processing/` |
| Normalizasyon | Türkçe tarih / tutar / oran / vade | `app/core/normalization/` |
| Çıkarım | Tablo, kural ve LLM katmanları | `app/ai/extraction/` |
| Doğrulama | Altı katmanlı halüsinasyon guard'ı | `app/ai/validation/` |
| Erişim | BM25, anlamsal arama, RRF, toplama | `app/retrieval/` |
| Servis | Karşılaştırma, simülatör, BDDK, sohbet | `app/services/` |
| API | 33 REST ucu, OpenAPI | `app/api/v1/` |
| Arayüz | 11 sayfa, kanıt çekmecesi | `frontend/src/` |

**184 Python modülü.** Bağımlılık yüzeyi bilinçli olarak dar: **12 çalışma
zamanı paketi**. Docker zorunlu değil, Redis yok, mesaj kuyruğu yok.

### Teknoloji yığını

**Backend** Python 3.11+ · FastAPI · SQLAlchemy 2.0 · Alembic · Pydantic v2 ·
httpx · BeautifulSoup4 + lxml · protego · tenacity · structlog

**Frontend** React 18 + TypeScript (strict) · Vite · Tailwind · Radix ·
TanStack Query v5

**Veritabanı** SQLite (geliştirme) → PostgreSQL için yalnızca `DATABASE_URL`
değişir. ⚠️ SQLite'a özgü FTS5 bu yüzden **kullanılmadı**; saf Python BM25 bu
boyutta milisaniyenin altında çalışıyor.

**Para ve oran alanları `Decimal`.** `float` yasak: ikili kayan nokta finansal
değerlerde yuvarlama hatası üretir.

---

## 3. Veri akışı

Sekiz adımlı boru hattı. **Sıra bağımlılık zinciridir, tercih değil** — her
adım bir öncekinin çıktısını okur; bozulursa hata *vermez*, sessizce eski
veriyle çalışır.

| # | Adım | Komut | Ağa çıkar |
|---|---|---|---|
| 1 | Kampanya sayfaları | `dev.py scrape` | ✓ |
| 2 | Ürün / oran / limit sayfaları | `dev.py urun-kazi` | ✓ |
| 3 | Temiz metni arşivden tazele | `dev.py yeniden-isle` | — |
| 4 | Dört eksende sınıflandır | `dev.py siniflandir` | — |
| 5 | Alan çıkarımı | `dev.py cikarim` | LLM katmanı için ✓ |
| 6 | Aranabilir varlık kartları | `dev.py kart-uret` | — |
| 7 | Gömme vektörleri | `dev.py gomme-uret` | ✓ |
| 8 | Gold set'e karşı ölçüm | `dev.py degerlendir` | — |

Tamamı tek komutla: `python dev.py boru-hatti` · yalnızca yeniden işleme:
`--agsiz`.

⚠️ **Ayrıştırıcı değiştiyse ağa çıkmak gerekmez.** Ham HTML arşivi hiç
silinmediği için tüm veri bankalara yeni istek atmadan yeniden üretilir.
Bankaya istek yalnızca sayfaların *kendisi* değiştiyse gerekir.

---

## 4. Veri seti

### Kapsam

BDDK'nın katılım bankacılığı listesindeki **10 kuruluşun tamamı**.
İktisat Katılım, ticari faaliyete geçmediği için kapsam dışıdır ve bu karar
`app/db/seed.py` içinde gerekçesiyle yazılıdır.

| Tablo | Kayıt | Not |
|---|---|---|
| `banks` | 10 | 9'unda kampanya verisi var |
| `campaigns` | 482 | tümünde çıkarım yapıldı |
| `campaign_extractions` | 5.794 | kanıt metni ve karakter aralığıyla |
| `campaign_metrics` | 482 | yalnızca guard'ı geçen değerler |
| `campaign_categories` | 2.860 | 4 dik eksen |
| `products` | 300 | limit kaynağı etiketli |
| `product_rates` | 1.853 | bağlayıcılık (`is_binding`) ve kaynak türü kayıtlı |
| `product_limits` | 113 | tutar / vade / LTV matrisi |
| `entity_cards` | 2.919 | aranabilir varlık kartı |
| `embeddings` | 2.880 | `bge-m3-embed`, 1024 boyut |
| `gold_annotations` | 3.174 | elle etiketlenmiş cevap anahtarı |
| `glossary` | 33 | katılım bankacılığı terminolojisi |
| `source_documents` | 8.759 | ham HTML arşiv indeksi |

Banka bazında kampanya: Kuveyt Türk 101 · Ziraat 95 · Emlak 65 · Albaraka 63 ·
T.O.M. 52 · Dünya 44 · Vakıf 37 · Türkiye Finans 15 · Hayat Finans 10 ·
**Adil Katılım 0**.

> **Adil Katılım'ın sıfırı eksiklik değil bulgudur.** Banka lisanslı ama
> ticari faaliyete geçmemiş; kamuya açık kampanya ya da ürün sayfası yok.
> 9 aday adres denetlendi ve belgelendi. Site var olmayan her adres için ana
> sayfayı HTTP 200 ile döndürdüğünden, içerik özeti karşılaştırması
> yapılmasaydı **9 uydurma kayıt** oluşacaktı.

### Ham arşiv

Ham HTML **asla silinmez** ve içerik adreslidir (`{url_özeti}_{içerik_özeti}.html`),
böylece aynı adresin farklı zamanlardaki hâlleri birbirini ezmez. Biten
kampanyalar bankaların sitesinden kalktığı için arşiv kanıt zinciridir.

⚠️ Arşiv boyutu **1,7 GB** olduğu için depoya girmez. Veritabanı ise Git LFS
ile paylaşılır: depoyu klonlayan kişi kazıma yapmadan sistemi çalıştırabilir.

### Veri kaynağı hiyerarşisi

`html_table` (yapısal oran tablosu, güven 1.00) > `html_attr` (hesaplayıcı form
envanteri) > `payment_plan_derived` (ödeme planından geri hesap, 0.95) >
`text` (serbest metinden çıkarım, 0.75).

⚠️ **Hesaplayıcılar sorgulanmaz.** Form nitelikleri bankanın yayımladığı
yapısal limittir ve tek istek atmadan okunur; bu yüzden `is_binding=True`
kalır. Sorgulama yapılan satırlar `is_binding=False` ile işaretlenir ve
karşılaştırmayı **kazanamaz**.

---

## 5. Ön işleme

Aşağıdaki kuralların hepsi kurgusal testleri geçtiği hâlde gerçek banka
sayfaları çekildiğinde ortaya çıkan hatalardan doğdu. Ortak özellikleri:
**hata fırlatmadan sessizce yanlış veri üretmeleri.** Her biri için regresyon
testi var.

| Kural | Neden | Ölçüm |
|---|---|---|
| `<nav>`/`<header>`/`<footer>` koşulsuz silinmez | Bozuk HTML kampanya metnini bu etiketlere yerleştirebiliyor | Emlak: koşulsuz silme 6.308 karakteri 771'e düşürüyor, tarih hiç bulunamıyor |
| `<form>` silinmez | ASP.NET WebForms içeriğin tamamını tek forma sarar | Metin taşımayan kontroller (`input`, `button`) kaldırılır |
| Ana kapsayıcı "en çok metin taşıyan" | Emlak'ta `<main>` yalnızca mobil afişi içeriyor | Asıl metin dışarıda kalıyordu |
| Başlık zinciri `<h1>`→`<h2>`→`og:title`→`<title>` | Emlak'ta `<h1>` JS şablonu, `<title>` tüm kampanyalarda aynı | Yalnızca ikisi kullanılsa 65 kampanya aynı başlıkla kaydedilirdi |
| `normalize_text()` zorunlu | Türkiye Finans başlıklarında kelime içi zero-width space | Kolon eşleştirmesi sessizce boş dönüyordu |
| Ham HTML bayt kipinde yazılır | Windows `\r\n` → `\r\r\n` yapıyor, `sha256` tutmuyor | Arşiv doğrulaması kırılıyordu |
| `www.` yok sayılır | Hayat Finans yönlendiriyor, sitemap ön eksiz | Keşif **sıfır** sonuç veriyordu |

### Türkçe normalizasyon

`app/core/normalization/` dört alanı çözer:

- **Tarih** — 7 biçim, `date_precision` ile birlikte (`exact` / `partial` /
  `inferred` / `unknown`). ⚠️ `exact` kanıt metni olmadan **geçersizdir**;
  veritabanı düzeyinde CHECK ile zorlanır.
- **Tutar** — Türkçe binlik ayracı, `TL` / `₺` / `bin` / `milyon`.
  ⚠️ Para birimi işareti **zorunlu**: "36 ay" ve "%80" tutar sayılıyordu.
- **Oran** — `%2,05` · `% 2.05` · `2.05 %` · `yüzde 2,05` aynı değer
  (şartname §5.6).
- **Vade** — `120 ay` · `120 aya kadar` · `120 aya varan` · `10 yıl`.
  ⚠️ "4 aya varan **taksit**" taksit sayısıdır, vade değildir.

---

## 6. Bilgi çıkarımı — üç katman

Şartname §5.3'ün istediği **22 alan** üç katmandan çıkarılır. Öncelik sırası
`METHOD_PRIORITY` ile sabittir: çakışmada güçlü kaynak kazanır.

| Katman | Yöntem | Güven | Ne zaman |
|---|---|---|---|
| `table` | Yapısal HTML tablosu | 1.00 | Banka oranı tabloda yayımlıyorsa |
| `rule` | Regex kalıpları + normalizasyon | 0.90 | Serbest metinde kalıp varsa |
| `llm` | EVREN / yerel model, JSON şema | 0.70 | Kural katmanının bulamadığı alanlar |

### Çıkarılan alanlar

`profit_rate_pct` · `profit_share_rate_pct` · `allocation_fee_pct` ·
`file_fee_try` · `has_no_fee` · `appraisal_fee_covered` · `term_months_min/max` ·
`installment_count` · `financing_amount_min/max` · `min_spend_try` ·
`max_spend_try` · `reward_amount_try` · `reward_type` · `cashback_pct` ·
`discount_pct` · `loyalty_points` · `max_total_benefit_try` · `tier_structure` ·
`currency` · `start_date` · `end_date` · `sector` · `product_type` ·
`target_customer`

### Üretim kipi: `rule_only`

Ablasyon ölçümü LLM katmanının alan çıkarımına **net katkı sağlamadığını**
gösterdi (§12). Proje kendi kuralını kendine uyguladı:

> *"Hibrit, `rule_only`'den kötüyse LLM katmanı açılmaz."*

Aynı kural daha önce yeniden sıralama (`rerank`) için de uygulanmıştı. LLM
katmanı kaldırılmadı; `--tumu` ile çalıştırılabilir, ama üretim verisi
`rule_only` ile üretilir.

---

## 7. Halüsinasyon savunması

Altı katmanlı guard. ⚠️ **Katman 3, 4 ve 5 yalnızca LLM çıktısına uygulanır:**
kural ve tablo katmanı kanıtını kaynaktan *dilimleyerek* üretir; onları
kaynakta aramak tanımı gereği doğru olanı doğrulamaktır.

| # | Katman | Ne yapar |
|---|---|---|
| 1 | Grounding | Modele her zaman kaynak metin verilir |
| 2 | Kanıt zorunluluğu | `evidence` boşsa alan reddedilir |
| 3 | Alt dize doğrulama | Kanıt kaynakta **fiilen** geçiyor mu? |
| 4 | Sayısal doğrulama | Üretilen rakam varyantlarıyla kaynakta var mı? |
| 5 | Taksit/vade ayrımı | Kanıt "taksit" deyip "ay" demiyorsa vade alanı reddedilir |
| 6 | Terminoloji | Ürettiğimiz metinde konvansiyonel terim var mı? |

⚠️ **Reddedilen kayıt silinmez.** `rejected_reason` ile saklanır: halüsinasyon
oranı ancak reddedilenler kayıtlıysa raporlanabilir; silinen bir hata
ölçülemez, ölçülemeyen bir hata düzeltilemez.

### Terminoloji guard'ı

Kodda, log mesajlarında, API alan adlarında ve arayüz metinlerinde şu kelimeler
**kullanılmaz**: faiz → kâr payı · kredi → finansman · mevduat → katılım fonu ·
vadeli mevduat → katılma hesabı. Bu bir üslup tercihi değil alan gereğidir.

**Tek istisna:** bankanın kaynak metnindeki ifade `value_raw` ve
`conditions_text` gibi ham alanlarda olduğu gibi saklanır — kaynak veri
değiştirilmez.

---

## 8. Taksonomi ve sınıflandırma

Dört **dik** eksen; bir kampanya her eksende birden fazla etiket alabilir.

| Eksen | Değer | Kaynak |
|---|---|---|
| `product_type` | 15 | Şartnamenin 8 zorunlu türü + 7 ek |
| `sector` | 22 | Ziraat'in 14 gerçek kategorisi temel alındı |
| `audience` | 14 | Şartname 5.3 "Hedef Kitle" |
| `benefit` | 11 | Fayda türü |

Kanıt önceliği: `url` (1.00) > `bank_category` (1.00) > `merchant` (0.90) >
`keyword` (0.70). İlk ikisi **çıkarım değil kaynak veridir** — banka sektörü
kendi sayfasında yazıyor.

> **Uydurma etiket yok.** Kaynak yoksa etiket yazılmaz. Sektör sinyali
> bulunmayan kampanyalara `genel` yazılır ama **0.30 güvenle**.

Sınıflandırma deterministiktir ve **ağa çıkmadan** yeniden çalıştırılabilir.
Etiketler her koşuda silinip yeniden yazılır: sözlükten çıkarılan bir kelimenin
ürettiği etiket veritabanında kalmaz.

---

## 9. Karşılaştırma mantığı

İki ayrı motor: **kampanya sıralaması** ve **ürün/oran sıralaması**.

### Zorunlu ayrımlar

⚠️ **`rate_type` zorunludur.** Finansman maliyeti ile katılma getirisi aynı
sütunda durur ama biri gider biri gelirdir; karıştıkları anda "en iyi banka"
sonucu tesadüfe döner. Yön `rate_direction` tek kaynağından okunur.

⚠️ **Ölçütün alanı boş olan ürün sıralanmaz.** `without_data` grubunda
nedeniyle döner. `NULL`'u sıfır sayıp "en düşük kâr payı" ilan etmek yanlıştır.

⚠️ **Bağlayıcı olmayan satır kazanan olamaz.** Hesaplayıcı sorgusundan gelen ya
da "bilgilendirme amaçlıdır" notu taşıyan oran listede kalır ama
karşılaştırmayı kazanamaz. Ölçüldü: bu kapı olmadan "en düşük konut finansmanı
kâr payı" sorusu, kaynakta oranı yayımlanmamış bir `%0` satırını kazanan ilan
ediyordu; doğru yanıt **Ziraat Katılım %2,89** (`html_table`).

⚠️ **Beraberlik gizlenmez.** Kazanan cümlesi aynı değeri taşıyan kayıt sayısını
söyler.

### Yedi ölçüt

`en_dusuk_kar_payi` · `en_dusuk_masraf` · `en_dusuk_toplam_maliyet` ·
`en_yuksek_getiri` · `en_yuksek_paylasim_orani` · `en_uzun_vade` ·
`en_avantajli` (ağırlıklı skor)

⚠️ Ağırlıklı skorda **bir bileşenin verisi yoksa o bileşen ağırlığıyla birlikte
paydadan da düşer.** Aksi hâlde masraf verisi olmayan ürün, masrafı sıfırmış
gibi davranıp haksız avantaj kazanır.

### Karşılaştırılabilirlik uyarıları

Sigortalı/sigortasız ya da farklı hesap kademeleri aynı listede yer alırsa
uyarı döner. Türkiye Finans aynı ürün için sigortalı ve sigortasız iki ayrı
tablo yayımlıyor; hangisinin hangisi olduğu yalnızca üstteki başlıkta yazılı.
Başlık okunmazsa bir bankanın sigortalı oranı başka bankanın sigortasız
oranıyla kıyaslanır.

### Simülatör ve BDDK

Finansman simülatörü annüite ödeme planı üretir; BSMV ve KKDF ürün türüne göre
uygulanır (konut finansmanı 6802 s.K. gereği muaf). BDDK azami finansman
oranları ve vade tavanları kanon dosyasından okunur
(`data/seed/bddk_finansman_limitleri.json`) ve arayüzde **değer bandı seçimi**
olarak sunulur — kullanıcı serbest değer yazmaz.

---

## 10. Sohbet ve erişim (RAG)

| Katman | Yöntem | Model kullanır mı |
|---|---|---|
| Sorgu anlama | Taksonomi sözlüğü + sayı/karşılaştırma kalıpları | Hayır (son çare) |
| Sözcüksel erişim | BM25, saf Python | Hayır |
| Anlamsal erişim | `bge-m3-embed` (1024 boyut) + Qdrant | Yalnızca sorgu vektörü |
| Birleştirme | Reciprocal Rank Fusion | Hayır |
| Sert süzgeç | Banka · durum · 4 eksen · sayısal eşik | Hayır |
| Toplama (en düşük / kaç tane) | **SQL** | **Hayır** |
| Cevap cümlesi | EVREN / yerel model | Evet |
| Denetim | Sayı doğrulama · terim guard'ı · yön denetimi | Hayır |

### Toplama soruları erişime hiç girmez

"En düşük kâr payı hangi bankada?" sorusunda en benzer 8 kart getirilip modele
okutulsaydı, model yalnızca o 8 kartın en küçüğünü söylerdi — 482 kampanyanın
gerçek en küçüğünü değil. Yanıt makul görünür, kaynak da gösterir, ama
yanlıştır ve yanlışlığı hiçbir yerde bildirilmez.

Hesap tüm kayıtlar üzerinde SQL ile yapılır ve yanıt üç şeyi birlikte söyler:
**beraberlik sayısı**, **hesaba giren** ve **hesaba girmeyen** kayıt sayısı.
"En düşük oran %0" ifadesi, 148 kayıt üzerinden mi 482 kayıt üzerinden mi
söylendiği bilinmeden değersizdir. `NULL` sıfır sayılmaz.

### Boş sonuç sessizce gevşetilmez

Süzgeçler kesişmiyorsa sonuç boş kalır — ama **hangi süzgecin kaldırılmasıyla
kaç sonuç çıkacağı** yanıtta döner:

```
"KT'de akaryakıt indirimi olan kampanyalar"  ->  0 sonuç
   Sektör: akaryakıt  süzgecini kaldır  ->  11 sonuç
   Fayda:  indirim    süzgecini kaldır  ->   3 sonuç
```

Sonucu kendi başına gevşetmek kullanıcının sormadığı soruyu yanıtlamak olurdu;
boş göstermek ise "banka bunu yapmıyor" izlenimi verirdi. Karar kullanıcıya
bırakılır.

### Şeffaflık

Her yanıt şunları taşır: "anladığım" süzgeç çipleri (kaldırılabilir), erişim
şeridi (kaç karttan kaçı, hangi kanal, ne elendi, kaç ms), kanıt metni,
yanıtın kaynağı (`model` · `computed` · `template` · `refusal`) ve
doğrulanamayan sayılar listesi.

Model erişilemediğinde sistem **çökmez**: `source="template"` ile sıralı
kanıtlar gösterilmeye devam eder ve nedeni `model_error` alanında yazar.

---

## 11. On-premise ve kapalı ağ

### Neden kolay

- **Tek süreç, tek port.** Backend arayüzü kendisi servis eder.
- **12 çalışma zamanı bağımlılığı.** Redis, kuyruk, ayrı arama motoru yok.
- **SQLite → PostgreSQL** için yalnızca `DATABASE_URL` değişir.
- **Qdrant zorunlu değil.** Erişilemezse arama yerel `embeddings` tablosuna
  düşer ve bunu **yanıtta bildirir**.
- **Tüm modeller açık ağırlıklı ve izin verici lisanslı** (§16).

### `AIRGAP_MODE` gerçek bir kapıdır

`AIRGAP_MODE=true` iken dış servise bağlı yapılandırma **açılışta reddedilir**:

```
AIRGAP_MODE=true LLM_PROVIDER=evren   →  ValidationError, sunucu BAŞLAMAZ
AIRGAP_MODE=true LLM_PROVIDER=local   →  açılır, kanıtlı yanıt verir
```

Denetim `app/config.py::_airgap_dis_servisi_reddeder`; altı regresyon testi
`tests/unit/test_airgap.py` içinde. Çalışma anında engellemek yetmez — yanlış
yapılandırmayla ayağa kalkan bir sistem, kapalı ağda "acaba dışarı çıktı mı"
sorusunu açık bırakır.

### Docker ile kanıt

```bash
docker build -t katip:latest .
docker run --rm -p 8000:8000 katip:latest

# Ağı fiziksel olarak kapalı konteyner:
docker compose --profile airgap up katip-airgap
```

`network_mode: none` konteynerin ağ arayüzünü tamamen kaldırır: uygulama
dışarı çıkmak istese bile çıkamaz. İddia ayar dosyasına değil çekirdeğe
dayanır.

### Ölçülen kapalı ağ davranışı

| Senaryo | Sonuç |
|---|---|
| `AIRGAP_MODE=true` + dış sağlayıcı | Sunucu açılmıyor, hangi ayarın bozuk olduğunu yazıyor |
| `AIRGAP_MODE=true` + yerel model (`qwen3:8b`) | **9 sn** (ısındıktan sonra), doğru cevap, `source=model` |
| Model hiç yoksa | `HTTP 200` · `source=template` · `is_grounded=true` — doğru kampanyayı kanıtıyla getiriyor |

⚠️ Kapalı ağda anlamsal kanal kapalıdır: kayıtlı vektörler `bge-m3-embed`
(1024 boyut), yerel `nomic-embed-text` 768 üretir. Sistem bunu **bildirir**,
sessizce başarısız olmaz. Yerel gömme üretilirse kanal açılır.

Ayrıntı: [`docs/kurumsal_entegrasyon.md`](docs/kurumsal_entegrasyon.md)

---

## 12. Performans değerlendirmesi

### Alan çıkarımı — gold set'e karşı

66 kampanya, 3.174 elle etiketlenmiş alan. Gold **kör** yazıldı: sorular
sistemin çıktısına bakılmadan etiketlendi.

| Kip | Mikro F1 | Uydurma | Doğru susma |
|---|---|---|---|
| **`rule_only`** (üretim) | **0,834** | 0,167 | 0,917 |
| `hybrid` | 0,823 | 0,205 | — |
| `llm_only` | 0,036 | 0,941 | — |

Rapor: [`docs/ablation.md`](docs/ablation.md)

### Doğru paydalı geri çağırma

⚠️ "Alan doldurma oranı" ile "kaynakta var olanı yakalama" **farklı sorulardır.**
Kart kampanyalarının çoğunda banka zaten oran yayımlamaz; onları paydaya
koymak sistemi olduğundan kötü gösterir.

| Ölçüt | Değer | Payda |
|---|---|---|
| **Geri çağırma** | **%83,1** | gold'da değeri **bulunan** 502 alan |
| Uydurma oranı | **%5,4** | üretilen 498 değer |
| Doğru susma | **%97,2** | gold'da boş olan 950 alan |

Rapor: [`docs/kapsama_ve_geri_cagirma.md`](docs/kapsama_ve_geri_cagirma.md)

### Paraf değişmezliği — şartname K4 ilk alt madde

Aynı olgu N farklı biçimde yazıldığında sistem aynı değeri çıkarıyor mu?

| | |
|---|---|
| Sınanan yazım | **87** |
| Doğru çözümlenen | **86** |
| Oran | **%98,9** |

Örnek küme: `%2,05` · `% 2.05` · `2,05%` · `yüzde 2,05` — `120 ay` ·
`120 aya varan` · `10 yıl` — `dosya masrafı alınmaz` · `masrafsız` ·
`ücret yansıtılmaz`

Rapor: [`docs/paraf_degismezlik.md`](docs/paraf_degismezlik.md)

### Şartnamenin kendi örnek senaryosu

A/B/C Bankası metinleri, üç farklı yazım biçimi:

| | |
|---|---|
| Doğru doldurma | **9 / 9** |
| Doğru susma | **7 / 7** |

Rapor: [`docs/sartname_senaryolari.md`](docs/sartname_senaryolari.md)

### Erişim isabeti

11 sorgu, 39 ilgili etiket:

| Kanal | R@5 | R@10 | MRR |
|---|---|---|---|
| Hibrit (BM25 + yoğun + RRF) | **0,780** | 0,894 | 0,826 |

⚠️ Kanal ablasyonu dürüstçe raporlandı: bu kümede sözcüksel kanal ilk isabette
(MRR 0,932), yoğun kanal derinlikte (R@10 0,939) önde. **Mimari 11 sorguyla
değiştirilmedi**; gerekçe raporda.

Rapor: [`docs/erisim_recall.md`](docs/erisim_recall.md)

### Sohbet uçtan uca

35 soruluk kör gold set:

| Metrik | Değer |
|---|---|
| Doğru niyet oranı | **0,971** |
| Halüsinasyon oranı | **0,000** |
| Doğru susma (5 vaka) | **1,000** |
| Netleştirme isabeti | **1,000** |

Rapor: [`docs/sprint5_evaluation.md`](docs/sprint5_evaluation.md)

### Kalite kapıları

| Kapı | Durum |
|---|---|
| `pytest` | **1.944 geçiyor** · kırık yok · 1 atlanan |
| Test kapsamı | **%78** |
| `ruff check` (`app` + `tests`) | temiz |
| `ruff format --check` | 296 dosya biçimli |
| `mypy app` | temiz (184 dosya) |
| `tsc -b --noEmit` | temiz |

Tek komut: `python dev.py lint` ve `python dev.py test`.

### Yanlılık denetimi

Kör ve ön-doldurmalı etiketlenmiş alt kümeler arasındaki F1 farkı **0,009**
(eşik 0,05). Etiketleme yöntemi sonucu kaydırmıyor.

---

## 13. Örnek çıktılar

### Serbest metinden çıkarım

**Girdi:**

```
Konut Finansmanında Avantajlı Kâr Payı Fırsatı!
Yeni müşterilerimize özel, 1.000.000 TL'ye varan konut finansmanında
%2,05 kâr payı oranı ile 120 aya varan vade imkânı sunuyoruz.
Kampanya 01.09.2026 - 31.12.2026 tarihleri arasında geçerlidir.
Dosya masrafı alınmaz. Emeklilere ek olarak 5.000 TL nakit iade fırsatı.
```

**Çıktı** (her alan kanıt metni ve karakter aralığıyla):

| Alan | Değer | Kanıt |
|---|---|---|
| `profit_rate_pct` | `2.05` | `%2,05 kâr payı` |
| `term_months_max` | `120` | `120 aya varan` |
| `financing_amount_max` | `1000000` | `1.000.000 TL'ye varan konut finansmanı` |
| `file_fee_try` | `0` | `Dosya masrafı alınmaz` |
| `has_no_fee` | `true` | `Dosya masrafı alınmaz` |
| `start_date` | `2026-09-01` | `01.09.2026 - 31.12.2026` |
| `end_date` | `2026-12-31` | `01.09.2026 - 31.12.2026` |
| `reward_amount_try` | `5000` | `5.000 TL nakit iade` |
| `reward_type` | `nakit_iade` | `nakit iade` |

**Etiketler:** `product_type: konut_finansmani, finansman` ·
`sector: konut_gayrimenkul` · `audience: emekli, yeni_musteri` ·
`benefit: avantajli_kar_payi, nakit_iade`

⚠️ `%2,05` Türkçe ondalık virgülüyle, `1.000.000` ve `5.000` Türkçe binlik
ayracıyla doğru okundu. *"Dosya masrafı alınmaz"* olumsuzlaması `0` olarak
çözümlendi — bu tuzağa iki yerel model de düşmüştü.

### Toplama sorusu

**Soru:** *"En düşük konut finansmanı kâr payı oranı hangi katılım bankasında?"*

**Yanıt:**

> En düşük kâr payı oranı **%2,89** ile **Ziraat Katılım**'da uygulanmaktadır.
> Bu oran Kentsel Dönüşüm Konut Edinme/Yapım Finansmanı ürünü için geçerlidir.
> Aynı değeri taşıyan **2 kayıt** daha var; **8 kayıtta** bu bilgi yok.

Kaynak: `html_table`, `is_binding=true`. Hesaplayıcı sorgusundan gelen daha
düşük satırlar listede görünür ama kazanamaz.

### Kapsam dışı soru

**Soru:** *"Yarın hava nasıl olacak?"*

**Yanıt:** *"Bu soru katılım bankacılığı kampanya ve ürün kapsamının dışında.
Kampanya, finansman, katılma hesabı veya kâr payı hakkında soru
sorabilirsiniz."* (`intent=kapsam_disi`, `source=refusal`)

---

## 14. Karşılaşılan problemler ve çözümleri

Hepsi **hata fırlatmadan yanlış sonuç üretiyordu**; her biri için regresyon
testi var.

### Veri toplama

| Bulgu | Etki | Önlem |
|---|---|---|
| Ziraat detay sayfalarında ilk `<h1>` logo metni | 209 kampanyanın 209'u "Ziraat Katılım Bankası" adıyla kaydedildi | `extract_title(ignore_headings=…)` |
| Aynı `<h1>` sorunu soft-404'ü gizliyordu | 2 "sayfa yok" yanıtı kampanya sanıldı | `is_soft_404` ham `<title>`'a da bakıyor |
| T.O.M.'da aynı kampanya iki yol önekinde | 76 kampanya 157 kayda çıkıyordu | Slug bazında tekilleştirme |
| Sayfanın tamamında çıplak sayı tutar sayılıyordu | "36 ay" ve "%80" `amount_max` yazılmıştı | Tutarda para birimi işareti zorunlu |
| Göç sırasında SQLite FK denetimi açık | Tablo yeniden kurulurken `product_rates` siliniyordu | Göç boyunca denetim kapatılıyor |

### Çıkarım ve model

| Bulgu | Etki | Önlem |
|---|---|---|
| **Qwen3 düşünme token'ları bütçeyi yiyordu** | 482 kampanyanın **%42'sinde** LLM katmanı `finish_reason=length` ile sessizce atlanıyordu. Ölçüldü: `{"a":1}` döndüren istem, düşünme açıkken 312 token, kapalıyken 6 | `chat_template_kwargs: {enable_thinking: false}` |
| `max_tokens` 22 alanlık şemaya yetmiyordu | Aynı kesilme | `EXTRACT_MAX_TOKENS = 4096` |
| LLM taksit sayısını vade alanına yazıyordu | 222 vade değerinin 173'ünün kanıtı "taksit" diyor, "ay" demiyordu | Guard katman 5 |
| OpenAI uyumlu uç düşünen modelde boş `content` döndürüyordu | HTTP 200, içerik boş, F1 sıfıra düşüyor, hata mesajı yok | Ollama `/api/chat` + `think: false`; boş yanıt artık hata fırlatıyor |
| Gömme etiketi vektörü üreten modelden bağımsızdı | `bge-m3` ile üretilen 1.519 vektör `nomic` etiketiyle kaydedilmişti; airgap'te boyut uyuşmazlığı anlamsal kanalı **sessizce** öldürürdü | Tek doğruluk kaynağı `active_embedding_model()` |

### Erişim ve sorgu

| Bulgu | Etki | Önlem |
|---|---|---|
| `" ay"` işaretçisi **"kâr p-ay-ı"** içine uyuyordu | "En düşük kâr payı" sorusu vade üzerinden yanıtlanıp "en düşük kâr payı 1" diyordu | İşaretçiler kelime sınırında aranıyor |
| Taksonomi anahtarı `altın`, `altında` sözcüğüne uyuyordu | "%2'nin **altında**" ifadesi sektör süzgeci ekliyor, 0 sonuç | Karşılaştırma işaretçileri taksonomiden **önce** maskeleniyor |
| Sert süzgeç yalnızca ilk 120 adaya uygulanıyordu | Seçici süzgeç havuzu boşaltıyordu | Süzgeç gövdenin tamamına, sıralama sonra |
| `""` her slug'ın alt dizesi | Ürün tipi boş olan her kayıt süzgeçten geçiyor, bir **ücret tablosu** uç değeri kazanıyordu | Boş tip eşleşmez; gevşek eşleşme yalnızca yedek |
| Bağlam devri süzgecin **yokluğuna** bağlıydı | "Kuveyt Türk alışveriş puanı" → "hangi bankada en uzun vade" sorusu Kuveyt Türk'e kilitleniyordu | Devir kanıta bağlı; `opens_scope()` banka devrini veto ediyor |

### Veri kalitesi

**Hesaplayıcı oran karantinası.** Sohbet yanıtlarında `%5000` ve `%64,49 kâr
payı` görüldü. Kaynak bazında ölçüm tek bir kaynağın ayrıştığını gösterdi:

| Kaynak | n | Ortalama | Max |
|---|---|---|---|
| `html_table` | 291 | %3,97 | %6,1 |
| `calculator_api` | 28 | %3,90 | %5,7 |
| **`calculator_playwright`** | **78** | **%136,03** | **%5000** |

İki kök neden: (1) Playwright yeni tutar/vade gönderdikten sonra sayfa
güncellenmeden okuyor, **önceki probe'un sonucunu** alıyor; (2) yıllık maliyet
oranı aylık alana yazılıyor. İki kapı eklendi (`probe_orani_guvenilir_mi`):
planın ima ettiği vade ≠ probe vadesi → yazılmaz; `%20` üstü → yazılmaz.

**Sonuç:** aynı kaynak ortalama **%3,44**, max **%4,99**. Kapı hassas, kör
değil: 94 meşru satır korundu, 12'si reddedildi. Ham satır silinmez
(`is_binding=False`), kanıt olarak kalır.

⚠️ *"Oran bilinmiyor"*, *"oran %5000"* bilgisinden iyidir.

### Bozuk veritabanı kurtarma

`app.db` bir kez aktarım sırasında kırpılmış geldi. `PRAGMA integrity_check`
üç ağacın dosya sonunun ötesine işaret ettiğini gösterdi. Kurtarma oranı:
`entity_cards` 1.252/1.253 · `campaign_extractions` 4.463/4.508 · diğer 16
tablo %100. Kaynak dosya değiştirilmedi, kanıt olarak korundu.

---

## 15. Bilinçli kırpmalar ve açık işler

Şartname sessiz kapsam daraltmayı yasaklıyor. Aşağıdakiler **ölçülmüş
kararlardır**:

1. **Hesaplayıcılar sorgulanmadı.** Form envanteri bankanın yayımladığı
   yapısal limittir ve tek istek atmadan okunur; bankaya ek yük binmez.
2. **Ürün varyant satırı yazılmadı.** Hesaplayıcı dropdown'ları ölçüldüğünde
   ürüne değil **siteye** ait çıktı (Ziraat'in tek seçicisi 17 finansman türünü
   birden sunuyor). Filtresiz çalıştırma 42 sahte varyant üretiyordu.
3. **2025 öncesinde bitmiş kampanyalar yazılmadı.** Eşik bitiş tarihine
   uygulanır, başlangıca değil: uzun vadeli kampanyalar yıllar önce başlayıp
   hâlâ sürüyor olabiliyor.
4. **Yeniden sıralama (`rerank`) açılmadı.** Ölçüldü, isabeti düşürdü
   (ilk sonuç 4/8 → 3/8). Yetenek `EvrenProvider.rerank()` olarak duruyor.
5. **LLM alan çıkarımı üretimde kapalı.** Ablasyon `rule_only` lehine çıktı.

### Veri bulgusu — `konut_finansmani` etiketi sıfır

482 kampanyanın hiçbiri `konut_finansmani` etiketi taşımıyor. Bu bir sözlük
hatası **değil**: kampanya gövdesinde "konut finansmanı" ifadesi **0 kez**
geçiyor. Bankalar konutu kampanya olarak duyurmuyor, ürün sayfasında oran
tablosu olarak yayımlıyor — veri `product_rates`'te **7 bankada 137 satır**
olarak duruyor ve karşılaştırma motoru bu soruyu ürün alanından yanıtlıyor.

### Açık işler

| Alan | Durum |
|---|---|
| Kapalı ağ **tam koşusu** (yerel gömmeyle anlamsal kanal) | ⏳ |
| Erişimde zayıf kalan üç sorgu (`e07`, `e03`, `e11`) | ⏳ teşhis edildi, düzeltilmedi |
| Kullanıcı testi | ⏳ |

Ayrıntı: [`docs/EKSIKLER_VE_COZUMLER.md`](docs/EKSIKLER_VE_COZUMLER.md)

---

## 16. Lisans ve etik

### Proje lisansı

**Apache License 2.0.** Copyleft (GPL/AGPL) lisanslı bileşen kullanılmamıştır:
kurum içi kurulumda türev çalışmayı aynı lisansla dağıtma zorunluluğu
kurumsal kullanımı engelleyebilirdi.

### Modeller

Üretimde kullanılan modellerin tamamı Hugging Face'te **açık ağırlıklı ve izin
verici lisanslı**; kurum içi kurulumda aynı modeller lokal çalıştırılabilir.

| Alias | Depo | Lisans | Kullanım |
|---|---|---|---|
| `llm-fast` | `Qwen/Qwen3.6-35B-A3B` | Apache-2.0 | **üretim** — MoE, 35B toplam / **3B aktif** |
| `bge-m3-embed` | `BAAI/bge-m3` | MIT | **üretim** — gömme, 1024 boyut |
| `llm-large` | `Qwen/Qwen3.5-122B-A10B` | Apache-2.0 | seçenek |
| `rerank` | `Qwen/Qwen3-Reranker-4B` | Apache-2.0 | ölçüldü, açılmadı |
| `qwen3:8b` (yerel) | Ollama | Apache-2.0 | kapalı ağ yolu |
| `nomic-embed-text` | Ollama | Apache-2.0 | kapalı ağ gömme |

Künye kodda tek kaynaktan tutulur (`app/ai/providers/evren.py::EVREN_MODEL_KUNYE`);
künyesi bilinmeyen model için lisans alanı **"doğrulanmadı"** döner.

**Yerel model seçimi beyaz listeyle süzülür.** Ollama'da kurulu olsa bile Llama
türevi ya da "Research License" taşıyan model seçenek olarak sunulmaz. Beyaz
liste kullanılır, siyah liste değil: bilinmeyen lisansı izin verici saymak,
şartname §5.10'un yasakladığı riski üretir.

⚠️ **EVREN ücretli bir bulut servisi değildir.** TEKNOFEST 2026 kapsamında
Savunma Sanayii Başkanlığı tarafından yarışmacı takımlara tahsis edilmiş,
kotasız ve ücretsiz bir çıkarım servisidir.

Bağımlılık matrisi: [`LICENSES.md`](LICENSES.md)

### Etik kazıma

- `robots.txt` kurallarına uyulur; engellenen adrese istek yapılmaz ve durum
  `source_documents.robots_allowed=false` ile belgelenir.
- Host başına **1,5 saniye** bekleme uygulanır.
- Hesaplayıcılar sorgulanmaz; bankaya ek yük binmez.
- Her yanıt ham HTML olarak arşivlenir — kanıt zinciri.
- Yalnızca **kamuya açık** sayfalar toplanır; kişisel veri işlenmez.

Banka adları ve markaları ilgili kurumlara aittir.

---

## Belge dizini

| Konu | Dosya |
|---|---|
| Kurulum ve hızlı başlangıç | [`README.md`](README.md) |
| Ablasyon (üç kip) | [`docs/ablation.md`](docs/ablation.md) |
| Kapsama ve geri çağırma | [`docs/kapsama_ve_geri_cagirma.md`](docs/kapsama_ve_geri_cagirma.md) |
| Paraf değişmezliği | [`docs/paraf_degismezlik.md`](docs/paraf_degismezlik.md) |
| Erişim isabeti | [`docs/erisim_recall.md`](docs/erisim_recall.md) |
| Şartname örnek senaryoları | [`docs/sartname_senaryolari.md`](docs/sartname_senaryolari.md) |
| Sohbet değerlendirmesi | [`docs/sprint5_evaluation.md`](docs/sprint5_evaluation.md) |
| Kurumsal entegrasyon | [`docs/kurumsal_entegrasyon.md`](docs/kurumsal_entegrasyon.md) |
| Bağımlılık lisansları | [`LICENSES.md`](LICENSES.md) |
| Açık işler | [`docs/EKSIKLER_VE_COZUMLER.md`](docs/EKSIKLER_VE_COZUMLER.md) |
