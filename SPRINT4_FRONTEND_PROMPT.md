# SPRINT 4 — FRONTEND & REKABET İSTİHBARATI ARAYÜZÜ GELİŞTİRME PROMPT'U

> **Nasıl Kullanılır:** Bu dosyayı doğrudan Claude Code / Antigravity / Cursor'a istem olarak verin:
> `@docs/SPRINT4_FRONTEND_PROMPT.md dosyasını oku ve uygula.`
>
> **Son doğrulama: 19 Ağustos 2026.** Bu belgedeki her uç nokta, alan adı ve
> örnek yanıt çalışan backend'e karşı ölçülerek yazıldı. Backend sözleşmesi
> `docs/sprint25_devir.md` §5'te dondurulmuştur.

---

## 🎯 1. PROJE VE ARAYÜZ AMACI

Bu arayüz, Türkiye'deki 10 Katılım Bankasının kamuya açık kampanya, finansman
ve ürün verilerini karşılaştırılabilir hâle getiren **TEKNOFEST 2026 Katılım
Bankacılığı Rekabet İstihbaratı Platformu**'dur.

Hedef kullanıcı tüketiciden ziyade **Banka Çalışanı ve Finans Analistidir.**
Bu nedenle tasarım parlak AI ajansı konseptleri yerine **kurumsal, şeffaf,
veri yoğun, hızlı ve şık** olmak zorundadır.

### ⚠️ Bu projenin en ayırt edici özelliği: eksik veriyi saklamamak

Backend hiçbir yerde veri uydurmaz. Oranı olmayan banka teklif üretmez,
ölçülemeyen radar ekseni `null` döner, sıralanamayan ürün ayrı grupta gelir.
**Arayüz bu dürüstlüğü görünür kılmak zorundadır.** Boş hücreyi gizleyen ya
da `0` gösteren bir tasarım, projenin en güçlü tarafını çöpe atar — ve jüri
"veriniz yok mu?" diye sorduğunda savunulacak bir şey kalmaz.

---

## 🎨 2. TASARIM VE KULLANICI DENEYİMİ İLKELERİ

### Renk Paleti & Tipografi
- **Kurumsal Tema:** Derin Zümrüt Yeşili (`#0F3D2E`), Katılım Turkuazı
  (`#1B6B4A`), Taş Grisi (`#FAFAF9` zemin), Saf Beyaz (`#FFFFFF` kartlar),
  İnce Çizgi (`#E7E5E4` 1px border).
- **Tipografi:** System / Inter font, sayısal kolonlar `tabular-nums` ve sağa
  hizalı, Türkçe sayı biçimi (`%2,05`, `500.000 ₺`).
- **Yasaklar:** ❌ Mor/indigo neon gradientler, ❌ robot/AI ikonları,
  ❌ "AI ✨" parlak rozetleri, ❌ koyu tema varsayılan, ❌ arayüz metninde emoji.

### Modern UI Bileşen Standartları
1. **Bento Grid Layout** — KPI kartları farklı boyutlarda yan yana.
2. **Slide-over Evidence Drawer** — herhangi bir sayıya tıklandığında sağdan
   kayan kanıt çekmecesi: `evidence_text`, güven skoru, kaynak URL.
3. **Multi-select Combobox / Chip Filters** — silinebilir rozetler.
4. **Inline Alert / Callout** — terminoloji uyarıları için.
5. **Range Slider with Value Badge** — simülatör ve ağırlık slider'ları.
6. **Dense Data Table** — 40-44px satır, `ellipsis` + tooltip.

---

## 🧱 3. MEVCUT KOD TABANI — SIFIRDAN BAŞLAMA

`frontend/` zaten kurulu ve **iki sayfa çalışıyor**. Yeni yapı kurma, mevcut
düzene ekle:

