"""Glossary çekirdek terimleri — katılma ≠ katılım bankası ≠ katılım fonu."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import GlossaryTerm
from app.db.seed import GLOSSARY_SEED
from app.retrieval.query import parse_query
from app.schemas.chat import ChatGlossaryItem
from app.services.chat_service import _top_from_glossary


def test_glossary_cekirdek_terimler_seedde() -> None:
    terimler = {row["term"] for row in GLOSSARY_SEED if not row.get("is_forbidden_conventional")}
    assert "Katılma Hesabı" in terimler
    assert "Standart Katılma Hesabı" in terimler
    assert "Ara Ödemeli Katılma Hesabı" in terimler
    assert "Katılım Bankası" in terimler
    assert "Katılım Fonu" in terimler
    assert "Dağıtılan Kâr Payı (Getiri)" in terimler
    assert "Stopaj (Katılma Getirisi)" in terimler
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


def test_tanim_niyeti() -> None:
    plan = parse_query("Kâr payı oranı ne demek?")
    assert plan.intent == "tanim"


def test_ara_odemeli_tanim_terimi() -> None:
    from app.core.normalization.text import ascii_fold_tr, lower_tr, normalize_text
    from app.retrieval.query import _tanim_terimi

    q = "Ara ödemeli katılma hesabı nedir, normal katılma hesabından farkı ne?"
    k = ascii_fold_tr(lower_tr(normalize_text(q)))
    assert _tanim_terimi(q, k) == "ara odemeli katilma hesabi"


def test_ara_odemeli_glossary_eslesme(seeded_session) -> None:
    from app.retrieval.corpus import build_corpus
    from app.retrieval.query import parse_query
    from app.services.chat_service import _tanim_glossary_kayitlari

    plan = parse_query("Ara ödemeli katılma hesabı nedir, normal katılma hesabından farkı ne?")
    corpus = build_corpus(seeded_session)
    docs = _tanim_glossary_kayitlari(corpus, plan)
    assert len(docs) == 2
    assert docs[0].term == "Ara Ödemeli Katılma Hesabı"
    assert docs[1].term == "Standart Katılma Hesabı"


def test_ara_odemeli_chat_api(api_client) -> None:
    veri = api_client.post(
        "/api/v1/chat",
        json={"query": ("Ara ödemeli katılma hesabı nedir, normal katılma hesabından farkı ne?")},
    ).json()
    assert veri["intent"] == "tanim"
    assert len(veri.get("glossary") or []) == 2
    assert veri["glossary"][0]["term"] == "Ara Ödemeli Katılma Hesabı"
    assert "vade" in veri["glossary"][0]["definition"].lower()
    assert veri["glossary"][1]["term"] == "Standart Katılma Hesabı"
    assert "fark" in veri["answer"]["text"].lower()


def test_top_from_glossary_tanimi_reasona_yazmaz() -> None:
    """Çift cevap önlemi: kart reason alanına tanım metni konmaz."""
    items = [
        ChatGlossaryItem(
            term_id=1,
            term="Kâr Payı Oranı",
            definition="Katılım bankacılığında faiz yerine kullanılan oran.",
            conventional_equivalent="Faiz oranı",
        )
    ]
    matches = _top_from_glossary(items)
    assert matches
    assert matches[0].reason is None or matches[0].reason == ""
    assert matches[0].title == "Kâr Payı Oranı"
