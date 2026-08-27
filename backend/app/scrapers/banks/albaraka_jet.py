"""Albaraka Jet Finansman limitleri — saf ayrıştırıcı (ağ yok).

Kaynak (ölçüldü 26 Ağustos 2026): başvuru formunun `wsGetSettingParams`
yanıtı ve `#txtFinansmanType` / `#txtFinansmanSubType` option kodları.

⚠️ Bu modül ORAN üretmez. Kâr payı `getFinanceCalculate` (pazarlama
hesaplayıcısı) yolundadır. Buradaki veri tutar/vade tavanı ve LTV'dir;
JS'in input'lara yazdığı `max_amount` / `max_maturity` / `max_ratio`
niteliklerinin kanonik kaynağıdır.

⚠️ Yandex Metrica (`mc.yandex.ru/watch/...`) ürün verisi değildir; burada
kullanılmaz.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, Tag

from app.scrapers.models import RawProduct
from app.scrapers.products import product_external_key
from app.utils.slugify import slug_from_url_path

JET_APP_URL = "https://basvur.albaraka.com.tr/jet-finansman"
SETTINGS_URLS: tuple[str, ...] = (
    "https://basvur.albaraka.com.tr/ws/wsGetSettingParams",
    "https://basvur.albaraka.com.tr/ws//wsGetSettingParams",
)

# Aile kodları: HTML `txtFinansmanType` value ↔ settings soneki.
FAMILY_KONUT = "001"
FAMILY_TASIT = "002"
FAMILY_IHTIYAC = "003"

# Jet dropdown'da görülen alt türler (option value → etiket). HTML option
# varsa o geçer; bu tablo yalnızca option listesi boşken kullanılır.
# Ölçüldü: basvur.albaraka.com.tr/jet-finansman Fin=3, 26 Ağustos 2026.
JET_SUBTYPE_LABELS: dict[str, str] = {
    "137": "Bebek İhtiyaçları Finansmanı",
    "138": "Bina Tamamlama Finansmanı",
    "139": "Deniz Araçları Finansmanı",
    "140": "Devre Mülk Finansmanı",
    "141": "Devre Tatil Finansmanı",
    "142": "Diş Sağlığı Finansmanı",
    "143": "Doğalgaz Dönüşüm Finansmanı",
    "144": "Düğün Organizasyonu Finansmanı",
    "145": "Eğitim Finansmanı",
    "146": "Engelsiz Hayat Finansmanı",
    "147": "Doğal Enerji Sistemleri Finansmanı",
    "148": "Eşya Finansmanı",
    "149": "Hac Finansmanı",
    "152": "Diğer Taşıt Finansmanı (Motosiklet)",
    "153": "Prefabrik Finansmanı",
    "154": "Servis Taşımacılığı Finansmanı",
    "155": "Seyahat Finansmanı",
    "156": "Tadilat Finansmanı",
    "157": "Taşınma Finansmanı",
    "158": "Bilgisayar Finansmanı",
    "159": "Sağlık Finansmanı",
    "161": "Tablet Finansmanı",
    "163": "Yurt Hizmeti Finansmanı",
    "164": "Cep Telefonu Finansmanı",
    "165": "Diğer Teknoloji Finansmanı",
    "177": "Dijital Kira Finansmanı",
    "180": "Umre Finansmanı (Kampanyalı)",
}

# Bu kodların ayrı ürün sayfası var (`PRODUCT_PAGES`). Jet çocuğu olarak
# yeniden yazılmaz — o sayfa kazınırken overlay uygulanır.
DEDICATED_SUBTYPE_CODES: frozenset[str] = frozenset(
    {
        "138",
        "139",
        "142",
        "143",
        "145",
        "147",
        "148",
        "149",
        "152",
        "153",
        "155",
        "156",
        "159",
        "163",
        "180",
    }
)

# URL yol soneki → alt tür kodu. En uzun eşleşme kazanır.
_SUBTYPE_BY_SUFFIX: tuple[tuple[str, str], ...] = (
    ("egitim-finansmani", "145"),
    ("hac-ve-umre-finansmani", "149"),
    ("subesiz-umre-finansmani", "180"),
    ("tadilat-kredisi", "156"),
    ("esya-dekorasyon", "148"),
    ("dogal-enerji-sistemi", "147"),
    ("dogalgaz-donusum", "143"),
    ("bina-tamamlama", "138"),
    ("prefabrik", "153"),
    ("genel-saglik", "159"),
    ("dis-sagligi", "142"),
    ("seyahat", "155"),
    ("yurt", "163"),
    ("motosiklet-atv-bisiklet", "152"),
    ("deniz-tasitlari-finansmani", "139"),
)

_FAMILY_BY_SUFFIX: tuple[tuple[str, str], ...] = (
    ("dijital-arac-finansmani", FAMILY_TASIT),
    ("togg-finansmani", FAMILY_TASIT),
    ("tasit-finansmani", FAMILY_TASIT),
    ("konut-finansmani", FAMILY_KONUT),
    ("jet-finansman", FAMILY_IHTIYAC),
    ("sms-li-finansman", FAMILY_IHTIYAC),
    ("pratik-finansman-kart", FAMILY_IHTIYAC),
    ("bayide-finansman", FAMILY_IHTIYAC),
    ("arsa-finansmani", FAMILY_KONUT),
)

_HTML_FAMILY_INPUTS: tuple[tuple[str, str], ...] = (
    ("satisFiyatiKonut", FAMILY_KONUT),
    ("satisFiyatiArac", FAMILY_TASIT),
    ("satisFiyatiIhtiyac", FAMILY_IHTIYAC),
)


@dataclass(frozen=True)
class JetFamilyLimits:
    """001 / 002 / 003 aile tavanı."""

    code: str
    amount_max: Decimal | None = None
    term_months_max: int | None = None
    ltv_max_pct: Decimal | None = None
    ltv_alt_pct: Decimal | None = None
    ltv_threshold: Decimal | None = None
    vehicle_year_max: int | None = None


@dataclass(frozen=True)
class JetSubtype:
    """Jet dropdown'daki tek alt tür."""

    code: str
    main_code: str
    label: str


