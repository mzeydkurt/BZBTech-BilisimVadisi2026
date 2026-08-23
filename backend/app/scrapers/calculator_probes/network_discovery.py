"""Hesaplayıcı sayfalarında XHR/fetch network keşfi.

Öncelik (prompt §5–§7, §59):
  1) Resmi / açık JSON endpoint
  2) Sayfanın kullandığı XHR/fetch
  3) Playwright form doldurma + DOM (fallback)

CAPTCHA / auth bypass YOK. Rate limit: sayfa başına kontrollü etkileşim.
Ham kayıtlar `backend/data/debug/network/<bank>/<tarih>/` altına yazılır.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final
from urllib.parse import parse_qs, urlparse

from app.logging_config import get_logger
from app.scrapers.browser import NETWORK_IDLE_MS, browser_page, is_playwright_available
from app.scrapers.calculator_probes.common import cerez_kapat
from app.scrapers.calculator_probes.config_loader import CalculatorPage, pages_for_bank

logger = get_logger(__name__)

REPO_BACKEND = Path(__file__).resolve().parents[3]
DEBUG_ROOT = REPO_BACKEND / "data" / "debug" / "network"

# URL / gövde anahtar kelimeleri (prompt §6)
_FINANCE_URL_HINTS: Final[tuple[str, ...]] = (
    "calculate",
    "calculation",
    "calculator",
    "finance",
    "financing",
    "finansman",
    "kredi",
    "credit",
    "loan",
    "payment",
    "installment",
    "taksit",
    "hesaplama",
    "hesapla",
    "repayment",
    "maturity",
    "term",
    "profit",
    "odeme",
    "karoran",
    "kar-oran",
)

_AMOUNT_KEYS: Final[tuple[str, ...]] = (
    "amount",
    "tutar",
    "financeamount",
    "loanamount",
    "requiredamount",
    "principal",
    "anapara",
)
_TERM_KEYS: Final[tuple[str, ...]] = (
    "term",
    "maturity",
    "vade",
    "month",
    "ay",
    "installmentcount",
    "taksitsayisi",
)
_RATE_KEYS: Final[tuple[str, ...]] = (
    "profitrate",
    "profit_rate",
    "karorani",
    "kar_orani",
    "monthlyrate",
    "rate",
    "oran",
)
_INSTALLMENT_KEYS: Final[tuple[str, ...]] = (
    "monthlypayment",
    "installment",
    "taksit",
    "aylik",
    "monthlyinstallment",
)


@dataclass
class NetworkHit:
    """Tek bir yakalanmış istek/yanıt çifti."""

    bank: str
    page_url: str
    timestamp: str
    method: str
    url: str
    headers: dict[str, str]
    query_params: dict[str, Any]
    body: Any
    resource_type: str
    status: int | None
    content_type: str
    response: Any
    score: int = 0
    score_reasons: list[str] = field(default_factory=list)


@dataclass
class DiscoveryReport:
    """Bir sayfa için keşif özeti."""

    bank: str
    bank_name: str
    label: str
    page_url: str
    strategy: str
    hits: list[NetworkHit] = field(default_factory=list)
    candidates: list[dict[str, Any]] = field(default_factory=list)
    form_hints: dict[str, Any] = field(default_factory=dict)
    playwright_required: bool | None = None
    httpx_viable: bool | None = None
    auth_required: bool | None = None
    error: str | None = None
    debug_dir: str | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _safe_json(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return None


def _flatten_keys(obj: Any, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            yol = f"{prefix}.{k}" if prefix else str(k)
            keys.add(str(k).lower())
            keys.add(yol.lower())
            keys |= _flatten_keys(v, yol)
    elif isinstance(obj, list) and obj:
        keys |= _flatten_keys(obj[0], prefix)
    return keys


def _body_has_any(body: Any, anahtarlar: tuple[str, ...]) -> bool:
    if body is None:
        return False
    if isinstance(body, (dict, list)):
        flat = _flatten_keys(body)
        return any(a in flat or any(a in k for k in flat) for a in anahtarlar)
    metin = str(body).lower()
    return any(a in metin for a in anahtarlar)


def score_hit(hit: NetworkHit) -> tuple[int, list[str]]:
    """Prompt §24 skor sistemi."""
    puan = 0
    nedenler: list[str] = []
    url_l = hit.url.lower()
    ct = (hit.content_type or "").lower()

    # Analytics / telemetry asla hesaplama endpoint'i değildir
    if any(
        x in url_l
        for x in (
            "google-analytics",
            "analytics.google",
            "googletagmanager",
            "dataroid",
            "hotjar",
            "facebook.com",
            "doubleclick",
        )
    ):
        return 0, ["analytics/telemetry — elendi"]

    if "json" in ct:
        puan += 30
        nedenler.append("+30 JSON content-type")
    if hit.method.upper() == "POST":
        puan += 20
        nedenler.append("+20 POST")
    if any(h in url_l for h in _FINANCE_URL_HINTS):
        puan += 20
        nedenler.append("+20 finance URL hint")
    if _body_has_any(hit.response, _INSTALLMENT_KEYS):
        puan += 15
        nedenler.append("+15 installment in response")
    if _body_has_any(hit.response, _RATE_KEYS):
        puan += 15
        nedenler.append("+15 rate in response")
    # Güçlü sinyal: ödeme planı / Meta.ProfitRate tarzı banka cevabı
    if isinstance(hit.response, dict):
        meta = hit.response.get("Meta") or hit.response.get("meta")
        if isinstance(meta, dict) and (
            "ProfitRate" in meta or "profitRate" in meta or "InstallmentPayment" in meta
        ):
            puan += 25
            nedenler.append("+25 Meta.ProfitRate/InstallmentPayment")
        if "Installments" in hit.response or "installments" in hit.response:
            puan += 10
            nedenler.append("+10 Installments array")
    if _body_has_any(hit.body, _AMOUNT_KEYS) or _body_has_any(hit.query_params, _AMOUNT_KEYS):
        puan += 10
        nedenler.append("+10 amount in request")
    # Kuveyt tarzı p2/p3 gövdesi
    if isinstance(hit.body, dict):
        keys = {str(k).lower() for k in hit.body}
        if "p2" in keys and "p3" in keys:
            puan += 15
            nedenler.append("+15 obfuscated p2/p3 amount/term")
    if _body_has_any(hit.body, _TERM_KEYS) or _body_has_any(hit.query_params, _TERM_KEYS):
        puan += 10
        nedenler.append("+10 term in request")
    if hit.status and 200 <= hit.status < 300:
        puan += 5
        nedenler.append("+5 HTTP 2xx")
    return puan, nedenler


def _parse_post_data(raw: str | None) -> Any:
    if not raw:
        return None
    j = _safe_json(raw)
    if j is not None:
        return j
    try:
        return {k: v if len(v) > 1 else v[0] for k, v in parse_qs(raw).items()}
    except Exception:
        return raw[:4000]


def _form_hints(page: Any) -> dict[str, Any]:
    return page.evaluate(
        """() => {
        const pick = (el) => ({
          tag: el.tagName.toLowerCase(),
          type: el.getAttribute('type') || null,
          name: el.getAttribute('name') || null,
          id: el.id || null,
          placeholder: el.getAttribute('placeholder') || null,
          ariaLabel: el.getAttribute('aria-label') || null,
          label: (() => {
            const id = el.id;
            if (!id) return null;
            const lab = document.querySelector(`label[for="${CSS.escape(id)}"]`);
            return lab ? lab.textContent.trim().slice(0, 120) : null;
          })(),
        });
        const nodes = [...document.querySelectorAll('input, select, textarea')];
        return {
          fields: nodes.slice(0, 80).map(pick),
          buttons: [...document.querySelectorAll('button, input[type=submit], a')]
            .map(b => (b.textContent || b.value || '').trim())
            .filter(t => /hesapla|calculate|sorgula|plan/i.test(t))
            .slice(0, 20),
        };
      }"""
    )


def _try_trigger_calculate(page: Any) -> None:
    """Formu nazikçe doldurup hesapla tetikle (CAPTCHA yok varsayımı).

    Ana sayfa widget'ları için önce 'Kredi Hesapla' / 'Finansman Hesapla' sekmesi açılır.
    """
    for sel in (
        'button:has-text("Kredi Hesapla")',
        'button:has-text("Finansman Hesapla")',
        'button:has-text("Finansman Hesaplama")',
        'a:has-text("Kredi Hesapla")',
        'a:has-text("Finansman Hesapla")',
        '[role="tab"]:has-text("Kredi")',
        '[role="tab"]:has-text("Finansman")',
        'button:has-text("Hesaplama")',
    ):
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible():
                loc.click(timeout=3000)
                page.wait_for_timeout(1500)
                break
        except Exception:
            continue

    # Yaygın tutar / vade alanları
    for sel, val in (
        ('input[type="number"]', "500000"),
        ('input[name*="amount" i]', "500000"),
        ('input[id*="amount" i]', "500000"),
        ('input[id*="Amount" i]', "500000"),
        ('input[id*="tutar" i]', "500000"),
        ("#requiredAmount", "500000"),
        ("#edit-finansman-tutari", "500000"),
        ('input[name*="term" i]', "36"),
        ('input[id*="vade" i]', "36"),
        ('input[id*="maturity" i]', "36"),
        ("#maturity-period-input", "36"),
    ):
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible():
                loc.fill(val)
                loc.dispatch_event("input")
                loc.dispatch_event("change")
        except Exception:
            continue

    for sel in (
        'button:has-text("Hesapla")',
        'button:has-text("HESAPLA")',
        'a:has-text("Hesapla")',
        'input[type="submit"]',
        'button:has-text("Ödeme Planı")',
        'button:has-text("Kredi Hesapla")',
        'button:has-text("Finansman Hesapla")',
    ):
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible():
                loc.click(timeout=3000)
                page.wait_for_timeout(2000)
                return
        except Exception:
            continue


def discover_page(page_cfg: CalculatorPage, *, max_body_chars: int = 50_000) -> DiscoveryReport:
    """Tek sayfada network keşfi çalıştırır."""
    rapor = DiscoveryReport(
        bank=page_cfg.bank_code,
        bank_name=page_cfg.bank_name,
        label=page_cfg.label,
        page_url=page_cfg.url,
        strategy=page_cfg.strategy,
    )
    if not is_playwright_available():
        rapor.error = "Playwright kurulu değil"
        return rapor

    gun = datetime.now().strftime("%Y-%m-%d")
    out_dir = DEBUG_ROOT / page_cfg.bank_code / gun
    out_dir.mkdir(parents=True, exist_ok=True)
    rapor.debug_dir = str(out_dir)

    hits: list[NetworkHit] = []
    pending: dict[str, dict[str, Any]] = {}

    def on_request(request: Any) -> None:
        try:
            rtype = request.resource_type
            if rtype not in ("xhr", "fetch"):
                return
            pending[request.url + "|" + request.method] = {
                "method": request.method,
                "url": request.url,
                "headers": dict(request.headers),
                "post_data": request.post_data,
                "resource_type": rtype,
            }
        except Exception:
            return

    def on_response(response: Any) -> None:
        try:
            request = response.request
            rtype = request.resource_type
            if rtype not in ("xhr", "fetch"):
                return
            ct = response.headers.get("content-type", "")
            url_l = response.url.lower()
            finance_hint = any(h in url_l for h in _FINANCE_URL_HINTS)
            if "json" not in ct.lower() and not finance_hint:
                return

            body_text = ""
            try:
                body_text = response.text()[:max_body_chars]
            except Exception:
                body_text = ""

            parsed = urlparse(response.url)
            q = {k: v if len(v) > 1 else v[0] for k, v in parse_qs(parsed.query).items()}
            req_meta = pending.get(response.url + "|" + request.method, {})
            post_raw = req_meta.get("post_data") or request.post_data
            hit = NetworkHit(
                bank=page_cfg.bank_code,
                page_url=page_cfg.url,
                timestamp=_now_iso(),
                method=request.method,
                url=response.url,
                headers={
                    k: v
                    for k, v in dict(request.headers).items()
                    if k.lower() not in ("cookie", "authorization")
                },
                query_params=q,
                body=_parse_post_data(post_raw),
                resource_type=rtype,
                status=response.status,
                content_type=ct,
                response=_safe_json(body_text) if body_text else body_text[:2000],
            )
            puan, neden = score_hit(hit)
            hit.score = puan
            hit.score_reasons = neden
            # Düşük skorlu gürültüyü ele (analytics vs.)
            if puan >= 25 or finance_hint:
                hits.append(hit)
        except Exception as exc:
            logger.debug("network_response_skip", hata=str(exc))

    try:
        with browser_page() as page:
            page.on("request", on_request)
            page.on("response", on_response)
            logger.info(
                "calculator_discovery_start",
                bank=page_cfg.bank_code,
                url=page_cfg.url,
            )
            page.goto(page_cfg.url, wait_until="domcontentloaded", timeout=90_000)
            page.wait_for_timeout(NETWORK_IDLE_MS)
            cerez_kapat(page)
            try:
                rapor.form_hints = _form_hints(page)
            except Exception:
                rapor.form_hints = {}
            _try_trigger_calculate(page)
            page.wait_for_timeout(2500)
            time.sleep(2.0)
    except Exception as exc:
        rapor.error = f"{type(exc).__name__}: {exc}"
        logger.warning("calculator_discovery_fail", bank=page_cfg.bank_code, hata=rapor.error)

    hits.sort(key=lambda h: -h.score)
    rapor.hits = hits
    rapor.candidates = [
        {
            "url": h.url,
            "method": h.method,
            "score": h.score,
            "score_reasons": h.score_reasons,
            "status": h.status,
            "content_type": h.content_type,
            "confirmed": False,
            "parameters": {
                "amount_keys": [
                    k
                    for k in _flatten_keys(h.body or {}) | set(h.query_params)
                    if any(a in k.lower() for a in _AMOUNT_KEYS)
                ],
                "term_keys": [
                    k
                    for k in _flatten_keys(h.body or {}) | set(h.query_params)
                    if any(a in k.lower() for a in _TERM_KEYS)
                ],
            },
        }
        for h in hits[:15]
    ]

    top = hits[0] if hits else None
    if top and top.score >= 50:
        rapor.playwright_required = False
        rapor.httpx_viable = True
        # Cookie/CSRF header var mı?
        hdr = {k.lower() for k in top.headers}
        rapor.auth_required = bool(hdr & {"x-csrf-token", "authorization"})
    elif hits:
        rapor.playwright_required = True
        rapor.httpx_viable = False
        rapor.auth_required = None
    else:
        rapor.playwright_required = True
        rapor.httpx_viable = False

    # Ham JSON kaydı
    safe_label = re.sub(r"[^\w\-]+", "_", page_cfg.label)[:60]
    out_path = out_dir / f"{safe_label}.json"
    out_path.write_text(
        json.dumps(
            {
                "bank": rapor.bank,
                "bank_name": rapor.bank_name,
                "label": rapor.label,
                "page_url": rapor.page_url,
                "strategy": rapor.strategy,
                "error": rapor.error,
                "playwright_required": rapor.playwright_required,
                "httpx_viable": rapor.httpx_viable,
                "auth_required": rapor.auth_required,
                "form_hints": rapor.form_hints,
                "candidates": rapor.candidates,
                "hits": [asdict(h) for h in hits],
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    return rapor


def run_discovery(
    *,
    bank_code: str | None = None,
    url_filter: str | None = None,
    surface: str | None = None,
) -> list[DiscoveryReport]:
    """Config'teki hedefler için keşif çalıştırır."""
    pages = pages_for_bank(bank_code, surface=surface)
    if url_filter:
        pages = tuple(p for p in pages if url_filter.lower() in p.url.lower())
    raporlar: list[DiscoveryReport] = []
    for i, page_cfg in enumerate(pages):
        if i:
            time.sleep(2.0)  # bankalar arası nazik bekleme
        raporlar.append(discover_page(page_cfg))
    return raporlar


