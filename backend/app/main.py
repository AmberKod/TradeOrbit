"""Application factory with explicit runtime and safe failure responses."""

from contextlib import asynccontextmanager
from time import monotonic
from typing import Any
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException

from app.api import accounts, audit, auth, health
from app.core.config import Settings
from app.core.errors import AppError, failure
from app.core.logging import configure_logging
from app.db import Runtime, build_runtime


def create_app(
    settings: Settings | None = None, injected_runtime: Runtime | None = None
) -> FastAPI:
    config = settings or Settings()
    configure_logging()
    rt = injected_runtime or build_runtime(config)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.runtime = rt
        yield
        await rt.redis.aclose()
        await rt.engine.dispose()

    application = FastAPI(
        title="TradeOrbit API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs" if config.app_env != "production" else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if config.app_env != "production" else None,
    )
    application.state.runtime = rt
    application.add_middleware(
        CORSMiddleware,
        allow_origins=config.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Token", "Idempotency-Key"],
    )

    @application.middleware("http")
    async def request_context(request: Request, call_next: Any):
        request.state.request_id = str(uuid4())
        started = monotonic()
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request.state.request_id)
        unsafe = request.method not in {"GET", "HEAD", "OPTIONS"} and request.url.path.startswith(
            "/api/"
        )
        if unsafe and request.headers.get("origin") not in config.allowed_origins:
            response = JSONResponse(
                status_code=403,
                content=failure(request, AppError("ORIGIN_REJECTED", "请求来源未获授权", 403)),
            )
        else:
            response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        structlog.get_logger().info(
            "http.request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            elapsed_ms=round((monotonic() - started) * 1000, 2),
        )
        return response

    @application.exception_handler(AppError)
    async def application_error(request: Request, exc: AppError):
        return JSONResponse(status_code=exc.status, content=failure(request, exc))

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        fields = [
            {"field": ".".join(str(x) for x in issue["loc"]), "type": issue["type"]}
            for issue in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=failure(request, AppError("VALIDATION_ERROR", "输入格式不正确", 422, fields)),
        )

    @application.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        code = "NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR"
        return JSONResponse(
            status_code=exc.status_code,
            content=failure(
                request,
                AppError(
                    code,
                    "接口不存在" if exc.status_code == 404 else "请求无法处理",
                    exc.status_code,
                ),
            ),
        )

    @application.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError):
        structlog.get_logger().error("database.failure", error_type=type(exc).__name__)
        return JSONResponse(
            status_code=503,
            content=failure(request, AppError("DEPENDENCY_UNAVAILABLE", "数据服务暂不可用", 503)),
        )

    @application.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        structlog.get_logger().error("request.failure", error_type=type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content=failure(
                request, AppError("INTERNAL_ERROR", "服务暂不可用，请保留请求编号", 500)
            ),
        )

    for module in (auth, accounts, audit, health):
        application.include_router(module.router, prefix="/api/v1")
    return application
