"""`completion_id` zinciri — bağlam hangi cevaptan devralınıyor?

Önceki davranış "oturumun SON turunu devral"dı. Kullanıcı sohbet geçmişinden
eski bir tura dönüp soru sorduğunda yanlış bağlam taşınıyordu; hata
fırlatmıyor, sadece alakasız yanıt üretiyordu.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models.chat import ChatSession
from app.retrieval.query import parse_query
from app.schemas.chat import AnswerBlock, ChatResponse, RetrievalReport
from app.services import chat_session_service as css


def _yanit(metin: str) -> ChatResponse:
    return ChatResponse(
        query="test",
        intent="search",
        answer=AnswerBlock(text=metin, source="computed"),
        retrieval=RetrievalReport(
            corpus_size=0,
            returned=0,
            lexical_used=True,
            semantic_used=False,
        ),
    )


def _tur(db: Session, oturum: ChatSession, *, turn: int, soru: str, cid: str) -> None:
    css.record_turn(
        db,
        oturum,
        turn_index=turn,
        user_text=soru,
        plan=parse_query(soru),
        response=_yanit("test"),
        completion_id=cid,
    )


def test_varsayilan_son_turu_devralir(db_session: Session) -> None:
    oturum = css.create_session(db_session)
    db_session.flush()
    _tur(db_session, oturum, turn=0, soru="Kuveyt Türk konut finansmanı", cid="cmpl-a")
    _tur(db_session, oturum, turn=1, soru="Albaraka taşıt finansmanı", cid="cmpl-b")
    db_session.refresh(oturum)

    plan, kimlik = css.previous_plan(oturum)
    assert kimlik == "cmpl-b"
    assert plan is not None
    assert plan.bank_codes == ("albaraka",)


def test_belirli_tura_baglanabilir(db_session: Session) -> None:
    """Geçmişten eski bir tura dönülünce bağlam O turdan gelir."""
    oturum = css.create_session(db_session)
    db_session.flush()
    _tur(db_session, oturum, turn=0, soru="Kuveyt Türk konut finansmanı", cid="cmpl-a")
    _tur(db_session, oturum, turn=1, soru="Albaraka taşıt finansmanı", cid="cmpl-b")
    db_session.refresh(oturum)

    plan, kimlik = css.previous_plan(oturum, "cmpl-a")
    assert kimlik == "cmpl-a"
    assert plan is not None
    assert plan.bank_codes == ("kuveyt_turk",)


def test_taninmayan_kimlik_sessizce_son_tura_dusmez(db_session: Session) -> None:
    """Yanlış turdan devralmak, hiç devralmamaktan daha kötü yanıt üretir."""
    oturum = css.create_session(db_session)
    db_session.flush()
    _tur(db_session, oturum, turn=0, soru="Kuveyt Türk konut finansmanı", cid="cmpl-a")
    db_session.refresh(oturum)

    plan, kimlik = css.previous_plan(oturum, "cmpl-yok")
    assert plan is None
    assert kimlik is None


def test_bos_oturumda_devir_yok(db_session: Session) -> None:
    oturum = css.create_session(db_session)
    db_session.flush()
    assert css.previous_plan(oturum) == (None, None)


def test_gecmis_completion_id_ile_doner(db_session: Session) -> None:
    """Arayüz zinciri geçmişten sürdürebilsin."""
    oturum = css.create_session(db_session)
    db_session.flush()
    _tur(db_session, oturum, turn=0, soru="Kuveyt Türk konut finansmanı", cid="cmpl-a")
    db_session.refresh(oturum)

    detay = css.session_detail(oturum)
    asistan = [m for m in detay.messages if m.role == "assistant"]
    assert [m.completion_id for m in asistan] == ["cmpl-a"]
    # user satırında NULL kalır.
    assert all(m.completion_id is None for m in detay.messages if m.role == "user")
