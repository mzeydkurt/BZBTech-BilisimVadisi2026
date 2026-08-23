"""BDDK finansman tavanları — versiyonlu kanon servisi.

⚠️ UYDURMA YOK. Tavanlar `backend/data/seed/bddk_finansman_limitleri.json`
dosyasından okunur; koda gömülü matris kullanılmaz. Dosya yoksa veya bozuksa
hata yükselir — sessizce eski sabitlere düşülmez.

⚠️ İkinci konut: BDDK, ilk-ev oranlarını %75 azaltır (A-B ≤5M: %90 → %22,5).
Kuveyt Türk gibi bankaların yayımladığı düşük tablolar çoğunlukla budur;
kanonu "düşmüş LTV" sanmak jüri önünde kırılgan bir hatadır.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

from app.schemas.simulator import BDDKLimitCheckRequest, BDDKLimitCheckResponse

_KURUS = Decimal("0.01")
_YUZDE = Decimal("100")
_SEED_PATH: Final[Path] = (
    Path(__file__).resolve().parent.parent.parent / "data" / "seed" / "bddk_finansman_limitleri.json"
)

# product_type → aile anahtarı (ihtiyac / konut / tasit)
_PRODUCT_TYPE_TO_FAMILY: dict[str, str] = {}


def _kurusla(deger: Decimal) -> Decimal:
    return deger.quantize(_KURUS, rounding=ROUND_HALF_UP)


def _dec(ham: object) -> Decimal | None:
    if ham is None:
        return None
    return Decimal(str(ham))


@lru_cache(maxsize=1)
def load_bddk_canon() -> dict[str, Any]:
    """Kanon JSON'unu yükler; süreç ömrü boyunca önbelleklenir."""
    if not _SEED_PATH.is_file():
        raise FileNotFoundError(f"BDDK kanon dosyası bulunamadı: {_SEED_PATH}")
    with _SEED_PATH.open(encoding="utf-8") as f:
        veri = json.load(f)
    _PRODUCT_TYPE_TO_FAMILY.clear()
    for aile, icerik in veri.get("families", {}).items():
        for tip in icerik.get("product_types", []):
            _PRODUCT_TYPE_TO_FAMILY[str(tip)] = str(aile)
    return veri


def invalidate_bddk_canon_cache() -> None:
    """Test veya seed yenilemede önbelleği düşürür."""
    load_bddk_canon.cache_clear()
    _PRODUCT_TYPE_TO_FAMILY.clear()


def family_for_product_type(product_type: str | None) -> str | None:
    """Ürün türünü BDDK ailesine eşler; bilinmiyorsa None."""
    if not product_type:
        return None
    load_bddk_canon()
    return _PRODUCT_TYPE_TO_FAMILY.get(product_type)


def get_family(family_key: str) -> dict[str, Any]:
    """Aile kaydını döndürür; yoksa KeyError."""
    aileler = load_bddk_canon()["families"]
    if family_key not in aileler:
        raise KeyError(f"Bilinmeyen BDDK ailesi: {family_key}")
    return aileler[family_key]


@dataclass(frozen=True)
class CanonicalBandView:
    """UI / API için tek bant özeti."""

    label: str
    amount_min: Decimal | None = None
    amount_max: Decimal | None = None
    value_min: Decimal | None = None
    value_max: Decimal | None = None
    max_term_months: int | None = None
    max_ratio_pct: Decimal | None = None
    rates: dict[str, Decimal] | None = None


@dataclass(frozen=True)
class CanonicalLimitsView:
    """Liste/detay banner'ı için aile özeti."""

    family: str
    kind: str
    decision_no: str
    decision_date: str
    legal_reference: str
    source_url: str
    bands: tuple[CanonicalBandView, ...]
    max_term_months: int | None = None
    second_home_reduction_pct: Decimal | None = None
    second_home_note: str | None = None
    as_of: str | None = None