```
frontend/src/
├── App.tsx                 # rota tanımları burada
├── lib/
│   ├── api.ts              # ⚠️ ApiError sınıfı ve fetch sarmalayıcı BURADA
│   ├── format.ts           # Türkçe sayı/tarih biçimleyicileri
│   └── utils.ts
├── types/api.ts            # ⚠️ Backend şemalarının TS karşılıkları BURADA
├── components/
│   ├── ui/                 # shadcn ilkelleri (badge, button, card, ...)
│   ├── common/             # StatCard, EmptyState, ErrorState, LoadingState
│   ├── layout/             # AppShell, Sidebar
│   └── campaigns/          # CampaignTable, CampaignFilters, ...
├── hooks/
└── pages/
    ├── OverviewPage.tsx    # var
    └── CampaignsPage.tsx   # var
```

### Uyulacak mevcut sözleşmeler

- **`ApiError`** — `lib/api.ts` içinde tanımlı. Ağ hatası ve 4xx/5xx `ApiError`
  fırlatır. ⚠️ **Boş sonuç ASLA hata değildir.** API çöktüğünde kullanıcıya
  "kampanya yok" demek bu projede kabul edilemez bir hata sınıfıdır.
- **`types/api.ts`** — yeni tipleri buraya ekle, ayrı dosya açma.
- **TanStack Query** kurulu; veri çekme onunla.
- **`@/` yol takma adı** aktif.
- Yorumlar ve docstring'ler **Türkçe**.

### Kurulması gereken paket

```bash
cd frontend
npm install recharts
```

⚠️ `recharts` **kurulu değil.** Radar / bar / donut grafikleri onu gerektirir.

---

## 🔗 4. BACKEND API — DOĞRULANMIŞ SÖZLEŞME

Backend `http://localhost:8000/api/v1` altında. Vite proxy `/api` yolunu
buraya yönlendirir.

### ⚠️ 4.0 ÜÇ KRİTİK GENEL KURAL

#### (a) `Decimal` alanlar JSON'da **STRING** gelir

```jsonc
{ "profit_rate_pct": "3.0500", "monthly_payment_try": "23073.08" }
```

Sayı değil **string**. Pydantic v2 kesinlik kaybını önlemek için böyle
serileştirir. `parseFloat()` gerekir; doğrudan toplama yapılırsa string
birleşir (`"3.05" + "4.20"` → `"3.054.20"`).

`lib/format.ts`'e bir yardımcı ekle:

```ts
/** Backend'den string gelen Decimal'i sayıya çevirir; null güvenli. */
export function parseDecimal(value: string | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = Number.parseFloat(value);
  return Number.isFinite(n) ? n : null;
}
```

#### (b) Hata zarfı tek biçim

```jsonc
{ "error": { "code": "VALIDATION_ERROR", "message": "...", "detail": null } }
```

`code` değerleri: `VALIDATION_ERROR` (422), `NOT_FOUND` (404),
`METHOD_NOT_ALLOWED` (405), `HTTP_ERROR`, `NETWORK_ERROR` (istemci tarafı).
Kullanıcıya `message` gösterilir; `detail` geliştirici içindir.

#### (c) `null` sıfır değildir

Backend "bilmiyorum" ile "sıfır" arasında ayrım yapar. Arayüz de yapmalı:

| Backend | Anlam | Arayüz |
|---|---|---|
| `null` | Banka bu veriyi **yayımlamamış** | `—` + tooltip |
| `0` | Değer gerçekten **sıfır** | `0` göster (ör. Albaraka Togg %0 finansman **gerçektir**) |

---

### 4.1 Dashboard — `GET /api/v1/stats`

