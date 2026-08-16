"""Kural tabanlı çıkarıcı.

⚠️ EN KRİTİK TEST `test_ofset_kaynakla_birebir_uyusuyor`. Ofset kayarsa
sistem doğru değeri bulur ama kanıt olarak metnin YANLIŞ yerini gösterir —
hata fırlatmadan, yalnızca açıklanabilirlik iddiasını çökerterek.
"""

from __future__ import annotations

import pytest

from app.ai.extraction import extract_rule_based, solved_fields


def _deger(metin: str, alan: str) -> str | None:
    """Metinden bir alanın normalize değerini döndürür."""
    for bulgu in extract_rule_based(metin):
        if bulgu.field_name == alan:
            return bulgu.value_normalized
    return None


# ── Ofset doğrulaması (KAPI A4 geçiş koşulu) ──────────────


@pytest.mark.parametrize(
    "metin",
    [
        "Kampanya kapsamında %2,05 kâr payı oranı uygulanır.",
        "Vade farksız 4 aya varan taksit fırsatı. 01.01.2026 - 31.12.2026 arası geçerlidir.",
        "5.000 TL ve üzeri harcamalarda 250 TL nakit iade kazanın.",
        "120 aya kadar vade ile masrafsız finansman.",
        "Tahsis ücreti %0,50 · dosya masrafı 500 TL.",
    ],
)
def test_ofset_kaynakla_birebir_uyusuyor(metin: str) -> None:
    """⚠️ `clean_text[start:end] == evidence_text` HER ZAMAN doğru olmalı.

    Kanıt normalize edilmiş bir kopya olursa ofset kayar ve arayüz "bu değer
    nereden geldi?" sorusuna metnin yanlış yerini göstererek yanıt verir.
    """
    bulgular = extract_rule_based(metin)

    assert bulgular, "en az bir alan çıkarılmalı"
    for bulgu in bulgular:
        assert metin[bulgu.evidence_char_start : bulgu.evidence_char_end] == bulgu.evidence_text


# ── Kâr payı oranı ────────────────────────────────────────


@pytest.mark.parametrize(
    ("metin", "beklenen"),
    [
        ("Kâr payı oranı %2,05 olarak uygulanır.", "2.05"),
        ("%2,05 kâr payı ile finansman.", "2.05"),
        ("%1,89 oranlı özel finansman fırsatı.", "1.89"),
    ],
)
def test_kar_payi_orani_cikarilir(metin: str, beklenen: str) -> None:
    """Türkçe ondalık virgül doğru çözülür: `%2,05` → `2.05`."""
    assert _deger(metin, "profit_rate_pct") == beklenen


@pytest.mark.parametrize(
    "metin",
    [
        "Vade farksız 6 taksit imkânı.",
        "Peşin fiyatına 3 taksit.",
    ],
)
def test_vade_farksiz_orani_sifir_yapar(metin: str) -> None:
    """⚠️ "vade farksız" oranın SIFIR olduğunu söyler, bilinmeyen değil.

    Bilinmeyen sayılırsa bu kampanyalar "en düşük kâr payı" karşılaştırmasına
    hiç girmez.
    """
    assert _deger(metin, "profit_rate_pct") == "0"


@pytest.mark.parametrize(
    "metin",
    [
        "Konut finansmanında avantajlı kâr payı fırsatı sizi bekliyor.",
        "Özel oranlı finansman için şubelerimize başvurun.",
    ],
)
def test_dolayli_ifadeden_oran_cikarilmaz(metin: str) -> None:
    """⚠️ EN KRİTİK NEGATİF TEST.

    "avantajlı kâr payı" bir ORAN BELİRTMEZ. Buradan sayı üretmek, kaynakta
    olmayan bilgi uydurmaktır.
    """
    assert _deger(metin, "profit_rate_pct") is None


# ── Taksit / vade ayrımı ──────────────────────────────────


def test_taksit_ile_vade_karistirilmaz() -> None:
    """⚠️ "4 aya varan TAKSİT" taksit sayısıdır, vade değil."""
    metin = "120 aya kadar vade ve 4 aya varan taksit fırsatı."

    assert _deger(metin, "installment_count") == "4"
    assert _deger(metin, "term_months_max") == "120"


def test_sadece_taksit_varsa_vade_cikarilmaz() -> None:
    """Taksit ifadesinden vade türetilmez."""
    metin = "Alışverişlerinizde 6 aya varan taksit."

    assert _deger(metin, "installment_count") == "6"
    assert _deger(metin, "term_months_max") is None


# ── Tutarlar ──────────────────────────────────────────────


