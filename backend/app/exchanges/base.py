"""Shared public-market contracts; amounts remain decimal strings on the wire."""

from abc import ABC, abstractmethod
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict

Exchange = Literal["binance", "bitget", "okx"]
MarketType = Literal["SPOT", "USDT_PERP"]
EXCHANGES: tuple[Exchange, ...] = ("binance", "bitget", "okx")
MARKET_TYPES: tuple[MarketType, ...] = ("SPOT", "USDT_PERP")


def number(value: Any, *, positive: bool = False) -> str | None:
    """Reject NaN, infinity, booleans and missing prices rather than inventing zero."""
    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite() or (positive and parsed <= 0):
        return None
    return format(parsed, "f")


def change_percent(last: Any, opening: Any) -> str | None:
    last_value, open_value = number(last, positive=True), number(opening, positive=True)
    if last_value is None or open_value is None:
        return None
    return format((Decimal(last_value) / Decimal(open_value) - 1) * 100, "f")


class Instrument(BaseModel):
    model_config = ConfigDict(frozen=True)
    key: str
    exchange: Exchange
    market_type: MarketType
    symbol: str
    base: str
    quote: str = "USDT"
    settle: str | None = None
    price_tick: str | None = None
    quantity_step: str | None = None
    contract_size: str | None = None
    quantity_unit: Literal["BASE", "CONTRACT"] = "BASE"


class Ticker(BaseModel):
    model_config = ConfigDict(frozen=True)
    key: str
    last: str | None
    bid: str | None = None
    ask: str | None = None
    high_24h: str | None = None
    low_24h: str | None = None
    change_percent_24h: str | None = None
    volume_base_24h: str | None = None
    volume_quote_24h: str | None = None
    source_ts: int | None = None
    received_at: int
    transport: Literal["WS", "REST"] = "WS"


class PublicAdapter(ABC):
    """Implementations use fixed official hosts and public GET/subscription operations."""

    exchange: Exchange

    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    @abstractmethod
    async def instruments(self, market_type: MarketType) -> list[Instrument]:
        raise NotImplementedError

    @abstractmethod
    def websocket(
        self, market_type: MarketType, instruments: list[Instrument]
    ) -> tuple[str, dict[str, Any] | None]:
        raise NotImplementedError

    @abstractmethod
    def parse_tickers(
        self,
        market_type: MarketType,
        message: dict[str, Any],
        instruments: dict[str, Instrument],
        received_at: int,
    ) -> list[Ticker]:
        raise NotImplementedError

    @abstractmethod
    async def tickers(self, market_type: MarketType, instruments: list[Instrument]) -> list[Ticker]:
        raise NotImplementedError

    @abstractmethod
    async def detail(self, instrument: Instrument) -> dict[str, Any]:
        raise NotImplementedError
