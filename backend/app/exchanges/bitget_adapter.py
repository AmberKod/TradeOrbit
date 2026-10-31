"""Bitget v2 public market data, independent of private CLASSIC/UTA accounts."""

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


class BitgetAdapter(PublicAdapter):
    exchange: Exchange = "bitget"
    root = "https://api.bitget.com/api/v2"

    async def instruments(self, market_type: MarketType) -> list[Instrument]:
        path = "/spot/public/symbols" if market_type == "SPOT" else "/mix/market/contracts"
        body = await get_json(
            self.client,
            self.root + path,
            {} if market_type == "SPOT" else {"productType": "USDT-FUTURES"},
        )
        result = []
        for row in body["data"]:
            if row.get("quoteCoin") != "USDT":
                continue
            if market_type == "SPOT" and row.get("status") != "online":
                continue
            if market_type == "USDT_PERP" and (
                row.get("symbolStatus") != "normal"
                or row.get("symbolType") != "perpetual"
                or "USDT" not in row.get("supportMarginCoins", [])
            ):
                continue
            places = int(row["pricePrecision"] if market_type == "SPOT" else row["pricePlace"])
            tick = Decimal(10) ** -places * Decimal(row.get("priceEndStep", "1"))
            step = (
                format(Decimal(10) ** -int(row["quantityPrecision"]), "f")
                if market_type == "SPOT"
                else number(row.get("sizeMultiplier"), positive=True)
            )
            result.append(
                Instrument(
                    key=f"bitget:{market_type}:{row['symbol']}",
                    exchange="bitget",
                    market_type=market_type,
                    symbol=row["symbol"],
                    base=row["baseCoin"],
                    settle="USDT" if market_type == "USDT_PERP" else None,
                    price_tick=format(tick, "f"),
                    quantity_step=step,
                )
            )
        return result

    def websocket(
        self, market_type: MarketType, instruments: list[Instrument]
    ) -> tuple[str, dict[str, Any] | None]:
        inst_type = "SPOT" if market_type == "SPOT" else "USDT-FUTURES"
        return "wss://ws.bitget.com/v2/ws/public", {
            "op": "subscribe",
            "args": [
                {"instType": inst_type, "channel": "ticker", "instId": item.symbol}
                for item in instruments
            ],
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
            symbol = str(
                row.get("instId", row.get("symbol", message.get("arg", {}).get("instId", "")))
            )
            item, last = instruments.get(symbol), number(row.get("lastPr"), positive=True)
            if item is None or last is None:
                continue
            change = change_percent(last, row.get("open24h"))
            ratio = number(row.get("change24h"))
            if change is None and ratio is not None:
                change = format(Decimal(ratio) * 100, "f")
            result.append(
                Ticker(
                    key=item.key,
                    last=last,
                    bid=number(row.get("bidPr"), positive=True),
                    ask=number(row.get("askPr"), positive=True),
                    high_24h=number(row.get("high24h"), positive=True),
                    low_24h=number(row.get("low24h"), positive=True),
                    change_percent_24h=change,
                    volume_base_24h=number(row.get("baseVolume")),
                    volume_quote_24h=number(row.get("quoteVolume", row.get("usdtVolume"))),
                    source_ts=timestamp(row.get("ts", message.get("ts"))),
                    received_at=received_at,
                )
            )
        return result

    async def tickers(self, market_type: MarketType, instruments: list[Instrument]) -> list[Ticker]:
        path = "/spot/market/tickers" if market_type == "SPOT" else "/mix/market/tickers"
        params = {} if market_type == "SPOT" else {"productType": "USDT-FUTURES"}
        body = await get_json(self.client, self.root + path, params)
        return [
            tick.model_copy(update={"transport": "REST"})
            for tick in self.parse_tickers(
                market_type, body, {item.symbol: item for item in instruments}, now_ms()
            )
        ]

    async def detail(self, instrument: Instrument) -> dict[str, Any]:
        spot, symbol = instrument.market_type == "SPOT", instrument.symbol
        prefix = self.root + ("/spot/market" if spot else "/mix/market")
        params = {"symbol": symbol} if spot else {"symbol": symbol, "productType": "USDT-FUTURES"}
        return await snapshot_components(
            self.client,
            {
                "book": (
                    prefix + ("/orderbook" if spot else "/merge-depth"),
                    {
                        **params,
                        "limit": "5",
                        **({"type": "step0"} if spot else {"precision": "scale0"}),
                    },
                    lambda body: book(body["data"], instrument),
                ),
                "candles": (
                    prefix + "/candles",
                    {**params, "granularity": "1min" if spot else "1m", "limit": 120},
                    lambda body: candles(body["data"]),
                ),
                "trades": (
                    prefix + "/fills",
                    {**params, "limit": 20},
                    lambda body: trades(
                        body["data"],
                        instrument,
                        price_key="price",
                        quantity_key="size",
                        time_key="ts",
                        id_key="tradeId",
                        side_key="side",
                    ),
                ),
            },
        )
