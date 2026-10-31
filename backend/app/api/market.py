"""Authenticated, workspace-scoped watchlists and public market snapshots."""

import json
from contextlib import suppress
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from redis.exceptions import RedisError
from sqlalchemy import func, select

from app.api.deps import CurrentIdentity, Database, runtime
from app.core.errors import AppError, success
from app.exchanges.base import Exchange, MarketType
from app.market.service import EVENTS, MarketService
from app.models.identity import AuditLog, Role, Workspace
from app.models.market import WatchlistEntry

router = APIRouter(prefix="/market", tags=["market"])


def service(request: Request) -> MarketService:
    return request.app.state.market_service


class WatchlistInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(
        max_length=120, pattern=r"^(binance|bitget|okx):(SPOT|USDT_PERP):[A-Z0-9_-]{1,60}$"
    )


@router.get("/instruments")
async def instruments(
    request: Request,
    current: CurrentIdentity,
    exchange: Exchange | None = None,
    market_type: MarketType = "SPOT",
    search: Annotated[str, Query(max_length=30)] = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    catalogs = await service(request).catalogs(exchange, market_type)
    term = search.strip().upper()
    rows = [
        item
        for catalog in catalogs
        for item in catalog.get("items", [])
        if not term or term in item["symbol"] or term in item["base"]
    ]
    priority = {"BTC": 0, "ETH": 1, "SOL": 2}
    rows.sort(key=lambda item: (priority.get(item["base"], 10), item["base"], item["exchange"]))
    return success(
        request,
        {"items": rows[:limit], "total": len(rows), "sources": await service(request).sources()},
    )


@router.get("/watchlist")
async def watchlist(request: Request, current: CurrentIdentity) -> dict[str, Any]:
    return success(request, await service(request).snapshot(current.workspace_id))


@router.post("/watchlist", status_code=201)
async def add_watchlist(
    payload: WatchlistInput, request: Request, current: CurrentIdentity, db: Database
) -> dict[str, Any]:
    if current.role is Role.VIEWER:
        raise AppError("FORBIDDEN", "观察者仅可查看行情自选", 403)
    await service(request).instrument(payload.key, require_recent=True)
    await db.scalar(select(Workspace).where(Workspace.id == current.workspace_id).with_for_update())
    existing = await db.scalar(
        select(WatchlistEntry).where(
            WatchlistEntry.workspace_id == current.workspace_id,
            WatchlistEntry.instrument_key == payload.key,
        )
    )
    if existing is not None:
        return success(
            request, {"id": str(existing.id), "key": existing.instrument_key, "created": False}
        )
    count = await db.scalar(
        select(func.count())
        .select_from(WatchlistEntry)
        .where(WatchlistEntry.workspace_id == current.workspace_id)
    )
    if (count or 0) >= 40:
        raise AppError("WATCHLIST_LIMIT", "每个工作空间最多添加 40 个行情自选", 409)
    row = WatchlistEntry(
        workspace_id=current.workspace_id, created_by=current.user.id, instrument_key=payload.key
    )
    db.add(row)
    await db.flush()
    db.add(
        AuditLog(
            workspace_id=current.workspace_id,
            actor_id=current.user.id,
            action="market.watchlist_added",
            target_id=str(row.id),
            request_id=request.state.request_id,
            details={"instrument_key": payload.key},
        )
    )
    await db.commit()
    with suppress(RedisError):
        await runtime(request).redis.publish(
            EVENTS,
            json.dumps({"type": "watchlist_changed", "workspace_id": str(current.workspace_id)}),
        )
    return success(request, {"id": str(row.id), "key": row.instrument_key, "created": True})


@router.delete("/watchlist/{entry_id}")
async def remove_watchlist(
    entry_id: UUID, request: Request, current: CurrentIdentity, db: Database
) -> dict[str, Any]:
    if current.role is Role.VIEWER:
        raise AppError("FORBIDDEN", "观察者仅可查看行情自选", 403)
    row = await db.scalar(
        select(WatchlistEntry).where(
            WatchlistEntry.id == entry_id, WatchlistEntry.workspace_id == current.workspace_id
        )
    )
    if row is None:
        raise AppError("NOT_FOUND", "行情自选不存在", 404)
    db.add(
        AuditLog(
            workspace_id=current.workspace_id,
            actor_id=current.user.id,
            action="market.watchlist_removed",
            target_id=str(row.id),
            request_id=request.state.request_id,
            details={"instrument_key": row.instrument_key},
        )
    )
    await db.delete(row)
    await db.commit()
    await runtime(request).redis.publish(EVENTS, '{"type":"watchlist_changed"}')
    return success(request, {"removed": True})


@router.get("/detail")
async def detail(
    request: Request, current: CurrentIdentity, key: Annotated[str, Query(max_length=120)]
) -> dict[str, Any]:
    return success(request, await service(request).detail(key))
