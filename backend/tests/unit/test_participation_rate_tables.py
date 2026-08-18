"""Katılma hesabı oran tabloları ayrıştırma testleri (SPRINT 2.5 KAPI F2A)."""

from decimal import Decimal
from app.core.normalization.rate import parse_profit_sharing_ratio
from app.processing.rate_tables import parse_rate_tables


class TestParticipationAccountTables:
    def test_emlak_katilim_kpo(self) -> None:
        html = """
        <html><body>
        <h2>Katılma Hesabı Kâr Paylaşım Oranları</h2>
        <table>
            <tr><th>Tutar Bandı</th><th>Vade</th><th>Kâr Paylaşım Oranı</th></tr>
            <tr><td>250 - 24.999 TL</td><td>1 Aylık</td><td>90/10</td></tr>
            <tr><td>25.000 - 99.999 TL</td><td>3 Aylık</td><td>92/8</td></tr>
        </table>
        </body></html>
        """
        tablolar = parse_rate_tables(html)
        assert len(tablolar) == 1
        rows = tablolar[0].rows
        assert len(rows) == 2
        assert rows[0].rate_type == "profit_sharing_ratio"
        assert rows[0].investor_share_pct == Decimal("90")
        assert rows[0].bank_share_pct == Decimal("10")
        assert rows[1].investor_share_pct == Decimal("92")
        assert rows[1].bank_share_pct == Decimal("8")

    def test_turkiye_finans_iki_sayfa_ayrimi(self) -> None:
        # Sayfa 1: Kar Paylaşım Oranları
        html_paylasim = """
        <html><body>
        <h2>Katılma Hesabı Kâr Paylaşım Oranları</h2>
        <table>
            <tr><th>Vade</th><th>Kâr Paylaşım Oranı</th></tr>
            <tr><td>1 Ay</td><td>98/2</td></tr>
            <tr><td>3 Ay</td><td>96/4</td></tr>
        </table>
        </body></html>
        """
        # Sayfa 2: Kar Payı Oranları (Getiri)
        html_getiri = """
        <html><body>
        <h2>Katılma Hesabı Yıllık Brüt Kâr Payı Oranları</h2>
        <table>
            <tr><th>Vade</th><th>Kâr Payı Oranı</th></tr>
            <tr><td>1 Yıl</td><td>%31,22</td></tr>
            <tr><td>1 Yıldan Uzun</td><td>%31,24</td></tr>
        </table>
        </body></html>
        """
        tablas_paylasim = parse_rate_tables(html_paylasim)
        assert len(tablas_paylasim) == 1
        assert tablas_paylasim[0].rows[0].rate_type == "profit_sharing_ratio"
        assert tablas_paylasim[0].rows[0].investor_share_pct == Decimal("98")

        tablas_getiri = parse_rate_tables(html_getiri)
        assert len(tablas_getiri) == 1
        assert tablas_getiri[0].rows[0].rate_type == "participation_yield"
        assert tablas_getiri[0].rows[0].profit_rate_pct == Decimal("31.22")

    def test_ziraat_katilim_doviz_altin(self) -> None:
        html = """
        <html><body>
        <h2>Katılma Hesabı Oranları</h2>
        <table>
            <tr><th>Vade</th><th>Kâr Paylaşım</th><th>Para Birimi</th></tr>
            <tr><td>1 Aylık</td><td>90/10</td><td>TL</td></tr>
            <tr><td>1 Aylık</td><td>30/70</td><td>USD</td></tr>
            <tr><td>1 Aylık</td><td>10/90</td><td>XAU</td></tr>
        </table>
        </body></html>
        """
        tablolar = parse_rate_tables(html)
        assert len(tablolar) == 1
        rows = tablolar[0].rows
        assert len(rows) == 3
        assert rows[0].currency == "TRY"
        assert rows[0].investor_share_pct == Decimal("90")
        assert rows[1].currency == "USD"
        assert rows[1].investor_share_pct == Decimal("30")
        assert rows[2].currency == "XAU"
        assert rows[2].investor_share_pct == Decimal("10")

    def test_matrix_layout_emlak_katilim(self) -> None:
        html = """
        <html><body>
        <h3>Türk Lirası Kar Paylaşım Oranları</h3>
        <table>
            <tr><th>Minimum Bakiye</th><th>Maksimum Bakiye</th><th>1 Günlük</th><th>31 Günlük</th><th>3 Aylık</th></tr>
            <tr><td>250</td><td>24.999</td><td>75</td><td>85</td><td>86</td></tr>
        </table>
        </body></html>
        """
        tablolar = parse_rate_tables(html)
        assert len(tablolar) == 1
        rows = tablolar[0].rows
        assert len(rows) == 3
        assert rows[0].rate_type == "profit_sharing_ratio"
        assert rows[0].term_days_min == 1
        assert rows[0].investor_share_pct == Decimal("75")
        assert rows[0].currency == "TRY"
        assert rows[1].term_days_min == 31
        assert rows[1].investor_share_pct == Decimal("85")

    def test_matrix_layout_turkiye_finans_yield(self) -> None:
        html = """
        <html><body>
        <h3>E-Katılma Hesabı</h3>
        <table>
            <tr><th>E-Katılma Hesabı</th><th>1 Ay (%)</th><th>3 Ay (%)</th><th>1 Yıl (%)</th></tr>
            <tr><td>250-10,000,000</td><td>28.29</td><td>28.73</td><td>31.21</td></tr>
        </table>
        </body></html>
        """
        tablolar = parse_rate_tables(html)
        assert len(tablolar) == 1
        rows = tablolar[0].rows
        assert len(rows) == 3
        assert rows[0].rate_type == "participation_yield"
        assert rows[0].term_months == 1
        assert rows[0].profit_rate_pct == Decimal("28.29")
        assert rows[2].term_months == 12
        assert rows[2].profit_rate_pct == Decimal("31.21")
