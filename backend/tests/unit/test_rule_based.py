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


# ── Sadakat puanı ve ödül tutarı ──────────────────────────
#
# ⚠️ AŞAĞIDAKİ METİNLERİN HEPSİ GERÇEK BANKA SAYFALARINDAN. Her biri 50
# kampanyalık gold set'te ölçülmüş bir kaçağı temsil ediyor; kalıplar
# "sadeleştirilirse" o kaçaklar geri gelir.


@pytest.mark.parametrize(
    ("metin", "beklenen"),
    [
        # ⚠️ Marka adı tutar ile ödül adının ARASINDA: "TL" ile "Lira"
        # bitişik arandığında 6 kampanya kaçıyordu.
        ("Akaryakıt Harcamalarınıza 400 TL Bankkart Lira!", "400"),
        ("Seyahat Alışverişlerinize 3.500 TL'ye varan ParafPara!", "3500"),
        # ⚠️ "Mil" TL cinsinden değil; yalnızca sadakat puanı sayılır.
        ("Yeni Mobil Müşterilerine 10.000 Mil'e Varan Fırsat!", "10000"),
    ],
)
def test_sadakat_puani_cikarilir(metin: str, beklenen: str) -> None:
    """Sadakat programı birimi tutardan ayrı bir marka adıyla yazılıyor."""
    assert _deger(metin, "loyalty_points") == beklenen


@pytest.mark.parametrize(
    ("metin", "beklenen"),
    [
        # ⚠️ Tipografik kesme işareti (U+2019), ASCII değil — bu tek karakter
        # yüzünden gold set'te birden çok ödül tutarı kaçıyordu.
        ("Yemek Harcamalarına 1.000 TL’ye Varan Nakit İade!", "1000"),
        ("Alışverişinizde 250 TL'ye varan hediye çeki.", "250"),
        # ⚠️ "nakit ödül" (Hayat Finans) ödül adları listesinde yoktu.
        ("Davet eden müşteri 500 TL nakit ödül kazanır.", "500"),
    ],
)
def test_odul_tutari_kesme_isareti_ve_odul_adiyla_cikarilir(metin: str, beklenen: str) -> None:
    """Kesme işareti çeşidi ve ödül adı sözlüğü ödül tutarını etkiler."""
    assert _deger(metin, "reward_amount_try") == beklenen


def test_mil_tl_olmadigi_icin_odul_tutari_yazilmaz() -> None:
    """⚠️ "10.000 Mil" bir TL tutarı DEĞİLDİR.

    Gold set'te bu kampanyalarda yalnızca `loyalty_points` dolu;
    `reward_amount_try` boş. Ayrımı `REWARD_AMOUNT` kalıbının zorunlu
    `TL` koşulu yapar.
    """
    metin = "Yeni Mobil Müşterilerine 10.000 Mil'e Varan Fırsat!"

    assert _deger(metin, "loyalty_points") == "10000"
    assert _deger(metin, "reward_amount_try") is None


def test_toplu_ust_sinir_odul_sayilmaz() -> None:
    """⚠️ "toplamda 5 kişi için maksimum 10.000 TL" TEK ÖDÜL DEĞİLDİR.

    Kampanyanın bir kişiye vaat ettiği ödül 2.000'dir; 10.000 bütün
    davetlerin toplam tavanı. "En yüksek" kuralı burada yanlış cevap
    veriyordu.
    """
    metin = (
        "Davet eden müşteri 2.000 TL nakit ödül kazanır. Koşulların sağlanması "
        "halinde kişi başı maksimum 2.000 TL, toplamda 5 kişi için maksimum "
        "10.000 TL nakit ödül kazanabilir."
    )

    assert _deger(metin, "reward_amount_try") == "2000"


def test_komsu_kampanya_karti_odulu_ezmez() -> None:
    """⚠️ Ziraat sayfalarının sonuna KOMŞU KAMPANYA KARTI sızıyor.

    Sızan kartın tutarı daha büyük olabiliyor; "en yüksek" kuralı o zaman
    başka bir kampanyanın ödülünü bu kampanyaya yazıyordu.
    """
    metin = (
        "Akaryakıt Harcamalarınıza 400 TL Bankkart Lira! Kampanya sona ermiştir. "
        "Banka kampanyayı durdurma hakkına sahiptir. "
        "Elektrikli Araç Şarj İstasyonlarında 750 TL Bankkart Lira!"
    )

    assert _deger(metin, "reward_amount_try") == "400"
    assert _deger(metin, "loyalty_points") == "400"


# ── Nakit iade oranı ──────────────────────────────────────


@pytest.mark.parametrize(
    ("metin", "beklenen"),
    [
        # ⚠️ Oran ile "iade" arasına çekim eki giriyor.
        ("İşlem tutarlarınızın %18’i kadar nakit iade kartınıza yatırılır.", "18"),
        ("Yemek harcamalarının %10’una kadar nakit iade kazanın.", "10"),
        ("%5 nakit iade fırsatı.", "5"),
    ],
)
def test_nakit_iade_orani_cekim_ekiyle_cikarilir(metin: str, beklenen: str) -> None:
    """Ek araya girdiğinde de oran bulunmalı."""
    assert _deger(metin, "cashback_pct") == beklenen