@dataclass
class JetCatalog:
    """Settings API + HTML'den birleşik limit kataloğu."""

    families: dict[str, JetFamilyLimits] = field(default_factory=dict)
    subtype_term_max: dict[str, int] = field(default_factory=dict)
    subtype_term_min: dict[str, int] = field(default_factory=dict)
    raw: dict[str, str] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        """Hiç aile tavanı veya alt tür vadesi yok mu?"""
        aile_dolu = any(
            aile.amount_max is not None
            or aile.term_months_max is not None
            or aile.ltv_max_pct is not None
            for aile in self.families.values()
        )
        return not aile_dolu and not self.subtype_term_max


def parse_setting_params(payload: str | dict[str, Any]) -> JetCatalog:
    """`wsGetSettingParams` gövdesini katalog yapar.

    Args:
        payload: JSON metni veya çözülmüş sözlük.

    Returns:
        Doldurulabilen alanlarla katalog; gövde bozuksa boş katalog.
    """
    veri = _as_str_map(payload)
    if not veri:
        return JetCatalog()

    families: dict[str, JetFamilyLimits] = {}
    for kod in (FAMILY_KONUT, FAMILY_TASIT, FAMILY_IHTIYAC):
        families[kod] = _family_from_raw(kod, veri)

    term_max: dict[str, int] = {}
    term_min: dict[str, int] = {}
    for anahtar, deger in veri.items():
        if anahtar.startswith("MAX_REQESTED_MATURITY_"):
            kod = anahtar.rsplit("_", 1)[-1]
            if kod in {FAMILY_KONUT, FAMILY_TASIT, FAMILY_IHTIYAC}:
                continue
            ay = _as_int(deger)
            if ay is not None:
                term_max[kod] = ay
        elif anahtar.startswith("MIN_REQESTED_MATURITY_"):
            kod = anahtar.rsplit("_", 1)[-1]
            ay = _as_int(deger)
            if ay is not None:
                term_min[kod] = ay

    return JetCatalog(
        families=families,
        subtype_term_max=term_max,
        subtype_term_min=term_min,
        raw=veri,
    )


def catalog_from_html_attrs(html: str) -> JetCatalog:
    """Jet form input `max_*` niteliklerini katalog yapar (settings yokken)."""
    soup = BeautifulSoup(html, "lxml")
    families: dict[str, JetFamilyLimits] = {}
    for input_id, kod in _HTML_FAMILY_INPUTS:
        dugme = soup.find(id=input_id)
        if not isinstance(dugme, Tag):
            continue
        families[kod] = JetFamilyLimits(
            code=kod,
            amount_max=_as_decimal(dugme.get("max_amount")),
            term_months_max=_as_int(dugme.get("max_maturity")),
            ltv_max_pct=_ratio_to_pct(dugme.get("max_ratio")),
            ltv_alt_pct=_ratio_to_pct(dugme.get("max_ratio2")),
            vehicle_year_max=_as_int(dugme.get("max_year")),
        )
    return JetCatalog(families=families)