def get_canonical_limits(
    product_type: str | None = None,
    *,
    family: str | None = None,
) -> CanonicalLimitsView | None:
    """Ürün türü veya aile anahtarı için kanonik BDDK tavanlarını döndürür."""
    aile_anahtari = family or family_for_product_type(product_type)
    if aile_anahtari is None:
        return None
    kanon = load_bddk_canon()
    kayit = get_family(aile_anahtari)
    bantlar: list[CanonicalBandView] = []
    for b in kayit.get("bands", []):
        oranlar = None
        if "rates" in b:
            oranlar = {k: Decimal(str(v)) for k, v in b["rates"].items()}
        bantlar.append(
            CanonicalBandView(
                label=str(b["label"]),
                amount_min=_dec(b.get("amount_min")),
                amount_max=_dec(b.get("amount_max")),
                value_min=_dec(b.get("value_min")),
                value_max=_dec(b.get("value_max")),
                max_term_months=b.get("max_term_months"),
                max_ratio_pct=_dec(b.get("max_ratio_pct")),
                rates=oranlar,
            )
        )
    return CanonicalLimitsView(
        family=aile_anahtari,
        kind=str(kayit["kind"]),
        decision_no=str(kayit["decision_no"]),
        decision_date=str(kayit["decision_date"]),
        legal_reference=str(kayit["legal_reference"]),
        source_url=str(kayit["source_url"]),
        bands=tuple(bantlar),
        max_term_months=kayit.get("max_term_months"),
        second_home_reduction_pct=_dec(kayit.get("second_home_reduction_pct")),
        second_home_note=kayit.get("second_home_note"),
        as_of=kanon.get("as_of"),
    )


def _enerji_sinifi(ham: str | None) -> str:
    if not ham:
        return "DIGER"
    temiz = ham.strip().upper().replace("İ", "I")
    if temiz.startswith("A") or temiz.startswith("B"):
        return "A-B"
    if temiz.startswith("C"):
        return "C"
    return "DIGER"


def max_term_for_ihtiyac_amount(amount_try: Decimal) -> tuple[int, str, str]:
    """İhtiyaç tutarına göre azami vade, bant etiketi ve yasal dayanak."""
    aile = get_family("ihtiyac")
    for b in aile["bands"]:
        alt = _dec(b.get("amount_min")) or Decimal("0")
        ust = _dec(b.get("amount_max"))
        if amount_try < alt:
            continue
        if ust is not None and amount_try > ust:
            continue
        return int(b["max_term_months"]), str(b["label"]), str(aile["legal_reference"])
    raise AssertionError("ihtiyaç vade bandı bulunamadı")  # pragma: no cover


def check_bddk_limits(req: BDDKLimitCheckRequest) -> BDDKLimitCheckResponse:
    """BDDK azami finansman oranı / vadesini kanondan denetler."""
    deger = req.asset_value_try
    tip = req.asset_type.strip().lower()

    if tip == "ihtiyac":
        vade, bant, dayanak = max_term_for_ihtiyac_amount(deger)
        return BDDKLimitCheckResponse(
            asset_type="ihtiyac",
            asset_value_try=deger,
            value_band_label=bant,
            max_financing_ratio_pct=Decimal("100"),
            max_financing_amount_try=deger,
            max_allowed_term_months=vade,
            is_financing_allowed=True,
            legal_reference=dayanak,
            first_home=None,
        )

    if tip == "tasit":
        aile = get_family("tasit")
        for b in aile["bands"]:
            alt = _dec(b.get("value_min")) or Decimal("0")
            ust = _dec(b.get("value_max"))
            if deger < alt:
                continue
            if ust is not None and deger > ust:
                continue
            oran = Decimal(str(b["max_ratio_pct"]))
            return BDDKLimitCheckResponse(
                asset_type="tasit",
                asset_value_try=deger,
                value_band_label=str(b["label"]),
                max_financing_ratio_pct=oran,
                max_financing_amount_try=_kurusla(deger * oran / _YUZDE),
                max_allowed_term_months=b.get("max_term_months"),
                is_financing_allowed=oran > 0,
                legal_reference=str(aile["legal_reference"]),
                first_home=None,
            )
        raise AssertionError("taşıt bandı bulunamadı")  # pragma: no cover

    # konut
    aile = get_family("konut")
    sinif = _enerji_sinifi(req.energy_class)
    first_home = True if req.first_home is None else bool(req.first_home)
    indirim = Decimal(str(aile.get("second_home_reduction_pct", "75")))

    for b in aile["bands"]:
        alt = _dec(b.get("value_min")) or Decimal("0")
        ust = _dec(b.get("value_max"))
        if deger < alt:
            continue
        if ust is not None and deger > ust:
            continue
        oran = Decimal(str(b["rates"][sinif]))
        if not first_home:
            # %75 azalt → kalan %25 uygulanır (90 → 22.5)
            oran = _kurusla(oran * (_YUZDE - indirim) / _YUZDE)
        return BDDKLimitCheckResponse(
            asset_type="konut",
            asset_value_try=deger,
            energy_class=sinif,
            value_band_label=str(b["label"]),
            max_financing_ratio_pct=oran,
            max_financing_amount_try=_kurusla(deger * oran / _YUZDE),
            max_allowed_term_months=aile.get("max_term_months"),
            is_financing_allowed=oran > 0,
            legal_reference=str(aile["legal_reference"]),
            first_home=first_home,
        )

    raise AssertionError("konut bandı bulunamadı")  # pragma: no cover


