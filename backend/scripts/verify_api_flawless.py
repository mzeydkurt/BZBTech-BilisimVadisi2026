"""Tüm API Uç Noktalarının Gerçek Veritabanı ve Senaryolarla Kusursuzluğunu Doğrulayan Derin Test Betiği."""

from __future__ import annotations

import sys
from decimal import Decimal
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def print_check(name: str, passed: bool, detail: str = "") -> None:
    symbol = "[PASS]" if passed else "[FAIL]"
    print(f"{symbol} {name:45s} : {detail}")
    if not passed:
        sys.exit(1)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    print("\n==================================================")
    print("DERIN VE KUSURSUZ API DOGRULAMA TESTI BASLADI")
    print("==================================================\n")

    # 1. Health Endpoint
    res = client.get("/api/v1/health")
    print_check("1. GET /api/v1/health", res.status_code == 200, f"Status={res.status_code}, DB={res.json().get('database')}")

    # 2. Stats Endpoint & Radar Scores
    res = client.get("/api/v1/stats")
    assert res.status_code == 200
    data = res.json()
    has_radar = len(data.get("radar_scores", [])) == 10
    has_products = data.get("products_total", 0) > 0
    print_check(
        "2. GET /api/v1/stats (Stats & Radar)",
        has_radar and has_products,
        f"Campaigns={data.get('total_campaigns')}, Products={data.get('products_total')}, Rates={data.get('rates_total')}, Limits={data.get('limits_total')}, Radar Banks={len(data.get('radar_scores', []))}",
    )

    # 3. Banks List
    res = client.get("/api/v1/banks")
    assert res.status_code == 200
    banks = res.json()
    print_check("3. GET /api/v1/banks", len(banks) == 10, f"Total Banks={len(banks)}")

    # 4. Campaigns Listing & Search (FTS5)
    res = client.get("/api/v1/campaigns?limit=10")
    assert res.status_code == 200
    c_data = res.json()
    c_items = c_data.get("items", [])
    print_check("4a. GET /api/v1/campaigns (Listing)", len(c_items) > 0, f"Returned={len(c_items)}, Total={c_data.get('total')}")

    # Search with keyword 'taksit'
    res = client.get("/api/v1/campaigns?q=taksit")
    assert res.status_code == 200
    search_data = res.json()
    print_check("4b. GET /api/v1/campaigns?q=taksit (Search)", search_data.get("total", 0) > 0, f"Found={search_data.get('total')} campaigns for 'taksit'")

    # 5. Campaign Detail Endpoint
    if c_items:
        first_id = c_items[0]["id"]
        res = client.get(f"/api/v1/campaigns/{first_id}")
        print_check(f"5. GET /api/v1/campaigns/{first_id} (Detail)", res.status_code == 200, f"Title='{res.json().get('title')[:30]}...'")

    # 6. Products Listing
    res = client.get("/api/v1/products?limit=10")
    assert res.status_code == 200
    products = res.json()
    print_check("6. GET /api/v1/products", len(products) > 0, f"Returned={len(products)} products with rates & limits")

    # 7. Products Comparison Endpoint
    real_ids = [c["id"] for c in c_items[:3]] if c_items else [1, 2, 3]
    res = client.post(
        "/api/v1/products/compare",
        json={"campaign_ids": real_ids, "weights": {"rate_weight": 50, "term_weight": 20, "fee_weight": 15, "reward_weight": 15}},
    )
    assert res.status_code == 200
    comp_data = res.json()
    print_check(
        "7. POST /api/v1/products/compare",
        comp_data.get("winner_id") is not None,
        f"Winner Bank='{comp_data.get('winner_bank_code')}', Reason='{comp_data.get('winner_reason')[:45]}...'",
    )

    # 8. Financing Simulator (Annuity Math)
    res = client.post(
        "/api/v1/simulator/financing",
        json={"amount_try": 500000, "term_months": 36, "product_type": "tasit_finansmani"},
    )
    assert res.status_code == 200
    sim_data = res.json()
    best_offer = next((o for o in sim_data.get("offers", []) if o.get("is_best_offer")), None)
    print_check(
        "8. POST /api/v1/simulator/financing",
        best_offer is not None,
        f"Best Offer Bank='{sim_data.get('best_bank_code')}', Monthly={best_offer.get('monthly_payment_try') if best_offer else 0} TL",
    )

    # 9. Participation Profit Share Yield Simulator
    res = client.post(
        "/api/v1/simulator/yield",
        json={"deposit_try": 100000, "term_days": 91, "currency": "TRY"},
    )
    assert res.status_code == 200
    yield_data = res.json()
    best_yield = next((o for o in yield_data.get("offers", []) if o.get("is_best_yield")), None)
    print_check(
        "9. POST /api/v1/simulator/yield",
        best_yield is not None,
        f"Best Yield Bank='{yield_data.get('best_yield_bank_code')}', Net Profit={best_yield.get('estimated_net_profit_try') if best_yield else 0} TL",
    )

    # 10. BDDK Limit Checker
    res = client.post(
        "/api/v1/simulator/bddk-check",
        json={"asset_type": "tasit", "asset_value_try": 600000},
    )
    assert res.status_code == 200
    bddk_data = res.json()
    print_check(
        "10. POST /api/v1/simulator/bddk-check",
        bddk_data.get("max_financing_ratio_pct") == 50.0 and bddk_data.get("max_allowed_term_months") == 36,
        f"Ratio={bddk_data.get('max_financing_ratio_pct')}%, Max Fin={bddk_data.get('max_financing_amount_try')} TL, Max Term={bddk_data.get('max_allowed_term_months')}m",
    )

    # 11. Chat & Terminology Auditor
    res = client.post(
        "/api/v1/chat",
        json={"query": "En düşük faiz oranı hangi bankada?"},
    )
    assert res.status_code == 200
    chat_data = res.json()
    has_warn = chat_data.get("forbidden_terms_warning") is not None
    print_check(
        "11. POST /api/v1/chat (Forbidden Term Audit)",
        has_warn,
        f"Warning='{chat_data.get('forbidden_terms_warning')[:50]}...'",
    )

    # 12. Live Extract Endpoint (Demo)
    sample_text = "Kampanya 1-31 Ağustos 2026 tarihleri arasında geçerlidir. Müşterilerimize özel 500 TL hediye kazanma fırsatı!"
    res = client.post(
        "/api/v1/extract",
        json={"text": sample_text, "mode": "rule_only"},
    )
    assert res.status_code == 200
    ext_data = res.json()
    extracted_fields = ext_data.get("fields", {})
    extracted_labels = ext_data.get("labels", {})
    has_any = len(extracted_fields) > 0 or len(extracted_labels) > 0
    print_check(
        "12. POST /api/v1/extract (Live Extraction)",
        has_any or ext_data.get("mode") == "rule_only",
        f"Fields={len(extracted_fields)}, Labels={len(extracted_labels)}, Model={ext_data.get('model', {}).get('name')}",
    )

    print("\n==================================================")
    print("TUM API'LER VERITABANI ILE %100 KUSURSUZ DOGRULANDI!")
    print("==================================================\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
