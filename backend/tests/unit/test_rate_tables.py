"""Yapısal oran tablosu ayrıştırma testleri.

Fixture canlı Türkiye Finans sayfasından alınmıştır; değerler gerçektir ve
görünmez karakterler korunmuştur.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.processing.rate_tables import (
    parse_ltv_matrices,
    parse_rate_tables,
    parse_vehicle_limit_matrices,
)

FIXTURE = "html/turkiye_finans/oran_tablolari.html"


class TestVaryantAyrimi:
    """⚠️ Varyant boyutu tablonun DIŞINDA, üstteki başlıkta yazılı."""

    def test_iki_tablo_ayri_varyant_olarak_okunur(self, read_fixture) -> None:  # type: ignore[no-untyped-def]
        tablolar = parse_rate_tables(read_fixture(FIXTURE))
        assert [t.variant_key for t in tablolar] == ["sigortali", "sigortasiz"]

    def test_ham_baslik_saklanir(self, read_fixture) -> None:  # type: ignore[no-untyped-def]
        tablolar = parse_rate_tables(read_fixture(FIXTURE))
        assert tablolar[0].variant_label
        assert "Sigortalı" in tablolar[0].variant_label

    def test_varyantlar_karismiyor(self, read_fixture) -> None:  # type: ignore[no-untyped-def]
        """Karışırsa "en düşük kâr payı" karşılaştırması yanlış çıkar."""
        sigortali, sigortasiz = parse_rate_tables(read_fixture(FIXTURE))
        assert sigortali.rows[0].profit_rate_pct == Decimal("4.20")
        assert sigortasiz.rows[0].profit_rate_pct == Decimal("6.10")


class TestGorunmezKarakterler:
    """⚠️ Başlıklarda kelimenin İÇİNDE zero-width space var."""

    def test_kolonlar_dogru_eslesir(self, read_fixture) -> None:  # type: ignore[no-untyped-def]
        """Ham dize karşılaştırması yapılsaydı tüm kolonlar boş kalırdı."""
        satir = parse_rate_tables(read_fixture(FIXTURE))[0].rows[0]
        assert satir.term_months == 3
        assert satir.profit_rate_pct == Decimal("4.20")
        assert satir.allocation_fee_pct == Decimal("0.50")
        assert satir.monthly_cost_pct == Decimal("5.77")
        assert satir.annual_cost_pct == Decimal("96.05")


class TestDegerAyristirma:
    """Türkçe ondalık ayracı ve birimsiz vade."""

    def test_turkce_virgul_dogru_okunur(self, read_fixture) -> None:  # type: ignore[no-untyped-def]
        """ "4,20%" -> 4.20 (4 değil, 420 değil)."""
        satir = parse_rate_tables(read_fixture(FIXTURE))[0].rows[0]
        assert satir.profit_rate_pct == Decimal("4.20")

    def test_birimsiz_vade_okunur(self, read_fixture) -> None:  # type: ignore[no-untyped-def]
        """⚠️ Oran tablolarında vade birimsiz yazılıyor ("3", "36")."""
        vadeler = [r.term_months for r in parse_rate_tables(read_fixture(FIXTURE))[0].rows]
        assert vadeler == [3, 12, 36]

    def test_her_satirda_kanit_metni(self, read_fixture) -> None:  # type: ignore[no-untyped-def]
        for tablo in parse_rate_tables(read_fixture(FIXTURE)):
            for satir in tablo.rows:
                assert satir.evidence_text


class TestIlgisizTablolar:
    """Oran taşımayan tablolar atlanır."""

    def test_belge_tablosu_alinmaz(self, read_fixture) -> None:  # type: ignore[no-untyped-def]
        """Sayfada 3 tablo var; yalnızca 2'si oran tablosu."""
        assert len(parse_rate_tables(read_fixture(FIXTURE))) == 2

    def test_bos_girdi(self) -> None:
        assert parse_rate_tables(None) == []
        assert parse_rate_tables("") == []
        assert parse_rate_tables("<html><body><p>Tablo yok</p></body></html>") == []

    def test_baslik_satiri_olmayan_tablo_atlanir(self) -> None:
        assert parse_rate_tables("<table><tr><td>3</td></tr></table>") == []


