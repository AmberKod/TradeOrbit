"""Opaque cookie sessions with Redis-backed login throttling."""

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Request, Response
from redis.exceptions import RedisError
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentIdentity, Database, runtime
from app.core.errors import AppError, success
from app.core.security import csrf_token, token_digest, verify_password
from app.models.identity import AuditLog, Membership, Session, User, Workspace
from app.schemas.auth import LoginInput

router = APIRouter(prefix="/auth", tags=["auth"])


def session_data(
    request: Request, user: User, workspace: Workspace, role: str, token: str
) -> dict[str, Any]:
    return {
        "user": {"id": str(user.id), "email": user.email},
        "workspace": {"id": str(workspace.id), "name": workspace.name},
        "role": role,
        "csrf_token": csrf_token(
            token, runtime(request).settings.session_secret.get_secret_value()
        ),
    }


@router.post("/login")
async def login(
    payload: LoginInput, request: Request, response: Response, db: Database
) -> dict[str, Any]:
    rt = runtime(request)
    email = str(payload.email).lower()
    source = request.client.host if request.client else "unknown"
    minute = int(datetime.now(UTC).timestamp() // 60)
    rate_key = f"login:{token_digest(source)}:{minute}"
    try:
        async with rt.redis.pipeline(transaction=True) as pipe:
            counts = await pipe.incr(rate_key).expire(rate_key, 65).execute()
    except RedisError as exc:
        raise AppError("DEPENDENCY_UNAVAILABLE", "登录服务暂不可用，请稍后重试", 503) from exc
    if int(counts[0]) > rt.settings.login_attempts_per_minute:
        raise AppError("RATE_LIMITED", "登录尝试过于频繁，请稍后重试", 429)
    user = await db.scalar(select(User).where(User.email == email))
    valid = await run_in_threadpool(
        verify_password, payload.password.get_secret_value(), user.password_hash if user else None
    )
    if not valid or user is None or not user.active:
        raise AppError("INVALID_CREDENTIALS", "邮箱或密码错误", 401)
    stmt = (
        select(Membership, Workspace)
        .join(Workspace, Workspace.id == Membership.workspace_id)
        .where(Membership.user_id == user.id)
        .order_by(Workspace.created_at)
    )
    if payload.workspace_id:
        stmt = stmt.where(Membership.workspace_id == payload.workspace_id)
    row = (await db.execute(stmt)).first()
    if row is None:
        raise AppError("FORBIDDEN", "没有可访问的工作空间", 403)
    membership, workspace = row
    raw_token = secrets.token_urlsafe(32)
    db.add(
        Session(
            token_hash=token_digest(raw_token),
            user_id=user.id,
            workspace_id=workspace.id,
            expires_at=datetime.now(UTC) + timedelta(hours=rt.settings.session_hours),
        )
    )
    db.add(
        AuditLog(
            workspace_id=workspace.id,
            actor_id=user.id,
            action="auth.login",
            request_id=request.state.request_id,
            details={},
        )
    )
    await db.commit()
    response.set_cookie(
        rt.settings.cookie_name,
        raw_token,
        httponly=True,
        secure=rt.settings.cookie_secure,
        samesite="lax",
        max_age=rt.settings.session_hours * 3600,
        path="/",
    )
    return success(request, session_data(request, user, workspace, membership.role, raw_token))


@router.get("/session")
async def read_session(request: Request, current: CurrentIdentity) -> dict[str, Any]:
    return success(
        request,
        session_data(request, current.user, current.workspace, current.role, current.raw_token),
    )


@router.post("/logout")
async def logout(
    request: Request, response: Response, current: CurrentIdentity, db: Database
) -> dict[str, Any]:
    db.add(
        AuditLog(
            workspace_id=current.workspace_id,
            actor_id=current.user.id,
            action="auth.logout",
            request_id=request.state.request_id,
            details={},
        )
    )
    await db.delete(current.session)
    await db.commit()
    response.delete_cookie(
        runtime(request).settings.cookie_name,
        path="/",
        secure=runtime(request).settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return success(request, {"logged_out": True})
