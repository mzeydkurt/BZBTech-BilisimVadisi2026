"""Ürün ve oran API uçları testleri (SPRINT 2.5 KAPI F5)."""

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_products_endpoint_returns_200() -> None:
    response = client.get("/api/v1/products")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_products_endpoint_rate_type_filter() -> None:
    response = client.get("/api/v1/products?rate_type=financing_rate")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
