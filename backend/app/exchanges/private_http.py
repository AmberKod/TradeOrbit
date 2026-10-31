"""Fixed-host GET-only HMAC transport. Never logs headers, URLs, or exchange errors."""

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlencode

import httpx

from app.exchanges.private_contracts import PrivateReadError


@dataclass(frozen=True)
class ReadRoute:
    path: str
    bucket: str = "main"
    params: tuple[tuple[str, str], ...] = ()


ROUTES: dict[str, dict[str, ReadRoute]] = {
    "binance": {
        "spot_balances": ReadRoute("/api/v3/account", "spot"),
        "usdm_balances": ReadRoute("/fapi/v3/account", "usdm"),
        "usdm_positions": ReadRoute("/fapi/v3/positionRisk", "usdm"),
    },
    "bitget": {
        "spot_balances": ReadRoute("/api/v2/spot/account/assets"),
        "usdt_futures_balances": ReadRoute(
            "/api/v2/mix/account/accounts", params=(("productType", "USDT-FUTURES"),)
        ),
        "usdt_futures_positions": ReadRoute(
            "/api/v2/mix/position/all-position", params=(("productType", "USDT-FUTURES"),)
        ),
        "uta_config": ReadRoute("/api/v3/account/settings"),
        "uta_balances": ReadRoute("/api/v3/account/assets"),
        "uta_positions": ReadRoute(
            "/api/v3/position/current-position", params=(("category", "USDT-FUTURES"),)
        ),
    },
    "okx": {
        "account_config": ReadRoute("/api/v5/account/config"),
        "trading_balances": ReadRoute("/api/v5/account/balance"),
        "funding_balances": ReadRoute("/api/v5/asset/balances"),
        "swap_positions": ReadRoute("/api/v5/account/positions", params=(("instType", "SWAP"),)),
    },
}
TIME_PATHS = {
    "binance": {"spot": "/api/v3/time", "usdm": "/fapi/v1/time"},
    "bitget": {"main": "/api/v2/public/time"},
    "okx": {"main": "/api/v5/public/time"},
}
PROFILE_SCOPES: dict[tuple[str, str], tuple[str, ...]] = {
    ("binance", "STANDARD"): ("spot_balances", "usdm_balances", "usdm_positions"),
    ("bitget", "CLASSIC"): ("spot_balances", "usdt_futures_balances", "usdt_futures_positions"),
    ("bitget", "UTA"): ("uta_config", "uta_balances", "uta_positions"),
    ("okx", "UNIFIED"): (
        "account_config",
        "trading_balances",
        "funding_balances",
        "swap_positions",
    ),
}


def scopes_for(exchange: str, environment: str, mode: str, region: str) -> tuple[str, ...]:
    if region != "GLOBAL":
        raise PrivateReadError("UNSUPPORTED_REGION")
    if environment not in {"LIVE", "DEMO"}:
        raise PrivateReadError("UNSUPPORTED_ENVIRONMENT")
    if exchange == "binance" and environment == "DEMO":
        raise PrivateReadError("BINANCE_DEMO_NOT_SUPPORTED")
    scopes = PROFILE_SCOPES.get((exchange, mode))
    if scopes is None:
        raise PrivateReadError("ACCOUNT_MODE_REQUIRED")
    return scopes


