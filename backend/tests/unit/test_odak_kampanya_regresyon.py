"""Kampanya odağı — "Bu kampanyanın bitiş tarihi ne zaman?".

Ölçüldü (100 soruluk gerçek test havuzu, oturum S3 · 3. tur): bağlam devri
GERÇEKLEŞİYOR, çip görünüyor, ama sonuç 0 dönüyor ve kullanıcıya "elimizdeki
veriyle yanıt verilemiyor" deniyordu. Üç ayrı neden vardı:

1. `previous_focus` yalnızca BANKAYI taşıyordu, kampanyayı değil.
2. Önceki turdan devralınan 5 eksen süzgeci odak kaydı eliyordu.
3. Sert süzgeç kapısı yetmiyordu: erişim ondan ÖNCE çalışıyor ve sorguda
   içerik terimi olmadığı için BM25 o kaydı hiç getirmiyordu.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.db.models.chat import ChatSession
from app.retrieval.query import parse_query
from app.retrieval.relevance import refers_to_focus_entity
from app.schemas.chat import AnswerBlock, ChatResponse, ChatResultItem, RetrievalReport
from app.services import chat_session_service as css


@pytest.mark.parametrize(
    "soru",
    [
        "Bu kampanyanın bitiş tarihi ne zaman?",
        "bu kampanyada kaç ay taksit var",
        "söz konusu kampanya kimlere geçerli",
        "o kampanyanın koşulları neler",
        "bu ürünün kâr payı oranı nedir",
    ],
)
def test_kampanya_atfi_taninir(soru: str) -> None:
    assert refers_to_focus_entity(soru)


@pytest.mark.parametrize(
    "soru",
    [
        "Kuveyt Türk taşıt finansmanı oranı nedir",
        "hangi bankada en uzun vade var",
        "peki onun koşulları neler",
    ],
)
def test_kampanya_atfi_yanlis_pozitif_vermez(soru: str) -> None:
    """ "Peki onun koşulları" BANKA anaforasıdır; tek kayda kilitlenmemeli."""
    assert not refers_to_focus_entity(soru)


def _yanit(sonuclar: list[ChatResultItem]) -> ChatResponse:
    return ChatResponse(
        query="test",
        intent="search",
        answer=AnswerBlock(text="test", source="model"),
        results=sonuclar,
        retrieval=RetrievalReport(
            corpus_size=10, returned=len(sonuclar), lexical_used=True, semantic_used=False
        ),
    )


def _oge(kid: int, kod: str) -> ChatResultItem:
    return ChatResultItem(
        campaign_id=kid,
        bank_code=kod,
        bank_name=kod,
        title=f"kampanya-{kid}",
        status="active",
        source_url="https://example.test",
        card_text="",
    )


def _tur(db: Session, oturum: ChatSession, *, turn: int, resp: ChatResponse, cid: str) -> None:
    css.record_turn(
        db,
        oturum,
        turn_index=turn,
        user_text="soru",
        plan=parse_query("Kuveyt Türk kampanyaları"),
        response=resp,
        completion_id=cid,
    )


def test_tek_sonuc_odak_olur(db_session: Session) -> None:
    oturum = css.create_session(db_session)
    db_session.flush()
    _tur(db_session, oturum, turn=0, resp=_yanit([_oge(585, "vakif_katilim")]), cid="c1")
    db_session.refresh(oturum)
    banka, kampanya = css.previous_focus(oturum)
    assert (banka, kampanya) == ("vakif_katilim", 585)


def test_cok_sonucta_en_ust_kayit_odak_olur(db_session: Session) -> None:
    """⚠️ Bu bir SEÇİM. "Belirsizse None" kuralı burada garanti başarısızlık
    üretiyordu; kullanıcı açıkça "bu kampanya" dediğinde yanıt metninin
    başladığı kayıt kastedilir. Bağ çip olarak görünür."""
    oturum = css.create_session(db_session)
    db_session.flush()
    _tur(
        db_session,
        oturum,
        turn=0,
        resp=_yanit([_oge(101, "kuveyt_turk"), _oge(102, "kuveyt_turk")]),
        cid="c1",
    )
    db_session.refresh(oturum)
    banka, kampanya = css.previous_focus(oturum)
    assert kampanya == 101
    assert banka == "kuveyt_turk"


def test_farkli_bankalarda_banka_belirsiz_kampanya_belli(db_session: Session) -> None:
    oturum = css.create_session(db_session)
    db_session.flush()
    _tur(
        db_session,
        oturum,
        turn=0,
        resp=_yanit([_oge(201, "albaraka"), _oge(202, "kuveyt_turk")]),
        cid="c1",
    )
    db_session.refresh(oturum)
    banka, kampanya = css.previous_focus(oturum)
    assert banka is None
    assert kampanya == 201


def test_sonuc_yoksa_odak_yok(db_session: Session) -> None:
    oturum = css.create_session(db_session)
    db_session.flush()
    _tur(db_session, oturum, turn=0, resp=_yanit([]), cid="c1")
    db_session.refresh(oturum)
    assert css.previous_focus(oturum) == (None, None)


def test_odak_sert_suzgecte_tek_kayda_indirir() -> None:
    """Odak kapısı diğer süzgeçlerden ÖNCE gelir ve tek kayıt bırakır."""
    from dataclasses import replace

    from app.retrieval.corpus import CampaignDoc
    from app.retrieval.search import filter_all

    class _Corpus:
        def __init__(self, docs: dict[int, CampaignDoc]) -> None:
            self.docs = docs

        @property
        def size(self) -> int:
            return len(self.docs)

    def _doc(kid: int) -> CampaignDoc:
        return CampaignDoc(
            campaign_id=kid,
            bank_code="kuveyt_turk",
            bank_name="Kuveyt Türk",
            title=f"k{kid}",
            card_text="",
            status="active",
            source_url="https://example.test",
            date_precision="exact",
            axis_values={},
            metrics={},
            summary="",
        )

    corpus = _Corpus({1: _doc(1), 2: _doc(2), 3: _doc(3)})
    plan = replace(parse_query("kampanyalar"), focus_campaign_id=2)
    docs, rapor = filter_all(corpus, plan)  # type: ignore[arg-type]
    assert [d.campaign_id for d in docs] == [2]
    assert rapor.rejected.get("odak") == 2
