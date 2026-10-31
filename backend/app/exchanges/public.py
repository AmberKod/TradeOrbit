"""Bounded public HTTP access and normalized REST snapshot components."""

import asyncio
import time
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import httpx

from app.exchanges.base import Instrument, number


def now_ms() -> int:
    return time.time_ns() // 1_000_000


class PublicDataError(Exception):
    def __init__(self, code: str, retry_after: int = 10):
        super().__init__(code)
        self.code = code
        self.retry_after = max(1, min(retry_after, 120))


def error_code(exc: BaseException) -> str:
    return (
        exc.code
        if isinstance(exc, PublicDataError)
        else "NETWORK_ERROR"
        if isinstance(exc, (httpx.HTTPError, OSError, TimeoutError))
        else "INVALID_DATA"
    )


async def get_json(
    client: httpx.AsyncClient, url: str, params: dict[str, Any] | None = None
) -> Any:
    try:
        response = await client.get(url, params=params)
    except httpx.HTTPError as exc:
        raise PublicDataError("NETWORK_ERROR") from exc
    if response.status_code != 200:
        retry = response.headers.get("retry-after", "10")
        raise PublicDataError(
            "RATE_LIMITED" if response.status_code == 429 else f"HTTP_{response.status_code}",
            int(retry) if retry.isdigit() else 10,
        )
    try:
        result = response.json()
    except ValueError as exc:
        raise PublicDataError("INVALID_DATA") from exc
    if isinstance(result, dict) and "code" in result and str(result["code"]) not in {"0", "00000"}:
        raise PublicDataError("EXCHANGE_REJECTED")
    return result


def timestamp(value: Any) -> int | None:
    try:
        parsed = int(value)
        return parsed if parsed > 0 else None
    except (ValueError, TypeError):
        return None


def quantity(value: Any, instrument: Instrument) -> str | None:
    parsed = number(value)
    if parsed is None or Decimal(parsed) < 0:
        return None
    if instrument.quantity_unit == "CONTRACT":
        if instrument.contract_size is None:
            return None
        return format(Decimal(parsed) * Decimal(instrument.contract_size), "f")
    return parsed


def book(data: dict[str, Any], instrument: Instrument) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for side, reverse in (("bids", True), ("asks", False)):
        levels = []
        for row in data.get(side, []):
            price, size = number(row[0], positive=True), quantity(row[1], instrument)
            if price is not None and size is not None and Decimal(size) > 0:
                levels.append({"price": price, "quantity": size, "native_quantity": str(row[1])})
        result[side] = sorted(levels, key=lambda item: Decimal(item["price"]), reverse=reverse)[:5]
    if (
        not result["bids"]
        or not result["asks"]
        or Decimal(result["bids"][0]["price"]) >= Decimal(result["asks"][0]["price"])
    ):
        raise PublicDataError("INVALID_BOOK")
    result["quantity_currency"] = instrument.base
    result["native_quantity_unit"] = instrument.quantity_unit
    return result


def candles(rows: list[list[Any]], *, confirmed_index: int | None = None) -> list[dict[str, Any]]:
    result = {}
    for row in rows:
        if len(row) < 6:
            continue
        opening = timestamp(row[0])
        prices = [number(value, positive=True) for value in row[1:5]]
        if opening is None or any(value is None for value in prices):
            continue
        op, hi, lo, cl = [Decimal(str(value)) for value in prices]
        if hi < max(op, cl, lo) or lo > min(op, cl, hi):
            continue
        result[opening] = {
            "open_time": opening,
            "open": prices[0],
            "high": prices[1],
            "low": prices[2],
            "close": prices[3],
            "confirmed": str(row[confirmed_index]) == "1"
            if confirmed_index is not None and len(row) > confirmed_index
            else None,
        }
    return [result[key] for key in sorted(result)[-120:]]


def trades(
    rows: list[dict[str, Any]],
    instrument: Instrument,
    *,
    price_key: str,
    quantity_key: str,
    time_key: str,
    id_key: str,
    side_key: str | None = None,
) -> list[dict[str, Any]]:
    result = {}
    for row in rows:
        price, size = (
            number(row.get(price_key), positive=True),
            quantity(row.get(quantity_key), instrument),
        )
        ts = timestamp(row.get(time_key))
        if price is None or size is None or Decimal(size) <= 0 or ts is None:
            continue
        raw_side = (
            str(row.get(side_key, "")).upper()
            if side_key
            else "SELL"
            if row.get("isBuyerMaker")
            else "BUY"
        )
        side = raw_side if raw_side in {"BUY", "SELL"} else "UNKNOWN"
        trade_id = str(row.get(id_key, ""))
        if not trade_id:
            continue
        result[trade_id] = {
            "id": trade_id,
            "price": price,
            "quantity": size,
            "native_quantity": str(row[quantity_key]),
            "timestamp": ts,
            "side": side,
        }
    return sorted(result.values(), key=lambda item: (item["timestamp"], item["id"]), reverse=True)[
        :20
    ]


async def snapshot_components(
    client: httpx.AsyncClient, requests: dict[str, tuple[str, dict[str, Any], Callable[[Any], Any]]]
) -> dict[str, Any]:
    async def fetch(
        name: str, request: tuple[str, dict[str, Any], Callable[[Any], Any]]
    ) -> tuple[str, dict[str, Any]]:
        url, params, parse = request
        try:
            data = parse(await get_json(client, url, params))
            return name, {"data": data, "status": "FRESH", "received_at": now_ms(), "error": None}
        except Exception as exc:
            return name, {
                "data": None,
                "status": "UNAVAILABLE",
                "received_at": None,
                "error": error_code(exc),
            }

    return dict(await asyncio.gather(*(fetch(name, request) for name, request in requests.items())))