```jsonc
{
  "total_banks": 10,
  "banks_with_data": 9,
  "total_campaigns": 602,
  "active_campaigns": 318,
  "upcoming_campaigns": 1,
  "expired_campaigns": 229,
  "unknown_status_campaigns": 54,   // ⚠️ expired'DAN AYRI
  "products_total": 222,
  "rates_total": 373,
  "limits_total": 108,
  "ai_coverage_pct": 94.5,
  "green_campaigns_count": 6,
  "campaigns_by_bank": [{ "bank_code": "...", "bank_name": "...", "count": 209 }],
  "campaigns_by_category": [{ "category": "...", "count": 0 }],
  "sector_distribution": [{ "sector": "market_gida", "count": 44 }],
  "radar_scores": [ /* aşağıda */ ],
  "last_scrape_at": "2026-08-19T..."
}
```

#### Rekabet Radarı — eksenler `null` olabilir

```jsonc
{
  "bank_code": "ziraat_katilim",
  "bank_name": "Ziraat Katılım",
  "rate_competitiveness": null,   // finansman oranı yayımlamıyor
  "campaign_volume": 100.0,       // daima sayı
  "reward_generosity": 3.6,
  "term_flexibility": 0.0,
  "transparency_index": 10.7,
  "measured_axes": 4              // 5 eksenden kaçı gerçek ölçüm
}
```

Eksenlerin anlamı:

| Eksen | Kaynak | Yön |
|---|---|---|
| `rate_competitiveness` | Bankanın en düşük finansman oranı | Düşük oran → yüksek puan |
| `campaign_volume` | Kampanya sayısı / en çok yayımlayan banka | — |
| `reward_generosity` | Ödül tutarlarının **ortancası** | — |
| `term_flexibility` | Yayımlanan azami vade | — |
| `transparency_index` | Ürünlerinin % kaçının yayımlanmış oranı/limiti var | — |

⚠️ **Puanlar bankalar arasında GÖRELİDİR**, mutlak not değil. Radar başlığına
bunu yazan bir alt metin koy: *"Puanlar bankalar arasında görelidir; 100 = bu
eksende en iyi."*

⚠️ **`null` eksen çizilmez.** Recharts `Radar` bileşeni `null`u 0 sanıp
şekli içe çeker ve banka "kötü" görünür. İki seçenekten birini uygula:
- O ekseni o banka için çizme (`connectNulls={false}`), **veya**
- Bankayı radardan çıkarıp "ölçüm yetersiz" listesine al.

`measured_axes < 3` olan bankayı radara koyma; kart olarak
*"Yalnızca N/5 eksende ölçüm var"* diye göster.

**Arayüz:** Bento Grid KPI kartları + Bar (banka hacmi) + Donut (sektör) +
Radar (rekabet).

---

### 4.2 Kampanya Kataloğu — `GET /api/v1/campaigns`

- **Query:** `q` (FTS5), `bank_code`, `category`, `status`, `page`, `limit`
- Sayfalı `Page<CampaignListItem>` döner.
- ⚠️ `status` **backend'de hesaplanır**; frontend tarihlerden yeniden
  hesaplamaz. Aksi hâlde iki taraf çelişir.
- ⚠️ `unknown` durumu `expired`'dan **ayrıdır** ve ayrı rozet alır.

**Arayüz:** FTS5 canlı arama + chip filtreleri + Dense Data Table.

---

### 4.3 Kampanya Detayı — `GET /api/v1/campaigns/{id}`

`extractions` listesi: `field_name`, `value_raw`, `value_normalized`,
`evidence_text`, `confidence`, `extraction_method`.

**Arayüz:** Evidence Drawer + orijinal sayfa bağlantısı. Her sayının yanında
kanıt ikonu; tıklanınca çekmece açılır ve `evidence_text` **birebir** gösterilir.

#### `products[]` — kampanyanın konu aldığı ürünler

```jsonc
"products": [{
  "product_id": 12,
  "product_name": "İhtiyaç Finansmanı (İhtiyaç Kredisi)*",
  "product_type": "ihtiyac_finansmani",
  "variant_label": null,
  "match_method": "title",        // title | slug | body
  "confidence": "0.900",          // STRING (Decimal)
  "evidence": "50.000 TL İhtiyaç Finansmanı Kampanyası"
}]
```

