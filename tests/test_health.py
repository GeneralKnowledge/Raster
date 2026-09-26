"""Health and version endpoint tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["service"] == "raster-to-svg"
    assert "X-Request-Id" in r.headers


def test_version(client: TestClient) -> None:
    r = client.get("/version")
    assert r.status_code == 200
    data = r.json()
    assert data["api_version"] == "0.1.0"
    assert data["vtracer_version"].startswith("1.")
