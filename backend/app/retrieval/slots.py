"""Sohbet araçları için slot (parametre) çıkarımı.

⚠️ SAYILAR MODELDE ÜRETİLMEZ. Tutar ve vade yalnızca kullanıcı metninden
`parse_money` / regex ile okunur. LLM router bir sayı önerirse bu modül
sorguda geçip geçmediğini doğrular; geçmiyorsa düşürülür.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Final

from app.core.normalization.money import parse_decimal_tr, parse_money
from app.core.normalization.text import ascii_fold_tr, lower_tr, normalize_text

_VADE_AY_RE: Final[re.Pattern[str]] = re.compile(
    r"(\d{1,3})\s*(?:ay(?:lik|lık)?|ay\b|vade)",
    re.IGNORECASE,
)
# "12 veya 24 ay/vade", "12-24 ay", "12 / 24 vade"
_VADE_COKLU_RE: Final[re.Pattern[str]] = re.compile(
    r"(\d{1,3})\s*(?:veya|/|-|–|—|ile|,)\s*(\d{1,3})\s*(?:ay(?:lik|lık)?|ay\b|vade)?",
    re.IGNORECASE,
)
_VADE_YIL_RE: Final[re.Pattern[str]] = re.compile(
    r"(\d{1,2})\s*(?:yil|yıl)",
    re.IGNORECASE,
)
_GUN_RE: Final[re.Pattern[str]] = re.compile(
    r"(\d{1,4})\s*(?:gun|gün)",
    re.IGNORECASE,
)

_PRODUCT_PATTERNS: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    (
        "tasit_finansmani",
        (
            "tasit finansmani",
            "taşıt finansmanı",
            "arac finansmani",
            "araç finansmanı",
            "tasit",
            "taşıt",
            "arac",
            "araç",
            "otomobil",
            "araba",
        ),
    ),
    (
        "konut_finansmani",
        (
            "konut finansmani",
            "konut finansmanı",
            "konut",
            "ev finansmani",
            "ev kredisi",
            "mortgage",
        ),
    ),
    (
        "ihtiyac_finansmani",
        (
            "ihtiyac finansmani",
            "ihtiyaç finansmanı",
            "ihtiyac",
            "ihtiyaç",
            "tuketici",
            "tüketici",
        ),
    ),
)

_ASSET_TYPE_PATTERNS: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("tasit", ("tasit", "taşıt", "arac", "araç", "kasko", "otomobil")),
    ("konut", ("konut", "ev", "ekspertiz", "gayrimenkul")),
    ("ihtiyac", ("ihtiyac", "ihtiyaç")),
)

_ENERJI_RE: Final[re.Pattern[str]] = re.compile(
    r"enerji\s*sinif[iı]?\s*[:\-]?\s*([abcd]|diger|diğer|a-b)",
    re.IGNORECASE,
)
_ENERJI_KISA: Final[re.Pattern[str]] = re.compile(
    r"\b([abc])\s*(?:sinif|sınıf)\b",
    re.IGNORECASE,
)

_CURRENCY_MAP: Final[dict[str, str]] = {
    "tl": "TRY",
    "try": "TRY",
    "usd": "USD",
    "dolar": "USD",
    "eur": "EUR",
    "euro": "EUR",
    "avro": "EUR",
    "altin": "XAU",
    "altın": "XAU",
    "gumuş": "XAG",
    "gumus": "XAG",
}


def _fold(text: str) -> str:
    return ascii_fold_tr(lower_tr(normalize_text(text or "")))


@dataclass
class QuerySlots:
    """Sorgudan çıkarılan araç parametreleri."""

    amount_try: Decimal | None = None
    term_months: int | None = None
    term_months_options: list[int] = field(default_factory=list)
    term_days: int | None = None
    product_type: str | None = None
    asset_type: str | None = None
    asset_value_try: Decimal | None = None
    energy_class: str | None = None
    first_home: bool | None = None
    deposit_try: Decimal | None = None
    currency: str = "TRY"
    bank_codes: list[str] = field(default_factory=list)
    tool_hint: str | None = None
    missing: list[str] = field(default_factory=list)

    def as_input_dict(self) -> dict[str, str]:
        """ChatToolRun.inputs için dize sözlüğü."""
        out: dict[str, str] = {}
        if self.amount_try is not None:
            out["amount_try"] = str(self.amount_try)
        if self.term_months is not None:
            out["term_months"] = str(self.term_months)
        if self.term_months_options:
            out["term_months_options"] = ",".join(str(t) for t in self.term_months_options)
        if self.term_days is not None:
            out["term_days"] = str(self.term_days)
        if self.product_type:
            out["product_type"] = self.product_type
        if self.asset_type:
            out["asset_type"] = self.asset_type
        if self.asset_value_try is not None:
            out["asset_value_try"] = str(self.asset_value_try)
        if self.energy_class:
            out["energy_class"] = self.energy_class
        if self.first_home is not None:
            out["first_home"] = "true" if self.first_home else "false"
        if self.deposit_try is not None:
            out["deposit_try"] = str(self.deposit_try)
        if self.currency:
            out["currency"] = self.currency
        if self.bank_codes:
            out["bank_codes"] = ",".join(self.bank_codes)
        return out


def extract_slots(raw: str, *, bank_codes: tuple[str, ...] = ()) -> QuerySlots:
    """Kullanıcı metninden araç slotlarını çıkarır."""
    slots = QuerySlots(bank_codes=list(bank_codes))
    katlanmis = _fold(raw)
    ham = raw or ""

    tutar, _pb = parse_money(ham)
    if tutar is not None and tutar > 0:
        slots.amount_try = tutar
        slots.asset_value_try = tutar
        slots.deposit_try = tutar

    # "400.000 TL finansman" gibi para birimi olmayan çıplak tutar.
    # ⚠️ "120 ay" tutar değildir — vade birimi varsa atla.
    if slots.amount_try is None:
        bare = re.search(
            r"(\d[\d.]*)\s*(bin|milyon|milyar)?(?!\s*(?:ay|vade|yil|yıl|gun|gün))"
            r"\s*(?:tl|₺|try)?(?!\w)",
            katlanmis,
        )
        if bare:
            sonrasi = katlanmis[bare.end() : bare.end() + 12].lstrip()
            if not re.match(r"(?:ay|vade|yil|yıl|gun|gün)\b", sonrasi):
                deger = parse_decimal_tr(bare.group(1))
                if deger is not None:
                    carpan = {"bin": 1000, "milyon": 1_000_000, "milyar": 1_000_000_000}.get(
                        (bare.group(2) or "").lower(), 1
                    )
                    if (
                        bare.group(2)
                        or re.search(r"(?:tl|₺|try)\b", bare.group(0))
                        or deger >= 1000
                    ):
                        slots.amount_try = deger * carpan
                        slots.asset_value_try = slots.amount_try
                        slots.deposit_try = slots.amount_try

    ay = _VADE_AY_RE.search(katlanmis)
    if ay:
        slots.term_months = int(ay.group(1))
        slots.term_days = slots.term_months * 30
    else:
        yil = _VADE_YIL_RE.search(katlanmis)
        if yil:
            slots.term_months = int(yil.group(1)) * 12
            slots.term_days = slots.term_months * 30
        else:
            gun = _GUN_RE.search(katlanmis)
            if gun:
                slots.term_days = int(gun.group(1))
                slots.term_months = max(1, round(slots.term_days / 30))

    # Çoklu vade: "12 veya 24", "12-24 ay" — tek seçim yapılmadan netleştirilir.
    coklu = _VADE_COKLU_RE.search(katlanmis)
    if coklu:
        adaylar = sorted({int(coklu.group(1)), int(coklu.group(2))})
        adaylar = [a for a in adaylar if 1 <= a <= 360]
        if len(adaylar) >= 2:
            slots.term_months_options = adaylar
            slots.term_months = None
            slots.term_days = None
        elif len(adaylar) == 1:
            slots.term_months = adaylar[0]
            slots.term_days = slots.term_months * 30

    # parse_money hâlâ "120 ay"yi tutar sanmış olabilir — vade ile çakışanı düş.
    if (
        slots.amount_try is not None
        and slots.term_months is not None
        and slots.amount_try == slots.term_months
        and not re.search(r"(?:tl|₺|try|lira)\b", katlanmis)
    ):
        slots.amount_try = None
        slots.asset_value_try = None
        slots.deposit_try = None

    for tip, kaliplar in _PRODUCT_PATTERNS:
        if any(k in katlanmis for k in kaliplar):
            slots.product_type = tip
            break

    for tip, kaliplar in _ASSET_TYPE_PATTERNS:
        if any(k in katlanmis for k in kaliplar):
            slots.asset_type = tip
            break

    if slots.product_type and slots.asset_type is None:
        slots.asset_type = {
            "tasit_finansmani": "tasit",
            "konut_finansmani": "konut",
            "ihtiyac_finansmani": "ihtiyac",
        }.get(slots.product_type)

    enerji = _ENERJI_RE.search(katlanmis) or _ENERJI_KISA.search(katlanmis)
    if enerji:
        sinif = enerji.group(1).upper().replace("İ", "I")
        if sinif in {"A", "B", "A-B"}:
            slots.energy_class = "A"
        elif sinif == "C":
            slots.energy_class = "C"
        else:
            slots.energy_class = "DIGER"

    if any(k in katlanmis for k in ("ilk konut", "birinci konut", "ilk ev")):
        slots.first_home = True
    elif any(k in katlanmis for k in ("ikinci konut", "ikinci ev", "sonraki konut")):
        slots.first_home = False

    for anahtar, kod in _CURRENCY_MAP.items():
        if anahtar in katlanmis:
            slots.currency = kod
            break

    # Araç ipucu — kelime sınırına duyarlı ( "hesapla" ⊂ "hesaplari" olmasın ).
    def _var(*kelimeler: str) -> bool:
        return any(
            re.search(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])", katlanmis) for k in kelimeler
        )

    limit_kok = re.search(r"(?<![a-z0-9])limit", katlanmis) is not None
    kampanya_sorusu = (
        _var(
            "kampanya",
            "kampanyalari",
            "kampanyasi",
            "kampanyalar",
            "nakit iade",
            "hediye ceki",
        )
        or re.search(r"(?<![a-z0-9])kampanya", katlanmis) is not None
    )
    if (
        _var("bddk", "azami finansman", "ltv", "kasko degeri", "kasko değeri")
        or (
            limit_kok
            and (
                slots.product_type
                or slots.asset_type
                or _var("finansman", "tasit", "konut", "ihtiyac", "arac", "kredi")
            )
        )
        or _var("azami oran", "azami vade", "azami tutar", "finansman limiti")
    ):
        slots.tool_hint = "bddk_limit"
    elif not kampanya_sorusu and _var(
        "simule",
        "simulasyon",
        "simülasyon",
        "hesapla",
        "taksit",
        "uygunlar",
        "bana uygun",
        "finansman tutar",
        "finansman istiyorum",
        "en mantikli",
        "en mantıklı",
        "mantikli finansman",
        "mantıklı finansman",
        "hangi finansman",
        "arac almak",
        "araç almak",
        "ev almak",
        "konut almak",
        "onerir",
        "önerir",
        "finansman oner",
        "finansman öner",
    ):
        slots.tool_hint = "finansman_teklif"
    elif (
        slots.amount_try is not None
        and slots.product_type
        and _var("hangisi", "oner", "öner", "uygun", "avantajli", "avantajlı")
    ):
        # Tutar + ürün türü varken "hangisi" oran listesi değil teklif simülasyonu.
        slots.tool_hint = "finansman_teklif"
    elif _var("getiri hesapla", "ne kadar kazani", "ne kadar kazanir", "ne kadar kazanır") or (
        _var("yatir", "yatirir", "yatirsam", "yatirdim")
        and _var("katilma", "katilim", "hesap", "hesabi")
    ):
        slots.tool_hint = "katilma_getiri"
    elif _var("karsilastir", "karşılaştır", "hangisi daha"):
        slots.tool_hint = "urun_karsilastir"

    # Oran tablosu sorusu: tutar/vade simülasyon slotlarını temizle.
    from app.retrieval.query import (
        finansman_oran_listesi_mi,
        katilma_kar_payi_paylasim_karsilastirma_mi,
        katilma_oran_listesi_mi,
        parse_katilma_vadeler,
    )

    if katilma_oran_listesi_mi(raw):
        slots.deposit_try = None
        slots.amount_try = None
        slots.asset_value_try = None
        if len(parse_katilma_vadeler(katlanmis)) >= 2:
            slots.term_months = None
            slots.term_days = None
        if slots.tool_hint == "katilma_getiri":
            slots.tool_hint = None

    if finansman_oran_listesi_mi(raw):
        if slots.amount_try is not None and not _var(
            "hesapla", "simule", "simulasyon", "taksit", "odeme", "ödeme"
        ):
            slots.amount_try = None
        if slots.tool_hint == "finansman_teklif":
            slots.tool_hint = None

    if katilma_kar_payi_paylasim_karsilastirma_mi(raw):
        slots.deposit_try = None
        slots.amount_try = None
        slots.tool_hint = None

    return slots


def validate_numeric_slots_against_query(
    raw: str,
    proposed: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """LLM'in önerdiği sayısal slotları sorgu metnine karşı doğrular.

    Sorguda geçmeyen sayı düşürülür. Dönüş: (temizlenmiş sözlük, reddedilen anahtarlar).
    """
    gercek = extract_slots(raw)
    temiz: dict[str, Any] = {}
    reddedilen: list[str] = []

    sayisal: dict[str, Decimal | int | None] = {
        "amount_try": gercek.amount_try,
        "term_months": gercek.term_months,
        "term_days": gercek.term_days,
        "asset_value_try": gercek.asset_value_try,
        "deposit_try": gercek.deposit_try,
    }
    # Çoklu vade adaylarından biri LLM önerisiyle örtüşüyorsa kabul et.
    term_adaylari = set(gercek.term_months_options)
    if gercek.term_months is not None:
        term_adaylari.add(gercek.term_months)

    for anahtar, deger in proposed.items():
        if anahtar not in sayisal:
            temiz[anahtar] = deger
            continue
        gercek_deger = sayisal[anahtar]
        if anahtar == "term_months" and gercek_deger is None and term_adaylari:
            try:
                onerilen_vade = int(Decimal(str(deger).replace(",", ".")))
            except Exception:
                reddedilen.append(anahtar)
                continue
            if onerilen_vade in term_adaylari:
                temiz[anahtar] = str(onerilen_vade)
            else:
                reddedilen.append(anahtar)
            continue
        if gercek_deger is None:
            reddedilen.append(anahtar)
            continue
        try:
            onerilen = Decimal(str(deger).replace(",", "."))
        except Exception:
            reddedilen.append(anahtar)
            continue
        # Tolerans: %1 veya 1 birim — biçim farkı (400000 vs 400.000).
        mevcut = Decimal(str(gercek_deger))
        if mevcut == 0:
            if onerilen != 0:
                reddedilen.append(anahtar)
                continue
        elif abs(onerilen - mevcut) / mevcut > Decimal("0.01") and abs(onerilen - mevcut) > 1:
            reddedilen.append(anahtar)
            continue
        temiz[anahtar] = str(gercek_deger)

    return temiz, reddedilen


def missing_for_tool(tool: str, slots: QuerySlots) -> list[str]:
    """Araç için zorunlu ama eksik slot adları."""
    if tool == "finansman_teklif":
        eksik = []
        if slots.amount_try is None:
            eksik.append("amount_try")
        if slots.term_months is None:
            eksik.append("term_months")
        if slots.product_type is None:
            eksik.append("product_type")
        return eksik
    if tool == "bddk_limit":
        eksik = []
        if slots.asset_type is None:
            eksik.append("asset_type")
        # Genel "limitler nedir" sorusunda değer zorunlu değil — kanon özeti verilir.
        return eksik
    if tool == "katilma_getiri":
        eksik = []
        if slots.deposit_try is None:
            eksik.append("deposit_try")
        if slots.term_days is None and slots.term_months is None:
            eksik.append("term_days")
        return eksik
    if tool == "urun_karsilastir":
        return []
    return []


__all__ = [
    "QuerySlots",
    "extract_slots",
    "missing_for_tool",
    "validate_numeric_slots_against_query",
]