def merge_catalogs(primary: JetCatalog, fallback: JetCatalog) -> JetCatalog:
    """Birincil katalog boş alanlarını yedekten doldurur."""
    families = dict(fallback.families)
    for kod, aile in primary.families.items():
        onceki = families.get(kod)
        if onceki is None:
            families[kod] = aile
            continue
        families[kod] = JetFamilyLimits(
            code=kod,
            amount_max=aile.amount_max or onceki.amount_max,
            term_months_max=aile.term_months_max or onceki.term_months_max,
            ltv_max_pct=aile.ltv_max_pct or onceki.ltv_max_pct,
            ltv_alt_pct=aile.ltv_alt_pct or onceki.ltv_alt_pct,
            ltv_threshold=aile.ltv_threshold or onceki.ltv_threshold,
            vehicle_year_max=aile.vehicle_year_max or onceki.vehicle_year_max,
        )
    term_max = dict(fallback.subtype_term_max)
    term_max.update(primary.subtype_term_max)
    term_min = dict(fallback.subtype_term_min)
    term_min.update(primary.subtype_term_min)
    raw = dict(fallback.raw)
    raw.update(primary.raw)
    return JetCatalog(
        families=families,
        subtype_term_max=term_max,
        subtype_term_min=term_min,
        raw=raw,
    )


def parse_jet_subtypes(html: str) -> list[JetSubtype]:
    """`#txtFinansmanSubType` option listesini okur."""
    soup = BeautifulSoup(html, "lxml")
    sel = soup.find(id="txtFinansmanSubType")
    if not isinstance(sel, Tag):
        return []
    bulunan: list[JetSubtype] = []
    for opt in sel.find_all("option"):
        kod = str(opt.get("value") or "").strip()
        etiket = opt.get_text(strip=True)
        if not kod or not etiket:
            continue
        main = str(opt.get("maincode") or FAMILY_IHTIYAC).strip() or FAMILY_IHTIYAC
        bulunan.append(JetSubtype(code=kod, main_code=main, label=etiket))
    return bulunan


def is_jet_page(url: str) -> bool:
    """Adres Jet Finansman ürün/başvuru sayfası mı?"""
    path = urlsplit(url).path.rstrip("/").lower()
    return path.endswith("jet-finansman")


def codes_for_url(url: str) -> tuple[str | None, str | None]:
    """Ürün adresinden (aile kodu, alt tür kodu) döndürür."""
    path = urlsplit(url).path.rstrip("/").lower()
    subtype: str | None = None
    family: str | None = None
    for son, kod in _SUBTYPE_BY_SUFFIX:
        if path.endswith(son):
            subtype = kod
            break
    for son, kod in _FAMILY_BY_SUFFIX:
        if path.endswith(son):
            family = kod
            break
    # Motosiklet (152) ve deniz aracı (139) yol olarak /ihtiyac altında
    # duruyor; Jet aile kodu taşıt (002). /ihtiyac eşlemesi önce çalışırsa
    # ihtiyaç tavanı (100 bin) yazılır ve `amount_min=125000` CHECK bozar.
    if subtype in {"139", "152"}:
        family = FAMILY_TASIT
    elif family is None and "/ihtiyac" in path:
        family = FAMILY_IHTIYAC
    elif family is None and subtype is not None:
        family = FAMILY_IHTIYAC
    return family, subtype


def overlay_fields(
    catalog: JetCatalog,
    *,
    family_code: str | None,
    subtype_code: str | None,
) -> dict[str, Any]:
    """RawProduct'a yazılacak limit alanları."""
    if catalog.is_empty or not family_code:
        return {}
    aile = catalog.families.get(family_code)
    amount_max = aile.amount_max if aile else None
    term_max = aile.term_months_max if aile else None
    term_min: int | None = None
    ltv = aile.ltv_max_pct if aile else None
    if subtype_code and subtype_code in catalog.subtype_term_max:
        term_max = catalog.subtype_term_max[subtype_code]
    if subtype_code and subtype_code in catalog.subtype_term_min:
        term_min = catalog.subtype_term_min[subtype_code]
    if term_min is not None and term_max is not None and term_min > term_max:
        term_min = None
    if amount_max is None and term_max is None and ltv is None:
        return {}

    parcalar = [f"wsGetSettingParams aile={family_code}"]
    if subtype_code:
        parcalar.append(f"alt={subtype_code}")
    if amount_max is not None:
        parcalar.append(f"MAX_REQESTED_AMOUNT_{family_code}={amount_max}")
    if term_max is not None:
        anahtar = (
            f"MAX_REQESTED_MATURITY_{subtype_code}"
            if subtype_code and subtype_code in catalog.subtype_term_max
            else f"MAX_REQESTED_MATURITY_{family_code}"
        )
        parcalar.append(f"{anahtar}={term_max}")
    if term_min is not None:
        parcalar.append(f"MIN_REQESTED_MATURITY_{subtype_code}={term_min}")
    if ltv is not None:
        parcalar.append(f"ltv={ltv}")
    if aile and aile.ltv_alt_pct is not None:
        parcalar.append(f"ltv2={aile.ltv_alt_pct}")
    if aile and aile.ltv_threshold is not None:
        parcalar.append(f"ltv_esik={aile.ltv_threshold}")
    if aile and aile.vehicle_year_max is not None:
        parcalar.append(f"VEHICLE_YEAR_LIMIT={aile.vehicle_year_max}")

    return {
        "amount_max": amount_max,
        "term_months_max": term_max,
        "term_months_min": term_min,
        "ltv_max_pct": ltv,
        "limits_source": "html_attr",
        "limits_evidence": "; ".join(parcalar)[:400],
    }