⚠️ **`confidence` bağın ne kadar sağlam olduğunu söyler, ürünün ne kadar iyi
olduğunu değil:**

| `match_method` | Güven | Anlamı |
|---|---|---|
| `title` | 0.90 | Ürün adı kampanya **başlığında** geçiyor |
| `slug` | 0.85 | Ürün adresi kampanya adresinde geçiyor |
| `body` | 0.60 | Yalnızca **gövde metninde** — geçerken anılmış olabilir |

`body` bağı "bu kampanya bu ürüne aittir" demez, **"metinde bu ürün anılıyor"**
der. Arayüz ikisini aynı ağırlıkta göstermemeli: `title`/`slug` bağını belirgin
bir kart olarak, `body` bağını "ayrıca anılan ürünler" başlığı altında soluk
göster. `evidence` her satırda var — tooltip ya da çekmecede göster.

⚠️ Bir kampanya **birden çok ürüne** bağlanabilir; bu gerçektir, gürültü
değildir ("Kadınlar Gününe Özel Avantajlar" kampanyası dört ayrı ürünü
anıyor). Listeyi kırpma, güvene göre sırala.

Kapsama (19 Ağustos 2026 ölçümü): 129/602 kampanya bağlandı; **finansman
kampanyalarında 14/16 (%88)**. Bağ yokken bölüm hiç gösterilmez — boş
"ürün bulunamadı" kutusu koyma.

---

### 4.4 Ürün Kataloğu — `GET /api/v1/products`

- **Query:** `bank_code`, `product_type`, `rate_type`, `limit` (1-100, vars. 50)
- `rate_type` verilirse **yalnızca o türden oranı olan ürünler** döner ve
  oranlar da o türe süzülür.
- Geçersiz `rate_type` → **422** (sessizce boş liste dönmez).
- Geçersiz `bank_code` → **404**.

Her ürün: `rates[]` (oran satırları) + `limits[]` (BDDK limit matrisi hücreleri).

#### ⚠️ Liste DÜZ gelir — varyantlar ayrı satırdır

Bir ürünün koşula bağlı farklı oranları varsa bunlar **ayrı ürün satırı**
olarak döner:

```jsonc
{ "id": 12,  "name": "Taşıt Finansmanı (Taşıt Kredisi)*",
  "variant_key": null, "parent_product_id": null, "rates": [] },
{ "id": 225, "name": "Taşıt Finansmanı … — 2. El Araç · Sigortalı",
  "variant_key": "ikinci_el_arac+sigortali", "parent_product_id": 12, "rates": [7 satır] },
{ "id": 227, "name": "Taşıt Finansmanı … — Sıfır Araç · Sigortalı",
  "variant_key": "sifir_arac+sigortali",     "parent_product_id": 12, "rates": [7 satır] }
```

Bu ayrım **anlamlıdır, gürültü değildir**: sigortalı taşıt finansmanı %3,67,
sigortasız %4,27. Tek satıra indirilirse hangi oranın hangi koşula ait olduğu
kaybolur.

**Arayüz kuralı:** listede varyantları ana ürünün altına **girintili grupla**
(`parent_product_id` ile). Ana ürünün `rates` dizisi çoğu zaman **boştur** —
oranlar varyantlarda durur; bu bir hata değildir, "ana satırın kendi oranı
yok" demektir. Ana satırı "oran yok" diye gizleme, varyantlarını gösteren
başlık satırı olarak kullan.

`variant_key` bileşik olabilir (`sifir_arac+sigortali` = araç durumu ×
sigorta). Gösterimde `variant_label` kullan — zaten okunur biçimde geliyor
(`"Sıfır Araç · Sigortalı"`).

### 4.5 Ürün Detayı — `GET /api/v1/products/{id}`

Oranlar, limitler, **varyantlar** ve **`source_url`** döner. Yok → **404**.

