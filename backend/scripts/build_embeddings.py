"""Kart metinlerinden gömme vektörleri üretir — mevcut semantic.py kanalını doldurur.

⚠️ YENİ VEKTÖR DB / FAISS YOK. `embeddings` tablosuna yazar; brute-force kosinüs
yeterli. `source_hash == card_hash` iken yeniden gömme.

Kullanım:
    python -m scripts.build_embeddings
    python -m scripts.build_embeddings --entity-type campaign
    python -m scripts.build_embeddings --limit 50
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import select

from app.ai.providers import active_embedding_model, get_provider
from app.ai.providers.base import LLMProviderError
from app.config import get_settings
from app.db.models import Embedding, EntityCard
from app.db.session import SessionLocal
from app.logging_config import configure_logging, get_logger
from app.retrieval.semantic import pack_vector

logger = get_logger(__name__)

# Kart zaten kısa özet; agresif chunk yok. Tek parça (chunk_index=0).
BATCH = 16


async def _gom(
    *,
    entity_types: list[str],
    limit: int | None,
    force: bool,
) -> int:
    settings = get_settings()
    try:
        provider = get_provider(settings)
    except ValueError as exc:
        print(f"Sağlayıcı kurulamadı: {exc}")
        return 1

    # ⚠️ ETİKET, VEKTÖRÜ GERÇEKTEN ÜRETEN MODELDEN GELİR. `settings.embedding_model`
    # okumak, EVREN ile üretilmiş bir vektörü `nomic-embed-text` diye
    # etiketliyordu (bkz. `active_embedding_model` gerekçesi).
    model_name = active_embedding_model(settings)
    yazilan = 0
    atlanan = 0

    with SessionLocal() as session:
        stmt = select(EntityCard).where(EntityCard.entity_type.in_(entity_types))
        if limit:
            stmt = stmt.limit(limit)
        kartlar = list(session.scalars(stmt).all())

        for i in range(0, len(kartlar), BATCH):
            grup = kartlar[i : i + BATCH]
            metinler: list[str] = []
            hedefler: list[EntityCard] = []
            for kart in grup:
                mevcut = session.scalar(
                    select(Embedding).where(
                        Embedding.entity_type == kart.entity_type,
                        Embedding.entity_id == kart.entity_id,
                        Embedding.chunk_index == 0,
                        Embedding.model_name == model_name,
                    )
                )
                if mevcut is not None and mevcut.source_hash == kart.card_hash and not force:
                    atlanan += 1
                    continue
                metinler.append(kart.card_text)
                hedefler.append(kart)

            if not metinler:
                continue

            try:
                vektorler = await provider.embed(metinler)
            except (NotImplementedError, LLMProviderError, ValueError) as exc:
                print(
                    f"Gömme üretilemedi ({type(exc).__name__}: {exc}). "
                    "Lexical-only devam eder; 3B local embed hazır olunca tekrar çalıştırın."
                )
                return 0

            for kart, vektor in zip(hedefler, vektorler, strict=True):
                mevcut = session.scalar(
                    select(Embedding).where(
                        Embedding.entity_type == kart.entity_type,
                        Embedding.entity_id == kart.entity_id,
                        Embedding.chunk_index == 0,
                        Embedding.model_name == model_name,
                    )
                )
                blob = pack_vector(vektor)
                if mevcut is None:
                    session.add(
                        Embedding(
                            entity_type=kart.entity_type,
                            entity_id=kart.entity_id,
                            chunk_index=0,
                            chunk_text=kart.card_text,
                            embedding=blob,
                            dim=len(vektor),
                            model_name=model_name,
                            source_hash=kart.card_hash,
                        )
                    )
                else:
                    mevcut.chunk_text = kart.card_text
                    mevcut.embedding = blob
                    mevcut.dim = len(vektor)
                    mevcut.source_hash = kart.card_hash
                yazilan += 1
            session.commit()
            logger.info("gomme_parti", yazilan=yazilan, atlanan=atlanan)

    print(f"Gömme tamam: yazılan={yazilan}, atlanan(hash aynı)={atlanan}, model={model_name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description="entity_cards → embeddings")
    parser.add_argument(
        "--entity-type",
        action="append",
        dest="entity_types",
        help="Tekrarlanabilir: campaign, product, product_rate (varsayılan: hepsi)",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--force", action="store_true", help="Hash aynı olsa da yeniden göm")
    args = parser.parse_args(argv)
    types = args.entity_types or ["campaign", "product", "product_rate"]
    return asyncio.run(_gom(entity_types=types, limit=args.limit, force=args.force))


if __name__ == "__main__":
    raise SystemExit(main())
