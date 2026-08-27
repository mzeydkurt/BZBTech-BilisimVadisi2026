"""Şartname örnek senaryoları — regresyon kapısı (E6).

⚠️ ŞARTNAMENİN KENDİ ÖRNEĞİ PAZARLIK KONUSU DEĞİLDİR. Bu dosyadaki bir
başarısızlık "F1 biraz düştü" demek değil; şartnamede ADIYLA verilen bir
örneğin çözülemediği demek. Bu yüzden eşik yok, tolerans yok: hepsi geçmeli.

⚠️ SUSMA BEKLENTİLERİ DE TEST EDİLİR. C Bankası satırında masraf bilgisi
yok; sistemin o alanları boş bırakması, doldurması gerekenleri doldurması
kadar önemli (şartname 7). Yalnızca doldurmayı test eden bir kapı,
halüsinasyona açık kapı bırakır.
"""

from __future__ import annotations

import pytest

from scripts.spec_scenarios import SenaryoSonucu, olc


@pytest.fixture(scope="module")
def senaryolar() -> list[SenaryoSonucu]:
    """Şartname senaryolarını bir kez koşar."""
    return olc()


def test_uc_banka_satiri_da_kumede(senaryolar: list[SenaryoSonucu]) -> None:
    """⚠️ Kümeden bir satır düşerse ölçüm sessizce kolaylaşır."""
    kodlar = {s.kod for s in senaryolar}
    assert kodlar == {"s1-a", "s1-b", "s1-c"}


def test_doldurulmasi_gereken_alanlarin_tamami_dolu(senaryolar: list[SenaryoSonucu]) -> None:
    """Şartname tablosundaki her hücre üretilmeli."""
    eksik = [
        (s.kod, alan, beklenen, deger)
        for s in senaryolar
        for alan, (beklenen, deger, dogru, _) in s.dolu.items()
        if not dogru
    ]
    assert not eksik, f"Şartname senaryosunda çözülmeyen alan: {eksik}"


def test_bos_kalmasi_gereken_alanlarda_susuluyor(senaryolar: list[SenaryoSonucu]) -> None:
    """⚠️ ŞARTNAME 7 — bilgi yokken bilgi üretmeme.

    C Bankası satırında masraf bilgisi yok. Sistem oraya bir değer yazarsa
    bu bir halüsinasyondur ve gold set'te ölçülmesini beklemeye gerek yok:
    şartnamenin kendi örneği bunu doğrudan söylüyor.
    """
    uydurma = [
        (s.kod, alan, deger)
        for s in senaryolar
        for alan, (deger, susuldu) in s.bos.items()
        if not susuldu
    ]
    assert not uydurma, f"Kaynakta olmayan alan doldurulmuş: {uydurma}"


def test_her_dolu_alanin_kaniti_var(senaryolar: list[SenaryoSonucu]) -> None:
    """⚠️ KANITSIZ DEĞER SUNULMAZ. Kanıt yoksa kullanıcı "bu nereden geldi?"
    sorusunu yanıtlayamaz ve açıklanabilirlik iddiası çöker.
    """
    kanitsiz = [
        (s.kod, alan)
        for s in senaryolar
        for alan, (_, deger, _, kanit) in s.dolu.items()
        if deger is not None and not (kanit or "").strip()
    ]
    assert not kanitsiz, f"Kanıtsız üretilen alan: {kanitsiz}"


def test_kanit_kaynak_metinde_birebir_geciyor(senaryolar: list[SenaryoSonucu]) -> None:
    """⚠️ `clean_text[start:end] == evidence_text` değişmezinin sonucu.

    Kanıt kaynağın HAM DİLİMİ olmak zorunda; normalize edilmiş bir kopya
    arayüzde metnin yanlış yerini işaret eder.
    """
    kacak = [
        (s.kod, alan, kanit)
        for s in senaryolar
        for alan, (_, _, _, kanit) in s.dolu.items()
        if kanit and kanit not in s.metin
    ]
    assert not kacak, f"Kanıt kaynak metinde geçmiyor: {kacak}"


def test_konut_finansmani_siniflandirmasi_uc_satirda_da_var(
    senaryolar: list[SenaryoSonucu],
) -> None:
    """Üç satır da konut finansmanı; ürün türü ekseni bunu görmeli."""
    eksik = [
        s.kod for s in senaryolar if "konut_finansmani" not in s.etiketler.get("product_type", [])
    ]
    assert not eksik, f"`konut_finansmani` etiketi çıkmayan satır: {eksik}"