`variants[]` alanı ana ürünün alt varyantlarını tam hâlleriyle taşır (her
biri kendi `rates[]` dizisiyle). Detay sayfasında varyantları sekme ya da
karşılaştırma tablosu olarak sun: aynı ürünün sigortalı/sigortasız oranını
yan yana göstermek bu ekranın en güçlü tarafıdır.

⚠️ `source_url` her ürün detayında var. Arayüzde "Bankanın sayfasında gör"
bağlantısı olarak göster — bu, "veriyi nereden aldınız?" sorusunun cevabıdır.

⚠️ **Oran türü etiketi zorunlu.** Aynı `profit_rate_pct` sütunu üç farklı
şeyi taşır:

| `rate_type` | Anlam | Rozet metni |
|---|---|---|
| `financing_rate` | Finansman **maliyeti** (aylık) | "Finansman maliyeti · aylık" |
| `participation_yield` | Katılma hesabı **getirisi** (yıllık) | "Katılma getirisi · yıllık" |
| `profit_sharing_ratio` | Kâr **bölüşüm** oranı (`investor_share_pct`) | "Katılımcı payı" |

Etiket olmadan gösterilen bir oran yanıltıcıdır: %3,05 maliyet ile %31,22
getiri aynı görünür.

---

### 4.6 Karşılaştırma Motoru — `POST /api/v1/products/compare`

> ⚠️ **DONDURULMUŞ SÖZLEŞME.** `GET /products/compare` **YOKTUR**, yalnızca POST.

**İstek:**

```jsonc
{
  "rate_type": "financing_rate",      // ZORUNLU — varsayılanı YOK
  "criterion": "en_dusuk_kar_payi",   // ZORUNLU
  "product_type": "tasit_finansmani", // opsiyonel
  "bank_codes": ["albaraka"],         // opsiyonel
  "term_months": 36,                  // opsiyonel
  "term_days": 365,                   // opsiyonel
  "currency": "TRY",                  // varsayılan TRY
  "amount_try": "500000",             // opsiyonel (string!)
  "weights": { "rate_weight": "50", "fee_weight": "25", "term_weight": "25" },
  "limit": 20
}
```

**Ölçütler ve zorunlu oran türü:**

| `criterion` | Sıralanan alan | Yön | Gerekli `rate_type` |
|---|---|---|---|
| `en_dusuk_kar_payi` | `profit_rate_pct` | artan | `financing_rate` |
| `en_dusuk_masraf` | `allocation_fee_pct` | artan | `financing_rate` |
| `en_dusuk_toplam_maliyet` | `annual_cost_pct` | artan | `financing_rate` |
| `en_yuksek_getiri` | `profit_rate_pct` | azalan | `participation_yield` |
| `en_yuksek_paylasim_orani` | `investor_share_pct` | azalan | `profit_sharing_ratio` |
| `en_uzun_vade` | `term_months` | azalan | her tür |
| `en_avantajli` | ağırlıklı skor | azalan | her tür |

⚠️ Bağdaşmayan çift (`en_yuksek_getiri` + `financing_rate`) → **422**. Arayüz
ölçüt listesini seçili `rate_type`'a göre süzmeli; kullanıcıya geçersiz
kombinasyon sunulmamalı.

⚠️ `weights` yalnızca `en_avantajli`'de etkili. Slider'ları diğer ölçütlerde
gizle ya da devre dışı bırak — etkisi olmayan bir kontrol göstermek kullanıcıya
var olmayan bir denetim vaat eder. **`reward_weight` YOKTUR**, üç ağırlık var.

**Yanıt:**

```jsonc
{
  "rate_type": "financing_rate",
  "criterion": "en_dusuk_kar_payi",
  "sort_field": "profit_rate_pct",
  "descending": false,
  "winner": { /* RankedProduct | null */ },
  "winner_reason": "Albaraka Türk — en düşük kâr payı oranı: %0.0000",
  "ranked": [ /* RankedProduct[], rank 1'den */ ],
  "without_data": [ /* RankedProduct[], rank: null */ ],
  "note": "2 ürün sıralandı, 0 ürün ölçütün alanı boş olduğu için ..."
}
```

