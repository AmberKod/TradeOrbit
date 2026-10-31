"""Public-market fixture tests; exchange keys and live funds are never used."""

import asyncio
import json
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from app.core.errors import AppError
from app.exchanges.base import Instrument, number
from app.exchanges.binance_adapter import BinanceAdapter
from app.exchanges.bitget_adapter import BitgetAdapter
from app.exchanges.okx_adapter import OkxAdapter
from app.exchanges.public import PublicDataError, book, candles, get_json, now_ms, trades
from app.market.service import MarketService, catalog_key, quote_key
from app.models.identity import AuditLog
from app.models.market import WatchlistEntry


def instrument(exchange="binance", kind="SPOT"):
    symbol = ("BTC-USDT" if kind == "SPOT" else "BTC-USDT-SWAP") if exchange == "okx" else "BTCUSDT"
    return Instrument(
        key=f"{exchange}:{kind}:{symbol}",
        exchange=exchange,
        market_type=kind,
        symbol=symbol,
        base="BTC",
        quantity_unit="CONTRACT" if exchange == "okx" and kind != "SPOT" else "BASE",
        contract_size="0.01" if exchange == "okx" and kind != "SPOT" else None,
    )


async def seed(harness, item=None, *, old=False):
    item = item or instrument()
    await harness.runtime.redis.set(
        catalog_key(item.exchange, item.market_type),
        json.dumps(
            {"updated_at": now_ms() - (8_000_000 if old else 0), "items": [item.model_dump()]}
        ),
    )
    return item


@pytest.mark.parametrize("value", [None, "", True, "NaN", "Infinity", "-Infinity", "invalid"])
def test_invalid_numbers_are_not_zero(value):
    assert number(value) is None


def test_contract_quantities_and_book_validation():
    item = instrument("okx", "USDT_PERP")
    result = book({"bids": [["99", "4"], ["100", "2"]], "asks": [["102", "3"], ["101", "1"]]}, item)
    assert result["bids"][0]["price"] == "100"
    assert Decimal(result["bids"][0]["quantity"]) == Decimal("0.02")
    assert result["asks"][0]["native_quantity"] == "1"
    with pytest.raises(PublicDataError, match="INVALID_BOOK"):
        book({"bids": [["102", "2"]], "asks": [["101", "1"]]}, item)
    parsed = trades(
        [{"tradeId": "1", "px": "100", "sz": "3", "ts": "123", "side": "buy"}],
        item,
        price_key="px",
        quantity_key="sz",
        time_key="ts",
        id_key="tradeId",
        side_key="side",
    )
    assert parsed[0]["quantity"] == "0.03"
    assert parsed[0]["side"] == "BUY"


def test_candles_sort_deduplicate_and_reject_invalid_ohlc():
    rows = [
        [200, "11", "13", "10", "12", "0"],
        [100, "10", "11", "9", "10", "0"],
        [300, "10", "9", "8", "10", "0"],
    ]
    parsed = candles(rows + [rows[0]])
    assert [row["open_time"] for row in parsed] == [100, 200]


@pytest.mark.parametrize(
    "exchange,kind",
    [
        ("binance", "SPOT"),
        ("binance", "USDT_PERP"),
        ("bitget", "SPOT"),
        ("bitget", "USDT_PERP"),
        ("okx", "SPOT"),
        ("okx", "USDT_PERP"),
    ],
)
async def test_native_tickers_keep_market_identity(exchange, kind):
    item = instrument(exchange, kind)
    async with httpx.AsyncClient(trust_env=False) as client:
        cls = {"binance": BinanceAdapter, "bitget": BitgetAdapter, "okx": OkxAdapter}[exchange]
        source = cls(client)
        if exchange == "binance":
            body = {
                "data": {
                    "s": item.symbol,
                    "c": "110",
                    "o": "100",
                    "P": "10",
                    "v": "2",
                    "q": "220",
                    "E": 1000,
                }
            }
        elif exchange == "bitget":
            body = {
                "arg": {"instId": item.symbol},
                "data": [
                    {
                        "lastPr": "110",
                        "open24h": "100",
                        "baseVolume": "2",
                        "quoteVolume": "220",
                        "ts": "1000",
                    }
                ],
            }
        else:
            body = {
                "data": [
                    {
                        "instId": item.symbol,
                        "last": "110",
                        "open24h": "100",
                        "vol24h": "200" if kind == "USDT_PERP" else "2",
                        "volCcy24h": "2" if kind == "USDT_PERP" else "220",
                        "ts": "1000",
                    }
                ]
            }
        tick = source.parse_tickers(kind, body, {item.symbol: item}, 2000)[0]
    assert tick.key == item.key and tick.last == "110"
    assert Decimal(tick.change_percent_24h) == 10
    assert tick.volume_base_24h == "2"
    assert tick.volume_quote_24h == (None if exchange == "okx" and kind == "USDT_PERP" else "220")


