"""robots.txt izin denetimi ve açık izinle geçme testleri.

Testler ağa çıkmaz: `httpx.MockTransport` kullanılır (§13).

⚠️ `scraper_robots_override` yalnızca site sahibinden AÇIK İZİN alındığında
açılır. TEKNOFEST şartname madde 15 (Etik Kurallar) uyum belgelemesini
puanlıyor; anahtar açıkken bile hangi adresin yasağa rağmen çekildiği
`robots_allowed=False` ile kayıtlı kalmalıdır ki `data/robots_report.md`
doğruluğunu korusun.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx

from app.config import Settings
from app.scrapers.fetcher import Fetcher

# Kampanya yolunu kapatan robots.txt.
YASAKLI_ROBOTS = "User-agent: *\nDisallow: /kampanyalar/\n"

HEDEF = "https://ornek.com.tr/kampanyalar/trendyol"
SAYFA = "<html><body><h1>Kampanya</h1></body></html>"


def _fetcher(tmp_path: Path, transport: httpx.MockTransport, *, override: bool) -> Fetcher:
    """Verilen izin geçersiz kılma ayarıyla çekici üretir."""
    ayarlar = Settings(
        raw_html_dir=str(tmp_path / "raw_html"),
        scraper_request_delay_seconds=0.0,
        scraper_robots_override=override,
        airgap_mode=False,
    )
    istemci = httpx.Client(transport=transport, follow_redirects=True)
    return Fetcher("ornek_banka", settings=ayarlar, client=istemci)


class TestVarsayilanDavranis:
    """Anahtar KAPALIYKEN yasak mutlaktır."""

    def test_yasakli_adrese_istek_yapilmaz(
        self, tmp_path: Path, make_transport: Callable[..., httpx.MockTransport]
    ) -> None:
        tasiyici = make_transport({HEDEF: (200, SAYFA)}, robots_body=YASAKLI_ROBOTS)

        sonuc = _fetcher(tmp_path, tasiyici, override=False).fetch(HEDEF)

        assert sonuc.robots_allowed is False
        assert sonuc.status_code is None
        assert "robots" in (sonuc.error or "")

    def test_izinli_adres_normal_cekilir(
        self, tmp_path: Path, make_transport: Callable[..., httpx.MockTransport]
    ) -> None:
        """Yasak dar olmalı: başka yol etkilenmez."""
        izinli = "https://ornek.com.tr/urunler/tasit"
        tasiyici = make_transport({izinli: (200, SAYFA)}, robots_body=YASAKLI_ROBOTS)

        sonuc = _fetcher(tmp_path, tasiyici, override=False).fetch(izinli)

        assert sonuc.robots_allowed is True
        assert sonuc.status_code == 200


class TestAcikIzinleGecme:
    """Anahtar AÇIKKEN veri alınır ama kayıt gerçeği söyler."""

    def test_yasakli_adres_cekilir(
        self, tmp_path: Path, make_transport: Callable[..., httpx.MockTransport]
    ) -> None:
        tasiyici = make_transport({HEDEF: (200, SAYFA)}, robots_body=YASAKLI_ROBOTS)

        sonuc = _fetcher(tmp_path, tasiyici, override=True).fetch(HEDEF)

        assert sonuc.status_code == 200
        assert sonuc.error is None

    def test_kayit_robots_yasagini_gizlemez(
        self, tmp_path: Path, make_transport: Callable[..., httpx.MockTransport]
    ) -> None:
        """⚠️ `robots_allowed` True yazılırsa uyum raporu YALAN söyler.

        Rapor jüriye sunuluyor; hangi adresin yasağa rağmen çekildiği
        izlenebilir kalmalıdır.
        """
        tasiyici = make_transport({HEDEF: (200, SAYFA)}, robots_body=YASAKLI_ROBOTS)

        sonuc = _fetcher(tmp_path, tasiyici, override=True).fetch(HEDEF)

        assert sonuc.robots_allowed is False

    def test_izinli_adres_isaretlenmez(
        self, tmp_path: Path, make_transport: Callable[..., httpx.MockTransport]
    ) -> None:
        """Anahtar açıkken zaten izinli olan adres yasaklıymış gibi görünmemeli."""
        izinli = "https://ornek.com.tr/urunler/tasit"
        tasiyici = make_transport({izinli: (200, SAYFA)}, robots_body=YASAKLI_ROBOTS)

        sonuc = _fetcher(tmp_path, tasiyici, override=True).fetch(izinli)

        assert sonuc.robots_allowed is True
