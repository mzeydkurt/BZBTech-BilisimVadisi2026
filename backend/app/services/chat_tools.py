"""Sohbet araç kayıt defteri — deterministik, model sayı üretmez.

Araçlar mevcut Python servislerini çağırır:
  finansman_teklif → calculate_financing_simulation
  bddk_limit       → check_bddk_limits
  katilma_getiri   → calculate_participation_yield
  urun_karsilastir → rank_products

Zorunlu slot eksikse hesaplama yapılmaz; netleştirme aksiyonları döner.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Final

from sqlalchemy.orm import Session

from app.retrieval.slots import QuerySlots, extract_slots, missing_for_tool
from app.schemas.chat import (
    ChatAction,
    ChatBddkBlock,
    ChatOfferItem,
    ChatToolRun,
)
from app.schemas.simulator import (
    BDDKLimitCheckRequest,
    FinancingSimulationRequest,
    ParticipationYieldRequest,
)
from app.services.bddk_limits_service import check_bddk_limits, get_canonical_limits
from app.services.comparison_service import RankingError, rank_products
from app.services.simulator_service import (
    _kurusla,
    calculate_financing_simulation,
    calculate_participation_yield,
)

TOOL_NAMES: Final[tuple[str, ...]] = (
    "finansman_teklif",
    "bddk_limit",
    "katilma_getiri",
    "urun_karsilastir",
)

_PRODUCT_LABEL: Final[dict[str, str]] = {
    "tasit_finansmani": "Taşıt",
    "konut_finansmani": "Konut",
    "ihtiyac_finansmani": "İhtiyaç",
}


@dataclass
class ToolResult:
    """Araç çalıştırmasının sohbete eklenecek çıktısı."""

    answer_text: str
    offers: list[ChatOfferItem] = field(default_factory=list)
    actions: list[ChatAction] = field(default_factory=list)
    tool_runs: list[ChatToolRun] = field(default_factory=list)
    bddk: ChatBddkBlock | None = None
    clarification_needed: bool = False
    clarification_question: str | None = None
    products: list[Any] = field(default_factory=list)
    comparison: Any | None = None


def detect_tool(raw: str, *, source_domain: str, slots: QuerySlots | None = None) -> str | None:
    """Hangi aracın çalışması gerektiğini seçer. Yoksa None."""
    import re

    from app.retrieval.slots import _fold

    # Kampanya araması RAG ile yapılır; finansman simülasyonuna düşme.
    if source_domain == "kampanya":
        return None

    s = slots or extract_slots(raw)
    katlanmis = _fold(raw)

    from app.retrieval.query import (
        finansman_oran_listesi_mi,
        katilma_kar_payi_paylasim_karsilastirma_mi,
        katilma_oran_listesi_mi,
    )

    # Oran listesi → pivot / ürün oranı; simülasyon değil.
    if source_domain == "katilma" and katilma_oran_listesi_mi(raw):
        return None
    if source_domain == "finansman" and finansman_oran_listesi_mi(raw):
        return None
    if katilma_kar_payi_paylasim_karsilastirma_mi(raw):
        return None

    def _var(*kelimeler: str) -> bool:
        return any(
            re.search(rf"(?<![a-z0-9]){re.escape(_fold(k))}(?![a-z0-9])", katlanmis)
            for k in kelimeler
        )

    teklif_niyeti = _var(
        "uygun",
        "bul",
        "öner",
        "oner",
        "önerir",
        "onerir",
        "hesapla",
        "taksit",
        "hangisi",
        "mantikli",
        "avantajli",
        "almak",
        "simule",
        "simulasyon",
    ) or re.search(r"(?<![a-z0-9])oner", katlanmis) is not None

    # BDDK / limit soruları — oran listesi veya tanıma düşmesin.
    limit_kok = re.search(r"(?<![a-z0-9ğüşıöç])limit", katlanmis) is not None
    limit_niyeti = (
        s.tool_hint == "bddk_limit"
        or _var("bddk", "azami finansman", "ltv", "azami oran", "azami vade")
        or (
            limit_kok
            and (s.asset_type or s.product_type or _var("finansman", "tasit", "konut", "ihtiyac"))
        )
    )
    if limit_niyeti and (s.asset_type or s.product_type or _var("bddk", "finansman")):
        if s.product_type and not s.asset_type:
            s.asset_type = {
                "tasit_finansmani": "tasit",
                "konut_finansmani": "konut",
                "ihtiyac_finansmani": "ihtiyac",
            }.get(s.product_type)
        return "bddk_limit"

    # Tutar + ürün + teklif niyeti → toplam maliyet simülasyonu (oran listesi değil).
    if s.amount_try is not None and s.product_type and (
        teklif_niyeti or s.tool_hint == "finansman_teklif" or bool(s.term_months_options)
    ):
        return "finansman_teklif"

    # Vade + ürün + öneri, tutar yok → netleştir (120 ay'ı tutar sanma).
    if s.product_type and s.term_months is not None and (
        teklif_niyeti or s.tool_hint == "finansman_teklif"
    ):
        return "finansman_teklif"

    if s.tool_hint and s.tool_hint != "urun_karsilastir":
        return s.tool_hint
    if s.tool_hint == "urun_karsilastir" and s.amount_try is None:
        return "urun_karsilastir"

    # Finansman teklifi: tutar + vade (+ isteğe bağlı ürün) veya açık istek.
    if s.amount_try is not None and s.term_months is not None and source_domain == "finansman":
        return "finansman_teklif"
    if s.amount_try is not None and s.term_months is not None and (
        teklif_niyeti or _var("finansman")
    ):
        return "finansman_teklif"

    if (
        _var("bddk", "azami finansman", "ne kadar alabilir", "kasko")
        and (s.asset_value_try is not None or "bddk" in katlanmis)
    ):
        return "bddk_limit"

    if (
        source_domain == "katilma"
        and s.deposit_try is not None
        and (s.term_days is not None or s.term_months is not None)
        and _var(
            "hesapla",
            "ne kadar",
            "getiri",
            "kazan",
            "yatir",
            "yatirir",
            "yatirsam",
            "donem sonu",
            "olur",
            "olma",
            "param",
            "bakiye",
        )
    ):
        return "katilma_getiri"

    if s.tool_hint:
        return s.tool_hint

    return None


def _simulator_action(
    *,
    label: str,
    tab: str,
    params: dict[str, str],
    reason: str | None = None,
) -> ChatAction:
    tum = {"tab": tab, "autorun": "1", **params}
    return ChatAction(
        kind="prefill",
        label=label,
        path="/simulator",
        params=tum,
        reason=reason,
    )


def _product_clarify_actions(slots: QuerySlots) -> list[ChatAction]:
    """Ürün türü eksikse seçim aksiyonları."""
    base: dict[str, str] = {}
    if slots.amount_try is not None:
        base["amount"] = str(int(slots.amount_try))
    if slots.term_months is not None:
        base["term"] = str(slots.term_months)
    aksiyonlar: list[ChatAction] = []
    for tip, etiket in _PRODUCT_LABEL.items():
        aksiyonlar.append(
            ChatAction(
                kind="refine",
                label=etiket,
                path=None,
                params={**base, "product_type": tip},
                reason=f"{etiket} finansmanı için hesapla",
            )
        )
    return aksiyonlar


def run_tool(
    session: Session,
    tool: str,
    slots: QuerySlots,
    *,
    rate_type: str | None = None,
) -> ToolResult:
    """Seçilen aracı çalıştırır veya netleştirme döner."""
    eksik = missing_for_tool(tool, slots)
    if eksik:
        return _clarify(tool, slots, eksik)

    baslangic = time.perf_counter()
    if tool == "finansman_teklif":
        return _finansman(session, slots, baslangic)
    if tool == "bddk_limit":
        return _bddk(slots, baslangic)
    if tool == "katilma_getiri":
        return _katilma(session, slots, baslangic)
    if tool == "urun_karsilastir":
        return _karsilastir(session, slots, rate_type=rate_type, baslangic=baslangic)
    return ToolResult(answer_text="Bu araç desteklenmiyor.")


def _clarify(tool: str, slots: QuerySlots, eksik: list[str]) -> ToolResult:
    if "product_type" in eksik and tool == "finansman_teklif":
        soru = (
            "Finansman türünü belirtir misiniz? Taşıt, konut veya ihtiyaç "
            "finansmanından hangisini arıyorsunuz?"
        )
        return ToolResult(
            answer_text=soru,
            clarification_needed=True,
            clarification_question=soru,
            actions=_product_clarify_actions(slots),
            tool_runs=[
                ChatToolRun(
                    tool=tool,
                    inputs=slots.as_input_dict(),
                    summary="Ürün türü eksik — hesaplama yapılmadı.",
                    note=f"Eksik: {', '.join(eksik)}",
                )
            ],
        )
    if "term_months" in eksik and tool == "finansman_teklif" and slots.term_months_options:
        secenekler = " veya ".join(f"{t} ay" for t in slots.term_months_options)
        soru = (
            f"Hangi vade ile hesaplayayım: {secenekler}? "
            "Seçince simülatörde taksitler otomatik hesaplanır."
        )
        aksiyonlar: list[ChatAction] = []
        for t in slots.term_months_options:
            params: dict[str, str] = {"term": str(t)}
            if slots.amount_try is not None:
                params["amount"] = str(int(slots.amount_try))
            if slots.product_type:
                params["product_type"] = slots.product_type
            aksiyonlar.append(
                _simulator_action(
                    label=f"{t} ay — simülatörde hesapla",
                    tab="financing",
                    params=params,
                )
            )
            # Sohbette de devam etmek isteyenler için refine.
            aksiyonlar.append(
                ChatAction(
                    kind="refine",
                    label=f"{t} ay (sohbette)",
                    params={"term_months": str(t)},
                )
            )
        return ToolResult(
            answer_text=soru,
            clarification_needed=True,
            clarification_question=soru,
            actions=aksiyonlar,
            tool_runs=[
                ChatToolRun(
                    tool=tool,
                    inputs=slots.as_input_dict(),
                    summary="Vade seçimi bekleniyor — simülatör hazır.",
                    note=f"Aday vadeler: {', '.join(str(t) for t in slots.term_months_options)}",
                )
            ],
        )
    if "asset_type" in eksik:
        soru = "BDDK limiti için varlık türünü belirtin: taşıt, konut veya ihtiyaç."
        return ToolResult(
            answer_text=soru,
            clarification_needed=True,
            clarification_question=soru,
            actions=[
                ChatAction(kind="refine", label="Taşıt", params={"asset_type": "tasit"}),
                ChatAction(kind="refine", label="Konut", params={"asset_type": "konut"}),
                ChatAction(kind="refine", label="İhtiyaç", params={"asset_type": "ihtiyac"}),
            ],
            tool_runs=[
                ChatToolRun(
                    tool=tool,
                    inputs=slots.as_input_dict(),
                    summary="Varlık türü eksik — BDDK kontrolü yapılmadı.",
                    note=f"Eksik: {', '.join(eksik)}",
                )
            ],
        )
    etiketler = {
        "amount_try": "finansman tutarı",
        "term_months": "vade (ay)",
        "asset_value_try": "varlık / kasko / ekspertiz değeri",
        "deposit_try": "yatırılacak tutar",
        "term_days": "vade (gün veya ay)",
    }
    eksik_tr = ", ".join(etiketler.get(e, e) for e in eksik)
    soru = f"Hesaplama için şunları belirtmeniz gerekiyor: {eksik_tr}."
    aksiyonlar: list[ChatAction] = []
    # Yalnızca tutar eksikse sık kullanılan tutarlarla simülatöre / sohbete yönlendir.
    if (
        tool == "finansman_teklif"
        and eksik == ["amount_try"]
        and slots.term_months is not None
        and slots.product_type
    ):
        soru += " Tutar seçerseniz simülatörde taksitler otomatik hesaplanır."
        for tutar in (500_000, 1_000_000, 2_000_000, 5_000_000):
            aksiyonlar.append(
                _simulator_action(
                    label=f"{tutar // 1000}.000 TL — simülatörde hesapla"
                    if tutar < 1_000_000
                    else f"{tutar // 1_000_000} milyon TL — simülatörde hesapla",
                    tab="financing",
                    params={
                        "amount": str(tutar),
                        "term": str(slots.term_months),
                        "product_type": slots.product_type,
                    },
                )
            )
    # Yalnızca vade eksikse sık kullanılan vadelerle simülatöre derin bağlantı.
    elif (
        tool == "finansman_teklif"
        and eksik == ["term_months"]
        and slots.amount_try is not None
        and slots.product_type
    ):
        soru += " Aşağıdan vade seçerseniz simülatörde taksitler otomatik hesaplanır."
        for t in (12, 24, 36, 48):
            aksiyonlar.append(
                _simulator_action(
                    label=f"{t} ay — simülatörde hesapla",
                    tab="financing",
                    params={
                        "amount": str(int(slots.amount_try)),
                        "term": str(t),
                        "product_type": slots.product_type,
                    },
                )
            )
    return ToolResult(
        answer_text=soru,
        clarification_needed=True,
        clarification_question=soru,
        actions=aksiyonlar,
        tool_runs=[
            ChatToolRun(
                tool=tool,
                inputs=slots.as_input_dict(),
                summary="Zorunlu parametre eksik — hesaplama yapılmadı.",
                note=f"Eksik: {', '.join(eksik)}",
            )
        ],
    )


def _finansman(session: Session, slots: QuerySlots, baslangic: float) -> ToolResult:
    assert slots.amount_try is not None
    assert slots.term_months is not None
    assert slots.product_type is not None

    req = FinancingSimulationRequest(
        amount_try=slots.amount_try,
        term_months=slots.term_months,
        product_type=slots.product_type,
        bank_codes=slots.bank_codes or None,
    )
    sonuc = calculate_financing_simulation(session, req)
    ms = int((time.perf_counter() - baslangic) * 1000)

    params = {
        "amount": str(int(slots.amount_try)),
        "term": str(slots.term_months),
        "product_type": slots.product_type,
    }
    offers: list[ChatOfferItem] = []
    for teklif in sonuc.offers[:3]:
        offers.append(
            ChatOfferItem(
                bank_code=teklif.bank_code,
                bank_name=teklif.bank_name,
                product_id=teklif.product_id,
                product_name=teklif.product_name,
                product_type=slots.product_type,
                profit_rate_pct=teklif.profit_rate_pct,
                monthly_payment_try=teklif.monthly_payment_try,
                total_cost_try=teklif.total_cost_try,
                term_months=slots.term_months,
                term_exact_match=teklif.is_exact_term_match,
                is_binding=teklif.is_binding,
                source_url=teklif.source_url,
                summary=(
                    f"Aylık {teklif.monthly_payment_try:,.2f} ₺ · "
                    f"Toplam {teklif.total_cost_try:,.2f} ₺ · "
                    f"Kâr payı %{teklif.profit_rate_pct}"
                ).replace(",", "X").replace(".", ",").replace("X", "."),
                action=_simulator_action(
                    label="Simülatörde taksitleri gör",
                    tab="financing",
                    params=params,
                    reason=teklif.bank_name,
                ),
            )
        )

    etiket = _PRODUCT_LABEL.get(slots.product_type, slots.product_type)
    if not offers:
        metin = sonuc.method_note or (
            f"{etiket} finansmanı için {slots.amount_try} ₺ / {slots.term_months} ay "
            "ile teklif üretilemedi. Oranı yayımlayan banka bulunamadı veya "
            "BDDK vade tavanı aşıldı."
        )
    else:
        satirlar = []
        for i, o in enumerate(offers, 1):
            satirlar.append(
                f"{i}. {o.bank_name}: aylık {o.monthly_payment_try} ₺, "
                f"toplam {o.total_cost_try} ₺ (kâr payı %{o.profit_rate_pct})."
            )
        metin = (
            f"{etiket} finansmanı · {slots.amount_try} ₺ · {slots.term_months} ay "
            f"için en uygun {len(offers)} teklif:\n" + "\n".join(satirlar)
        )
        if sonuc.method_note:
            metin += f"\n{sonuc.method_note}"

    aksiyonlar = [
        _simulator_action(
            label="Simülatörde tüm bankaları hesapla",
            tab="financing",
            params=params,
        )
    ]
    return ToolResult(
        answer_text=metin,
        offers=offers,
        actions=aksiyonlar,
        tool_runs=[
            ChatToolRun(
                tool="finansman_teklif",
                inputs=slots.as_input_dict(),
                summary=(
                    f"{etiket} · {slots.amount_try} ₺ / {slots.term_months} ay · "
                    f"{len(sonuc.offers)} teklif · {len(sonuc.banks_without_data)} banka veri yok"
                ),
                elapsed_ms=ms,
                note=sonuc.method_note,
            )
        ],
    )


def _bddk(slots: QuerySlots, baslangic: float) -> ToolResult:
    if slots.asset_type is None and slots.product_type:
        slots.asset_type = {
            "tasit_finansmani": "tasit",
            "konut_finansmani": "konut",
            "ihtiyac_finansmani": "ihtiyac",
        }.get(slots.product_type)

    assert slots.asset_type is not None

    # Değer yoksa: banka oranlarını uydurma — BDDK kanon özetini ver.
    if slots.asset_value_try is None:
        return _bddk_ozet(slots, baslangic)

    req = BDDKLimitCheckRequest(
        asset_type=slots.asset_type,
        asset_value_try=slots.asset_value_try,
        energy_class=slots.energy_class,
        first_home=slots.first_home,
    )
    sonuc = check_bddk_limits(req)
    ms = int((time.perf_counter() - baslangic) * 1000)

    bddk = ChatBddkBlock(
        asset_type=sonuc.asset_type,
        asset_value_try=sonuc.asset_value_try,
        energy_class=sonuc.energy_class,
        first_home=sonuc.first_home,
        value_band_label=sonuc.value_band_label,
        max_financing_ratio_pct=sonuc.max_financing_ratio_pct,
        max_financing_amount_try=sonuc.max_financing_amount_try,
        max_allowed_term_months=sonuc.max_allowed_term_months,
        is_financing_allowed=sonuc.is_financing_allowed,
        legal_reference=sonuc.legal_reference,
    )

    if not sonuc.is_financing_allowed:
        metin = (
            f"{sonuc.value_band_label or sonuc.asset_type} bandında finansman "
            f"izin verilmiyor (değer: {sonuc.asset_value_try} ₺). "
            f"Dayanak: {sonuc.legal_reference or 'BDDK'}."
        )
    else:
        parcalar = [
            f"Varlık değeri {sonuc.asset_value_try} ₺ "
            f"({sonuc.value_band_label or sonuc.asset_type}).",
            f"Azami finansman oranı %{sonuc.max_financing_ratio_pct}.",
            f"Azami tutar {sonuc.max_financing_amount_try} ₺.",
        ]
        if sonuc.max_allowed_term_months:
            parcalar.append(f"Azami vade {sonuc.max_allowed_term_months} ay.")
        if sonuc.legal_reference:
            parcalar.append(f"Dayanak: {sonuc.legal_reference}.")
        metin = " ".join(parcalar)

    params: dict[str, str] = {
        "asset_value": str(int(slots.asset_value_try)),
        "asset_type": slots.asset_type,
    }
    if slots.energy_class:
        params["energy_class"] = slots.energy_class
    if slots.first_home is not None:
        params["first_home"] = "true" if slots.first_home else "false"

    return ToolResult(
        answer_text=metin,
        bddk=bddk,
        actions=[
            _simulator_action(
                label="Simülatörde BDDK hesapla",
                tab="bddk",
                params=params,
            )
        ],
        tool_runs=[
            ChatToolRun(
                tool="bddk_limit",
                inputs=slots.as_input_dict(),
                summary=(
                    f"{sonuc.asset_type} · {sonuc.asset_value_try} ₺ → "
                    f"azami {sonuc.max_financing_amount_try} ₺"
                ),
                elapsed_ms=ms,
                note=sonuc.legal_reference,
            )
        ],
    )


def _bddk_ozet(slots: QuerySlots, baslangic: float) -> ToolResult:
    """Değer verilmeden genel BDDK tavan özeti (kanon JSON)."""
    assert slots.asset_type is not None
    aile = slots.asset_type
    view = get_canonical_limits(family=aile)
    ms = int((time.perf_counter() - baslangic) * 1000)
    etiket = {"tasit": "Taşıt", "konut": "Konut", "ihtiyac": "İhtiyaç"}.get(aile, aile)

    if view is None:
        return ToolResult(
            answer_text=f"{etiket} için BDDK kanon kaydı bulunamadı.",
            tool_runs=[
                ChatToolRun(
                    tool="bddk_limit",
                    inputs=slots.as_input_dict(),
                    summary="Kanon yok",
                    elapsed_ms=ms,
                )
            ],
        )

    satirlar: list[str] = [f"BDDK {etiket} finansmanı azami limitleri ({view.decision_date}):"]
    for b in view.bands:
        parca = f"• {b.label}"
        if b.max_ratio_pct is not None:
            parca += f" — azami oran %{b.max_ratio_pct}"
        if b.rates:
            oran_yaz = ", ".join(f"{k}: %{v}" for k, v in sorted(b.rates.items()))
            parca += f" — {oran_yaz}"
        if b.max_term_months is not None:
            parca += f" — azami vade {b.max_term_months} ay"
        elif b.max_ratio_pct == 0:
            parca += " — finansman izin verilmiyor"
        satirlar.append(parca)
    if view.max_term_months:
        satirlar.append(f"Genel azami vade: {view.max_term_months} ay.")
    if view.second_home_note:
        satirlar.append(view.second_home_note)
    satirlar.append(f"Dayanak: {view.legal_reference}.")
    satirlar.append(
        "Belirli bir araç/konut değeri yazarsanız o banda göre azami tutarı hesaplarım."
    )
    metin = "\n".join(satirlar)

    return ToolResult(
        answer_text=metin,
        actions=[
            _simulator_action(
                label="Simülatörde BDDK sorgula",
                tab="bddk",
                params={"asset_type": aile},
            )
        ],
        tool_runs=[
            ChatToolRun(
                tool="bddk_limit",
                inputs=slots.as_input_dict(),
                summary=f"{etiket} · {len(view.bands)} bant · kanon özeti",
                elapsed_ms=ms,
                note=view.legal_reference,
            )
        ],
    )


def _katilma(session: Session, slots: QuerySlots, baslangic: float) -> ToolResult:
    assert slots.deposit_try is not None
    term_days = slots.term_days or (slots.term_months or 12) * 30
    ay = slots.term_months or max(1, round(term_days / 30))

    req = ParticipationYieldRequest(
        deposit_try=slots.deposit_try,
        term_days=term_days,
        currency=slots.currency or "TRY",
        bank_codes=slots.bank_codes or None,
    )
    sonuc = calculate_participation_yield(session, req)
    ms = int((time.perf_counter() - baslangic) * 1000)

    offers: list[ChatOfferItem] = []
    for teklif in sonuc.offers[:3]:
        bakiye = _kurusla(slots.deposit_try + teklif.net_profit_try)
        paylasim = ""
        if teklif.investor_share_pct is not None:
            paylasim = f" · Müşteri payı %{teklif.investor_share_pct}"
        offers.append(
            ChatOfferItem(
                bank_code=teklif.bank_code,
                bank_name=teklif.bank_name,
                product_id=teklif.product_id,
                product_name=teklif.product_name,
                product_type="birikim_katilma_hesabi",
                profit_rate_pct=teklif.annual_yield_gross_pct,
                monthly_payment_try=None,
                total_cost_try=teklif.net_profit_try,
                term_months=ay,
                term_exact_match=teklif.is_exact_term_match,
                is_binding=None,
                source_url=teklif.source_url,
                summary=(
                    f"Brüt {teklif.gross_profit_try} ₺ · Stopaj {teklif.withholding_try} ₺ "
                    f"(%{teklif.withholding_pct}) · Net {teklif.net_profit_try} ₺ · "
                    f"Bakiye {bakiye} ₺{paylasim}"
                ),
                action=_simulator_action(
                    label="Simülatörde getiriyi hesapla",
                    tab="yield",
                    params={
                        "deposit": str(int(slots.deposit_try)),
                        "term_days": str(term_days),
                        "currency": slots.currency or "TRY",
                    },
                ),
            )
        )

    if not offers:
        banka_notu = ""
        if sonuc.banks_without_data:
            banka_notu = " " + "; ".join(
                f"{m.bank_name}: {m.reason}" for m in sonuc.banks_without_data[:3]
            )
        metin = (
            "Katılma hesabı getirisi için yayımlanmış oran bulunamadı."
            + banka_notu
        )
    elif len(offers) == 1:
        t = sonuc.offers[0]
        bakiye = _kurusla(slots.deposit_try + t.net_profit_try)
        metin = (
            f"{t.bank_name} · Standart Katılma Hesabı · {slots.deposit_try} ₺ · "
            f"{ay} ay ({term_days} gün):\n"
            f"• Geçmiş dağıtılan kâr payı (yıllık): %{t.annual_yield_gross_pct}"
            f"{' (tam vade eşleşmesi)' if t.is_exact_term_match else ''}\n"
            f"• Brüt kâr payı: {t.gross_profit_try} ₺\n"
            f"• Stopaj kesintisi (%{t.withholding_pct}): {t.withholding_try} ₺\n"
            f"• Net kâr: {t.net_profit_try} ₺\n"
            f"• Dönem sonu tahmini bakiye: {bakiye} ₺"
        )
        if t.investor_share_pct is not None:
            metin += f"\n• Müşteri kâr paylaşım oranı: %{t.investor_share_pct}"
            if t.bank_share_pct is not None:
                metin += f" (banka payı %{t.bank_share_pct})"
        metin += f"\n\n{sonuc.withholding_note}"
        metin += f"\n{sonuc.method_note}"
    else:
        satirlar = []
        for i, o in enumerate(offers, 1):
            t = sonuc.offers[i - 1]
            satirlar.append(
                f"{i}. {o.bank_name}: net {o.total_cost_try} ₺ "
                f"(brüt {t.gross_profit_try} ₺, stopaj {t.withholding_try} ₺, "
                f"yıllık %{o.profit_rate_pct})"
            )
        metin = (
            f"{slots.deposit_try} ₺ · {ay} ay · {slots.currency} "
            f"katılma hesabı için en yüksek {len(offers)} getiri:\n"
            + "\n".join(satirlar)
            + f"\n\n{sonuc.withholding_note}"
        )

    return ToolResult(
        answer_text=metin,
        offers=offers,
        actions=[
            _simulator_action(
                label="Simülatörde getiriyi hesapla",
                tab="yield",
                params={
                    "deposit": str(int(slots.deposit_try)),
                    "term_days": str(term_days),
                    "currency": slots.currency or "TRY",
                },
            ),
            ChatAction(
                kind="navigate",
                label="Katılma hesabı tablosu",
                path="/katilim-hesabi",
            ),
        ],
        tool_runs=[
            ChatToolRun(
                tool="katilma_getiri",
                inputs=slots.as_input_dict(),
                summary=f"{slots.deposit_try} ₺ / {term_days} gün · {len(sonuc.offers)} teklif",
                elapsed_ms=ms,
            )
        ],
    )


def _karsilastir(
    session: Session,
    slots: QuerySlots,
    *,
    rate_type: str | None,
    baslangic: float,
) -> ToolResult:
    rt = rate_type or "financing_rate"
    criterion = {
        "financing_rate": "en_dusuk_kar_payi",
        "participation_yield": "en_yuksek_getiri",
        "profit_sharing_ratio": "en_yuksek_paylasim_orani",
    }.get(rt, "en_dusuk_kar_payi")
    try:
        ranking = rank_products(
            session,
            rate_type=rt,
            criterion=criterion,
            product_type=slots.product_type,
            bank_codes=slots.bank_codes or None,
            term_months=slots.term_months,
            amount_try=slots.amount_try,
            limit=5,
        )
    except RankingError as exc:
        return ToolResult(
            answer_text=str(exc),
            tool_runs=[
                ChatToolRun(
                    tool="urun_karsilastir",
                    inputs=slots.as_input_dict(),
                    summary="Karşılaştırma başarısız",
                    note=str(exc),
                    elapsed_ms=int((time.perf_counter() - baslangic) * 1000),
                )
            ],
        )
    ms = int((time.perf_counter() - baslangic) * 1000)
    metin = ranking.winner_reason or ranking.note or "Karşılaştırma tamamlandı."
    return ToolResult(
        answer_text=metin,
        comparison=ranking,
        actions=[
            ChatAction(
                kind="navigate",
                label="Karşılaştırma sayfasını aç",
                path="/compare",
                params={"rate_type": rt},
            )
        ],
        tool_runs=[
            ChatToolRun(
                tool="urun_karsilastir",
                inputs={**slots.as_input_dict(), "rate_type": rt, "criterion": criterion},
                summary=f"{rt} · {criterion} · {len(ranking.ranked)} ürün",
                elapsed_ms=ms,
            )
        ],
    )


__all__ = [
    "TOOL_NAMES",
    "ToolResult",
    "detect_tool",
    "run_tool",
]
