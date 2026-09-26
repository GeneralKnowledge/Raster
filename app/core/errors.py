"""Typed application errors with stable client-facing codes."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base error raised by the raster-to-svg service."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


def invalid_image(message: str) -> AppError:
    return AppError("invalid_image", message, 400)


def unsupported_format(message: str) -> AppError:
    return AppError("unsupported_format", message, 415)


def file_too_large(message: str) -> AppError:
    return AppError("file_too_large", message, 413)


def image_too_large(message: str) -> AppError:
    return AppError("image_too_large", message, 413)


def invalid_parameter(message: str) -> AppError:
    return AppError("invalid_parameter", message, 422)


def unauthorized(message: str = "Invalid or missing API key") -> AppError:
    return AppError("unauthorized", message, 401)


def vectorization_failed(message: str) -> AppError:
    return AppError("vectorization_failed", message, 500)


def busy(message: str = "Server is busy; try again shortly") -> AppError:
    return AppError("busy", message, 503)