# ── Tutar sınırları ───────────────────────────────────────


def test_aralik_iki_uca_da_yazilir() -> None:
    """Aralık ifadesi hem alt hem üst sınır verir."""
    metin = "TROY kartlarınız ile yapacağınız 1.000 TL - 100.000 TL arası sağlık harcamaları."

    assert _deger(metin, "min_spend_try") == "1000"
    assert _deger(metin, "max_spend_try") == "100000"


def test_finansman_baglami_yoksa_finansman_limiti_yazilmaz() -> None:
    """⚠️ Her harcama eşiği bir finansman limiti DEĞİLDİR."""
    metin = "Hediye çeki kampanyasında 1.000 TL - 5.000 TL arası alışverişler geçerlidir."

    assert _deger(metin, "max_spend_try") == "5000"
    assert _deger(metin, "financing_amount_max") is None


def test_kademeli_tablo_ust_sinir_uretmez() -> None:
    """⚠️ ARA KADEMENİN üst ucu kampanyanın tavanı değildir.

    "20.000 TL ve Üzeri" en üst kademe — yani üst sınır YOK. Ara kademeden
    tavan yazmak 16 kampanyada asgariden küçük bir azami üretiyordu.
    """
    metin = (
        "Bir aylık maaşı 10.000 TL - 14.999 TL arası olanlara 3.000 TL; "
        "20.000 TL ve Üzeri olanlara 8.000 TL verilir."
    )

    assert _deger(metin, "min_spend_try") == "20000"
    assert _deger(metin, "max_spend_try") is None


def test_ust_sinir_alt_sinir_uretmez() -> None:
    """⚠️ "100.000 TL'ye kadar" alt sınır BELİRTMEZ; sıfır yazılmaz."""
    metin = "Anlaşmalı mağazalarda 100.000 TL’ye kadar alışverişlerinizde 6 taksit."

    assert _deger(metin, "max_spend_try") == "100000"
    assert _deger(metin, "min_spend_try") is None
    assert _deger(metin, "financing_amount_min") is None
    assert _deger(metin, "financing_amount_max") is None


def test_taksit_finansman_limiti_uretmez() -> None:
    """Kart taksiti finansman tavanı değildir."""
    metin = "TROY kartınızla 50.000 TL - 150.000 TL arası alışverişlerinizde 9 taksit."

    assert _deger(metin, "max_spend_try") == "150000"
    assert _deger(metin, "financing_amount_max") is None


def test_finansman_cumlesinde_limit_yazilir() -> None:
    """Gerçek finansman bağlamında aralık limit olarak kalır."""
    metin = "Konut finansmanında 50.000 TL - 2.000.000 TL arası kullandırım."

    assert _deger(metin, "financing_amount_min") == "50000"
    assert _deger(metin, "financing_amount_max") == "2000000"


def test_indirim_yuzdesi_kar_payi_yazilmaz() -> None:
    """'%10 oranlı nakit iade' kâr payı değildir."""
    metin = "Seçili üye işyerlerinde %10 oranlı nakit iade kazanın."

    assert _deger(metin, "profit_rate_pct") is None


def test_iki_oranda_kar_payi_kanitlisi_kalir() -> None:
    """İki sayı varsa yalnızca 'kâr payı' kanıtlı olan yazılır."""
    metin = "Kâr payı oranı %7,50, kampanyalı alternatif oran %12,50 olarak uygulanır."

    assert _deger(metin, "profit_rate_pct") == "7.50"


def test_iki_belirsiz_oran_yazilmaz() -> None:
    """İki oran da 'kâr payı' demiyorsa birini seçmek FP üretir."""
    metin = "Özel oranlı finansman %7,50, kampanyalı oran %12,50 ile sunulur."

    assert _deger(metin, "profit_rate_pct") is None


def test_ucret_alinmaz_has_no_fee_yazar() -> None:
    """Gold'daki kaçırılan masrafsızlık ifadeleri."""
    metin = "Kampanya kapsamında tahsis ücreti alınmaz, dosya masrafı yoktur."

    assert _deger(metin, "has_no_fee") == "true"


# ── Katılma hesabı paylaşım oranı ─────────────────────────


def test_paylasim_orani_bolu_bicimindeki_orandan_cikarilir() -> None:
    """⚠️ Paylaşım oranı YÜZDE DEĞİL, `98/2` biçiminde yayımlanıyor.

    Müşteri payı İKİNCİ sayıdır; birinci sayı bankada kalan pay. Yanlış
    sayı alınırsa katılma hesapları tam ters sıralanır.
    """
    metin = "Katılma Hesabı açın, 98/2 kâr paylaşım oranı ile birikime başlayın!"

    assert _deger(metin, "profit_share_rate_pct") == "2"


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
