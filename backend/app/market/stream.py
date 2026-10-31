"""Session-authenticated WebSocket fanout; every snapshot is workspace-scoped."""

import asyncio
import contextlib
import time
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from redis.exceptions import RedisError

from app.api.deps import resolve_identity
from app.core.errors import AppError
from app.market.service import EVENTS, MarketService, now_ms, unpack

router = APIRouter()


@router.websocket("/market/stream")
async def market_stream(socket: WebSocket) -> None:
    runtime = socket.app.state.runtime
    if socket.headers.get("origin") not in runtime.settings.allowed_origins:
        await socket.close(code=4403)
        return
    token = socket.cookies.get(runtime.settings.cookie_name, "")
    try:
        async with runtime.sessions() as db:
            identity = await resolve_identity(token, db)
    except AppError:
        await socket.close(code=4401)
        return
    service: MarketService = socket.app.state.market_service
    await socket.accept()
    connection_id, sequence = str(uuid4()), 0
    receive_task = asyncio.create_task(socket.receive_text())

    async def send(kind: str, data: dict[str, Any]) -> None:
        nonlocal sequence
        sequence += 1
        await socket.send_json(
            {
                "type": kind,
                "schema_version": 1,
                "connection_id": connection_id,
                "sequence": sequence,
                "server_time": now_ms(),
                "data": data,
            }
        )

    try:
        async with runtime.redis.pubsub() as pubsub:
            await pubsub.subscribe(EVENTS)
            state = await service.snapshot(identity.workspace_id)
            allowed = {item["key"] for item in state["entries"]}
            await send("snapshot", state)
            snapshot_at = authenticated_at = flushed_at = heartbeat_at = time.monotonic()
            pending: dict[str, Any] = {}
            while True:
                current = time.monotonic()
                if receive_task.done():
                    message = receive_task.result()
                    if len(message) > 512:
                        await socket.close(code=1009)
                        break
                    body = unpack(message, {})
                    if not isinstance(body, dict) or body.get("type") not in {"ping", "resync"}:
                        await socket.close(code=1008)
                        break
                    if body.get("type") == "resync" and current - snapshot_at > 1:
                        snapshot_at = 0
                    receive_task = asyncio.create_task(socket.receive_text())
                event = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.2)
                if event is not None:
                    body = unpack(event.get("data"), {})
                    if body.get("type") == "ticker" and body.get("data", {}).get("key") in allowed:
                        pending[body["data"]["key"]] = body["data"]
                    elif body.get("type") == "status" or (
                        body.get("type") == "watchlist_changed"
                        and body.get("workspace_id") == str(identity.workspace_id)
                    ):
                        snapshot_at = min(snapshot_at, current - 5)
                if current - authenticated_at >= 15:
                    try:
                        async with runtime.sessions() as db:
                            await resolve_identity(token, db)
                    except AppError:
                        await socket.close(code=4401)
                        break
                    authenticated_at = current
                if current - snapshot_at >= 5:
                    state = await service.snapshot(identity.workspace_id)
                    allowed = {item["key"] for item in state["entries"]}
                    pending = {key: item for key, item in pending.items() if key in allowed}
                    await send("snapshot", state)
                    snapshot_at = current
                if pending and current - flushed_at >= 0.25:
                    await send("tickers", {"items": list(pending.values())})
                    pending.clear()
                    flushed_at = current
                if current - heartbeat_at >= 2:
                    await send("heartbeat", {})
                    heartbeat_at = current
    except RedisError:
        with contextlib.suppress(Exception):
            await socket.close(code=1013)
    except (WebSocketDisconnect, OSError, RuntimeError):
        return
    finally:
        receive_task.cancel()
        with contextlib.suppress(
            asyncio.CancelledError, WebSocketDisconnect, RuntimeError, OSError
        ):
            await receive_task
