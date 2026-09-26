"""FastAPI application factory."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.deps import init_job_semaphore
from app.api.routes import router
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import get_logger, request_id_var, setup_logging

logger = get_logger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)
    init_job_semaphore(settings.max_concurrent_jobs)

    app = FastAPI(
        title="Raster to SVG",
        description=(
            "Convert raster images (PNG, JPEG, WebP, BMP) into editable SVG "
            "using VTracer 1.x (currently 1.0.0a4). Photo mode uses watershed "
            "clustering for stylized poster / illustration output — not "
            "continuous-tone photographic fidelity."
        ),
        version=settings.app_version,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[
            "X-Request-Id",
            "X-Processing-Ms",
            "X-Input-Format",
            "X-Input-Size",
            "X-Preset",
            "X-Smooth-Level",
            "X-Compression-Level",
            "X-Detail",
            "X-Denoise",
            "X-Max-Colors",
            "Content-Disposition",
        ],
    )

    @app.middleware("http")
    async def request_id_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        incoming = request.headers.get("X-Request-Id") or request.headers.get(
            "X-Request-ID"
        )
        rid = (incoming or "").strip() or str(uuid.uuid4())
        token = request_id_var.set(rid)
        try:
            response = await call_next(request)
            response.headers.setdefault("X-Request-Id", rid)
            return response
        finally:
            request_id_var.reset(token)

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        rid = request_id_var.get("-")
        logger.warning(
            "AppError %s: %s",
            exc.code,
            exc.message,
            extra={"request_id": rid},
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.code,
                "message": exc.message,
                "request_id": rid,
            },
            headers={"X-Request-Id": rid},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        rid = request_id_var.get("-")
        # Avoid dumping huge bodies; summarize
        messages = []
        for err in exc.errors():
            loc = ".".join(str(x) for x in err.get("loc", ()))
            messages.append(f"{loc}: {err.get('msg', 'invalid')}")
        message = "; ".join(messages) or "Invalid request parameters"
        return JSONResponse(
            status_code=422,
            content={
                "error": "invalid_parameter",
                "message": message,
                "request_id": rid,
            },
            headers={"X-Request-Id": rid},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        rid = request_id_var.get("-")
        code = "invalid_parameter" if exc.status_code == 422 else "error"
        if exc.status_code == 401:
            code = "unauthorized"
        elif exc.status_code == 413:
            code = "file_too_large"
        elif exc.status_code == 415:
            code = "unsupported_format"
        elif exc.status_code == 503:
            code = "busy"
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": code,
                "message": str(exc.detail),
                "request_id": rid,
            },
            headers={"X-Request-Id": rid},
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        rid = request_id_var.get("-")
        logger.exception("Unhandled error", extra={"request_id": rid})
        return JSONResponse(
            status_code=500,
            content={
                "error": "vectorization_failed",
                "message": "Internal server error",
                "request_id": rid,
            },
            headers={"X-Request-Id": rid},
        )

    app.include_router(router)
    return app


app = create_app()
