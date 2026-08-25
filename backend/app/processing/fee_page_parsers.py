"""Banka ürün/hizmet ücret sayfalarından tahsis ve YMO çıkarımı.

Ziraat Katılım'ın "Masraf Adı" tablo düzeni `ziraat_katilim.py` içinde kalır.
Bu modül diğer bankaların farklı ücret sayfası biçimlerini kapsar.
"""

from __future__ import annotations

import re
from decimal import Decimal

from bs4 import BeautifulSoup, Tag

from app.core.normalization.money import parse_decimal_tr
from app.core.normalization.rate import parse_rate
from app.core.normalization.text import collapse_whitespace, lower_tr
from app.logging_config import get_logger
from app.scrapers.calculator_probes.common import urun_tipi_ipucu
from app.scrapers.models import RawProduct, RawProductRate
from app.scrapers.products import product_external_key
from app.utils.slugify import slug_from_url_path, slugify

logger = get_logger(__name__)

_VADE_RE = re.compile(r"\((\d+)\s*-\s*(\d+)\s*ay\s*vade\)", re.IGNORECASE)


def _oran_hucre(ham: str) -> Decimal | None:
    metin = ham.strip()
    if not metin or metin in ("-", "—"):
        return None
    if "%" in metin or "yüzde" in metin.casefold():
        return parse_rate(metin)
    return parse_decimal_tr(metin)


def _hucrelerde_oran(hucreler: list[str]) -> Decimal | None:
    for hucre in hucreler[1:]:
        oran = _oran_hucre(hucre)
        if oran is not None:
            return oran
    return None


def _ucret_urunu(
    *,
    url: str,
    ad: str,
    product_type: str,
    allocation_fee_pct: Decimal | None = None,
    annual_cost_pct: Decimal | None = None,
    evidence: str,
    slug_parca: str,
) -> RawProduct:
    slug = slug_from_url_path(url)
    return RawProduct(
        external_key=product_external_key(f"{slug}-{slug_parca}", None),
        name=ad,
        source_url=url,
        product_type=product_type,
        rates=[
            RawProductRate(
                rate_source="html_table",
                rate_type="financing_rate",
                allocation_fee_pct=allocation_fee_pct,
                annual_cost_pct=annual_cost_pct,
                evidence_text=evidence,
            )
        ],
        limits_source="none",
    )


def parse_albaraka_ucret_page(html: str, url: str) -> list[RawProduct]:
    """Albaraka `/tr/urun-ve-hizmet-ucretleri` — Tahsis Ücreti bölümü / satırları."""
    soup = BeautifulSoup(html, "lxml")
    urunler: list[RawProduct] = []
    tahsis_modu = False
    genel_tahsis = None

    for satir in soup.find_all("tr"):
        hucreler = [
            collapse_whitespace(td.get_text())
            for td in satir.find_all("td")
            if collapse_whitespace(td.get_text())
        ]
        if not hucreler:
            continue
        baslik_dusuk = lower_tr(hucreler[0])
        if len(hucreler) == 1 and baslik_dusuk in ("tahsis ücreti", "tahsis ucreti"):
            tahsis_modu = True
            continue
        # Tek satır: "Finansman Tahsis" + oran (arşiv biçimi)
        if "finansman tahsis" in baslik_dusuk:
            oran = _hucrelerde_oran(hucreler)
            if oran is not None:
                genel_tahsis = oran
            continue
        if not tahsis_modu:
            continue
        baslik = hucreler[0]
        if "finansman" not in lower_tr(baslik):
            # Başka bölüme geçildi
            if len(hucreler) == 1:
                tahsis_modu = False
            continue
        oran = _hucrelerde_oran(hucreler)
        if oran is None:
            continue
        ipucu = urun_tipi_ipucu(baslik) or "ihtiyac_finansmani"
        urunler.append(
            _ucret_urunu(
                url=url,
                ad=f"{baslik} — Tahsis Ücreti",
                product_type=ipucu,
                allocation_fee_pct=oran,
                evidence=(
                    f"{baslik} Tahsis Ücreti %{oran}. Kaynak: Albaraka ürün ve hizmet ücretleri."
                ),
                slug_parca=f"tahsis-{slugify(baslik)}",
            )
        )

    # Ürün satırı yoksa genel "Finansman Tahsis" oranını tüm ana finansman
    # ailelerine yaz (konut / taşıt / ihtiyaç).
    if not urunler and genel_tahsis is not None:
        for tip, ad in (
            ("konut_finansmani", "Konut Finansmanı"),
            ("tasit_finansmani", "Taşıt Finansmanı"),
            ("ihtiyac_finansmani", "İhtiyaç Finansmanı"),
        ):
            urunler.append(
                _ucret_urunu(
                    url=url,
                    ad=f"{ad} — Tahsis Ücreti",
                    product_type=tip,
                    allocation_fee_pct=genel_tahsis,
                    evidence=(
                        f"Finansman Tahsis %{genel_tahsis}. "
                        "Kaynak: Albaraka ürün ve hizmet ücretleri."
                    ),
                    slug_parca=f"tahsis-{tip}",
                )
            )
    return urunler