# ── LTV matrisi (konut değeri × enerji sınıfı) ─────────────
#
# ⚠️ HTML üç bankanın CANLI SAYFASINDAN alınan yapıyı birebir taklit eder.

LTV_HTML = """
<h3>Standart Konut Alımında Kullandırılabilecek Azami Tutar</h3>
<table>
  <tr><td colspan="4">KONUT ALIMINDA KULLANDIRILABİLECEK AZAMİ KREDİ TUTARI</td></tr>
  <tr><td rowspan="2">Konut Değeri</td><td colspan="3">Enerji Sınıf</td></tr>
  <tr><td>A-B</td><td>C</td><td>DİĞER</td></tr>
  <tr><td>Değer &lt;= 5 Milyon TL</td>
      <td>Değer x 90%</td><td>Değer x 80%</td><td>Değer x 70%</td></tr>
  <tr><td>5 Milyon - 7 Milyon TL</td>
      <td>Değer x 80%</td><td>Değer x 70%</td><td>Değer x 60%</td></tr>
  <tr><td>20 Milyon TL Üzeri</td>
      <td>Değer x 40%</td><td>Değer x 30%</td><td>Değer x 20%</td></tr>
</table>
"""


def test_ltv_matrisi_her_hucreyi_ayri_satir_yazar() -> None:
    """⚠️ Matris TEK bir orana indirgenmez.

    %90 yalnızca 5 milyon altı A-B sınıfında geçerli; 20 milyon üstü DİĞER
    sınıfta oran %20. İndirgeme pahalı konutlarda bankayı olduğundan cömert
    gösterirdi.
    """
    matrisler = parse_ltv_matrices(LTV_HTML)

    assert len(matrisler) == 1
    assert len(matrisler[0].cells) == 9  # 3 değer bandı × 3 enerji sınıfı


@pytest.mark.parametrize(
    ("sinif", "alt", "ust", "beklenen"),
    [
        ("A-B", None, Decimal("5000000"), Decimal("90")),
        ("DİĞER", None, Decimal("5000000"), Decimal("70")),
        ("A-B", Decimal("5000000"), Decimal("7000000"), Decimal("80")),
        ("DİĞER", Decimal("20000000"), None, Decimal("20")),
    ],
)
def test_ltv_deger_bandi_ve_sinif_dogru_eslesir(
    sinif: str, alt: Decimal | None, ust: Decimal | None, beklenen: Decimal
) -> None:
    """Değer bandının üç yazım biçimi de doğru uçlara çevrilmeli."""
    hucreler = parse_ltv_matrices(LTV_HTML)[0].cells

    eslesen = [
        h
        for h in hucreler
        if h.energy_class == sinif and h.amount_min == alt and h.amount_max == ust
    ]
    assert len(eslesen) == 1, f"{sinif} {alt}-{ust} bandı bulunamadı"
    assert eslesen[0].ltv_max_pct == beklenen


def test_enerji_sinif_basligi_son_harfsiz_de_taninir() -> None:
    """⚠️ Emlak Katılım başlığı "Enerji Sınıf" yazıyor, "Sınıfı" değil.

    Bankanın dizgi hatası; tam eşleşme arandığında Emlak'ın matrisi hiç
    bulunamıyordu.
    """
    assert parse_ltv_matrices(LTV_HTML)[0].cells


def test_oran_tablosu_olmayan_sayfada_ltv_uretilmez() -> None:
    """Enerji sınıfı başlığı olmayan tablo LTV matrisi sayılmaz."""
    html = "<table><tr><th>Vade</th><th>Tutar</th></tr><tr><td>12</td><td>100 TL</td></tr></table>"

    assert parse_ltv_matrices(html) == []


