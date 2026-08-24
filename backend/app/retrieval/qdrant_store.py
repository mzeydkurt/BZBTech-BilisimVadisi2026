"""Qdrant vektör deposu — anlamsal kanalın uzak arka ucu.

 `qdrant-client` BAĞIMLILIĞI EKLENMEDİ. Qdrant'ın REST arayüzü bu kullanım
için yeterli (koleksiyon kur · upsert · ara) ve `httpx` projede zaten var.
Yeni bir paket, `LICENSES.md`'ye yeni bir satır ve şartname madde 5.10'un
("lisans problemi çıkarma potansiyeli olan çözüm") kapsamına yeni bir yüzey
demektir.

 QDRANT ZORUNLU DEĞİL. Erişilemediğinde `chat_service` yerel `embeddings`
t1blosuna düşer ve bu durum yanıttaki `semantic_note` alanında BİLDİRİLİR.
Kapalı ağ (airgap) gösterimi bu yüzden Qdrant olmadan da çalışır — sessizce
tek kanala düşmek yasak.

SÜZGEÇLEME QDRANT'A DEVREDİLMEDİ. Qdrant `filter` desteklese de sert
süzgeç kapısı Python tarafında (`search._suzgecten_gecir`) kalıyor: orada
ölçülmüş, test edilmiş ve "değeri yok" ile "eşiği geçmedi" ayrımını yapan tek
bir uygulama var. Aynı mantığı iki yerde tutmak, ikisinin sessizce ıraksaması
demektir. Qdrant yalnızca **anlamsal aday kaynağıdır**.

 NOKTA KİMLİĞİ TÜRETİLMİŞTİR. Qdrant tamsayı ya da UUID kimlik istiyor;
kart kimliği `(entity_type, entity_id, chunk_index)` üçlüsü. Üçlü kararlı bir
tamsayıya katlanır ki yeniden yükleme aynı noktayı GÜNCELLESİN, ikinci bir
kopya AÇMASIN.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

import httpx

from app.logging_config import get_logger
from app.retrieval.semantic import SemanticHit

logger = get_logger(__name__)

# Kosinüs mesafesi: kart metinleri farklı uzunlukta, büyüklük anlam taşımıyor.
DISTANCE: Final[str] = "Cosine"

# Tek upsert isteğinde gönderilecek nokta sayısı.
UPSERT_BATCH: Final[int] = 128

# Varlık türü → kararlı sayısal önek. Nokta kimliği bu önekle üretilir;
# `campaign:5` ile `product:5` aynı noktaya yazmasın.
_ENTITY_PREFIX: Final[dict[str, int]] = {
    "campaign": 1,
    "product": 2,
    "product_rate": 3,
    "glossary": 4,
    "bank": 5,
}
_PREFIX_STRIDE: Final[int] = 10_000_000
_CHUNK_STRIDE: Final[int] = 1_000


def point_id(entity_type: str, entity_id: int, chunk_index: int) -> int:
    """`(tür, kimlik, parça)` üçlüsünü kararlı bir tamsayıya katlar.

    ⚠️ KARARLI OLMAK ZORUNDA. Rastgele ya da sıra numarasına dayalı bir kimlik,
    her yükleme turunda aynı kartı YENİ bir nokta olarak eklerdi; koleksiyon
    şişer ve arama aynı kaydı birden fazla kez döndürür.

    Raises:
        ValueError: Tanımsız varlık türü. Sessizce 0 öneki kullanmak, iki farklı
            türü aynı kimlik uzayına sıkıştırıp veri kaybettirirdi.
    """
    onek = _ENTITY_PREFIX.get(entity_type)
    if onek is None:
        raise ValueError(f"Tanımsız varlık türü: {entity_type!r}")
    return onek * _PREFIX_STRIDE + entity_id * _CHUNK_STRIDE + chunk_index


@dataclass(frozen=True)
class QdrantPoint:
    """Yüklenecek tek bir vektör ve yükü."""

    entity_type: str
    entity_id: int
    chunk_index: int
    vector: list[float]
    payload: dict[str, Any]


class QdrantStore:
    """Qdrant koleksiyonu üzerinde anlamsal arama.

    Arayüzü `EmbeddingStore` ile UYUMLUDUR (`is_empty`, `dim`, `model_name`)
    ki `chat_service` ikisi arasında geçiş yaparken çağrı yeri değişmesin.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        collection: str,
        model_name: str,
        timeout: float = 20.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._collection = collection
        self._model_name = model_name
        self._timeout = timeout
        # `ensure_collection` / `describe` sonrası dolar; bilinmiyorsa 0.
        self._dim = 0
        self._count = 0

    # ── Kimlik ────────────────────────────────────────────

    @property
    def is_empty(self) -> bool:
        """Koleksiyonda nokta yok mu? Arama bu durumda sözcüksel kanala düşer."""
        return self._count == 0

    @property
    def dim(self) -> int:
        """Koleksiyonun vektör boyutu; bilinmiyorsa 0."""
        return self._dim

    @property
    def model_name(self) -> str:
        """Vektörlerin üretildiği model."""
        return self._model_name

    @property
    def vector_count(self) -> int:
        """Koleksiyondaki nokta sayısı."""
        return self._count

    # ── Ağ ────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        return {"api-key": self._api_key, "Content-Type": "application/json"}

    async def _istek(
        self, method: str, path: str, govde: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Qdrant'a istek atar.

        Raises:
            QdrantUnavailableError: Servise ulaşılamıyor ya da hata döndürdü.
        """
        url = f"{self._base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.request(
                    method, url, json=govde, headers=self._headers()
                )
        except httpx.HTTPError as exc:
            raise QdrantUnavailableError(f"Qdrant'a ulaşılamıyor: {exc}") from exc

        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise QdrantUnavailableError(
                f"Qdrant hata döndürdü: HTTP {response.status_code} — {response.text[:200]}"
            )
        sonuc: Any = response.json()
        if not isinstance(sonuc, dict):
            raise QdrantUnavailableError(f"Beklenmeyen yanıt biçimi: {type(sonuc).__name__}")
        return sonuc

    # ── Koleksiyon yönetimi ───────────────────────────────

    async def describe(self) -> bool:
        """Koleksiyonun var olup olmadığını ve boyut/sayıyı okur.

        Returns:
            Koleksiyon varsa `True`.

        ⚠️ İSTİSNA YÜKSELTMEZ. Bu bir sağlık yoklamasıdır; Qdrant kapalıysa
        arama yerel depoya düşer ve kullanıcıya bildirilir.
        """
        try:
            yanit = await self._istek("GET", f"/collections/{self._collection}")
        except QdrantUnavailableError as exc:
            logger.info("qdrant_koleksiyon_okunamadi", hata=str(exc))
            return False

        sonuc = yanit.get("result") or {}
        self._count = int(sonuc.get("points_count") or 0)
        vektorler = ((sonuc.get("config") or {}).get("params") or {}).get("vectors") or {}
        self._dim = int(vektorler.get("size") or 0)
        return True

    async def ensure_collection(self, *, dim: int, recreate: bool = False) -> None:
        """Koleksiyonu kurar; yoksa oluşturur.

        ⚠️ BOYUT DEĞİŞTİYSE YENİDEN KURULMASI GEREKİR. Qdrant, farklı boyutlu
        vektörü reddeder; gömme modeli değiştiğinde (`bge-m3-embed` 1024 →
        `nomic-embed-text` 768) eski koleksiyona yazmak HTTP 400 verir. Bu
        durumda `recreate=True` ile açık onay istenir — sessizce silmek,
        yeniden gömme maliyetini görünmez kılardı.

        Args:
            dim: Vektör boyutu.
            recreate: Var olan koleksiyonu silip yeniden kurar.
        """
        varmi = await self.describe()
        if varmi and not recreate:
            if self._dim and self._dim != dim:
                raise QdrantDimensionError(
                    f"Koleksiyon {self._dim} boyutlu, gömmeler {dim} boyutlu. "
                    "Gömme modeli değişmiş; `--yeniden-kur` ile koleksiyonu "
                    "yeniden oluşturun (mevcut vektörler silinir)."
                )
            return

        if varmi and recreate:
            await self._istek("DELETE", f"/collections/{self._collection}")
            logger.warning("qdrant_koleksiyon_silindi", koleksiyon=self._collection)

        await self._istek(
            "PUT",
            f"/collections/{self._collection}",
            {"vectors": {"size": dim, "distance": DISTANCE}},
        )
        self._dim = dim
        self._count = 0
        logger.info("qdrant_koleksiyon_kuruldu", koleksiyon=self._collection, boyut=dim)

    async def upsert(self, points: list[QdrantPoint]) -> int:
        """Noktaları parça parça yükler.

        Returns:
            Yüklenen nokta sayısı.
        """
        yazilan = 0
        for basla in range(0, len(points), UPSERT_BATCH):
            parca = points[basla : basla + UPSERT_BATCH]
            govde = {
                "points": [
                    {
                        "id": point_id(nokta.entity_type, nokta.entity_id, nokta.chunk_index),
                        "vector": nokta.vector,
                        "payload": nokta.payload,
                    }
                    for nokta in parca
                ]
            }
            await self._istek("PUT", f"/collections/{self._collection}/points?wait=true", govde)
            yazilan += len(parca)
            logger.info("qdrant_parti_yazildi", yazilan=yazilan, toplam=len(points))
        self._count += yazilan
        return yazilan

    # ── Arama ─────────────────────────────────────────────

    async def search(
        self,
        query_vector: list[float],
        *,
        limit: int = 50,
        entity_type: str | None = None,
    ) -> list[SemanticHit]:
        """Sorgu vektörüne en yakın noktaları döndürür.

        ⚠️ SÜZGEÇ GÖNDERİLMEZ (yalnızca `entity_type`). Sert süzgeç kapısı
        Python tarafında; bkz. modül başındaki not.

        Args:
            query_vector: Sorgunun gömme vektörü.
            limit: Döndürülecek en fazla nokta.
            entity_type: Yalnızca bu türdeki kartlar (ör. `campaign`).

        Returns:
            Azalan benzerliğe göre sıralı sonuçlar; boş listede arama yapılmaz.

        Raises:
            QdrantUnavailableError: Servise ulaşılamıyor.
        """
        if not query_vector:
            return []

        govde: dict[str, Any] = {
            "vector": query_vector,
            "limit": limit,
            "with_payload": True,
        }
        if entity_type:
            govde["filter"] = {
                "must": [{"key": "entity_type", "match": {"value": entity_type}}]
            }

        yanit = await self._istek(
            "POST", f"/collections/{self._collection}/points/search", govde
        )
        satirlar = yanit.get("result") or []

        sonuc: list[SemanticHit] = []
        for satir in satirlar:
            yuk = satir.get("payload") or {}
            entity_id = yuk.get("entity_id")
            if entity_id is None:
                # ⚠️ Yükü olmayan nokta atlanır: kimliği payload'dan okumak
                # zorunlu, nokta kimliğinden geri çözmek türe göre değişir ve
                # yanlış kampanyayı göstermeye yol açardı.
                continue
            sonuc.append(
                SemanticHit(
                    doc_id=int(entity_id),
                    score=float(satir.get("score") or 0.0),
                    chunk_index=int(yuk.get("chunk_index") or 0),
                )
            )
        return sonuc


class QdrantUnavailableError(RuntimeError):
    """Qdrant servisine ulaşılamıyor ya da hata döndürdü."""


class QdrantDimensionError(RuntimeError):
    """Koleksiyonun boyutu gömmelerin boyutuyla uyuşmuyor."""
