"""Yapısal oran tablosu ayrıştırma testleri.

Fixture canlı Türkiye Finans sayfasından alınmıştır; değerler gerçektir ve
görünmez karakterler korunmuştur.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.processing.rate_tables import parse_ltv_matrices, parse_rate_tables

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
