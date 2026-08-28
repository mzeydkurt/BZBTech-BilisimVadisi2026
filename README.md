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

---

## Lisans

[Apache License 2.0](LICENSE). Bağımlılık ve model lisans matrisi:
[`LICENSES.md`](LICENSES.md). Projede copyleft (GPL/AGPL) lisanslı bileşen
kullanılmamıştır.

Banka adları ve markaları ilgili kurumlara aittir.
