# Bağımlılık Lisans Matrisi

Şartname madde 5.10 gereği, projede **lisans riski taşıyan hiçbir bileşen
kullanılmamıştır**. Tüm doğrudan bağımlılıklar izin verici (permissive)
lisanslara sahiptir: MIT, BSD, Apache-2.0, ISC veya PSF.

Projenin kendi lisansı: **Apache License 2.0** (bkz. [LICENSE](LICENSE)).

## Neden copyleft bileşen yok

GPL/AGPL lisanslı bir bileşen, türev çalışmanın da aynı lisansla dağıtılmasını
zorunlu kılar. Bu proje kamu kurumlarında ve bankalarda on-premise kurulabilir
olacak şekilde tasarlandığından, böyle bir zorunluluk kurumsal kullanımı
engelleyebilirdi. Bu nedenle bağımlılıklar bilinçli olarak izin verici
lisanslardan seçilmiştir.

## Backend (Python)

| Paket | Sürüm aralığı | Lisans | Kullanım amacı |
|---|---|---|---|
| fastapi | >=0.115,<0.116 | MIT | HTTP API çatısı |
| uvicorn[standard] | >=0.32,<0.33 | BSD-3-Clause | ASGI sunucusu |
| sqlalchemy | >=2.0.36,<2.1 | MIT | ORM ve sorgu katmanı |
| alembic | >=1.13,<2.0 | MIT | Veritabanı göçleri |
| pydantic | >=2.9,<3.0 | MIT | Şema doğrulama |
| pydantic-settings | >=2.6,<3.0 | MIT | Ortam değişkeni yönetimi |
| httpx | >=0.27,<0.29 | BSD-3-Clause | HTTP istemcisi |
| beautifulsoup4 | >=4.12,<5.0 | MIT | HTML ayrıştırma |
| lxml | >=5.3,<6.0 | BSD-3-Clause | Hızlı HTML/XML ayrıştırıcı |
| protego | >=0.3,<0.5 | BSD-3-Clause | robots.txt yorumlama |
| tenacity | >=9.0,<10.0 | Apache-2.0 | Yeniden deneme mantığı |
| structlog | >=24.4,<26 | Apache-2.0 / MIT | Yapılandırılmış loglama |
| tzdata | >=2024.1 | Apache-2.0 | IANA zaman dilimi veritabanı |

### Geliştirme bağımlılıkları (dağıtıma girmez)

| Paket | Lisans | Kullanım amacı |
|---|---|---|
| pytest | MIT | Test çatısı |
| pytest-asyncio | Apache-2.0 | Asenkron test desteği |
| pytest-cov | MIT | Kapsam ölçümü |
| ruff | MIT | Kural ve biçim denetimi |
| mypy | MIT | Statik tip denetimi |

## Frontend (Node)

| Paket | Sürüm aralığı | Lisans | Kullanım amacı |
|---|---|---|---|
| react / react-dom | ^18.3.1 | MIT | Arayüz kütüphanesi |
| react-router-dom | ^6.27.0 | MIT | İstemci tarafı yönlendirme |
| @tanstack/react-query | ^5.59.0 | MIT | Sunucu durumu ve önbellek |
| @radix-ui/react-select | ^2.1.2 | MIT | Erişilebilir seçim bileşeni |
| @radix-ui/react-tooltip | ^1.1.3 | MIT | Erişilebilir ipucu bileşeni |
| @radix-ui/react-slot | ^1.1.0 | MIT | Bileşen kompozisyonu |
| lucide-react | ^0.454.0 | ISC | İkon seti |
| class-variance-authority | ^0.7.0 | Apache-2.0 | Varyant yönetimi |
| clsx | ^2.1.1 | MIT | Sınıf birleştirme |
| tailwind-merge | ^2.5.4 | MIT | Tailwind sınıf çakışma çözümü |
| tailwindcss | ^3.4.14 | MIT | CSS çatısı |
| vite | ^5.4.10 | MIT | Derleme aracı |
| typescript | ^5.6.3 | Apache-2.0 | Tip sistemi |

## Çalışma zamanı

| Bileşen | Sürüm | Lisans |
|---|---|---|
| CPython | 3.11+ | PSF License |
| Node.js (yalnızca frontend derlemesi için) | 20+ | MIT |

## Veri kaynakları

Toplanan veriler, katılım bankalarının **kamuya açık** web sayfalarından
alınmıştır. Kazıma sırasında:

- Her isteğe kimliğimizi bildiren bir `User-Agent` eklenir; kimlik gizlenmez.
- `robots.txt` kuralları uygulanır; yasaklı adreslere istek yapılmaz ve bu
  durum `source_documents` tablosunda `robots_allowed=false` ile belgelenir.
- İstekler arasında bekleme uygulanır, sitenin `Crawl-delay` talebi daha uzunsa
  ona uyulur.

Banka adları ve markaları ilgili kurumlara aittir; bu projede yalnızca veri
kaynağını göstermek amacıyla kullanılmıştır.

## Yerel LLM ve gömme (Sprint 5)

| Bileşen | Lisans | Bağlantı | Kullanım |
|---|---|---|---|
| [Ollama](https://ollama.com) | MIT | https://github.com/ollama/ollama | Yerel model sunucusu |
| `qwen2.5:7b` (sohbet) | Apache-2.0 (Qwen) | https://ollama.com/library/qwen2.5 | `LOCAL_LLM_MODEL` |
| `nomic-embed-text` | Apache-2.0 | https://ollama.com/library/nomic-embed-text · https://huggingface.co/nomic-ai/nomic-embed-text-v1.5 | `EMBEDDING_MODEL` / `embeddings` tablosu |

Tam pip denetimi: [`docs/dependency_licenses.md`](docs/dependency_licenses.md).