def apply_overlay(product: RawProduct, fields: dict[str, Any]) -> None:
    """Katalog tavanlarını ürüne yazar; boş alanları ezmez (None gelirse).

    Sayfa metnindeki taban, ayarlar tavanından büyükse taban silinir.
    Aksi halde `products.amount_range_valid` / `term_range_valid` CHECK'i
    kazımayı durdurur (Albaraka motosiklet: metin 125 bin–250 bin, yanlış
    aile overlay'i 100 bin).
    """
    if not fields:
        return
    for alan in ("amount_max", "term_months_max", "term_months_min", "ltv_max_pct"):
        deger = fields.get(alan)
        if deger is not None:
            setattr(product, alan, deger)
    if (
        product.amount_min is not None
        and product.amount_max is not None
        and product.amount_min > product.amount_max
    ):
        product.amount_min = None
    if (
        product.term_months_min is not None
        and product.term_months_max is not None
        and product.term_months_min > product.term_months_max
    ):
        product.term_months_min = None
    product.limits_source = str(fields.get("limits_source") or "html_attr")
    kanit = fields.get("limits_evidence")
    if kanit:
        eski = product.limits_evidence or ""
        birlesik = str(kanit) if not eski else f"{kanit} | {eski}"
        product.limits_evidence = birlesik[:400]


def apply_catalog_to_products(
    urunler: list[RawProduct],
    url: str,
    html: str,
    catalog: JetCatalog,
) -> list[RawProduct]:
    """Mevcut ürünlere limit overlay + Jet-only alt tür çocukları."""
    family, subtype = codes_for_url(url)
    alanlar = overlay_fields(catalog, family_code=family, subtype_code=subtype)
    if alanlar:
        for urun in urunler:
            if urun.parent_external_key is None:
                apply_overlay(urun, alanlar)

    if not is_jet_page(url):
        return urunler

    kokler = [u for u in urunler if u.parent_external_key is None]
    diger = [
        u
        for u in urunler
        if u.parent_external_key is not None and u.variant_source != "dropdown_option"
    ]
    parent = kokler[0] if kokler else None
    if parent is None:
        return urunler
    cocuklar = jet_child_products(parent, html, catalog)
    return [*kokler, *diger, *cocuklar]


def jet_child_products(
    parent: RawProduct,
    html: str,
    catalog: JetCatalog,
) -> list[RawProduct]:
    """Ayrı sayfası olmayan Jet alt türlerini çocuk ürün yapar."""
    by_code: dict[str, JetSubtype] = {}
    for aday in parse_jet_subtypes(html):
        by_code[aday.code] = aday
    for kod, etiket in JET_SUBTYPE_LABELS.items():
        if kod in DEDICATED_SUBTYPE_CODES or kod in by_code:
            continue
        by_code[kod] = JetSubtype(code=kod, main_code=FAMILY_IHTIYAC, label=etiket)

    slug = slug_from_url_path(parent.source_url)
    cocuklar: list[RawProduct] = []
    for kod in sorted(by_code):
        if kod in DEDICATED_SUBTYPE_CODES:
            continue
        aday = by_code[kod]
        alanlar = overlay_fields(catalog, family_code=aday.main_code, subtype_code=kod)
        urun = RawProduct(
            external_key=product_external_key(slug, f"jet-{kod}"),
            name=aday.label,
            source_url=parent.source_url,
            product_type=parent.product_type or "ihtiyac_finansmani",
            segment=parent.segment or "bireysel",
            parent_external_key=parent.external_key,
            variant_label=aday.label,
            variant_source="dropdown_option",
            collateral_type=parent.collateral_type or "yok",
            has_calculator=True,
            calculator_url=_deep_link(aday.main_code, kod),
            is_binding=True,
        )
        apply_overlay(urun, alanlar)
        cocuklar.append(urun)
    return cocuklar


