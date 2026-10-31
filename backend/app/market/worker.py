"""Public-only collector. No account credentials, sessions or order endpoints."""

import asyncio
import contextlib
import json
import random
import signal
import sys
import time
from typing import Any
from uuid import uuid4

import httpx
import structlog
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from websockets.asyncio.client import connect

from app.core.logging import configure_logging
from app.exchanges.base import EXCHANGES, MARKET_TYPES, Exchange, Instrument, MarketType, Ticker
from app.exchanges.factory import adapter
from app.exchanges.public import PublicDataError, error_code, now_ms
from app.market.service import EVENTS, HEARTBEAT, PREFIX, catalog_key, quote_key, status_key, unpack
from app.models.market import WatchlistEntry

LEASE = PREFIX + "worker:lease"
COMPARE_DELETE = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
COMPARE_RENEW = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('expire', KEYS[1], 30) else return 0 end"


class CollectorSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TRADEORBIT_", extra="ignore", hide_input_in_errors=True
    )
    database_url: SecretStr
    redis_url: SecretStr
    public_proxy_url: SecretStr | None = None

    @field_validator("public_proxy_url", mode="before")
    @classmethod
    def empty_proxy(cls, value: Any) -> Any:
        return value or None


class Collector:
    def __init__(self, settings: CollectorSettings):
        self.settings = settings
        self.redis: Any = Redis.from_url(
            settings.redis_url.get_secret_value(), socket_connect_timeout=3, socket_timeout=3
        )
        self.engine = create_async_engine(
            settings.database_url.get_secret_value(),
            pool_pre_ping=True,
            pool_size=2,
            max_overflow=1,
        )
        self.sessions = async_sessionmaker(self.engine)
        self.proxy = (
            settings.public_proxy_url.get_secret_value() if settings.public_proxy_url else None
        )
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(12, connect=5),
            trust_env=False,
            proxy=self.proxy,
            limits=httpx.Limits(max_connections=16, max_keepalive_connections=8),
        )
        self.token = str(uuid4())
        self.stop = asyncio.Event()
        self.catalogs: dict[tuple[Exchange, MarketType], dict[str, Instrument]] = {}
        self.groups: dict[
            tuple[Exchange, MarketType], tuple[tuple[str, ...], asyncio.Task[None]]
        ] = {}
        self.last_quotes: dict[str, Ticker] = {}
        self.logger = structlog.get_logger()

    async def status(
        self,
        exchange: Exchange,
        kind: MarketType,
        state: str,
        *,
        error: str | None = None,
        transport: str | None = None,
        received: int | None = None,
        requested: int = 0,
        subscribed: int = 0,
    ) -> None:
        body = {
            "exchange": exchange,
            "market_type": kind,
            "state": state,
            "error": error,
            "transport": transport,
            "last_received_at": received,
            "requested": requested,
            "subscribed": subscribed,
        }
        await self.redis.set(status_key(exchange, kind), json.dumps(body), ex=45)
        await self.redis.publish(EVENTS, json.dumps({"type": "status", "data": body}))

    async def save(self, ticks: list[Ticker]) -> int:
        accepted = 0
        for tick in ticks:
            if tick.last is None:
                continue
            prior = self.last_quotes.get(tick.key)
            if prior is None:
                cached = unpack(await self.redis.get(quote_key(tick.key)))
                if isinstance(cached, dict):
                    with contextlib.suppress(ValueError):
                        prior = Ticker.model_validate(cached)
            if (
                prior
                and tick.source_ts is not None
                and prior.source_ts is not None
                and tick.source_ts < prior.source_ts
            ):
                continue
            self.last_quotes[tick.key] = tick
            payload = tick.model_dump_json()
            pipe = self.redis.pipeline(transaction=False)
            pipe.set(quote_key(tick.key), payload, ex=300)
            pipe.publish(EVENTS, json.dumps({"type": "ticker", "data": tick.model_dump()}))
            await pipe.execute()
            accepted += 1
        return accepted

    async def restore_catalogs(self) -> None:
        groups = [(ex, kind) for ex in EXCHANGES for kind in MARKET_TYPES]
        values = await self.redis.mget([catalog_key(ex, kind) for ex, kind in groups])
        for (exchange, kind), raw in zip(groups, values, strict=True):
            cached = unpack(raw, {})
            if not isinstance(cached, dict):
                continue
            updated = cached.get("updated_at")
            if not isinstance(updated, int) or not -60_000 <= now_ms() - updated <= 7_200_000:
                continue
            items = {}
            for value in cached.get("items", []):
                try:
                    item = Instrument.model_validate(value)
                except ValueError:
                    continue
                if item.exchange == exchange and item.market_type == kind:
                    items[item.key] = item
            if items:
                self.catalogs[(exchange, kind)] = items
                self.logger.info(
                    "market.catalog_restored", exchange=exchange, market_type=kind, count=len(items)
                )

    async def catalog_loop(self, exchange: Exchange, kind: MarketType) -> None:
        while not self.stop.is_set():
            delay = 3600
            try:
                instruments = await adapter(exchange, self.client).instruments(kind)
                if not instruments:
                    raise PublicDataError("EMPTY_CATALOG")
                self.catalogs[(exchange, kind)] = {item.key: item for item in instruments}
                await self.redis.set(
                    catalog_key(exchange, kind),
                    json.dumps(
                        {
                            "exchange": exchange,
                            "market_type": kind,
                            "updated_at": now_ms(),
                            "items": [item.model_dump() for item in instruments],
                        }
                    ),
                )
                self.logger.info(
                    "market.catalog_ready",
                    exchange=exchange,
                    market_type=kind,
                    count=len(instruments),
                )
            except Exception as exc:
                delay = max(60, exc.retry_after) if isinstance(exc, PublicDataError) else 60
                self.logger.warning(
                    "market.catalog_failed",
                    exchange=exchange,
                    market_type=kind,
                    error=error_code(exc),
                )
                if (exchange, kind) not in self.catalogs:
                    await self.status(exchange, kind, "UNAVAILABLE", error=error_code(exc))
            await asyncio.sleep(delay)

    async def group(
        self, exchange: Exchange, kind: MarketType, instruments: list[Instrument], requested: int
    ) -> None:
        source = adapter(exchange, self.client)
        mapping = {item.symbol: item for item in instruments}
        ws_alive = asyncio.Event()
        latest: dict[str, int | None] = {"received": None}
        count = len(instruments)

        async def rest_fallback() -> None:
            while True:
                try:
                    if not ws_alive.is_set():
                        ticks = await source.tickers(kind, instruments)
                        if not ws_alive.is_set() and await self.save(ticks):
                            if ws_alive.is_set():
                                continue
                            latest["received"] = now_ms()
                            await self.status(
                                exchange,
                                kind,
                                "DEGRADED",
                                transport="REST",
                                received=latest["received"],
                                requested=requested,
                                subscribed=count,
                            )
                except Exception as exc:
                    if ws_alive.is_set():
                        await asyncio.sleep(10)
                        continue
                    await self.status(
                        exchange,
                        kind,
                        "UNAVAILABLE",
                        error=error_code(exc),
                        received=latest["received"],
                        requested=requested,
                        subscribed=count,
                    )
                    if isinstance(exc, PublicDataError):
                        await asyncio.sleep(max(10, exc.retry_after))
                await asyncio.sleep(10)

        fallback = asyncio.create_task(rest_fallback())
        attempt = 0
        try:
            while True:
                await self.status(
                    exchange,
                    kind,
                    "CONNECTING",
                    received=latest["received"],
                    requested=requested,
                    subscribed=count,
                )
                try:
                    url, subscription = source.websocket(kind, instruments)
                    async with connect(
                        url,
                        proxy=self.proxy,
                        open_timeout=12,
                        close_timeout=3,
                        ping_interval=20 if exchange == "binance" else None,
                        ping_timeout=15,
                        max_size=2_000_000,
                        max_queue=16,
                    ) as socket:
                        if subscription:
                            await socket.send(json.dumps(subscription))
                        ping_at = time.monotonic()
                        data_at = time.monotonic()
                        status_at = 0.0
                        while True:
                            current = time.monotonic()
                            if exchange != "binance" and current - ping_at >= 20:
                                await socket.send("ping")
                                ping_at = current
                            if current - data_at > 45:
                                raise PublicDataError("WS_STALE")
                            try:
                                message = await asyncio.wait_for(socket.recv(), timeout=1)
                            except TimeoutError:
                                continue
                            if message == "pong":
                                continue
                            body = unpack(message, {})
                            if not isinstance(body, dict):
                                continue
                            if body.get("event") == "error" or (
                                body.get("code") and str(body["code"]) not in {"0", "00000"}
                            ):
                                raise PublicDataError("SUBSCRIPTION_REJECTED")
                            ticks = source.parse_tickers(kind, body, mapping, now_ms())
                            if await self.save(ticks):
                                ws_alive.set()
                                attempt = 0
                                data_at = current
                                latest["received"] = now_ms()
                                if current - status_at >= 5:
                                    await self.status(
                                        exchange,
                                        kind,
                                        "LIVE",
                                        transport="WS",
                                        received=latest["received"],
                                        requested=requested,
                                        subscribed=count,
                                    )
                                    status_at = current
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    ws_alive.clear()
                    await self.status(
                        exchange,
                        kind,
                        "DEGRADED",
                        error=error_code(exc),
                        received=latest["received"],
                        requested=requested,
                        subscribed=count,
                    )
                    self.logger.warning(
                        "market.websocket_retry",
                        exchange=exchange,
                        market_type=kind,
                        error=error_code(exc),
                    )
                    delay = min(30, 2 ** min(attempt, 5)) + random.uniform(0, 1)
                    attempt += 1
                    await asyncio.sleep(delay)
        finally:
            fallback.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await fallback

    async def reconcile(self) -> None:
        async with self.sessions() as db:
            keys = set((await db.scalars(select(WatchlistEntry.instrument_key).distinct())).all())
        for exchange in EXCHANGES:
            for kind in MARKET_TYPES:
                group_key = (exchange, kind)
                catalog = self.catalogs.get(group_key, {})
                desired = tuple(sorted(key for key in keys if key in catalog))
                active = self.groups.get(group_key)
                if active and (active[0] != desired or active[1].done()):
                    active[1].cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await active[1]
                    del self.groups[group_key]
                if desired and group_key not in self.groups:
                    task = asyncio.create_task(
                        self.group(
                            exchange, kind, [catalog[key] for key in desired[:80]], len(desired)
                        )
                    )
                    self.groups[group_key] = (desired, task)
                elif not desired and catalog:
                    await self.status(exchange, kind, "IDLE")

    async def run(self) -> None:
        catalog_tasks: list[asyncio.Task[None]] = []
        try:
            while not await self.redis.set(LEASE, self.token, nx=True, ex=30):
                await asyncio.sleep(5)
            await self.restore_catalogs()
            catalog_tasks = [
                asyncio.create_task(self.catalog_loop(ex, kind))
                for ex in EXCHANGES
                for kind in MARKET_TYPES
            ]
            while not self.stop.is_set():
                if not await self.redis.eval(COMPARE_RENEW, 1, LEASE, self.token):
                    raise RuntimeError("collector lease lost")
                await self.redis.set(HEARTBEAT, str(now_ms()), ex=30)
                try:
                    await self.reconcile()
                except Exception as exc:
                    self.logger.error("market.reconcile_failed", error_type=type(exc).__name__)
                try:
                    await asyncio.wait_for(self.stop.wait(), timeout=5)
                except TimeoutError:
                    pass
        finally:
            tasks = catalog_tasks + [entry[1] for entry in self.groups.values()]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            with contextlib.suppress(Exception):
                await self.redis.eval(COMPARE_DELETE, 1, LEASE, self.token)
            await self.client.aclose()
            await self.redis.aclose()
            await self.engine.dispose()


async def main() -> None:
    settings = CollectorSettings()
    if "--check" in sys.argv:
        redis = Redis.from_url(
            settings.redis_url.get_secret_value(), socket_connect_timeout=3, socket_timeout=3
        )
        try:
            if not await redis.exists(HEARTBEAT):
                raise SystemExit(1)
        finally:
            await redis.aclose()
        return
    configure_logging()
    collector = Collector(settings)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, collector.stop.set)
    await collector.run()


if __name__ == "__main__":
    asyncio.run(main())
