"""Read-only workspace audit feed, restricted to administrators."""

from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from sqlalchemy import select

from app.api.deps import Administrator, Database
from app.core.errors import success
from app.core.security import aware_utc
from app.models.identity import AuditLog

router = APIRouter(tags=["audit"])


@router.get("/audit-logs")
async def audit_logs(
    request: Request,
    current: Administrator,
    db: Database,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> dict[str, Any]:
    rows = (
        await db.scalars(
            select(AuditLog)
            .where(AuditLog.workspace_id == current.workspace_id)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
        )
    ).all()
    return success(
        request,
        [
            {
                "id": str(row.id),
                "action": row.action,
                "target_id": row.target_id,
                "actor_id": str(row.actor_id) if row.actor_id else None,
                "request_id": row.request_id,
                "details": row.details,
                "created_at": aware_utc(row.created_at).isoformat(),
            }
            for row in rows
        ],
    )
