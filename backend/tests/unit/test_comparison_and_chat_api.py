"""Karşılaştırma ve Chatbot API uç noktaları testleri."""

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_products_compare_post_api() -> None:
    response = client.post(
        "/api/v1/products/compare",
        json={"campaign_ids": [1, 2], "weights": {"rate_weight": 40, "term_weight": 20}},
    )
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "weights" in data


def test_chat_query_forbidden_terms_warning() -> None:
    response = client.post(
        "/api/v1/chat",
        json={"query": "En düşük faiz oranı hangi katılım bankasında var?"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["forbidden_terms_warning"] is not None
    assert "kâr payı" in data["forbidden_terms_warning"]


def test_stats_api_with_radar_scores() -> None:
    response = client.get("/api/v1/stats")
    assert response.status_code == 200
    data = response.json()
    assert "radar_scores" in data
    assert "sector_distribution" in data
    assert "products_total" in data