def sign_get(
    exchange: str,
    path: str,
    params: tuple[tuple[str, str], ...],
    credentials: dict[str, str],
    timestamp_ms: int,
    environment: str,
) -> tuple[str, dict[str, str]]:
    """Pure signing. The network boundary separately enforces route/profile allowlists."""
    if exchange == "binance":
        query = urlencode((*params, ("timestamp", str(timestamp_ms)), ("recvWindow", "5000")))
        signature = hmac.new(
            credentials["secret"].encode(), query.encode(), hashlib.sha256
        ).hexdigest()
        return path + "?" + query + "&signature=" + signature, {
            "X-MBX-APIKEY": credentials["api_key"]
        }
    query = urlencode(params)
    request_path = path + ("?" + query if query else "")
    stamp = (
        str(timestamp_ms)
        if exchange == "bitget"
        else datetime.fromtimestamp(timestamp_ms / 1000, UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
    signature = base64.b64encode(
        hmac.new(
            credentials["secret"].encode(), (stamp + "GET" + request_path).encode(), hashlib.sha256
        ).digest()
    ).decode()
    if exchange == "bitget":
        headers = {
            "ACCESS-KEY": credentials["api_key"],
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": stamp,
            "ACCESS-PASSPHRASE": credentials["passphrase"],
        }
        if environment == "DEMO":
            headers["paptrading"] = "1"
    elif exchange == "okx":
        headers = {
            "OK-ACCESS-KEY": credentials["api_key"],
            "OK-ACCESS-SIGN": signature,
            "OK-ACCESS-TIMESTAMP": stamp,
            "OK-ACCESS-PASSPHRASE": credentials["passphrase"],
        }
        if environment == "DEMO":
            headers["x-simulated-trading"] = "1"
    else:
        raise PrivateReadError("UNSUPPORTED_EXCHANGE")
    return request_path, headers


def error_code(exchange: str, status: int, body: Any) -> str | None:
    if status == 418:
        return "IP_BANNED"
    if status == 429:
        return "RATE_LIMITED"
    code = str(body.get("code", "")) if isinstance(body, dict) else ""
    if code in {"-1021", "40004", "40005", "40008", "50102", "50112"}:
        return "CLOCK_SKEW"
    if code in {"-1022", "40009", "50113"}:
        return "SIGNATURE_REJECTED"
    if code in {
        "-2014",
        "-2015",
        "40006",
        "40012",
        "40014",
        "40018",
        "40036",
        "50101",
        "50103",
        "50104",
        "50105",
        "50110",
        "50111",
        "50119",
    }:
        return "AUTH_OR_PERMISSION"
    if code == "40010":
        return "TIMEOUT"
    if code in {"50011", "50040", "429"}:
        return "RATE_LIMITED"
    if status in {401, 403, 451}:
        return "ACCESS_RESTRICTED"
    if status >= 500:
        return "EXCHANGE_UNAVAILABLE"
    if not 200 <= status < 300:
        return "EXCHANGE_REJECTED"
    if exchange == "binance":
        return "EXCHANGE_REJECTED" if code.startswith("-") else None
    if code != ("00000" if exchange == "bitget" else "0"):
        return "EXCHANGE_REJECTED"
    return None


class PrivateHTTP:
    def __init__(
        self,
        client: httpx.AsyncClient,
        exchange: str,
        environment: str,
        mode: str,
        region: str,
        credentials: dict[str, str],
    ):
        self.scopes = scopes_for(exchange, environment, mode, region)
        self.client, self.exchange, self.environment = client, exchange, environment
        self._credentials = credentials
        self._offsets: dict[str, float] = {}
        self.clock_offsets_ms: dict[str, int] = {}
        required = (
            ("api_key", "secret") if exchange == "binance" else ("api_key", "secret", "passphrase")
        )
        if any(
            not credentials.get(k) or any(ord(c) < 32 or ord(c) > 126 for c in credentials[k])
            for k in required
        ):
            raise PrivateReadError("INVALID_CREDENTIAL_FORMAT")

    def host(self, bucket: str) -> str:
        if self.exchange == "binance":
            return {"spot": "https://api.binance.com", "usdm": "https://fapi.binance.com"}[bucket]
        return {"bitget": "https://api.bitget.com", "okx": "https://www.okx.com"}[self.exchange]

    async def _request(self, url: str, headers: dict[str, str] | None = None) -> Any:
        try:
            async with self.client.stream(
                "GET", url, headers=headers, follow_redirects=False
            ) as response:
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > 2_000_000:
                        raise PrivateReadError("INVALID_RESPONSE")
                    chunks.append(chunk)
                try:
                    body = json.loads(b"".join(chunks), parse_float=str)
                except (ValueError, UnicodeDecodeError):
                    body = None
                failure = error_code(self.exchange, response.status_code, body)
                if failure:
                    retry_after = None
                    value = response.headers.get("Retry-After", "")
                    if value:
                        try:
                            seconds = (
                                float(value)
                                if value.isdigit()
                                else parsedate_to_datetime(value).timestamp() - time.time()
                            )
                            retry_after = min(31_536_000, max(1, int(seconds)))
                        except (ValueError, TypeError, OverflowError):
                            pass
                    raise PrivateReadError(failure, retry_after=retry_after)
                if not isinstance(body, (dict, list)):
                    raise PrivateReadError("INVALID_RESPONSE")
                return body
        except httpx.TimeoutException:
            raise PrivateReadError("TIMEOUT") from None
        except httpx.HTTPError:
            raise PrivateReadError("NETWORK_ERROR") from None
        except (UnicodeError, ValueError):
            raise PrivateReadError("INVALID_RESPONSE") from None

    async def _sync_clock(self, bucket: str) -> None:
        start = time.time() * 1000
        began = time.monotonic()
        body = await self._request(self.host(bucket) + TIME_PATHS[self.exchange][bucket])
        elapsed = (time.monotonic() - began) * 1000
        try:
            if self.exchange == "binance":
                server = int(body["serverTime"])
            elif self.exchange == "bitget":
                server = int(body["data"]["serverTime"])
            else:
                server = int(body["data"][0]["ts"])
        except (KeyError, TypeError, IndexError, ValueError):
            raise PrivateReadError("INVALID_RESPONSE") from None
        offset = server - (start + elapsed / 2)
        if elapsed > 5000 or abs(offset) > 300_000:
            raise PrivateReadError("CLOCK_UNRELIABLE")
        self._offsets[bucket] = offset
        self.clock_offsets_ms[bucket] = round(offset)

    async def get(self, scope: str) -> Any:
        if scope not in self.scopes:
            raise PrivateReadError("READ_ROUTE_NOT_ALLOWED")
        route = ROUTES[self.exchange][scope]
        for attempt in range(2):
            if route.bucket not in self._offsets:
                await self._sync_clock(route.bucket)
            timestamp_ms = int(time.time() * 1000 + self._offsets[route.bucket])
            path, headers = sign_get(
                self.exchange,
                route.path,
                route.params,
                self._credentials,
                timestamp_ms,
                self.environment,
            )
            headers["Content-Type"] = "application/json"
            try:
                return await self._request(self.host(route.bucket) + path, headers)
            except PrivateReadError as exc:
                if exc.code != "CLOCK_SKEW" or attempt:
                    raise
                self._offsets.pop(route.bucket, None)
        raise PrivateReadError("CLOCK_SKEW")
