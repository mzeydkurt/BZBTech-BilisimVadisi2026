"""Gövde — ürün / oran / glossary varlıkları."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.retrieval.corpus import build_corpus, invalidate_corpus


def test_corpus_glossary_ve_parmak_izi(seeded_session: Session) -> None:
    invalidate_corpus()
    corpus = build_corpus(seeded_session)
    # Seed glossary dolu olmalı.
    assert corpus.glossary_docs is not None
    assert len(corpus.glossary_docs) >= 1
    # İkinci çağrı aynı imza ile önbellekten.
    corpus2 = build_corpus(seeded_session)
    assert corpus2 is corpus
