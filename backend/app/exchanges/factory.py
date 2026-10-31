"""Only allow explicitly supported, fixed-host public adapters."""

import httpx

from app.exchanges.base import Exchange, PublicAdapter
from app.exchanges.binance_adapter import BinanceAdapter
from app.exchanges.bitget_adapter import BitgetAdapter
from app.exchanges.okx_adapter import OkxAdapter


def adapter(exchange: Exchange, client: httpx.AsyncClient) -> PublicAdapter:
    factories: dict[Exchange, type[PublicAdapter]] = {
        "binance": BinanceAdapter,
        "bitget": BitgetAdapter,
        "okx": OkxAdapter,
    }
    return factories[exchange](client)
