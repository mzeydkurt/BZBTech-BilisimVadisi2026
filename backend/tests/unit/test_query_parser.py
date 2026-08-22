"""Sorgu anlama katmanı — 30 soruluk sorgu kümesine karşı ölçüm.

⚠️ SORGU KÜMESİ GOLD SET'TEN TÜRETİLMEDİ. `data/gold/gold_set.jsonl` cevap
anahtarıdır; ondan sorgu üretmek sızıntı olur ve ölçümü şişirir. Kümedeki 30
soru gerçek veri setine (608 kampanya / 10 banka) bakılarak elle yazıldı.

⚠️ BEKLENEN DEĞER SONUCA GÖRE DÜZELTİLMEZ. Bir sorgu tutmuyorsa düzeltilecek
yer ayrıştırıcıdır; kümedeki beklenti ancak beklentinin KENDİSİ yanlışsa
değişir ve o zaman gerekçesi `not` alanına yazılır.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.retrieval.query import parse_query

SORGU_KUMESI = Path(__file__).parents[1] / "fixtures" / "query_set" / "sorgu_kumesi.json"


def _kume() -> list[dict[str, Any]]:
    veri = json.loads(SORGU_KUMESI.read_text(encoding="utf-8"))
    sorgular: list[dict[str, Any]] = veri["sorgular"]
    return sorgular


def _kimlik(kayit: dict[str, Any]) -> str:
    return str(kayit["soru"])


class TestSorguKumesi:
    """Kümedeki her soru için beklenen süzgeçler çıkarılıyor mu?"""

    @pytest.mark.parametrize("kayit", _kume(), ids=_kimlik)
    def test_banka_kodlari(self, kayit: dict[str, Any]) -> None:
        plan = parse_query(kayit["soru"])
        assert set(plan.bank_codes) == set(kayit.get("bank_codes", []))

    @pytest.mark.parametrize("kayit", _kume(), ids=_kimlik)
    def test_eksen_suzgecleri(self, kayit: dict[str, Any]) -> None:
        """Beklenen değerler çıkarılanların ALT KÜMESİ olmalı.

        Eşitlik istenmiyor: "konut finansmanı" sorgusu hem `konut_finansmani`
        hem başka bir geçerli etiket üretebilir. Eksik olan hatadır, fazlası
        değil.
        """
        plan = parse_query(kayit["soru"])
        for eksen, beklenen in kayit.get("axis", {}).items():
            assert set(beklenen) <= set(plan.axis_filters.get(eksen, ())), eksen

    @pytest.mark.parametrize("kayit", _kume(), ids=_kimlik)
    def test_durumlar(self, kayit: dict[str, Any]) -> None:
        plan = parse_query(kayit["soru"])
        assert set(plan.statuses) == set(kayit.get("statuses", []))

    @pytest.mark.parametrize("kayit", _kume(), ids=_kimlik)
    def test_sayisal_kisitlar(self, kayit: dict[str, Any]) -> None:
        plan = parse_query(kayit["soru"])
        beklenen = {
            (alan, islec, Decimal(deger)) for alan, islec, deger in kayit.get("numeric", [])
        }
        cikan = {(k.field, k.op, k.value) for k in plan.numeric}
        assert cikan == beklenen

    @pytest.mark.parametrize("kayit", _kume(), ids=_kimlik)
    def test_niyet(self, kayit: dict[str, Any]) -> None:
        assert parse_query(kayit["soru"]).intent == kayit["intent"]


class TestSertKapiKurallari:
    """Sessizce yanlış süzgeç üretme ihtimallerinin tek tek sınanması."""

    def test_yon_isaretcisi_olmadan_kisit_uretilmez(self) -> None:
        """⚠️ "12 taksit" bir eşik değil betimlemedir.

        Yön işaretçisi yokken kısıt üretmek listeyi sessizce daraltır: metinde
        "12 taksit" yazan kampanya, 12'den az taksit sunan kampanyaları da
        eleyerek dönerdi.
        """
        assert parse_query("12 taksit yapan giyim kampanyası").numeric == ()

    def test_yuzde_isareti_tutar_alanina_yazilmaz(self) -> None:
        """⚠️ Sprint 2'de ölçülen hata: "%80" ifadesi `amount_max` sanılıyordu."""
        plan = parse_query("kâr payı %2'nin altında olan kampanyalar")
        assert [k.field for k in plan.numeric] == ["profit_rate_pct"]

    def test_isaretcisiz_ciplak_sayi_kisit_uretmez(self) -> None:
        """Hangi alana ait olduğu bilinmeyen sayı süzgece çevrilmez."""
        assert parse_query("2026 kampanyaları").numeric == ()

    def test_en_az_sayiyla_gelirse_kisit_olur(self) -> None:
        """ "en az 250 TL" bir üstünlük sorusu değil, eşiktir."""
        plan = parse_query("En az 250 TL ödül veren market kampanyaları")
        assert plan.intent == "search"
        assert (plan.numeric[0].field, plan.numeric[0].op) == ("reward_amount_try", "gte")

    def test_en_az_sayisiz_gelirse_toplama_olur(self) -> None:
        plan = parse_query("En az kâr payı oranı hangi bankada?")
        assert plan.intent == "aggregate"
        assert plan.aggregate is not None
        assert plan.aggregate.direction == "min"

    def test_bilinmeyen_ile_suresi_dolmus_ayridir(self) -> None:
        """⚠️ CLAUDE.md kuralı: `unknown` ≠ `expired`."""
        assert parse_query("tarihi belli olmayan kampanyalar").statuses == ("unknown",)
        assert parse_query("süresi dolmuş kampanyalar").statuses == ("expired",)

    def test_suzgec_cikarilamayan_sorgu_reddedilmez(self) -> None:
        """⚠️ "Anlamadım" ile "sonuç yok" ayrı şeylerdir.

        Süzgeç çıkarılamayan sorgu serbest metin aramasına düşer; boş plan
        döndürmek arama yapılmadığı hâlde "sonuç bulunamadı" göstermek olurdu.
        """
        plan = parse_query("evlenecek çiftlere uygun bir şey var mı?")
        assert plan.intent == "search"
        assert plan.has_filters is False
        assert plan.free_terms  # serbest terimler BM25 kanalına gidiyor

    def test_her_suzgecin_kaniti_var(self) -> None:
        """Kaynaksız süzgeç arayüzde gösterilemez; her sinyalin kanıtı olmalı."""
        plan = parse_query("Kuveyt Türk'te emeklilere market indirimi, kâr payı %2 altında")
        assert plan.signals
        for sinyal in plan.signals:
            assert sinyal.evidence.strip()
            assert sinyal.label.strip()

    def test_kisaltilmis_banka_adi_taninir(self) -> None:
        assert parse_query("KT'de akaryakıt kampanyası").bank_codes == ("kuveyt_turk",)
        assert parse_query("T.O.M. Katılım kampanyaları").bank_codes == ("tom_bank",)

    def test_ciplak_eksen_sozcugu_yalnizca_yedek(self) -> None:
        """⚠️ Çıplak "finansman", daha özgül bir değer eşleştiyse eklenmez.

        Aksi hâlde her konut sorgusu genel finansman kampanyalarını da içine
        alır ve isabet düşer.
        """
        genel = parse_query("En uzun vadeli finansman hangi bankada?")
        assert "finansman" in genel.axis_filters["product_type"]

        ozgul = parse_query("konut finansmanı kampanyaları")
        assert "konut_finansmani" in ozgul.axis_filters["product_type"]
        assert "finansman" not in ozgul.axis_filters["product_type"]