async def test_http_rate_limit_has_safe_error_and_cooldown():
    async with httpx.AsyncClient(
        trust_env=False,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(429, headers={"Retry-After": "60"})
        ),
    ) as client:
        with pytest.raises(PublicDataError) as info:
            await get_json(client, "https://api.bitget.com/api/v2/spot/market/tickers")
    assert info.value.code == "RATE_LIMITED" and info.value.retry_after == 60


async def test_watchlist_requires_session_csrf_and_role(harness):
    item = await seed(harness)
    assert (await harness.client.get("/api/v1/market/watchlist")).status_code == 401
    await harness.login("viewer")
    assert (
        await harness.client.post("/api/v1/market/watchlist", json={"key": item.key})
    ).status_code == 403
    await harness.login("admin")
    harness.client.headers.pop("X-CSRF-Token")
    assert (
        await harness.client.post("/api/v1/market/watchlist", json={"key": item.key})
    ).status_code == 403


async def test_watchlist_deduplicates_scopes_and_audits(harness):
    item = await seed(harness)
    await harness.login("trader")
    first = await harness.client.post("/api/v1/market/watchlist", json={"key": item.key})
    assert first.status_code == 201
    assert first.json()["data"]["created"] is True
    again = await harness.client.post("/api/v1/market/watchlist", json={"key": item.key})
    assert again.json()["data"]["created"] is False
    async with harness.runtime.sessions() as db:
        other = WatchlistEntry(
            workspace_id=harness.other_workspace_id,
            created_by=(await db.scalar(select(WatchlistEntry))).created_by,
            instrument_key=item.key,
        )
        db.add(other)
        await db.commit()
        other_id = str(other.id)
    result = (await harness.client.get("/api/v1/market/watchlist")).json()["data"]
    assert len(result["entries"]) == 1 and result["entries"][0]["ticker"] is None
    assert (await harness.client.delete("/api/v1/market/watchlist/" + other_id)).status_code == 404
    assert (
        await harness.client.delete("/api/v1/market/watchlist/" + first.json()["data"]["id"])
    ).status_code == 200
    async with harness.runtime.sessions() as db:
        audits = (await db.scalars(select(AuditLog).where(AuditLog.action.like("market.%")))).all()
    assert len(audits) == 2
    assert (await harness.client.get("/api/v1/market/watchlist")).json()["data"]["entries"] == []


async def test_old_catalog_rejects_new_subscriptions(harness):
    item = await seed(harness, old=True)
    await harness.login()
    response = await harness.client.post("/api/v1/market/watchlist", json={"key": item.key})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "CATALOG_STALE"


async def test_public_details_preserve_components_and_bounded_cache(harness, monkeypatch):
    item = await seed(harness)
    calls = []
    fail = False

    def respond(request):
        calls.append(request.url.path)
        if fail:
            return httpx.Response(503)
        if request.url.path.endswith("/depth"):
            return httpx.Response(200, json={"bids": [["100", "2"]], "asks": [["101", "3"]]})
        if request.url.path.endswith("/klines"):
            return httpx.Response(200, json=[[100, "100", "102", "99", "101", "1"]])
        return httpx.Response(
            200, json=[{"id": 1, "price": "100", "qty": "1", "time": 100, "isBuyerMaker": True}]
        )

    # Emulate Redis compare-delete for fixture Redis without the optional Lua engine.
    async def unlock(script, count, key, token):
        current = await harness.runtime.redis.get(key)
        if current == token.encode():
            return await harness.runtime.redis.delete(key)
        return 0

    monkeypatch.setattr(harness.runtime.redis, "eval", unlock)
    async with httpx.AsyncClient(trust_env=False, transport=httpx.MockTransport(respond)) as client:
        service = MarketService(harness.runtime, client)
        first = await service.detail(item.key)
        assert all(first[part]["status"] == "FRESH" for part in ("book", "candles", "trades"))
        assert (await service.detail(item.key)) == first and len(calls) == 3
        fail = True
        monkeypatch.setattr("app.market.service.now_ms", lambda: first["fetched_at"] + 6000)
        second = await service.detail(item.key)
        assert (
            second["book"]["status"] == "STALE" and second["book"]["data"] == first["book"]["data"]
        )
        assert second["candles"]["status"] == "STALE" and second["trades"]["status"] == "STALE"
        assert second["mode"] == "REST_SNAPSHOT"
        await service.detail(item.key)
        assert len(calls) == 6


