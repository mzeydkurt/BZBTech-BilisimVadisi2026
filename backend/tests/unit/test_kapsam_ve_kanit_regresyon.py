"""Canlı kullanımda bildirilen üç sorun — hepsi kanıt/kapsam uyumsuzluğu.

1. "Hangi bankalar var?" serbest metin aramasına düşüyor, rastgele 3 kampanya
   kartı dönüyor ve model o kartlardaki banka adlarını "bulunan bankalar"
   diye sunuyordu: "Dünya Katılım, T.O.M. ve Albaraka Türk bulunmaktadır."
   Gerçek sayı 10. Kapsam sorusunun yanıtı ÖRNEKLEM olamaz.
2. "Ben kimim?" sorusuna reddetme yanıtı dönerken kanıt olarak süresi dolmuş
   bir "Hac ve Umre Finansmanı" kampanyası gösteriliyordu. Başlık "Yanıtın
   dayandığı kanıt" der; yanıtlanamayan sorunun dayanağı olamaz.
3. "En uygun kredi hangisinde konut için" sorgusundan tek süzgeç
   `sector=konut_gayrimenkul` çıkıyor; ürün süzgeci yalnızca `product_type`a
   baktığı için ihtiyaç ve araç finansmanı ürünleri kanıt gösteriliyordu.
"""

from __future__ import annotations

import pytest

from app.retrieval.query import parse_query
from app.schemas.chat import AnswerBlock
from app.services.chat_service import _hedef_urun_tipleri, _yanitlanamadi_mi

# ── 1) Liste sorusu ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "soru",
    [
        "hangi bankalar var",
        "hangi bankalar kapsamda",
        "bankaları listele",
        "hangi katılım bankaları var",
    ],
)
def test_liste_sorusu_toplamaya_gider(soru: str) -> None:
    plan = parse_query(soru)
    assert plan.aggregate is not None
    assert plan.aggregate.kind == "bank_roster"


@pytest.mark.parametrize(
    ("soru", "beklenen"),
    [
        # ⚠️ Bir testin yakaladığı sıralama hatam: liste sorusu başa alınınca
        # "hangi bankalarDA ... YOK" da liste sorusuna dönüşüyordu.
        ("hangi bankalarda katılma hesabı yok", "absence"),
        ("hangi bankada taşıt kampanyası yok", "absence"),
        ("kaç banka konut finansmanı veriyor", "count_banks"),
        ("hangi bankalar var", "bank_roster"),
    ],
)
def test_banka_sorulari_karismaz(soru: str, beklenen: str) -> None:
    plan = parse_query(soru)
    assert plan.aggregate is not None
    assert plan.aggregate.kind == beklenen


# ── 2) Yanıtlanamayan yanıt kanıt taşımaz ────────────────────────────────


def test_reddetme_kanitsiz_sayilir() -> None:
    assert _yanitlanamadi_mi(AnswerBlock(text="herhangi bir metin", source="refusal"))


def test_sablon_metni_kanitsiz_sayilir() -> None:
    metin = "Bu soruya elimizdeki veriyle yanıt verilemiyor: sorgu süzgeçlerini sağlayan kayıt yok."
    assert _yanitlanamadi_mi(AnswerBlock(text=metin, source="model"))


def test_gecerli_yanit_kaniti_korur() -> None:
    assert not _yanitlanamadi_mi(
        AnswerBlock(text="Kuveyt Türk konut finansmanı oranı %3,50.", source="model")
    )


# ── 3) Sektör → ürün tipi eşlemesi ───────────────────────────────────────


def test_konut_sektoru_konut_urununu_hedefler() -> None:
    plan = parse_query("en uygun kredi hangisinde konut için")
    tipler = _hedef_urun_tipleri(plan)
    assert "konut_finansmani" in tipler
    assert "ihtiyac_finansmani" not in tipler
    assert "tasit_finansmani" not in tipler


def test_acik_urun_tipi_sektoru_ezer() -> None:
    """Ürün tipi doğrudan verilmişse sektörden türetme YAPILMAZ."""
    plan = parse_query("taşıt finansmanı oranları")
    tipler = _hedef_urun_tipleri(plan)
    assert "tasit_finansmani" in tipler
    assert "konut_finansmani" not in tipler


def test_karsiligi_olmayan_sektor_urun_uydurmaz() -> None:
    """⚠️ "giyim" sektörünün finansman ürünü karşılığı yoktur; uydurulmaz."""
    plan = parse_query("giyim kampanyaları")
    assert _hedef_urun_tipleri(plan) == set()