def parse_hayat_ucret_page(html: str, url: str) -> list[RawProduct]:
    """Hayat Finans ücret sayfası — Finansman Tahsis Ücreti satırı."""
    soup = BeautifulSoup(html, "lxml")
    urunler: list[RawProduct] = []

    for satir in soup.find_all("tr"):
        hucreler = [collapse_whitespace(td.get_text()) for td in satir.find_all("td")]
        if len(hucreler) < 3:
            continue
        baslik = lower_tr(hucreler[0])
        if "finansman tahsis" not in baslik:
            continue
        oran = _hucrelerde_oran(hucreler)
        if oran is None:
            continue
        urunler.append(
            _ucret_urunu(
                url=url,
                ad="Finansman Tahsis Ücreti",
                product_type="ihtiyac_finansmani",
                allocation_fee_pct=oran,
                evidence=(
                    f"Finansman Tahsis Ücreti %{oran}. "
                    "Kaynak: Hayat Finans ürün ve hizmet ücretleri."
                ),
                slug_parca="finansman-tahsis",
            )
        )
    return urunler


def parse_turkiye_finans_ucret_page(html: str, url: str) -> list[RawProduct]:
    """TF `urun-hizmet-ucretleri.aspx` — başlık altındaki Tahsis / YMO satırları."""
    soup = BeautifulSoup(html, "lxml")
    urunler: list[RawProduct] = []
    baglam = ""

    for el in soup.find_all(["h1", "h2", "h3", "h4", "tr"]):
        if not isinstance(el, Tag):
            continue
        if el.name in {"h1", "h2", "h3", "h4"}:
            baglam = collapse_whitespace(el.get_text())
            continue
        hucreler = [collapse_whitespace(td.get_text()) for td in el.find_all("td")]
        if len(hucreler) < 2:
            continue
        masraf = lower_tr(hucreler[0])
        if masraf == "tahsis ücreti":
            oran = _oran_hucre(hucreler[1]) or _hucrelerde_oran(hucreler)
            if oran is None or not baglam:
                continue
            ipucu = urun_tipi_ipucu(baglam) or "ihtiyac_finansmani"
            urunler.append(
                _ucret_urunu(
                    url=url,
                    ad=f"{baglam} — Tahsis Ücreti",
                    product_type=ipucu,
                    allocation_fee_pct=oran,
                    evidence=(
                        f"{baglam}: Tahsis Ücreti %{oran}. "
                        f"{hucreler[2] if len(hucreler) > 2 else ''}"
                    ).strip(),
                    slug_parca=f"tahsis-{slugify(baglam)}",
                )
            )
        elif "yıllık maliyet" in masraf or "yillik maliyet" in masraf:
            oran = _oran_hucre(hucreler[1]) or _hucrelerde_oran(hucreler)
            if oran is None or not baglam:
                continue
            ipucu = urun_tipi_ipucu(baglam) or "ihtiyac_finansmani"
            urunler.append(
                _ucret_urunu(
                    url=url,
                    ad=f"{baglam} — Yıllık Maliyet Oranı",
                    product_type=ipucu,
                    annual_cost_pct=oran,
                    evidence=f"{baglam}: Yıllık Maliyet Oranı %{oran}.",
                    slug_parca=f"ymo-{slugify(baglam)}",
                )
            )
    return urunler