async def test_busy_snapshot_never_removes_another_owner_lock(harness):
    item = await seed(harness)
    await harness.runtime.redis.set(
        "tradeorbit:market:detail-lock:" + item.key, "another-owner", ex=30
    )
    async with httpx.AsyncClient(trust_env=False) as client:
        with pytest.raises(AppError, match=".*") as info:
            await MarketService(harness.runtime, client).detail(item.key)
    assert info.value.code == "MARKET_BUSY"
    assert (
        await harness.runtime.redis.get("tradeorbit:market:detail-lock:" + item.key)
        == b"another-owner"
    )


async def test_websocket_rejects_bad_origin_and_missing_session(harness):
    app = harness.client._transport.app
    for origin, expected in [("https://untrusted.example", 4403), ("http://testserver", 4401)]:
        sent = []

        async def send(message, target=sent):
            target.append(message)

        async def receive():
            return {"type": "websocket.connect"}

        await app(
            {
                "type": "websocket",
                "path": "/api/v1/market/stream",
                "raw_path": b"/api/v1/market/stream",
                "query_string": b"",
                "headers": [(b"origin", origin.encode())],
                "scheme": "ws",
                "server": ("testserver", 80),
                "client": ("127.0.0.1", 1),
                "subprotocols": [],
                "root_path": "",
            },
            receive,
            send,
        )
        assert sent[0] == {"type": "websocket.close", "code": expected, "reason": ""}


async def test_collector_does_not_regress_timestamps(harness):
    from app.exchanges.base import Ticker
    from app.market.worker import Collector

    collector = object.__new__(Collector)
    collector.redis = harness.runtime.redis
    collector.last_quotes = {}
    item = instrument()
    first = Ticker(key=item.key, last="110", source_ts=200, received_at=300)
    assert await collector.save([first]) == 1
    assert (
        await collector.save(
            [first.model_copy(update={"last": "99", "source_ts": 100, "received_at": 400})]
        )
        == 0
    )
    collector.last_quotes.clear()
    assert (
        await collector.save(
            [first.model_copy(update={"last": "98", "source_ts": 100, "received_at": 500})]
        )
        == 0
    )
    saved = json.loads(await harness.runtime.redis.get(quote_key(item.key)))
    assert saved["last"] == "110"


async def test_workspace_watchlist_limit_is_enforced(harness):
    item = await seed(harness)
    await harness.login()
    async with harness.runtime.sessions() as db:
        from app.models.identity import User

        user = await db.scalar(select(User).where(User.email == "admin@example.com"))
        db.add_all(
            [
                WatchlistEntry(
                    workspace_id=harness.workspace_id,
                    created_by=user.id,
                    instrument_key=f"binance:SPOT:TEST{i}USDT",
                )
                for i in range(40)
            ]
        )
        await db.commit()
    response = await harness.client.post("/api/v1/market/watchlist", json={"key": item.key})
    assert response.status_code == 409 and response.json()["error"]["code"] == "WATCHLIST_LIMIT"
    assert (
        len((await harness.client.get("/api/v1/market/watchlist")).json()["data"]["entries"]) == 40
    )