def test_harcama_esigi_ve_odul_ayrisir() -> None:
    """⚠️ Aynı cümlede iki tutar var; hangisi eşik hangisi ödül?

    Ayrım yalnızca komşu kelimeden (yakınlık kuralı) anlaşılır.
    """
    metin = "3.000 TL ve üzeri harcamalarda 150 TL nakit iade."

    assert _deger(metin, "min_spend_try") == "3000"
    assert _deger(metin, "reward_amount_try") == "150"


def test_kademeli_odulde_en_yuksek_alinir() -> None:
    """Kılavuz kuralı: kademeli yapıda kampanyanın vaat ettiği üst değer."""
    metin = "3.000 TL üzeri 150 TL, 7.500 TL üzeri 400 TL hediye."

    assert _deger(metin, "reward_amount_try") == "400"


def test_turkce_binlik_ayraci_dogru_cozulur() -> None:
    """`5.000` beş bindir, beş değil — İngilizce konvansiyonun tersi."""
    metin = "Asgari 50.000 TL harcama gereklidir."

    assert _deger(metin, "min_spend_try") == "50000"


# ── Ücret ve masraf ───────────────────────────────────────


def test_masrafsiz_iki_alan_birden_uretir() -> None:
    """Kılavuz kuralı: "masrafsız" → `has_no_fee=true` VE `file_fee_try=0`."""
    metin = "Masrafsız finansman imkânı."

    assert _deger(metin, "has_no_fee") == "true"
    assert _deger(metin, "file_fee_try") == "0"


def test_acik_masraf_tutari_sifiri_ezmez() -> None:
    """Metinde gerçek bir masraf tutarı varsa 0 yazılmaz."""
    metin = "Dosya masrafı 500 TL olarak uygulanır."

    assert _deger(metin, "file_fee_try") == "500"


def test_tahsis_ucreti_cikarilir() -> None:
    """Tahsis ücreti oranı ayrı bir alandır."""
    assert _deger("Tahsis ücreti %0,50 olarak alınır.", "allocation_fee_pct") == "0.50"


# ── Tarih ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("metin", "baslangic", "bitis"),
    [
        ("Kampanya 01.01.2026 - 31.12.2026 arasında geçerlidir.", "2026-01-01", "2026-12-31"),
        ("02 Ocak 2026 - 31 Aralık 2026 tarihleri arasında.", "2026-01-02", "2026-12-31"),
    ],
)
def test_tarih_araligi_cikarilir(metin: str, baslangic: str, bitis: str) -> None:
    """Ayrıştırma SPRINT 1 kütüphanesine devredilir, burada tekrarlanmaz."""
    assert _deger(metin, "start_date") == baslangic
    assert _deger(metin, "end_date") == bitis


def test_tarih_yoksa_alan_uretilmez() -> None:
    """⚠️ Türkiye Finans'ın TÜM kampanyaları böyle.

    Tarih yokluğu "süresi dolmuş" DEĞİLDİR ve uydurulmaz.
    """
    metin = "Kart kampanyamızdan yararlanmak için şubelerimize başvurun."

    assert _deger(metin, "start_date") is None
    assert _deger(metin, "end_date") is None


# ── Ödül türü ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("metin", "beklenen"),
    [
        ("250 TL nakit iade kazanın.", "nakit_iade"),
        ("500 TL Bankkart Lira hediye.", "puan"),
        ("%30 indirim fırsatı.", "indirim"),
    ],
)
def test_odul_turu_kontrollu_sozlukten(metin: str, beklenen: str) -> None:
    """Ödül türü serbest metin değil, sabit listeden bir değerdir."""
    assert _deger(metin, "reward_type") == beklenen


# ── Boş ve bulunamayan durumlar ───────────────────────────


@pytest.mark.parametrize("metin", ["", "   \n  ", None])
def test_bos_metinde_cikarim_yapilmaz(metin: str | None) -> None:
    """Boş metin için çağrı yapılmaz, hata da verilmez."""
    assert extract_rule_based(metin) == []


def test_bulunamayan_alan_icin_kayit_uretilmez() -> None:
    """⚠️ "Bilgi yok" durumu kaydın YOKLUĞUYLA temsil edilir.

    Sıfır ya da boş dize yazmak halüsinasyonun ta kendisidir.
    """
    bulgular = extract_rule_based("Bankamızın kampanyalarını takip edin.")

    assert all(bulgu.value_normalized not in ("", "None") for bulgu in bulgular)


def test_cozulen_alanlar_llm_icin_listelenir() -> None:
    """KAPI A6'daki `already_found` filtresi bu kümeyi kullanır."""
    metin = "%2,05 kâr payı oranı ile 01.01.2026 - 31.12.2026 arası geçerlidir."

    cozulen = solved_fields(extract_rule_based(metin))

    assert "profit_rate_pct" in cozulen
    assert "start_date" in cozulen
    # Çözülmeyen alan listede OLMAMALI; yoksa LLM'e hiç sorulmaz.
    assert "reward_amount_try" not in cozulen
