"""OKX global public data with explicit linear-contract-to-base conversion."""

from decimal import Decimal
from typing import Any

from app.exchanges.base import (
    Exchange,
    Instrument,
    MarketType,
    PublicAdapter,
    Ticker,
    change_percent,
    number,
)
from app.exchanges.public import (
    book,
    candles,
    get_json,
    now_ms,
    snapshot_components,
    timestamp,
    trades,
)


class OkxAdapter(PublicAdapter):
    exchange: Exchange = "okx"
    root = "https://www.okx.com/api/v5"

    async def instruments(self, market_type: MarketType) -> list[Instrument]:
        body = await get_json(
            self.client,
            self.root + "/public/instruments",
            {"instType": "SPOT" if market_type == "SPOT" else "SWAP"},
        )
        result = []
        for row in body["data"]:
            if row.get("state") != "live":
                continue
            spot = market_type == "SPOT"
            if spot and row.get("quoteCcy") != "USDT":
                continue
            if not spot and (row.get("settleCcy") != "USDT" or row.get("ctType") != "linear"):
                continue
            base = row["baseCcy"] if spot else row["instId"].removesuffix("-USDT-SWAP")
            if not spot and (
                row.get("ctValCcy") != base or number(row.get("ctVal"), positive=True) is None
            ):
                continue
            contract_size = (
                None
                if spot
                else format(Decimal(row["ctVal"]) * Decimal(row.get("ctMult") or "1"), "f")
            )
            result.append(
                Instrument(
                    key=f"okx:{market_type}:{row['instId']}",
                    exchange="okx",
                    market_type=market_type,
                    symbol=row["instId"],
                    base=base,
                    settle=None if spot else "USDT",
                    price_tick=number(row.get("tickSz"), positive=True),
                    quantity_step=number(row.get("lotSz"), positive=True),
                    contract_size=contract_size,
                    quantity_unit="BASE" if spot else "CONTRACT",
                )
            )
        return result

    def websocket(
        self, market_type: MarketType, instruments: list[Instrument]
    ) -> tuple[str, dict[str, Any] | None]:
        return "wss://ws.okx.com/ws/v5/public", {
            "op": "subscribe",
            "args": [{"channel": "tickers", "instId": item.symbol} for item in instruments],
        }

    def parse_tickers(
        self,
        market_type: MarketType,
        message: dict[str, Any],
        instruments: dict[str, Instrument],
        received_at: int,
    ) -> list[Ticker]:
        result = []
        for row in message.get("data", []):
            item, last = (
                instruments.get(str(row.get("instId", ""))),
                number(row.get("last"), positive=True),
            )
            if item is None or last is None:
                continue
            result.append(
                Ticker(
                    key=item.key,
                    last=last,
                    bid=number(row.get("bidPx"), positive=True),
                    ask=number(row.get("askPx"), positive=True),
                    high_24h=number(row.get("high24h"), positive=True),
                    low_24h=number(row.get("low24h"), positive=True),
                    change_percent_24h=change_percent(last, row.get("open24h")),
                    volume_base_24h=number(
                        row.get("vol24h") if market_type == "SPOT" else row.get("volCcy24h")
                    ),
                    volume_quote_24h=number(row.get("volCcy24h"))
                    if market_type == "SPOT"
                    else None,
                    source_ts=timestamp(row.get("ts")),
                    received_at=received_at,
                )
            )
        return result

    async def tickers(self, market_type: MarketType, instruments: list[Instrument]) -> list[Ticker]:
        body = await get_json(
            self.client,
            self.root + "/market/tickers",
            {"instType": "SPOT" if market_type == "SPOT" else "SWAP"},
        )
        return [
            tick.model_copy(update={"transport": "REST"})
            for tick in self.parse_tickers(
                market_type, body, {item.symbol: item for item in instruments}, now_ms()
            )
        ]

    async def detail(self, instrument: Instrument) -> dict[str, Any]:
        params = {"instId": instrument.symbol}
        return await snapshot_components(
            self.client,
            {
                "book": (
                    self.root + "/market/books",
                    {**params, "sz": 5},
                    lambda body: book(body["data"][0], instrument),
                ),
                "candles": (
                    self.root + "/market/candles",
                    {**params, "bar": "1m", "limit": 120},
                    lambda body: candles(body["data"], confirmed_index=8),
                ),
                "trades": (
                    self.root + "/market/trades",
                    {**params, "limit": 20},
                    lambda body: trades(
                        body["data"],
                        instrument,
                        price_key="px",
                        quantity_key="sz",
                        time_key="ts",
                        id_key="tradeId",
                        side_key="side",
                    ),
                ),
            },
        )
