"""Serve authenticated public market data without accessing account credentials."""

import asyncio
import json
from typing import Any
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select

from app.core.errors import AppError
from app.db import Runtime
from app.exchanges.base import EXCHANGES, MARKET_TYPES, Exchange, Instrument, MarketType
from app.exchanges.factory import adapter
from app.exchanges.public import now_ms
from app.models.market import WatchlistEntry

PREFIX = "tradeorbit:market:"
EVENTS = PREFIX + "events"
HEARTBEAT = PREFIX + "worker:heartbeat"


def catalog_key(exchange: Exchange, market_type: MarketType) -> str:
    return PREFIX + f"catalog:{exchange}:{market_type}"


def status_key(exchange: Exchange, market_type: MarketType) -> str:
    return PREFIX + f"status:{exchange}:{market_type}"


def quote_key(key: str) -> str:
    return PREFIX + "quote:" + key


def unpack(raw: Any, default: Any = None) -> Any:
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return default


class MarketService:
    def __init__(self, runtime: Runtime, client: httpx.AsyncClient):
        self.runtime, self.client = runtime, client
        self.detail_slots = asyncio.Semaphore(2)

    async def catalogs(
        self, exchange: Exchange | None = None, market_type: MarketType | None = None
    ) -> list[dict[str, Any]]:
        groups = [
            (ex, kind)
            for ex in EXCHANGES
            for kind in MARKET_TYPES
            if (exchange is None or ex == exchange) and (market_type is None or kind == market_type)
        ]
        values = await self.runtime.redis.mget([catalog_key(ex, kind) for ex, kind in groups])
        return [
            unpack(raw, {"exchange": ex, "market_type": kind, "updated_at": None, "items": []})
            for (ex, kind), raw in zip(groups, values, strict=True)
        ]

    async def instrument(self, key: str, *, require_recent: bool = False) -> Instrument:
        parts = key.split(":")
        if len(parts) != 3 or parts[0] not in EXCHANGES or parts[1] not in MARKET_TYPES:
            raise AppError("INSTRUMENT_NOT_FOUND", "交易对不存在或尚未获取规格", 404)
        raw = await self.runtime.redis.get(PREFIX + f"catalog:{parts[0]}:{parts[1]}")
        catalog = unpack(raw, {})
        if require_recent and now_ms() - (catalog.get("updated_at") or 0) > 7_200_000:
            raise AppError("CATALOG_STALE", "产品规格尚未就绪或已过期，请检查行情连接", 503)
        for item in catalog.get("items", []):
            if item["key"] == key:
                return Instrument.model_validate(item)
        raise AppError("INSTRUMENT_NOT_FOUND", "交易对已下架、不受支持或尚未获取规格", 404)

    async def sources(self) -> list[dict[str, Any]]:
        groups = [(ex, kind) for ex in EXCHANGES for kind in MARKET_TYPES]
        statuses = await self.runtime.redis.mget([status_key(ex, kind) for ex, kind in groups])
        catalogs = await self.catalogs()
        result = []
        for (exchange, kind), raw, catalog in zip(groups, statuses, catalogs, strict=True):
            state = unpack(raw, {})
            updated = catalog.get("updated_at")
            result.append(
                {
                    "exchange": exchange,
                    "market_type": kind,
                    "catalog_updated_at": updated,
                    "instrument_count": len(catalog.get("items", [])),
                    "catalog_stale": updated is None or now_ms() - updated > 7_200_000,
                    "state": state.get("state", "WAITING"),
                    "transport": state.get("transport"),
                    "error": state.get("error"),
                    "last_received_at": state.get("last_received_at"),
                    "subscribed": state.get("subscribed", 0),
                    "requested": state.get("requested", 0),
                }
            )
        return result

    async def entries(self, workspace_id: UUID) -> list[dict[str, Any]]:
        async with self.runtime.sessions() as db:
            rows = (
                await db.scalars(
                    select(WatchlistEntry)
                    .where(WatchlistEntry.workspace_id == workspace_id)
                    .order_by(WatchlistEntry.created_at)
                )
            ).all()
            return [{"id": str(row.id), "key": row.instrument_key} for row in rows]

    async def snapshot(self, workspace_id: UUID) -> dict[str, Any]:
        entries = await self.entries(workspace_id)
        catalogs = await self.catalogs()
        instruments = {
            item["key"]: item for catalog in catalogs for item in catalog.get("items", [])
        }
        quotes = (
            await self.runtime.redis.mget([quote_key(item["key"]) for item in entries])
            if entries
            else []
        )
        sources = await self.sources()
        for entry, raw in zip(entries, quotes, strict=True):
            entry["instrument"] = instruments.get(entry["key"])
            entry["ticker"] = unpack(raw)
        return {
            "entries": entries,
            "sources": sources,
            "worker_alive": bool(await self.runtime.redis.exists(HEARTBEAT)),
            "server_time": now_ms(),
            "trading_enabled": False,
        }

    async def detail(self, key: str) -> dict[str, Any]:
        instrument = await self.instrument(key)
        cache_key = PREFIX + "detail:" + key
        lock_key = PREFIX + "detail-lock:" + key
        prior = unpack(await self.runtime.redis.get(cache_key))
        cooldown = (
            5_000
            if not prior
            or any(
                prior.get(name, {}).get("status") == "FRESH"
                for name in ("book", "candles", "trades")
            )
            else 30_000
        )
        if prior and now_ms() - prior["fetched_at"] < cooldown:
            return prior
        token = str(uuid4())
        acquired = await self.runtime.redis.set(lock_key, token, nx=True, ex=30)
        if not acquired:
            if prior:
                return self.stale_detail(prior)
            raise AppError("MARKET_BUSY", "该交易对快照正在更新，请稍后重试", 503)
        try:
            try:
                await asyncio.wait_for(self.detail_slots.acquire(), timeout=1)
            except TimeoutError as exc:
                raise AppError("MARKET_BUSY", "快照请求繁忙，请稍后重试", 503) from exc
            try:
                async with asyncio.timeout(15):
                    parts = await adapter(instrument.exchange, self.client).detail(instrument)
            except TimeoutError:
                parts = {
                    name: {
                        "data": None,
                        "status": "UNAVAILABLE",
                        "received_at": None,
                        "error": "NETWORK_ERROR",
                    }
                    for name in ("book", "candles", "trades")
                }
            finally:
                self.detail_slots.release()
            for name, component in parts.items():
                if (
                    component["status"] == "UNAVAILABLE"
                    and prior
                    and prior.get(name, {}).get("data") is not None
                ):
                    parts[name] = {**prior[name], "status": "STALE", "error": component["error"]}
            result = {
                "instrument": instrument.model_dump(),
                **parts,
                "mode": "REST_SNAPSHOT",
                "refresh_seconds": 5,
                "fetched_at": now_ms(),
            }
            await self.runtime.redis.set(cache_key, json.dumps(result), ex=300)
            return result
        finally:
            await self.runtime.redis.eval(
                "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end",
                1,
                lock_key,
                token,
            )

    @staticmethod
    def stale_detail(detail: dict[str, Any]) -> dict[str, Any]:
        result = dict(detail)
        for name in ("book", "candles", "trades"):
            if result.get(name, {}).get("data") is not None:
                result[name] = {**result[name], "status": "STALE"}
        return result
