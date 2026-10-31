"""Binance market-data-only Spot and USD-M USDT perpetual public feeds."""

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


class BinanceAdapter(PublicAdapter):
    exchange: Exchange = "binance"

    def endpoint(self, market_type: MarketType) -> str:
        return (
            "https://data-api.binance.vision/api/v3"
            if market_type == "SPOT"
            else "https://fapi.binance.com/fapi/v1"
        )

    async def instruments(self, market_type: MarketType) -> list[Instrument]:
        body = await get_json(self.client, self.endpoint(market_type) + "/exchangeInfo")
        result = []
        for row in body["symbols"]:
            if row.get("quoteAsset") != "USDT" or row.get("status") != "TRADING":
                continue
            if market_type == "USDT_PERP" and (
                row.get("contractType") != "PERPETUAL" or row.get("marginAsset") != "USDT"
            ):
                continue
            if market_type == "SPOT" and not row.get("isSpotTradingAllowed", False):
                continue
            filters = {item["filterType"]: item for item in row["filters"]}
            result.append(
                Instrument(
                    key=f"binance:{market_type}:{row['symbol']}",
                    exchange="binance",
                    market_type=market_type,
                    symbol=row["symbol"],
                    base=row["baseAsset"],
                    settle="USDT" if market_type == "USDT_PERP" else None,
                    price_tick=number(
                        filters.get("PRICE_FILTER", {}).get("tickSize"), positive=True
                    ),
                    quantity_step=number(
                        filters.get("LOT_SIZE", {}).get("stepSize"), positive=True
                    ),
                )
            )
        return result

    def websocket(
        self, market_type: MarketType, instruments: list[Instrument]
    ) -> tuple[str, dict[str, Any] | None]:
        host = (
            "wss://data-stream.binance.vision/stream"
            if market_type == "SPOT"
            else "wss://fstream.binance.com/market/stream"
        )
        return host + "?streams=" + "/".join(
            item.symbol.lower() + "@ticker" for item in instruments
        ), None

    def parse_tickers(
        self,
        market_type: MarketType,
        message: dict[str, Any],
        instruments: dict[str, Instrument],
        received_at: int,
    ) -> list[Ticker]:
        row = message.get("data", message)
        item = instruments.get(str(row.get("s", row.get("symbol", ""))))
        last = number(row.get("c", row.get("lastPrice")), positive=True)
        if item is None or last is None:
            return []
        return [
            Ticker(
                key=item.key,
                last=last,
                bid=number(row.get("b", row.get("bidPrice")), positive=True),
                ask=number(row.get("a", row.get("askPrice")), positive=True),
                high_24h=number(row.get("h", row.get("highPrice")), positive=True),
                low_24h=number(row.get("l", row.get("lowPrice")), positive=True),
                change_percent_24h=number(row.get("P", row.get("priceChangePercent")))
                or change_percent(last, row.get("o", row.get("openPrice"))),
                volume_base_24h=number(row.get("v", row.get("volume"))),
                volume_quote_24h=number(row.get("q", row.get("quoteVolume"))),
                source_ts=timestamp(row.get("E", row.get("closeTime"))),
                received_at=received_at,
            )
        ]

    async def tickers(self, market_type: MarketType, instruments: list[Instrument]) -> list[Ticker]:
        rows = await get_json(self.client, self.endpoint(market_type) + "/ticker/24hr")
        mapping = {item.symbol: item for item in instruments}
        received = now_ms()
        return [
            tick.model_copy(update={"transport": "REST"})
            for row in rows
            for tick in self.parse_tickers(market_type, row, mapping, received)
        ]

    async def detail(self, instrument: Instrument) -> dict[str, Any]:
        root, symbol = self.endpoint(instrument.market_type), instrument.symbol
        return await snapshot_components(
            self.client,
            {
                "book": (
                    root + "/depth",
                    {"symbol": symbol, "limit": 5},
                    lambda body: book(body, instrument),
                ),
                "candles": (
                    root + "/klines",
                    {"symbol": symbol, "interval": "1m", "limit": 120},
                    candles,
                ),
                "trades": (
                    root + "/trades",
                    {"symbol": symbol, "limit": 20},
                    lambda body: trades(
                        body,
                        instrument,
                        price_key="price",
                        quantity_key="qty",
                        time_key="time",
                        id_key="id",
                    ),
                ),
            },
        )