def test_vehicle_limit_matrices_parsing() -> None:
    html = """
    <table>
        <tr><th>Kasko/Satış Değeri</th>
            <th>Finansman Tutarının Taşıt Tutarına Oranı</th>
            <th>Vade Üst Sınırı (Ay)</th></tr>
        <tr><td>0 - 400.000 TL</td><td>%70</td><td>48</td></tr>
        <tr><td>400.001 - 800.000 TL</td><td>%50</td><td>36</td></tr>
        <tr><td>2.000.001 TL ve üzeri</td><td>%0</td><td>Kullandırılmayacaktır.</td></tr>
    </table>
    """
    limits = parse_vehicle_limit_matrices(html)
    assert len(limits) == 3
    assert limits[0].asset_value_min == Decimal("0")
    assert limits[0].asset_value_max == Decimal("400000")
    assert limits[0].financing_ratio_pct == Decimal("70")
    assert limits[0].term_months_max == 48

    assert limits[2].asset_value_min == Decimal("2000001")
    assert limits[2].financing_ratio_pct == Decimal("0")
    assert limits[2].term_months_max is None


# ── Stopaj satırı ayıklama ─────────────────────────────────
#
# ⚠️ HTML Ziraat Katılım'ın CANLI paylaşım tablosundan alınmıştır: banka,
# bölüşüm satırlarının hemen altına vade bazlı stopaj oranını da koyuyor.

STOPAJ_HTML = """
<table>
  <caption>Kar Paylasim Oranlari</caption>
  <tr><th>Tutar</th><th>1 Aylık</th><th>3 Aylık</th></tr>
  <tr><td>10.000-24.999</td><td>30/70</td><td>30/70</td></tr>
  <tr><td>Stopaj Oranı</td><td>25%</td><td>25%</td></tr>
</table>
"""


def test_stopaj_satiri_paylasim_orani_sanilmaz() -> None:
    """⚠️ Stopaj bir VERGİ oranıdır, katılımcı payı değildir.

    Satır dizilimi bölüşüm satırlarıyla birebir aynı; ayıklanmazsa "%25"
    `investor_share_pct=25` diye yazılır ve gerçekte katılımcıya %70 veren
    banka karşılaştırmada en kötü sıraya düşer. Ölçüldü: canlı veride 17
    satır bu şekilde kirlenmişti.
    """
    satirlar = [r for t in parse_rate_tables(STOPAJ_HTML) for r in t.rows]

    assert satirlar, "bölüşüm satırı da düşmemeli"
    assert all("stopaj" not in (r.evidence_text or "").casefold() for r in satirlar)
    assert all(r.investor_share_pct != Decimal("25") for r in satirlar)


def test_stopaj_ayiklamasi_gercek_paylasim_satirini_korur() -> None:
    """Ayıklama fazla geniş olmamalı: 30/70 satırı yerinde kalır."""
    satirlar = [r for t in parse_rate_tables(STOPAJ_HTML) for r in t.rows]

    paylar = {r.investor_share_pct for r in satirlar}
    assert Decimal("30") in paylar


# ── Ek teşvik ve boş hesaplayıcı satırı ────────────────────

ILAVE_GETIRI_HTML = """
<table>
  <tr><th>Vade Süresi</th><th>İlave Getiri Oranları</th></tr>
  <tr><td>3 Ay</td><td>%1</td></tr>
  <tr><td>12 Ay</td><td>%3</td></tr>
</table>
"""


def test_ilave_getiri_tablosu_katilma_getirisi_sayilmaz() -> None:
    """⚠️ Yuvam hesabında devlet TABAN getirinin ÜSTÜNE %1-3 katkı veriyor.

    Bu tablo `participation_yield` sanılırsa Emlak ve Kuveyt Türk "yıllık %1
    getiri veriyor" gibi görünür ve Türkiye Finans'ın %31'i karşısında
    listenin dibine düşer. Ölçüldü: canlı veride 6 satır böyle kirlenmişti.
    """
    assert parse_rate_tables(ILAVE_GETIRI_HTML) == []


BOS_HESAPLAYICI_HTML = """
<table>
  <caption>Katılma Hesabı Kar Payı Oranları</caption>
  <tr><th>Tutar Bandı</th><th>Vade</th><th>Net Oran (Yıllık)</th></tr>
  <tr><td>0,00 TL</td><td>12</td><td>%0</td></tr>
  <tr><td>250-10.000.000 TL</td><td>12</td><td>%31,22</td></tr>
</table>
"""


