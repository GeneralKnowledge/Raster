"""Stdlib logging with request-id context."""

from __future__ import annotations

import logging
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    """Inject the current request id into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get("-")  # type: ignore[attr-defined]
        return True


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"
            )
        )
        handler.addFilter(RequestIdFilter())
        root.addHandler(handler)
    else:
        for handler in root.handlers:
            handler.addFilter(RequestIdFilter())
    root.setLevel(level.upper())


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
