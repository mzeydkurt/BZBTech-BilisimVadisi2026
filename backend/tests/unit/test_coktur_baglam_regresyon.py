"""Çok turlu bağlam devri — ölçülmüş sessiz hataların regresyonu.

Hepsinin ortak özelliği: yanıt biçimsel olarak geçerliydi, HATA FIRLATMIYORDU,
ama içerik yanlıştı. İkinci soruda alakasız cevap şikâyeti buradan geliyordu.

Önceki davranış "süzgeç yoksa önceki turdan devral"dı. Devir kararı sorgunun
KENDİ kanıtına değil, süzgecin yokluğuna bağlıydı; bu yüzden yeni bir konu
açan soru da önceki bankaya kilitleniyordu.
"""

from __future__ import annotations

import pytest

from app.retrieval.query import QueryPlan, merge_with_previous, parse_query
from app.retrieval.relevance import is_anaphoric_query, opens_scope


def _birlestir(once: str, sonra: str) -> QueryPlan:
    return merge_with_previous(parse_query(sonra), parse_query(once))


# ── DevralınmaMASI gerekenler ─────────────────────────────────────────────


def test_kendi_ekseni_olan_soru_bankayi_devralmaz() -> None:
    """Ölçüldü: Kuveyt Türk'e kilitlenip 'hangi bankada' sorusu tek banka
    yanıtı dönüyordu."""
    p = _birlestir(
        "Kuveyt Türk'ün alışveriş puanı kampanyaları",
        "taşıt finansmanında en uzun vade hangi bankada",
    )
    assert p.bank_codes == ()
    assert "tasit_finansmani" in p.axis_filters.get("product_type", ())


def test_tum_bankalar_sorgusu_onceki_bankayi_ezmez() -> None:
    """Ölçüldü: 'tüm bankalarda' denmesine rağmen Albaraka + yeni_musteri
    süzgeci taşınıyordu."""
    p = _birlestir(
        "Albaraka'da yeni müşteri kampanyası var mı",
        "tüm bankalarda kaç kampanya var",
    )
    assert p.bank_codes == ()
    assert p.axis_filters == {}


def test_kapsam_acan_soru_bankayi_dusurur_konuyu_tutar() -> None:
    """'peki' var (anafora) ama 'hangi bankada' kapsamı açıyor: konu kalır,
    banka düşer."""
    p = _birlestir("Albaraka konut finansmanı", "peki hangi bankada en uzun vade")
    assert p.bank_codes == ()
    assert "konut_finansmani" in p.axis_filters.get("product_type", ())


def test_farkli_urun_sorusu_onceki_bankayi_devralmaz() -> None:
    p = _birlestir(
        "Emlak Katılım taşıt finansmanı",
        "hangi bankalar konut finansmanı veriyor",
    )
    assert p.bank_codes == ()


def test_tanim_sorusu_baglam_tasimaz() -> None:
    p = _birlestir("Kuveyt Türk kampanyaları", "katılım bankacılığında kâr payı nedir")
    assert p.bank_codes == ()


# ── DevralınMASI gerekenler (gerçek takip soruları) ───────────────────────


def test_anafora_bankayi_ve_ekseni_devralir() -> None:
    p = _birlestir("Kuveyt Türk alışveriş puanı", "peki onun koşulları neler")
    assert p.bank_codes == ("kuveyt_turk",)
    assert p.axis_filters.get("benefit") == ("puan_mil",)
    assert any(s.evidence == "önceki soru" for s in p.signals)


def test_kisa_vade_takibi_devralir() -> None:
    p = _birlestir("Kuveyt Türk konut finansmanı", "Peki 6 aylıkta?")
    assert "kuveyt_turk" in p.bank_codes


def test_banka_degisince_konu_korunur() -> None:
    """Yalnızca banka adı yazan soru, konuyu önceki turdan devralır."""
    p = _birlestir("Kuveyt Türk taşıt finansmanı", "Albaraka")
    assert p.bank_codes == ("albaraka",)
    assert "tasit_finansmani" in p.axis_filters.get("product_type", ())


# ── Yardımcı belirleyiciler ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "soru",
    ["hangi bankada en yüksek", "tüm bankalarda kaç tane", "bankalar arası karşılaştır"],
)
def test_opens_scope_dogru(soru: str) -> None:
    assert opens_scope(soru)


@pytest.mark.parametrize("soru", ["Kuveyt Türk konut finansmanı", "taşıt kampanyaları"])
def test_opens_scope_yanlis_pozitif_yok(soru: str) -> None:
    assert not opens_scope(soru)


@pytest.mark.parametrize("soru", ["peki onun koşulları", "aynısı Albaraka'da var mı", "devam et"])
def test_anafora_dogru(soru: str) -> None:
    assert is_anaphoric_query(soru)


def test_anafora_yanlis_pozitif_yok() -> None:
    assert not is_anaphoric_query("Kuveyt Türk taşıt finansmanı oranı nedir")


# ── Ürün yedeği: rastlantısal tek terim eşleşmesi ─────────────────────────


def test_urun_yedegi_tek_rastlantisal_eslesmede_tetiklenmez() -> None:
    """Ölçüldü: "bana bir şiir yaz" sorgusu YALNIZCA "bana" simgesiyle 6.98
    puan alıp Hayat Finans "Bana Bunu Al" ürününü döndürüyor, sohbet de
    ilgisiz bir tanıtım metni üretiyordu.

    Puan eşiği ayırt etmiyor (çöp 6.98 > gerçek 7.73); kapsama oranı ayırt
    ediyor. Bu test kapının kuralını sabitler: eşleşen anlamlı terimler,
    sorgunun anlamlı terimlerinin en az yarısını kapsamalı.
    """
    from app.retrieval.lexical import tokenize
    from app.retrieval.query import STOPWORDS

    def kapsar(sorgu: str, eslesen: tuple[str, ...]) -> bool:
        terimler = tokenize(sorgu)
        anlamli = {k for k in terimler if len(k) >= 3 and k not in STOPWORDS and not k.isdigit()}
        gereken = max(1, (len(anlamli) + 1) // 2) if anlamli else 0
        return not gereken or len(anlamli & set(eslesen)) >= gereken

    # Çöp: uzun sorgu, tek rastlantısal eşleşme.
    assert not kapsar("bana bir şiir yaz", ("bana",))
    assert not kapsar("python kodu yaz", ("kodu",))
    assert not kapsar("kedim hasta ne yapmalıyım", ("ne",))

    # Gerçek: eşleşme sorgunun gövdesini kapsıyor.
    assert kapsar("taşıt finansmanı oranları", ("tasit", "finansmani", "oranlari"))
    assert kapsar("Bana Bunu Al nedir", ("al", "bana", "bunu"))
    assert kapsar("konut finansmanı en uzun vade", ("en", "finansmani", "konut", "uzun"))
    # Tek simgeli meşru arama (ürün adı) engellenmez.
    assert kapsar("Togg", ("togg",))
