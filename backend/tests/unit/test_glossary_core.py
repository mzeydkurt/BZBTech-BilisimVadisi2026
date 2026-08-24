"""Glossary çekirdek terimleri — katılma ≠ katılım bankası ≠ katılım fonu."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import GlossaryTerm
from app.db.seed import GLOSSARY_SEED


def test_glossary_cekirdek_terimler_seedde() -> None:
    terimler = {row["term"] for row in GLOSSARY_SEED if not row.get("is_forbidden_conventional")}
    assert "Katılma Hesabı" in terimler
    assert "Katılım Bankası" in terimler
    assert "Katılım Fonu" in terimler
    assert "Murabaha" in terimler
    assert "Mudarabe" in terimler
    assert "İcare" in terimler
    assert "Karz-ı Hasen" in terimler


def test_glossary_seed_db(seeded_session: Session) -> None:
    kayitlar = {
        g.term
        for g in seeded_session.scalars(
            select(GlossaryTerm).where(GlossaryTerm.is_forbidden_conventional.is_(False))
        )
    }
    # Seed çalıştıysa en azından klasik terimler vardır.
    assert "Murabaha" in kayitlar or "Katılma Hesabı" in kayitlar
