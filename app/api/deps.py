"""FastAPI dependencies: settings, API key, concurrency semaphore."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import Depends, Header, Request

from app.core.config import Settings, get_settings
from app.core.errors import busy, unauthorized


class JobSemaphore:
    """Process-local concurrency limiter for CPU-bound vectorization."""

    def __init__(self, limit: int) -> None:
        self._limit = max(1, limit)
        self._in_use = 0
        self._lock = asyncio.Lock()

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def in_use(self) -> int:
        return self._in_use

    async def acquire(self) -> bool:
        """Try to acquire without waiting; return False if full."""
        async with self._lock:
            if self._in_use >= self._limit:
                return False
            self._in_use += 1
            return True

    async def release(self) -> None:
        async with self._lock:
            self._in_use = max(0, self._in_use - 1)


_job_semaphore: JobSemaphore | None = None


def init_job_semaphore(limit: int) -> JobSemaphore:
    global _job_semaphore
    _job_semaphore = JobSemaphore(limit)
    return _job_semaphore


def get_job_semaphore() -> JobSemaphore:
    global _job_semaphore
    if _job_semaphore is None:
        settings = get_settings()
        _job_semaphore = JobSemaphore(settings.max_concurrent_jobs)
    return _job_semaphore


async def require_capacity(
    sem: Annotated[JobSemaphore, Depends(get_job_semaphore)],
) -> JobSemaphore:
    acquired = await sem.acquire()
    if not acquired:
        raise busy()
    return sem


def verify_api_key(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    if not settings.api_key_required:
        return
    expected = settings.api_key
    if not expected:
        raise unauthorized("API key required but server API_KEY is not configured")

    provided: str | None = None
    if x_api_key:
        provided = x_api_key.strip()
    elif authorization:
        parts = authorization.split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            provided = parts[1].strip()
        else:
            provided = authorization.strip()

    if not provided or provided != expected:
        raise unauthorized()
