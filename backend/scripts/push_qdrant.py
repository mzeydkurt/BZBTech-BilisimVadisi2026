"""`embeddings` tablosundaki vektörleri Qdrant'a yükler.

⚠️ GÖMMEYİ YENİDEN ÜRETMEZ. Kaynak `embeddings` tablosudur; vektörler orada
zaten var. Aynı vektörü ikinci kez servise sormak, ortak kullanılan EVREN'i
boşuna meşgul etmek ve 4 dakika beklemek olurdu. Sıra:

    python dev.py gomme-uret      # kart → vektör (EVREN'e gider)
    python dev.py qdrant-yukle    # vektör → Qdrant (EVREN'e GİTMEZ)

⚠️ YEREL TABLO SİLİNMEZ. Qdrant'a yüklendikten sonra `embeddings` yerinde
kalır: kapalı ağ (airgap) gösteriminde anlamsal kanal ona düşer. İkisi
birbirinin yedeğidir.

⚠️ YÜK (payload) KİMLİK İÇİN ZORUNLU. Qdrant nokta kimliği türetilmiş bir
tamsayı; hangi kampanyaya ait olduğu YALNIZCA payload'dan okunur. Payload'sız
nokta arama sonucunda atlanır.

Kullanım:
    python -m scripts.push_qdrant
    python -m scripts.push_qdrant --yeniden-kur      # boyut değiştiyse
    python -m scripts.push_qdrant --entity-type campaign
"""

from __future__ import annotations

import argparse
import asyncio
import sys

#  Windows konsolu varsayılan olarak cp1254 kullanıyor
# `UnicodeEncodeError` ile ÇÖKÜYOR — yükleme TAMAMLANDIKTAN
# sonra, yani iş bitmişken. `recover_database.py` ile aynı hata.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import select

from app.ai.providers import active_embedding_model
from app.config import get_settings
from app.db.models import Embedding
from app.db.session import SessionLocal
from app.logging_config import configure_logging, get_logger
from app.retrieval.qdrant_store import (
    QdrantDimensionError,
    QdrantPoint,
    QdrantStore,
    QdrantUnavailableError,
)
from app.retrieval.semantic import unpack_vector

logger = get_logger(__name__)


async def _yukle(*, entity_types: list[str] | None, yeniden_kur: bool) -> int:
    """Vektörleri okur ve Qdrant'a yükler.

    Returns:
        Süreç çıkış kodu.
    """
    ayarlar = get_settings()
    if not ayarlar.qdrant_url:
        print("QDRANT_URL tanımlı değil. `.env` dosyasına ekleyin.")
        return 1

    model = active_embedding_model(ayarlar)

    with SessionLocal() as oturum:
        stmt = select(Embedding).where(Embedding.model_name == model)
        if entity_types:
            stmt = stmt.where(Embedding.entity_type.in_(entity_types))
        satirlar = list(oturum.scalars(stmt))

    if not satirlar:
        # ⚠️ "Vektör yok" ile "Qdrant çalışmıyor" AYRI durumlar. Boş tabloyla
        # koleksiyon kurup başarı bildirmek, arama boş dönerken nedeni
        # gizlemek olurdu.
        print(
            f"'{model}' modeliyle üretilmiş vektör bulunamadı. "
            "Önce `python dev.py gomme-uret` çalıştırın."
        )
        return 1

    boyutlar = {satir.dim for satir in satirlar}
    if len(boyutlar) != 1:
        print(f"HATA: tabloda birden fazla vektör boyutu var: {sorted(boyutlar)}")
        print("Gömmeler farklı modellerle üretilmiş; `gomme-uret` ile yeniden üretin.")
        return 1
    boyut = boyutlar.pop()

    depo = QdrantStore(
        base_url=ayarlar.qdrant_url,
        api_key=ayarlar.qdrant_api_key,
        collection=ayarlar.qdrant_collection,
        model_name=model,
    )

    try:
        await depo.ensure_collection(dim=boyut, recreate=yeniden_kur)
    except QdrantDimensionError as exc:
        print(f"HATA: {exc}")
        return 1
    except QdrantUnavailableError as exc:
        print(f"HATA: {exc}")
        return 1

    noktalar = [
        QdrantPoint(
            entity_type=satir.entity_type,
            entity_id=satir.entity_id,
            chunk_index=satir.chunk_index,
            vector=unpack_vector(satir.embedding),
            payload={
                "entity_type": satir.entity_type,
                "entity_id": satir.entity_id,
                "chunk_index": satir.chunk_index,
                "model_name": satir.model_name,
                # Kart metninin ilk bölümü: Qdrant arayüzünde noktanın ne
                # olduğunu görebilmek için. Arama bu alanı kullanmıyor.
                "onizleme": satir.chunk_text[:200],
            },
        )
        for satir in satirlar
    ]

    try:
        yazilan = await depo.upsert(noktalar)
    except QdrantUnavailableError as exc:
        print(f"HATA: {exc}")
        return 1

    await depo.describe()
    print(
        f"Qdrant yükleme tamam: {yazilan} nokta · koleksiyon="
        f"{ayarlar.qdrant_collection} · boyut={boyut} · model={model}"
    )
    print(f"Koleksiyondaki toplam nokta: {depo.vector_count}")
    print("⚠️ Yerel `embeddings` tablosu SİLİNMEDİ — airgap gösteriminde kullanılır.")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Komut satırı girişi."""
    configure_logging()
    ayristirici = argparse.ArgumentParser(
        description="`embeddings` tablosundaki vektörleri Qdrant'a yükler."
    )
    ayristirici.add_argument(
        "--entity-type",
        action="append",
        dest="entity_types",
        help="Yalnızca bu varlık türü (birden çok kez verilebilir)",
    )
    ayristirici.add_argument(
        "--yeniden-kur",
        action="store_true",
        help="Koleksiyonu silip yeniden oluşturur (gömme boyutu değiştiyse gerekir)",
    )
    args = ayristirici.parse_args(argv)
    return asyncio.run(_yukle(entity_types=args.entity_types, yeniden_kur=args.yeniden_kur))


if __name__ == "__main__":
    sys.exit(main())
