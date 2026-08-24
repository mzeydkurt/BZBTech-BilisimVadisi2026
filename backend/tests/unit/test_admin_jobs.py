"""Admin job whitelist birim testleri."""

from __future__ import annotations

import pytest

from app.services import admin_jobs


@pytest.fixture(autouse=True)
def _temiz_kuyruk() -> None:
    admin_jobs._reset_for_tests()


def test_build_command_kampanya_banka_zorunlu() -> None:
    with pytest.raises(ValueError, match="banka"):
        admin_jobs.build_command("campaign", None)


def test_build_command_kampanya() -> None:
    komut = admin_jobs.build_command("campaign", "dunya_katilim")
    assert "-m" in komut
    assert "app.scrapers.run" in komut
    assert "--banka" in komut
    assert "dunya_katilim" in komut


def test_bank_pipeline_uc_adim() -> None:
    adimlar = admin_jobs.build_command_steps("bank_pipeline", "albaraka")
    assert len(adimlar) == 3
    assert "app.scrapers.run" in adimlar[0]
    assert "scrape_js_campaigns" in adimlar[1][2]
    assert "scrape_products" in adimlar[2][2]


def test_build_command_tkbb_banksiz() -> None:
    komut = admin_jobs.build_command("tkbb", None)
    assert "scripts.scrape_tkbb" in komut


def test_build_command_llm_health() -> None:
    komut = admin_jobs.build_command("llm_health", None)
    assert "scripts.llm_health" in komut


def test_admin_jobs_api_create_and_get(api_client) -> None:
    yanit = api_client.post("/api/v1/admin/jobs", json={"kind": "campaign"})
    assert yanit.status_code == 422

    yanit = api_client.post(
        "/api/v1/admin/jobs",
        json={"kind": "llm_health"},
    )
    assert yanit.status_code == 201
    veri = yanit.json()
    assert veri["kind"] == "llm_health"
    assert veri["status"] in {"queued", "running", "succeeded", "failed"}
    assert "summary" in veri

    get_yanit = api_client.get(f"/api/v1/admin/jobs/{veri['id']}")
    assert get_yanit.status_code == 200
    assert get_yanit.json()["id"] == veri["id"]


def test_admin_health(api_client) -> None:
    yanit = api_client.get("/api/v1/admin/health")
    assert yanit.status_code == 200
    assert "db_ok" in yanit.json()