`RankedProduct`:

```jsonc
{
  "rank": 1,                     // without_data'da null
  "product_id": 53,
  "product_name": "Togg Finansmanı",
  "bank_code": "albaraka",
  "bank_name": "Albaraka Türk",
  "product_type": "tasit_finansmani",
  "rate_type": "financing_rate",
  "profit_rate_pct": "0.0000",   // STRING
  "allocation_fee_pct": null,
  "annual_cost_pct": null,
  "investor_share_pct": null,
  "bank_share_pct": null,
  "term_months": 12,
  "term_label": "12",
  "currency": "TRY",
  "score": null,                 // yalnızca en_avantajli'de dolu
  "evidence_text": "T10F V2 | 12 | 1.000.000 | 0,00%",
  "source_url": "https://www.albaraka.com.tr/...",
  "missing_reason": null         // without_data'da dolu
}
```

⚠️ **`without_data` gizlenmez.** Ölçütün alanı `null` olan ürün sıralamaya
karışmaz, bu grupta `missing_reason` ile döner. Tablonun altına ayrı bir
bölüm aç: *"Veri yayımlamadığı için sıralanamayan N ürün"* ve her satırda
`missing_reason`'ı göster. Listeden gizlemek o bankayı yokmuş gibi sunar.

⚠️ **`winner_reason` backend'den gelir**, arayüzde yeniden yazılmaz. Kazanılan
ölçütü ve değeri söyler.

**Arayüz:** Ölçüt + oran türü seçici → yan yana matris → Kazanan rozeti →
ağırlık slider'ları (`en_avantajli` seçiliyse) → altta "veri yok" bölümü.

---

### 4.7 Simülatör — `POST /api/v1/simulator/*`

#### `POST /simulator/financing`

**İstek:** `{ "amount_try": 500000, "term_months": 36, "product_type": "tasit_finansmani" }`

```jsonc
{
  "amount_try": "500000",
  "term_months": 36,
  "product_type": "tasit_finansmani",
  "best_bank_code": "albaraka",
  "offers": [{
    "bank_code": "albaraka",
    "bank_name": "Albaraka Türk",
    "product_id": 53,
    "product_name": "Togg Finansmanı",
    "profit_rate_pct": "3.0500",
    "rate_term_months": 36,
    "is_exact_term_match": true,     // ⚠️ false ise teklif YAKLAŞIK
    "monthly_payment_try": "23073.08",
    "total_profit_try": "330630.88",
    "total_payment_try": "830630.88",
    "is_best_offer": true,
    "source_url": "https://...",
    "evidence_text": "T10F V2 4MORE | 36 | 1.500.000 | 3,05%"
  }],
  "banks_without_data": [{
    "bank_code": "adil_katilim",
    "bank_name": "Adil Katılım",
    "reason": "tasit_finansmani için yayımlanmış kâr payı oranı bulunamadı"
  }],
  "method_note": "Eşit taksitli (annüite) plan; taksit = P·r·(1+r)^n/((1+r)^n−1). ..."
}
```

⚠️ **`banks_without_data` mutlaka gösterilir.** 10 bankadan yalnızca 3'ü
teklif verdiyse kullanıcı bunu görmeli; 7 bankayı sessizce düşürmek "bu
bankalar pahalı" gibi okunur. Teklif tablosunun altında gri bir bölüm:
*"Oran yayımlamadığı için teklif üretilemeyen bankalar"* + her birinin `reason`'ı.

⚠️ **`is_exact_term_match: false`** ise oranın başka bir vade için yayımlandığı
anlamına gelir; satıra uyarı ikonu koy ve `rate_term_months`'u tooltip'te söyle:
*"Oran 12 ay için yayımlanmış, 36 aya uyarlandı."*