def family_code_for_hint(product_type_hint: str | None) -> str:
    """Hesaplayıcı ürün ipucunu Jet aile koduna çevirir."""
    if product_type_hint in {
        "konut_finansmani",
        "arsa_finansmani",
        "isyeri_finansmani",
        "gayrimenkul_finansmani",
    }:
        return FAMILY_KONUT
    if product_type_hint in {
        "tasit_finansmani",
        "digital_arac_finansmani",
        "marka_ozel_finansman",
    }:
        return FAMILY_TASIT
    return FAMILY_IHTIYAC


def cap_amount_term(
    catalog: JetCatalog,
    *,
    family_code: str,
    amount: Decimal,
    term_months: int,
) -> tuple[Decimal, int]:
    """Örnek sorgu tutar/vadesini bankanın yayımladığı tavana çeker."""
    aile = catalog.families.get(family_code)
    tutar = amount
    vade = term_months
    if aile and aile.amount_max is not None and tutar > aile.amount_max:
        tutar = aile.amount_max
    if aile and aile.term_months_max is not None:
        vade = min(vade, aile.term_months_max)
    return tutar, vade


def _deep_link(main_code: str, subtype_code: str) -> str:
    try:
        fin = int(main_code)
    except ValueError:
        fin = 3
    return f"{JET_APP_URL}?Fin={fin}&Sub={subtype_code}"


def _family_from_raw(kod: str, veri: dict[str, str]) -> JetFamilyLimits:
    ltv = None
    ltv_alt = None
    esik = None
    yas = None
    if kod == FAMILY_KONUT:
        ltv = _ratio_to_pct(veri.get("RC_RESIDENCE_CREDIBILITY_PERCENT"))
        esik, bant = _pipe_threshold(veri.get("CREDIBILITY_RATIO_001"))
        if ltv is None:
            ltv = bant
    elif kod == FAMILY_TASIT:
        ltv = _ratio_to_pct(veri.get("RC_VEHICLE_CREDIBILITY_RATIO_1"))
        ltv_alt = _ratio_to_pct(veri.get("RC_VEHICLE_CREDIBILITY_RATIO_2"))
        esik = _as_decimal(veri.get("RC_VEHICLE_CREDIBILITY_AMOUNT"))
        yas = _as_int(veri.get("VEHICLE_YEAR_LIMIT"))
    elif kod == FAMILY_IHTIYAC:
        ltv = _ratio_to_pct(veri.get("RC_CONSUMER_CREDIBILITY_RATIO"))
    return JetFamilyLimits(
        code=kod,
        amount_max=_as_decimal(veri.get(f"MAX_REQESTED_AMOUNT_{kod}")),
        term_months_max=_as_int(veri.get(f"MAX_REQESTED_MATURITY_{kod}")),
        ltv_max_pct=ltv,
        ltv_alt_pct=ltv_alt,
        ltv_threshold=esik,
        vehicle_year_max=yas,
    )


def _pipe_threshold(ham: str | None) -> tuple[Decimal | None, Decimal | None]:
    if not ham or "|" not in ham:
        return None, _ratio_to_pct(ham)
    sol, sag = ham.split("|", 1)
    return _as_decimal(sol), _ratio_to_pct(sag)


def _as_str_map(payload: str | dict[str, Any]) -> dict[str, str]:
    if isinstance(payload, dict):
        return {str(k): "" if v is None else str(v) for k, v in payload.items()}
    metin = payload.strip()
    if not metin or metin[0] not in "{[":
        return {}
    try:
        veri = json.loads(metin)
    except json.JSONDecodeError:
        return {}
    if not isinstance(veri, dict):
        return {}
    return {str(k): "" if v is None else str(v) for k, v in veri.items()}


def _as_int(value: object) -> int | None:
    if value is None:
        return None
    metin = str(value).strip().replace(" ", "")
    if not metin:
        return None
    try:
        return int(Decimal(metin.replace(",", ".")))
    except (InvalidOperation, ValueError):
        return None


def _as_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    metin = str(value).strip().replace(" ", "").replace(",", ".")
    if not metin:
        return None
    try:
        return Decimal(metin)
    except InvalidOperation:
        return None


def _ratio_to_pct(value: object) -> Decimal | None:
    """0.80 / 1.0 / 80 → yüzde puanı (80)."""
    oran = _as_decimal(value)
    if oran is None:
        return None
    if oran <= 1:
        return (oran * Decimal(100)).quantize(Decimal("0.1"))
    return oran