async def test_websocket_snapshot_filters_quotes_and_revokes_session(harness, monkeypatch):
    from types import SimpleNamespace

    from app.market import stream
    from app.market.service import EVENTS

    item = await seed(harness)
    await harness.login()
    await harness.client.post("/api/v1/market/watchlist", json={"key": item.key})
    incoming, outgoing = asyncio.Queue(), asyncio.Queue()
    await incoming.put({"type": "websocket.connect"})
    app = harness.client._transport.app
    cookie = harness.client.cookies.get(harness.runtime.settings.cookie_name)
    scope = {
        "type": "websocket",
        "path": "/api/v1/market/stream",
        "raw_path": b"/api/v1/market/stream",
        "query_string": b"",
        "headers": [
            (b"origin", b"http://testserver"),
            (b"cookie", (harness.runtime.settings.cookie_name + "=" + cookie).encode()),
        ],
        "scheme": "ws",
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 1),
        "subprotocols": [],
        "root_path": "",
    }
    task = asyncio.create_task(app(scope, incoming.get, outgoing.put))
    try:
        assert (await asyncio.wait_for(outgoing.get(), 2))["type"] == "websocket.accept"
        initial = json.loads((await asyncio.wait_for(outgoing.get(), 2))["text"])
        assert initial["type"] == "snapshot" and initial["data"]["entries"][0]["key"] == item.key
        await harness.runtime.redis.publish(
            EVENTS,
            json.dumps({"type": "ticker", "data": {"key": "bitget:SPOT:OTHERUSDT", "last": "999"}}),
        )
        await harness.runtime.redis.publish(
            EVENTS, json.dumps({"type": "ticker", "data": {"key": item.key, "last": "100"}})
        )
        batch = json.loads((await asyncio.wait_for(outgoing.get(), 2))["text"])
        assert batch["type"] == "tickers" and batch["data"]["items"] == [
            {"key": item.key, "last": "100"}
        ]
        assert batch["sequence"] == initial["sequence"] + 1
        await harness.client.post("/api/v1/auth/logout")
        original_clock = stream.time.monotonic
        monkeypatch.setattr(
            stream, "time", SimpleNamespace(monotonic=lambda: original_clock() + 16)
        )
        await incoming.put({"type": "websocket.receive", "text": '{"type":"ping"}'})
        closed = await asyncio.wait_for(outgoing.get(), 2)
        assert closed["type"] == "websocket.close" and closed["code"] == 4401
    finally:
        task.cancel()
        import contextlib

        with contextlib.suppress(asyncio.CancelledError):
            await task


@pytest.mark.parametrize("failure", [False, True])
async def test_late_rest_fallback_cannot_replace_live_ws(harness, monkeypatch, failure):
    import contextlib
    from types import SimpleNamespace

    from app.exchanges.base import Ticker
    from app.market import worker

    item = instrument()
    rest_started, live, fallback_finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
    observed, saved = [], []

    class Source:
        def websocket(self, kind, items):
            return "wss://example.test/public", None

        async def tickers(self, kind, items):
            rest_started.set()
            await live.wait()
            fallback_finished.set()
            if failure:
                raise PublicDataError("NETWORK_ERROR")
            return [
                Ticker(key=item.key, last="999", source_ts=999, received_at=999, transport="REST")
            ]

        def parse_tickers(self, kind, body, mapping, received):
            return [Ticker(key=item.key, last="100", source_ts=100, received_at=100)]

    class Socket:
        first = True

        async def recv(self):
            await rest_started.wait()
            if self.first:
                self.first = False
                return '{"data":[]}'
            await asyncio.Event().wait()

        async def send(self, payload):
            pass

    @contextlib.asynccontextmanager
    async def connection(*args, **kwargs):
        yield Socket()

    collector = object.__new__(worker.Collector)
    collector.client, collector.proxy = None, None
    collector.logger = SimpleNamespace(warning=lambda *args, **kwargs: None)

    async def save(ticks):
        saved.extend(ticks)
        return len(ticks)

    async def status(exchange, kind, state, **kwargs):
        observed.append(state)
        if state == "LIVE":
            live.set()

    collector.save, collector.status = save, status
    monkeypatch.setattr(worker, "adapter", lambda *args: Source())
    monkeypatch.setattr(worker, "connect", connection)
    task = asyncio.create_task(collector.group("binance", "SPOT", [item], 1))
    try:
        await asyncio.wait_for(fallback_finished.wait(), 2)
        await asyncio.sleep(0.03)
        assert observed == ["CONNECTING", "LIVE"]
        assert len(saved) == 1 and saved[0].transport == "WS"
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


@pytest.mark.parametrize("old", [False, True])
async def test_restart_restores_only_recent_catalog_without_refreshing_age(harness, old):
    from types import SimpleNamespace

    from app.market.worker import Collector

    item = await seed(harness, old=old)
    original = await harness.runtime.redis.get(catalog_key(item.exchange, item.market_type))
    collector = object.__new__(Collector)
    collector.redis = harness.runtime.redis
    collector.catalogs = {}
    collector.logger = SimpleNamespace(info=lambda *args, **kwargs: None)
    await collector.restore_catalogs()
    assert bool(collector.catalogs) is not old
    if not old:
        assert collector.catalogs[(item.exchange, item.market_type)][item.key] == item
    assert await harness.runtime.redis.get(catalog_key(item.exchange, item.market_type)) == original