def compare_bank_limit_to_canon(
    *,
    product_type: str | None,
    financing_ratio_pct: Decimal | None,
    asset_value_max: Decimal | None,
    energy_class: str | None,
    term_months_max: int | None,
) -> str | None:
    """Banka LTV satırı kanon tavana uymazsa kısa uyarı metni döner.

    Sessiz ezme yok: sapma varsa kullanıcıya gösterilir.
    """
    aile = family_for_product_type(product_type)
    if aile is None:
        return None

    if aile == "ihtiyac" and term_months_max is not None:
        # Tutar bandı bilinmiyorsa yalnızca genel azami (36) ile kaba kontrol
        if term_months_max > 36:
            return (
                f"Bankanın azami vadesi ({term_months_max} ay) BDDK ihtiyaç "
                "tavanının (36 ay) üzerinde."
            )
        return None

    if aile == "tasit" and financing_ratio_pct is not None and asset_value_max is not None:
        sonuc = check_bddk_limits(
            BDDKLimitCheckRequest(asset_type="tasit", asset_value_try=asset_value_max)
        )
        if financing_ratio_pct > sonuc.max_financing_ratio_pct:
            return (
                f"Banka oranı %{financing_ratio_pct} BDDK tavanı "
                f"%{sonuc.max_financing_ratio_pct} üzerinde ({sonuc.value_band_label})."
            )
        return None

    if aile == "konut" and financing_ratio_pct is not None and asset_value_max is not None:
        # Önce ilk-ev tavanı, yetmezse ikinci-ev (%75 indirimli) ile karşılaştır
        ilk = check_bddk_limits(
            BDDKLimitCheckRequest(
                asset_type="konut",
                asset_value_try=asset_value_max,
                energy_class=energy_class,
                first_home=True,
            )
        )
        ikinci = check_bddk_limits(
            BDDKLimitCheckRequest(
                asset_type="konut",
                asset_value_try=asset_value_max,
                energy_class=energy_class,
                first_home=False,
            )
        )
        # Bankanın düşük tablosu ikinci-konut tavanına uyuyorsa bunu bildir
        # (Kuveyt Türk %22,5 = %90 × 0,25). Sessizce "uyumlu" demek jüriyi yanıltır.
        if abs(financing_ratio_pct - ikinci.max_financing_ratio_pct) <= Decimal("0.5"):
            return (
                "Bu satır BDDK ikinci-konut tavanına uyuyor "
                f"(%{ikinci.max_financing_ratio_pct}; ilk-ev tavanı %{ilk.max_financing_ratio_pct})."
            )
        if financing_ratio_pct > ilk.max_financing_ratio_pct:
            return (
                f"Banka oranı %{financing_ratio_pct} BDDK ilk-ev tavanı "
                f"%{ilk.max_financing_ratio_pct} üzerinde ({ilk.value_band_label})."
            )
    return None


def allocation_fee_cap_pct() -> Decimal:
    """Yasal tahsis ücreti üst sınırı (%)."""
    return Decimal(str(load_bddk_canon().get("allocation_fee_cap_pct", "0.5")))