def technical_summary(raporlar: list[DiscoveryReport]) -> list[dict[str, Any]]:
    """Prompt §57 deliverable formatı."""
    ozet: list[dict[str, Any]] = []
    for r in raporlar:
        top = r.hits[0] if r.hits else None
        ozet.append(
            {
                "BANKA": r.bank_name,
                "bank_code": r.bank,
                "HESAPLAMA_URL": r.page_url,
                "LABEL": r.label,
                "NETWORK_ENDPOINT": top.url if top else None,
                "METHOD": top.method if top else None,
                "REQUEST_PAYLOAD": top.body if top else None,
                "PARAMETRELER": r.candidates[0]["parameters"] if r.candidates else {},
                "RESPONSE_ORNEGI": (top.response if top else None),
                "RESPONSE_FIELD_MAPPING": {
                    "score": top.score if top else 0,
                    "reasons": top.score_reasons if top else [],
                },
                "AUTH_GEREKLI_MI": r.auth_required,
                "PLAYWRIGHT_GEREKLI_MI": r.playwright_required,
                "DOGRUDAN_HTTPX_ILE_CALISIYOR_MU": r.httpx_viable,
                "HATA": r.error,
                "DEBUG_DIR": r.debug_dir,
                "CANDIDATE_COUNT": len(r.candidates),
            }
        )
    return ozet