def test_sifir_getirili_satir_yazilmaz() -> None:
    """⚠️ "%0" hesaplayıcının BOŞ BAŞLANGIÇ durumudur, bankanın teklifi değil.

    Kuveyt Türk sayfayı tutar girilmeden bu satırla sunuyor. Yazılırsa banka
    "%0 getiri veriyor" diye sıralanır.
    """
    satirlar = [r for t in parse_rate_tables(BOS_HESAPLAYICI_HTML) for r in t.rows]

    getiriler = [r for r in satirlar if r.rate_type == "participation_yield"]
    assert all(r.profit_rate_pct and r.profit_rate_pct > 0 for r in getiriler)


def test_sifir_bastirmasi_gercek_getiriyi_korur() -> None:
    """Bastırma fazla geniş olmamalı: %31,22 satırı yerinde kalır."""
    satirlar = [r for t in parse_rate_tables(BOS_HESAPLAYICI_HTML) for r in t.rows]

    assert any(r.profit_rate_pct == Decimal("31.22") for r in satirlar)


# ── Çok boyutlu varyant ────────────────────────────────────

COK_BOYUTLU_HTML = """
<h3>Sigortalı Taşıt Finansmanı (Taşıt Kredisi)* 0 km</h3>
<table>
  <tr><th>Vade</th><th>Kâr Oranı</th><th>Tahsis Ücreti</th></tr>
  <tr><td>12</td><td>3,63%</td><td>0,50%</td></tr>
</table>
<h3>Sigortalı Taşıt Finansmanı (Taşıt Kredisi)* 2. El</h3>
<table>
  <tr><th>Vade</th><th>Kâr Oranı</th><th>Tahsis Ücreti</th></tr>
  <tr><td>12</td><td>3,95%</td><td>0,50%</td></tr>
</table>
<h3>Sigortasız Taşıt Finansmanı (Taşıt Kredisi)* 0 km</h3>
<table>
  <tr><th>Vade</th><th>Kâr Oranı</th><th>Tahsis Ücreti</th></tr>
  <tr><td>12</td><td>4,23%</td><td>0,50%</td></tr>
</table>
"""


def test_varyant_iki_boyutu_birden_tasir() -> None:
    """⚠️ Varyant TEK BOYUTLU DEĞİLDİR: {sigorta} × {araç durumu}.

    Yalnızca ilk eşleşen işaret alınırsa "0 km" ile "2. El" tabloları aynı
    anahtarı paylaşır, `band_key` çakışır ve satırlardan biri sessizce düşer.
    Düşen taraf 2. el, yani oranı YÜKSEK olan — banka olduğundan ucuz görünür.
    Ölçüldü: Türkiye Finans taşıtta 28 satırın 14'ü bu yüzden kayboluyordu.
    """
    anahtarlar = [t.variant_key for t in parse_rate_tables(COK_BOYUTLU_HTML)]

    assert anahtarlar == [
        "sifir_arac+sigortali",
        "ikinci_el_arac+sigortali",
        "sifir_arac+sigortasiz",
    ]


def test_ayni_boyuttan_iki_anahtar_secilmez() -> None:
    """ "Sigortalı" ile "Sigortasız" aynı anahtarda birleşemez."""
    for anahtar in (t.variant_key or "" for t in parse_rate_tables(COK_BOYUTLU_HTML)):
        assert not ("sigortali" in anahtar and "sigortasiz" in anahtar)


def test_varyant_ayrimi_oranlari_karistirmaz() -> None:
    """Her varyant kendi oranını korumalı."""
    esleme = {t.variant_key: t.rows[0].profit_rate_pct for t in parse_rate_tables(COK_BOYUTLU_HTML)}

    assert esleme["sifir_arac+sigortali"] == Decimal("3.63")
    assert esleme["ikinci_el_arac+sigortali"] == Decimal("3.95")
    assert esleme["sifir_arac+sigortasiz"] == Decimal("4.23")


def test_tek_boyutlu_varyant_bozulmaz(read_fixture) -> None:  # type: ignore[no-untyped-def]
    """Araç durumu yazmayan tabloda anahtar sade kalır."""
    tablolar = parse_rate_tables(read_fixture(FIXTURE))

    assert [t.variant_key for t in tablolar] == ["sigortali", "sigortasiz"]
