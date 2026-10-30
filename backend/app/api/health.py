"""Dependency-aware readiness is separate from process liveness."""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.deps import CurrentIdentity, runtime
from app.core.config import SCHEMA_REVISION
from app.core.errors import success

router = APIRouter(tags=["system"])


async def dependencies(request: Request) -> dict[str, str]:
    rt = runtime(request)
    result = {"database": "UNAVAILABLE", "schema": "UNAVAILABLE", "redis": "UNAVAILABLE"}
    try:
        async with rt.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            result["database"] = "READY"
            revision = await conn.scalar(text("SELECT version_num FROM alembic_version"))
            result["schema"] = "READY" if revision == SCHEMA_REVISION else "MIGRATION_REQUIRED"
    except Exception:
        result["schema"] = "MIGRATION_REQUIRED" if result["database"] == "READY" else "UNAVAILABLE"
    try:
        if await rt.redis.ping():
            result["redis"] = "READY"
    except Exception:
        result["redis"] = "UNAVAILABLE"
    return result


@router.get("/health/live")
async def live(request: Request) -> dict[str, Any]:
    return success(
        request, {"status": "ALIVE", "version": "0.1.0", "stage": "E01", "trading_enabled": False}
    )


@router.get("/health/ready")
async def ready(request: Request) -> JSONResponse:
    checks = await dependencies(request)
    healthy = all(value == "READY" for value in checks.values())
    return JSONResponse(
        status_code=200 if healthy else 503,
        content=success(request, {"status": "READY" if healthy else "NOT_READY", "checks": checks}),
    )


@router.get("/system/status")
async def system_status(request: Request, current: CurrentIdentity) -> dict[str, Any]:
    return success(
        request,
        {
            "stage": "E01",
            "version": "0.1.0",
            "app_environment": runtime(request).settings.app_env,
            "trading_enabled": False,
            "checks": await dependencies(request),
            "exchange_integration": "NOT_IMPLEMENTED",
            "workspace_id": str(current.workspace_id),
        },
    )
