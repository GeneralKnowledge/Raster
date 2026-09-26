"""Vectorize endpoint tests (non-brittle)."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app
from app.services.image import sanitize_filename, svg_output_filename


def _has_vector_content(svg: str) -> bool:
    lower = svg.lower()
    assert "<svg" in lower
    return bool(
        re.search(r"<(path|polygon|polyline|circle|rect|g)\b", lower)
    )


def test_png_to_svg(client: TestClient, tiny_png: bytes) -> None:
    r = client.post(
        "/v1/vectorize",
        files={"file": ("tiny.png", tiny_png, "image/png")},
        data={"preset": "logo"},
    )
    assert r.status_code == 200
    assert "image/svg+xml" in r.headers["content-type"]
    assert _has_vector_content(r.text)
    assert r.headers["X-Preset"] == "logo"
    assert "X-Processing-Ms" in r.headers
    assert "Content-Disposition" in r.headers


def test_legacy_alias(client: TestClient, tiny_png: bytes) -> None:
    r = client.post(
        "/vectorize",
        files={"file": ("tiny.png", tiny_png, "image/png")},
    )
    assert r.status_code == 200
    assert _has_vector_content(r.text)


def test_jpeg_works(client: TestClient, shape_jpg: bytes) -> None:
    r = client.post(
        "/v1/vectorize",
        files={"file": ("shape.jpg", shape_jpg, "image/jpeg")},
        data={"preset": "illustration", "detail": "medium"},
    )
    assert r.status_code == 200
    assert _has_vector_content(r.text)
    assert r.headers["X-Input-Format"] == "jpeg"


def test_transparent_png(client: TestClient, transparent_png: bytes) -> None:
    # Soft alpha is not always preserved perfectly by VTracer; just require valid SVG.
    r = client.post(
        "/v1/vectorize",
        files={"file": ("transparent.png", transparent_png, "image/png")},
        data={"preset": "logo", "flatten_transparency": "false"},
    )
    assert r.status_code == 200
    assert _has_vector_content(r.text)


def test_random_bytes_error(client: TestClient) -> None:
    r = client.post(
        "/v1/vectorize",
        files={"file": ("bad.bin", b"not-an-image-at-all", "application/octet-stream")},
    )
    assert r.status_code == 400
    body = r.json()
    assert body["error"] == "invalid_image"
    assert "request_id" in body


def test_oversized_upload(monkeypatch: pytest.MonkeyPatch, tiny_png: bytes) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("MAX_FILE_SIZE_MB", "0.000001")  # ~1 byte
    monkeypatch.setenv("API_KEY_REQUIRED", "false")
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as client:
        r = client.post(
            "/v1/vectorize",
            files={"file": ("tiny.png", tiny_png, "image/png")},
        )
        assert r.status_code == 413
        assert r.json()["error"] == "file_too_large"
    get_settings.cache_clear()


def test_default_compression_applies_scour(
    client: TestClient, tiny_png: bytes
) -> None:
    """Default level 2 should Scour-minify (not only native optimize)."""
    off = client.post(
        "/v1/vectorize",
        files={"file": ("tiny.png", tiny_png, "image/png")},
        data={"compression_level": "0", "response_format": "json"},
    )
    default = client.post(
        "/v1/vectorize",
        files={"file": ("tiny.png", tiny_png, "image/png")},
        data={"response_format": "json"},  # compression_level defaults to 2
    )
    assert off.status_code == 200 and default.status_code == 200
    off_svg = off.json()["svg"]
    def_svg = default.json()["svg"]
    assert len(def_svg) < len(off_svg)
    assert default.json()["settings"]["compression_level"] == 2
    assert default.json()["output"]["optimized"] is True


@pytest.mark.parametrize("level", [0, 2, 3])
def test_compression_levels(
    client: TestClient, tiny_png: bytes, level: int
) -> None:
    r = client.post(
        "/v1/vectorize",
        files={"file": ("tiny.png", tiny_png, "image/png")},
        data={"compression_level": str(level)},
    )
    assert r.status_code == 200
    assert _has_vector_content(r.text)
    assert r.headers["X-Compression-Level"] == str(level)


@pytest.mark.parametrize("level", [0, 3])
def test_smooth_levels(client: TestClient, tiny_png: bytes, level: int) -> None:
    r = client.post(
        "/v1/vectorize",
        files={"file": ("tiny.png", tiny_png, "image/png")},
        data={"smooth_level": str(level)},
    )
    assert r.status_code == 200
    assert _has_vector_content(r.text)
    assert r.headers["X-Smooth-Level"] == str(level)


def test_json_response(client: TestClient, tiny_png: bytes) -> None:
    r = client.post(
        "/v1/vectorize",
        files={"file": ("tiny.png", tiny_png, "image/png")},
        data={"response_format": "json"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    assert data["svg"].lower().find("<svg") >= 0
    assert "meta" in data and "request_id" in data["meta"]
    assert "processing_ms" in data["meta"]
    assert data["settings"]["preset"] == "logo"


def test_smooth_compress_aliases(client: TestClient, tiny_png: bytes) -> None:
    r = client.post(
        "/v1/vectorize",
        files={"file": ("tiny.png", tiny_png, "image/png")},
        data={"smooth": "false", "compress": "false"},
    )
    assert r.status_code == 200
    assert r.headers["X-Smooth-Level"] == "0"
    assert r.headers["X-Compression-Level"] == "0"


def test_api_key_required(monkeypatch: pytest.MonkeyPatch, tiny_png: bytes) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("API_KEY_REQUIRED", "true")
    monkeypatch.setenv("API_KEY", "secret-test-key")
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as client:
        r = client.post(
            "/v1/vectorize",
            files={"file": ("tiny.png", tiny_png, "image/png")},
        )
        assert r.status_code == 401
        assert r.json()["error"] == "unauthorized"

        r2 = client.post(
            "/v1/vectorize",
            files={"file": ("tiny.png", tiny_png, "image/png")},
            headers={"X-API-Key": "secret-test-key"},
        )
        assert r2.status_code == 200

        r3 = client.post(
            "/v1/vectorize",
            files={"file": ("tiny.png", tiny_png, "image/png")},
            headers={"Authorization": "Bearer secret-test-key"},
        )
        assert r3.status_code == 200

        # Health also requires key when enabled
        assert client.get("/health").status_code == 401
        assert (
            client.get("/health", headers={"X-API-Key": "secret-test-key"}).status_code
            == 200
        )
    get_settings.cache_clear()


def test_filename_sanitization() -> None:
    assert ".." not in sanitize_filename("../../etc/passwd.png")
    assert "/" not in sanitize_filename("a/b/c.png")
    assert svg_output_filename("../../evil.png") == "evil.svg"
    assert svg_output_filename(None) == "image.svg"


def test_photo_preset(client: TestClient, fixtures_dir) -> None:
    data = (fixtures_dir / "photo_sample.png").read_bytes()
    r = client.post(
        "/v1/vectorize",
        files={"file": ("photo_sample.png", data, "image/png")},
        data={
            "preset": "photo",
            "detail": "low",
            "max_colors": "16",
            "response_format": "json",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert _has_vector_content(body["svg"])
    assert body["settings"]["preset"] == "photo"
    assert body["settings"]["max_colors"] == 16
    # Photo auto-enables Pillow enhance unless overridden
    assert body["settings"]["pillow_enhance"] is True
    assert r.headers.get("X-Max-Colors") == "16"
    assert r.headers.get("X-Pillow-Enhance") == "true"


def test_photo_pillow_enhance_can_be_disabled(
    client: TestClient, fixtures_dir
) -> None:
    data = (fixtures_dir / "photo_sample.png").read_bytes()
    r = client.post(
        "/v1/vectorize",
        files={"file": ("photo_sample.png", data, "image/png")},
        data={
            "preset": "photo",
            "detail": "low",
            "pillow_enhance": "false",
            "response_format": "json",
        },
    )
    assert r.status_code == 200
    assert r.json()["settings"]["pillow_enhance"] is False
    assert r.headers.get("X-Pillow-Enhance") == "false"


def test_pillow_enhance_toggle(client: TestClient, tiny_png: bytes) -> None:
    off = client.post(
        "/v1/vectorize",
        files={"file": ("tiny.png", tiny_png, "image/png")},
        data={"response_format": "json", "pillow_enhance": "false"},
    )
    on = client.post(
        "/v1/vectorize",
        files={"file": ("tiny.png", tiny_png, "image/png")},
        data={
            "preset": "logo",
            "response_format": "json",
            "pillow_enhance": "true",
            "smooth_level": "5",
        },
    )
    assert off.status_code == 200
    assert on.status_code == 200
    assert off.json()["settings"]["pillow_enhance"] is False
    assert on.json()["settings"]["pillow_enhance"] is True
    assert on.headers["X-Pillow-Enhance"] == "true"
    assert _has_vector_content(on.json()["svg"])


def test_invalid_preset(client: TestClient, tiny_png: bytes) -> None:
    r = client.post(
        "/v1/vectorize",
        files={"file": ("tiny.png", tiny_png, "image/png")},
        data={"preset": "not-a-preset"},
    )
    assert r.status_code == 422
    assert r.json()["error"] == "invalid_parameter"