⚠️ **`method_note` yanıtta gösterilir.** Tahsis ücreti ve sigortanın hesaba
dahil olmadığını söylüyor; gizlenirse taksit gerçekten ödenecek tutar sanılır.

#### `POST /simulator/yield`

**İstek:** `{ "deposit_try": 100000, "term_days": 365, "currency": "TRY" }`

Teklif alanları: `annual_yield_gross_pct`, `rate_term_label`,
`is_exact_term_match`, `investor_share_pct`, `bank_share_pct`,
`gross_profit_try`, `withholding_pct`, `withholding_try`, `net_profit_try`,
`is_best_yield`, `source_url`, `evidence_text`.
Ayrıca `banks_without_data`, `withholding_note`, `method_note`.

⚠️ **`annual_yield_gross_pct` bankanın yayımladığı gerçekleşmiş getiridir;
katılımcı payı bu orana ZATEN dahildir.** `investor_share_pct` yalnızca bilgi
amaçlı gösterilir — arayüzde getiriyle **çarpılmaz**, çarpılırsa pay iki kez
düşülür.

⚠️ **`withholding_note` gösterilir** — uygulanan stopajın mevzuat dayanağını
taşır. Net tutarın nasıl bulunduğu görünmeli.

⚠️ **`method_note`** geçmiş getirinin gelecek getiriyi taahhüt etmediğini
söylüyor. Katılma hesabında kâr payı önceden garanti edilemez; bu uyarı
Inline Alert olarak gösterilmeli — fıkhi olarak da, hukuken de zorunlu.

⚠️ Şu an **yalnızca Türkiye Finans** katılma getirisi yayımlıyor. Tek teklif
gelecek; arayüz bunu "sıralama" gibi değil "tek kaynak" olarak sunmalı.

#### `POST /simulator/bddk-check`

**İstek:** `{ "asset_type": "konut", "asset_value_try": 25000000, "energy_class": "A" }`

```jsonc
{
  "asset_type": "konut",
  "asset_value_try": "25000000",
  "energy_class": "A-B",
  "value_band_label": "20 milyon TL üzeri",
  "max_financing_ratio_pct": "40",
  "max_financing_amount_try": "10000000.00",
  "max_allowed_term_months": 120,
  "is_financing_allowed": true,
  "legal_reference": "BDDK 24.08.2023 tarihli 10631 sayılı Konut Kredileri LTV Kararı"
}
```

⚠️ **Konut LTV'si enerji sınıfına TEK BAŞINA bağlı değildir**; konut değeri
bandıyla birlikte belirlenir. `value_band_label` hangi bandın uygulandığını
söyler — mutlaka göster, yoksa kullanıcı %40'ın nereden geldiğini anlamaz.

⚠️ Taşıtta 2 milyon TL üzeri `is_financing_allowed: false` döner. `0` gösterip
geçme; *"BDDK bu değerde finansman kullandırılmasına izin vermiyor"* de.

⚠️ `legal_reference` her yanıtta var, dipnot olarak göster.

**Arayüz:** Üç sekmeli simülatör — Taksit / Getiri / BDDK Denetçisi. Slider'lar
canlı değer rozetli.

---

### 4.8 Sohbet — `POST /api/v1/chat`

**İstek:** `{ "query": "...", "bank_code": null }`

```jsonc
{
  "query": "faiz oranı en düşük hangi banka",
  "answer_text": "...",
  "forbidden_terms_warning": "Katılım bankacılığı ilkeleri gereği 'faiz' terimi yerine 'kâr payı' terimi kullanılmalıdır. ...",
  "results": [ /* ChatResultItem[] */ ]
}
```

⚠️ `forbidden_terms_warning` **dolu geldiğinde** Inline Alert olarak gösterilir.
Bu, projenin katılım bankacılığı uyumunun en görünür kanıtı — gizlenmez.
Metinde emoji yoktur, arayüzde de eklenmez.

