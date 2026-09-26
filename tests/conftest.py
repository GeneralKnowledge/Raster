"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    get_settings.cache_clear()
    monkeypatch.setenv("API_KEY_REQUIRED", "false")
    monkeypatch.setenv("MAX_CONCURRENT_JOBS", "4")
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


@pytest.fixture
def tiny_png(fixtures_dir: Path) -> bytes:
    return (fixtures_dir / "tiny.png").read_bytes()


@pytest.fixture
def logo_png(fixtures_dir: Path) -> bytes:
    return (fixtures_dir / "logo.png").read_bytes()


@pytest.fixture
def shape_jpg(fixtures_dir: Path) -> bytes:
    return (fixtures_dir / "shape.jpg").read_bytes()


@pytest.fixture
def transparent_png(fixtures_dir: Path) -> bytes:
    return (fixtures_dir / "transparent.png").read_bytes()
