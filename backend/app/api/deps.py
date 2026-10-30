"""Workspace authorization and session-bound mutation protection."""

import hmac
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.security import aware_utc, csrf_token, token_digest
from app.db import Runtime
from app.models.identity import Membership, Role, Session, User, Workspace


def runtime(request: Request) -> Runtime:
    return request.app.state.runtime


async def database(request: Request) -> AsyncIterator[AsyncSession]:
    async with runtime(request).sessions() as session:
        yield session


Database = Annotated[AsyncSession, Depends(database)]


@dataclass
class Identity:
    user: User
    workspace: Workspace
    role: Role
    raw_token: str
    session: Session

    @property
    def workspace_id(self) -> UUID:
        return self.workspace.id


async def identity(request: Request, db: Database) -> Identity:
    token = request.cookies.get(runtime(request).settings.cookie_name, "")
    if not token or len(token) > 128:
        raise AppError("UNAUTHENTICATED", "请先登录", 401)
    stmt = (
        select(Session, User, Membership, Workspace)
        .join(User, User.id == Session.user_id)
        .join(
            Membership,
            (Membership.user_id == Session.user_id)
            & (Membership.workspace_id == Session.workspace_id),
        )
        .join(Workspace, Workspace.id == Session.workspace_id)
        .where(Session.token_hash == token_digest(token))
    )
    row = (await db.execute(stmt)).first()
    if row is None or not row[1].active or aware_utc(row[0].expires_at) <= datetime.now(UTC):
        raise AppError("UNAUTHENTICATED", "登录已失效，请重新登录", 401)
    result = Identity(
        user=row[1], workspace=row[3], role=Role(row[2].role), raw_token=token, session=row[0]
    )
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        expected = csrf_token(token, runtime(request).settings.session_secret.get_secret_value())
        supplied = request.headers.get("x-csrf-token", "")
        if not hmac.compare_digest(supplied.encode(), expected.encode()):
            raise AppError("CSRF_REJECTED", "操作校验已失效，请刷新后重试", 403)
    return result


CurrentIdentity = Annotated[Identity, Depends(identity)]


def administrator(current: CurrentIdentity) -> Identity:
    if current.role is not Role.ADMIN:
        raise AppError("FORBIDDEN", "仅管理员可修改连接配置", 403)
    return current


Administrator = Annotated[Identity, Depends(administrator)]