⚠️ `results` boş + `answer_text` dolu bir **başarılı** yanıttır, hata değil.
`EmptyState` göster, `ErrorState` değil.

---

### 4.9 Canlı Çıkarım — `POST /api/v1/extract`

**İstek:** `{ "text": "...", "mode": "hybrid" | "rule_only" }`

Yanıt alanları: `fields`, `labels`, `summary`, `rejected`, `logic_violations`,
`model`, `latency_ms`, `mode`, `extras`.

⚠️ `rejected` ve `logic_violations` **gösterilir**. Sistemin neyi kabul
etmediğini göstermek, kabul ettiklerine olan güveni artırır. Jüri demosunun
en etkili parçası budur: *"model bunu buldu ama kanıtı doğrulanamadığı için
reddetti."*

**Arayüz:** Metin kutusu + "Çıkar" düğmesi + kanıt kartları + reddedilenler
bölümü + `latency_ms` göstergesi.

---

## 📱 5. SAYFA YAPISI VE ROTALAR

| Rota | Sayfa | Durum |
|---|---|---|
| `/` | **Dashboard** — Bento KPI + Radar + Sektör Donut + Banka Bar | Kısmen var (`OverviewPage`) |
| `/campaigns` | **Kampanya Kataloğu** — FTS5 arama + filtre + tablo + Evidence Drawer | Var (`CampaignsPage`) |
| `/products` | **Ürün Kataloğu** — oran türü sekmeleri + limit matrisi + detay | **YENİ** |
| `/compare` | **Karşılaştırma Motoru** — ölçüt seçici + matris + kazanan + veri yok bölümü | **YENİ** |
| `/simulator` | **Simülatör** — Taksit / Getiri / BDDK üç sekme | **YENİ** |
| `/chat` | **Akıllı Arama** — soru-cevap + terminoloji uyarısı + kaynak kartları | **YENİ** |
| `/extract` | **Canlı Çıkarım Laboratuvarı** — jüri demosu + reddedilenler | **YENİ** |

Rotalar `App.tsx`'e, gezinme bağlantıları `components/layout/Sidebar.tsx`'e eklenir.

---

## 💡 6. EKSİK VERİ (NULL) YÖNETİMİ — PROJENİN İMZASI

Bir alan `null` geldiğinde:

1. ❌ **Kesinlikle `null`, `undefined`, `NaN` veya `0.00` yazma.**
2. ✅ Hücreye `—` koy, üzerine gelindiğinde tooltip göster:
   > *"Bu veri ilgili bankanın kamuya açık sayfasında yayımlanmamıştır."*
3. ✅ Sıralamada `null` **en sona** değil, **ayrı gruba** gider — backend
   bunu `without_data` / `banks_without_data` olarak zaten ayırmış durumda.
4. ⚠️ **`0` ile `null`u karıştırma.** Albaraka'nın Togg kampanyasında
   finansman oranı **gerçekten %0**. Onu `—` göstermek gerçek bir avantajı
   siler.

### Üç ayrı "veri yok" kanalı ve arayüz karşılığı

| Uç | Alan | Arayüz |
|---|---|---|
| `/products/compare` | `without_data[]` | Tablo altında ayrı bölüm + `missing_reason` |
| `/simulator/*` | `banks_without_data[]` | Teklif listesi altında gri kart + `reason` |
| `/stats` radar | eksen `null` + `measured_axes` | Ekseni çizme; `measured_axes < 3` ise bankayı radardan çıkar |

---

## 🛠️ 7. ÇALIŞTIRMA

```powershell
# Terminal 1 — backend
python dev.py api

# Terminal 2 — frontend
cd frontend
npm install
npm install recharts
npm run dev
```

Bitirmeden önce:

```powershell
python dev.py lint    # ruff + mypy + tsc — tsc HATASIZ olmalı
```

⚠️ TypeScript **strict** modda. `any` kullanmadan yaz; backend tiplerini
`types/api.ts`'e ekle.
