"""Anlamsal arama — gömme vektörleri üzerinde kosinüs benzerliği.

`embeddings` tablosu şemada zaten var (Sprint 3A'da açıldı, boş bırakıldı) ve
vektörler `LargeBinary` olarak saklanıyor. 1.253 kart × 768 boyut = ~3,8 MB; bu boyutta kaba kuvvet
(brute-force) tarama tam isabetlidir ve yaklaşık komşuluk dizini (FAISS,
hnswlib) eklemek yeni bağımlılık ve lisans riski demektir.

GÖMME YOKSA SİSTEM ÇALIŞMAYA DEVAM EDER. `embeddings` boşsa bu katman boş
liste döndürür ve arama yalnızca sözcüksel kanalla yürür. Yanıtta hangi
kanalların çalıştığı bildirilir — sessizce tek kanala düşmek, kullanıcıya
"anlamsal arama yapıldı" izlenimi verirdi.

MODEL ADI ANAHTARIN PARÇASIDIR. `nomic-embed-text` ile üretilmiş bir
vektör, başka bir modelin sorgu vektörüyle karşılaştırılamaz — sonuç hata
vermez, ANLAMSIZ bir sıralama üretir. Bu yüzden arama, yapılandırılmış
modelle üretilmiş satırlarla sınırlıdır.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Embedding

# Vektör paketleme biçimi: little-endian 32-bit float dizisi.
# ⚠️ float64 SAKLANMIYOR. Kosinüs benzerliğinde 32 bit yeterli kesinliktir ve
# dosya boyutunu yarıya indirir. Bu bir PARA alanı değildir; `Decimal` kuralı
# tutar ve oranlar için geçerli, benzerlik puanı için değil.
_PACK_FORMAT: Final[str] = "<f"


def pack_vector(values: list[float]) -> bytes:
    """Float dizisini saklanabilir bayta çevirir."""
    return b"".join(struct.pack(_PACK_FORMAT, deger) for deger in values)


def unpack_vector(blob: bytes) -> list[float]:
    """Baytları float dizisine geri çevirir."""
    adet = len(blob) // struct.calcsize(_PACK_FORMAT)
    return [struct.unpack_from(_PACK_FORMAT, blob, i * 4)[0] for i in range(adet)]


def cosine(a: list[float], b: list[float]) -> float:
    """İki vektörün kosinüs benzerliği.

    ⚠️ SIFIR VEKTÖRDE 0.0 DÖNER, BÖLME HATASI FIRLATMAZ ama bu durum
    `LocalProvider.embed()` içinde zaten engellenmiştir (boş metin gömülemez).
    Buradaki koruma ikinci savunma hattıdır: bozuk bir satır tüm aramayı
    çökertmemeli.
    """
    if len(a) != len(b):
        return 0.0
    nokta = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return nokta / (norm_a * norm_b)


@dataclass(frozen=True)
class SemanticHit:
    """Tek bir belgenin anlamsal arama sonucu."""

    doc_id: int
    score: float
    chunk_index: int


class EmbeddingStore:
    """Bir varlık türünün gömme vektörlerini bellekte tutar.

    ⚠️ AYNI VARLIĞIN BİRDEN ÇOK PARÇASI OLABİLİR. Uzun kartlar parçalanıyor
    (`chunk_index`); bir varlığın puanı parçalarının EN YÜKSEĞİDİR, ortalaması
    değil. Ortalama alınsa, kartın tek bir bölümünde geçen çok isabetli bir
    ifade, ilgisiz bölümlerle seyreltilip sıralamadan düşer.
    """

    def __init__(self, vectors: dict[tuple[int, int], list[float]], model_name: str) -> None:
        self._vectors = vectors
        self._model_name = model_name

    @classmethod
    def load(cls, session: Session, *, entity_type: str, model_name: str) -> EmbeddingStore:
        """Veritabanından belirli model ve varlık türünün vektörlerini yükler."""
        satirlar = session.scalars(
            select(Embedding).where(
                Embedding.entity_type == entity_type,
                Embedding.model_name == model_name,
            )
        )
        vektorler = {
            (satir.entity_id, satir.chunk_index): unpack_vector(satir.embedding)
            for satir in satirlar
        }
        return cls(vektorler, model_name)

    @property
    def is_empty(self) -> bool:
        """Hiç vektör yüklenmedi mi? Arama bu durumda sözcüksel kanala düşer."""
        return not self._vectors

    @property
    def vector_count(self) -> int:
        """Yüklenen vektör (parça) sayısı."""
        return len(self._vectors)

    @property
    def dim(self) -> int:
        """Saklanan vektörlerin boyutu; depo boşsa 0.

        ⚠️ BOYUT DENETİMİ İÇİN GEREKLİ. `cosine()` uzunluk uyuşmazlığında
        sessizce 0.0 döndürüyor; bu, farklı bir gömme modeliyle üretilmiş
        vektörlerin bulunduğu bir depoda anlamsal kanalın **hiçbir hata
        vermeden ölmesi** demek. Ölçüldü: EVREN'in `bge-m3-embed` modeliyle
        üretilmiş 1.519 vektör `nomic-embed-text` etiketiyle kaydedilmişti
        (1024 boyut; oysa `nomic-embed-text` 768 üretir).
        """
        for vektor in self._vectors.values():
            return len(vektor)
        return 0

    @property
    def model_name(self) -> str:
        """Vektörlerin üretildiği model."""
        return self._model_name

    def search(self, query_vector: list[float], *, limit: int = 50) -> list[SemanticHit]:
        """Sorgu vektörüne en yakın varlıkları döndürür.

        Args:
            query_vector: Sorgunun gömme vektörü.
            limit: Döndürülecek en fazla varlık.

        Returns:
            Azalan benzerliğe göre sıralı varlıklar; her varlık BİR KEZ.
        """
        if not query_vector or self.is_empty:
            return []

        en_iyi: dict[int, tuple[float, int]] = {}
        for (entity_id, chunk_index), vektor in self._vectors.items():
            benzerlik = cosine(query_vector, vektor)
            mevcut = en_iyi.get(entity_id)
            if mevcut is None or benzerlik > mevcut[0]:
                en_iyi[entity_id] = (benzerlik, chunk_index)

        sirali = sorted(en_iyi.items(), key=lambda ikili: (-ikili[1][0], ikili[0]))
        return [
            SemanticHit(doc_id=entity_id, score=puan, chunk_index=parca)
            for entity_id, (puan, parca) in sirali[:limit]
        ]
