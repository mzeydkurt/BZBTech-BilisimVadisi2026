"""Kullanıcı tarafından verilen hesaplayıcı URL hedefleri."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProbeTarget:
    bank_code: str
    url: str
    strategy: str
    label: str
    """Rapor adı."""
    product_filter: tuple[str, ...] | None = None
    """Albaraka gibi birleşik sayfada yalnızca ilgili ürün ailesi."""


PROBE_TARGETS: tuple[ProbeTarget, ...] = (
    ProbeTarget(
        bank_code="albaraka",
        url="https://www.albaraka.com.tr/tr/hesaplama-araclari/finansman-hesaplama/ihtiyac-finansmani-hesaplama",
        strategy="albaraka_json",
        label="Albaraka — birleşik finansman hesaplayıcı (tüm ürünler)",
    ),
    ProbeTarget(
        bank_code="kuveyt_turk",
        url="https://www.kuveytturk.com.tr/hesaplama-araclari/finansman-hesaplama",
        strategy="kuveyt_product_dropdown",
        label="Kuveyt Türk — finansman hesaplama",
    ),
    ProbeTarget(
        bank_code="ziraat_katilim",
        url="https://www.ziraatkatilim.com.tr/bireysel/finansman-urunleri/konut-gayrimenkul-finansmani",
        strategy="ziraat_product_dropdown",
        label="Ziraat Katılım — konut hesaplayıcı",
        product_filter=("konut", "arsa", "işyeri", "isyeri", "kentsel"),
    ),
    ProbeTarget(
        bank_code="vakif_katilim",
        url="https://www.vakifkatilim.com.tr/tr/yardimci-sayfalar/hesaplama-araclari/finansman-hesaplama",
        strategy="vakif_loan_type",
        label="Vakıf Katılım — finansman hesaplama",
    ),
    ProbeTarget(
        bank_code="dunya_katilim",
        url="https://dunyakatilim.com.tr/kendim-icin/finansmanlar/konut-finansmanlari/konut-finansmani",
        strategy="dunya_embedded",
        label="Dünya Katılım — konut sayfası hesaplayıcı",
    ),
    ProbeTarget(
        bank_code="emlak_katilim",
        url="https://www.emlakkatilim.com.tr/tr/bireysel/finansmanlar",
        strategy="emlak_listing",
        label="Emlak Katılım — finansman listesi",
    ),
    ProbeTarget(
        bank_code="hayat_finans",
        url="https://hayatfinans.com.tr/",
        strategy="hayat_home",
        label="Hayat Finans — ana sayfa kredi hesaplayıcı",
    ),
    ProbeTarget(
        bank_code="turkiye_finans",
        url="https://www.turkiyefinans.com.tr/tr-tr/hesaplama-araclari/Sayfalar/finansman-odeme-plani.aspx",
        strategy="turkiye_finans_type",
        label="Türkiye Finans — finansman ödeme planı",
    ),
)
