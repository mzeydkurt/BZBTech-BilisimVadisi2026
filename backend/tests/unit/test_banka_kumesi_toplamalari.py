"""Banka kümesi toplamaları — yokluk ve banka sayımı.

Ölçülmüş iki sessiz hata:

1. "Kaç banka taşıt finansmanı veriyor?" sorgusu `search`e düşüyor, toplama
   hiç kurulmuyor ve MODEL sayıyı kendi üretiyordu: "iki banka" yanıtı geldi,
   gerçek sayı 7. Projenin "model sayı üretmez, sayılar veritabanından gelir"
   güvencesinin doğrudan ihlali.
2. "Hangi bankada taşıt finansmanı kampanyası yok?" sorusuna taşıt finansmanı
   ORANLARI listeleniyordu — tam ters yanıt.
"""

from __future__ import annotations

import pytest

from app.retrieval.aggregate import compute, describe
from app.retrieval.query import AggregateSpec, parse_query

# ── Niyet ayrıştırma ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "soru",
    [
        "kaç banka taşıt finansmanı veriyor",
        "kaç banka konut finansmanı sunuyor",
        "kaç kurum katılma hesabı açıyor",
    ],
)
def test_banka_sayimi_toplamaya_gider(soru: str) -> None:
    plan = parse_query(soru)
    assert plan.intent == "aggregate"
    assert plan.aggregate is not None
    assert plan.aggregate.kind == "count_banks"


@pytest.mark.parametrize(
    "soru",
    [
        "hangi bankada taşıt finansmanı kampanyası yok",
        "hiç kampanyası olmayan banka var mı",
        "hangi bankalarda katılma hesabı yok",
        "taşıt kampanyası sunmayan bankalar",
    ],
)
def test_yokluk_sorusu_toplamaya_gider(soru: str) -> None:
    plan = parse_query(soru)
    assert plan.aggregate is not None
    assert plan.aggregate.kind == "absence"


def test_banka_sayimi_kampanya_sayimini_ezmez() -> None:
    """⚠️ "kaç banka" ifadesi "kac" içerir; `count`tan ÖNCE denenmeli.
    Sıra bozulursa banka sayımı kampanya sayımına dönüşür (7 yerine 482)."""
    assert parse_query("kaç banka taşıt finansmanı veriyor").aggregate.kind == "count_banks"  # type: ignore[union-attr]
    assert parse_query("kaç tane kampanya var").aggregate.kind == "count"  # type: ignore[union-attr]


def test_banka_baglami_olmayan_olumsuzlama_yokluk_sorusu_degil() -> None:
    """ "Tahsis ücreti olmayan ürünler" süzgeçli ARAMADIR, yokluk sorusu değil.
    Bağlam koşulu olmasa her olumsuzlama banka yokluk sorusuna dönüşürdü."""
    plan = parse_query("tahsis ücreti olmayan finansman ürünleri")
    assert plan.aggregate is None or plan.aggregate.kind != "absence"


# ── Hesap ────────────────────────────────────────────────────────────────

EVREN = ("Adil Katılım", "Albaraka Türk", "Kuveyt Türk", "Ziraat Katılım")


class _Doc:
    """CampaignDoc yerine geçen asgari nesne (compute yalnızca bank_name okur)."""

    def __init__(self, bank_name: str) -> None:
        self.bank_name = bank_name
        self.metrics: dict[str, object] = {}
        self.campaign_id = 0


def test_yokluk_kumesi_evrenden_hesaplanir() -> None:
    docs = [_Doc("Albaraka Türk"), _Doc("Kuveyt Türk"), _Doc("Kuveyt Türk")]
    h = compute(docs, AggregateSpec(kind="absence"), tum_bankalar=EVREN)  # type: ignore[arg-type]
    assert h.banks_with == ("Albaraka Türk", "Kuveyt Türk")
    assert h.banks_without == ("Adil Katılım", "Ziraat Katılım")


def test_evren_verilmezse_yokluk_bos_doner() -> None:
    """⚠️ Evren geçilmezse kaydı olmayan banka GÖRÜNMEZ. Bu durum sessizce
    "yok yok" gibi okunmasın diye testle sabitlenir."""
    docs = [_Doc("Albaraka Türk")]
    h = compute(docs, AggregateSpec(kind="absence"))  # type: ignore[arg-type]
    assert h.banks_without == ()


def test_sifir_sayili_banka_dokumde_kalir() -> None:
    """CLAUDE.md: "veri yok bilgisi de başlı başına bir bulgudur, gizlenmez"."""
    docs = [_Doc("Kuveyt Türk")]
    h = compute(docs, AggregateSpec(kind="count"), tum_bankalar=EVREN)  # type: ignore[arg-type]
    assert h.by_bank is not None
    assert h.by_bank["Adil Katılım"] == 0
    assert h.by_bank["Kuveyt Türk"] == 1


# ── Cümle ────────────────────────────────────────────────────────────────


def test_yokluk_cumlesi_var_olanlari_yanit_sanmaz() -> None:
    docs = [_Doc("Albaraka Türk")]
    h = compute(docs, AggregateSpec(kind="absence"), tum_bankalar=EVREN)  # type: ignore[arg-type]
    metin = describe(h)
    # Yanıt YOK olanlarla başlar; var olanlar bağlam olarak sonra gelir.
    assert metin.index("Adil Katılım") < metin.index("Albaraka Türk")
    assert "OLMAYAN" in metin


def test_yokluk_yoksa_bu_da_soylenir() -> None:
    docs = [_Doc(ad) for ad in EVREN]
    h = compute(docs, AggregateSpec(kind="absence"), tum_bankalar=EVREN)  # type: ignore[arg-type]
    assert "karşılamayan banka yok" in describe(h)


def test_banka_sayimi_cumlesi_sayiyi_ve_listeyi_verir() -> None:
    docs = [_Doc("Albaraka Türk"), _Doc("Kuveyt Türk")]
    h = compute(docs, AggregateSpec(kind="count_banks"), tum_bankalar=EVREN)  # type: ignore[arg-type]
    metin = describe(h)
    assert "2 banka" in metin
    assert "Albaraka Türk" in metin and "Kuveyt Türk" in metin


def test_sifir_kampanyali_banka_count_cumlesinde_gorunur() -> None:
    docs = [_Doc("Kuveyt Türk")]
    h = compute(docs, AggregateSpec(kind="count"), tum_bankalar=EVREN)  # type: ignore[arg-type]
    assert "Hiç kaydı olmayan" in describe(h)
    assert "Adil Katılım" in describe(h)
