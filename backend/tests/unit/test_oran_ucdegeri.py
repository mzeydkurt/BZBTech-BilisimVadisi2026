"""Uç değer soruları ürün ORANLARI üzerinde hesaplanır.

Ölçüldü (100 soruluk gerçek test havuzu): "En düşük konut finansmanı kâr payı
oranı hangi katılım bankasında?" — rekabet analizinin en klasik sorusu —
*"uygun teklif bulunmamaktadır"* yanıtı dönüyordu. `aggregate.compute`
yalnızca KAMPANYA metriklerine bakıyor; oran verisi `product_rates`'te.
"""

from __future__ import annotations

from decimal import Decimal

from app.retrieval.corpus import ProductRateDoc
from app.retrieval.query import AggregateSpec, parse_query
from app.services.chat_service import _oran_ucdegeri


class _Corpus:
    def __init__(self, rate_docs: dict[int, ProductRateDoc]) -> None:
        self.rate_docs = rate_docs


def _oran(rid: int, kod: str, oran: str | None, tip: str = "konut_finansmani") -> ProductRateDoc:
    return ProductRateDoc(
        rate_id=rid,
        product_id=rid,
        bank_code=kod,
        bank_name=kod,
        product_name=f"urun-{rid}",
        product_type=tip,
        rate_type="financing_rate",
        card_text="",
        profit_rate_pct=None if oran is None else Decimal(oran),
        investor_share_pct=None,
        term_months=120,
        source_url=None,
    )


def _plan(soru: str):
    return parse_query(soru)


def test_en_dusuk_oran_bulunur() -> None:
    corpus = _Corpus({1: _oran(1, "albaraka", "3.50"), 2: _oran(2, "kuveyt_turk", "2.99")})
    kazanan, berabere, oransiz = _oran_ucdegeri(
        corpus,  # type: ignore[arg-type]
        _plan("en düşük konut finansmanı kâr payı oranı hangi bankada"),
        AggregateSpec(kind="extremum", field="profit_rate_pct", direction="min"),
    )
    assert kazanan is not None
    assert kazanan.bank_code == "kuveyt_turk"
    assert berabere == []
    assert oransiz == 0


def test_en_yuksek_oran_bulunur() -> None:
    corpus = _Corpus({1: _oran(1, "albaraka", "3.50"), 2: _oran(2, "kuveyt_turk", "2.99")})
    kazanan, _b, _o = _oran_ucdegeri(
        corpus,  # type: ignore[arg-type]
        _plan("en yüksek konut finansmanı kâr payı oranı hangi bankada"),
        AggregateSpec(kind="extremum", field="profit_rate_pct", direction="max"),
    )
    assert kazanan is not None
    assert kazanan.bank_code == "albaraka"


def test_beraberlik_gizlenmez() -> None:
    """⚠️ `aggregate.compute` ile aynı kural: aynı değeri taşıyanlar sayılır."""
    corpus = _Corpus(
        {
            1: _oran(1, "albaraka", "2.99"),
            2: _oran(2, "kuveyt_turk", "2.99"),
            3: _oran(3, "vakif_katilim", "3.50"),
        }
    )
    kazanan, berabere, _o = _oran_ucdegeri(
        corpus,  # type: ignore[arg-type]
        _plan("en düşük konut finansmanı kâr payı oranı hangi bankada"),
        AggregateSpec(kind="extremum", field="profit_rate_pct", direction="min"),
    )
    assert kazanan is not None
    assert len(berabere) == 1


def test_orani_olmayan_kayit_sayilir_ve_gizlenmez() -> None:
    """⚠️ KAPSAM YAZILIR: kaç kayıtta oran yok bilinmeden uç değer yanıltıcıdır."""
    corpus = _Corpus({1: _oran(1, "albaraka", "2.99"), 2: _oran(2, "kuveyt_turk", None)})
    kazanan, _b, oransiz = _oran_ucdegeri(
        corpus,  # type: ignore[arg-type]
        _plan("en düşük konut finansmanı kâr payı oranı hangi bankada"),
        AggregateSpec(kind="extremum", field="profit_rate_pct", direction="min"),
    )
    assert kazanan is not None
    assert oransiz == 1


def test_hic_oran_yoksa_kazanan_yok() -> None:
    corpus = _Corpus({1: _oran(1, "albaraka", None)})
    kazanan, _b, oransiz = _oran_ucdegeri(
        corpus,  # type: ignore[arg-type]
        _plan("en düşük konut finansmanı kâr payı oranı hangi bankada"),
        AggregateSpec(kind="extremum", field="profit_rate_pct", direction="min"),
    )
    assert kazanan is None
    assert oransiz == 1


def test_sifir_oran_kazanan_olabilir() -> None:
    """%0 gerçek bir değerdir (bedelsiz kampanya) — hesaptan DÜŞÜRÜLMEZ.
    Belirsizlik yanıtta yapısal not olarak bildirilir, veri değiştirilmez."""
    corpus = _Corpus({1: _oran(1, "albaraka", "0"), 2: _oran(2, "kuveyt_turk", "2.99")})
    kazanan, _b, _o = _oran_ucdegeri(
        corpus,  # type: ignore[arg-type]
        _plan("en düşük konut finansmanı kâr payı oranı hangi bankada"),
        AggregateSpec(kind="extremum", field="profit_rate_pct", direction="min"),
    )
    assert kazanan is not None
    assert kazanan.profit_rate_pct == Decimal("0")
