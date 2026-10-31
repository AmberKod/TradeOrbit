"""Three exchange normalizers; persist only allowlisted fields and exact decimal strings."""

import re
from decimal import Decimal, localcontext
from typing import Any

from app.exchanges.private_contracts import (
    Balance,
    Position,
    PrivateReadError,
    ScopeSnapshot,
    decimal_string,
    required_decimal,
)


def identifier(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,80}", value):
        raise PrivateReadError("INVALID_RESPONSE")
    return value


def rows(value: Any) -> list[dict[str, Any]]:
    if (
        not isinstance(value, list)
        or len(value) > 10000
        or any(not isinstance(v, dict) for v in value)
    ):
        raise PrivateReadError("INVALID_RESPONSE")
    return value


def object_value(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PrivateReadError("INVALID_RESPONSE")
    return value


def total(row: dict[str, Any], *keys: str) -> str:
    with localcontext() as context:
        context.prec = 256
        return format(sum((Decimal(required_decimal(row.get(k))) for k in keys), Decimal(0)), "f")


def positions(data: Any, exchange: str, *, uta: bool = False) -> list[Position]:
    result = []
    for row in rows(data):
        raw = required_decimal(
            row.get(
                "positionAmt" if exchange == "binance" else "pos" if exchange == "okx" else "total"
            )
        )
        quantity = Decimal(raw)
        if not quantity:
            continue
        side_key = (
            "positionSide"
            if exchange == "binance"
            else "posSide"
            if exchange == "okx" or uta
            else "holdSide"
        )
        native_side = row.get(side_key)
        if native_side not in {"long", "short", "net", "LONG", "SHORT", "BOTH"}:
            raise PrivateReadError("INVALID_RESPONSE")
        side = (
            "SHORT"
            if str(native_side).upper() == "SHORT"
            or (native_side in {"net", "BOTH"} and quantity < 0)
            else "LONG"
        )
        if exchange == "binance":
            fields = {
                "entry_price": "entryPrice",
                "mark_price": "markPrice",
                "liquidation_price": "liquidationPrice",
                "unrealized_pnl": "unRealizedProfit",
            }
        elif exchange == "okx":
            fields = {
                "entry_price": "avgPx",
                "mark_price": "markPx",
                "liquidation_price": "liqPx",
                "unrealized_pnl": "upl",
                "leverage": "lever",
                "margin_ratio": "mgnRatio",
            }
        else:
            fields = {
                "entry_price": "avgPrice" if uta else "openPriceAvg",
                "mark_price": "markPrice",
                "liquidation_price": "liquidationPrice",
                "unrealized_pnl": "unrealisedPnl" if uta else "unrealizedPL",
                "leverage": "leverage",
            }
        if exchange == "bitget" and not uta:
            fields["margin_ratio"] = "marginRatio"
        values = {key: decimal_string(row.get(native)) for key, native in fields.items()}
        # A zero liquidation price denotes unavailable / no liquidation estimate.
        if (
            values.get("liquidation_price") is not None
            and Decimal(values["liquidation_price"] or "0") <= 0
        ):
            values["liquidation_price"] = None
        margin = row.get("mgnMode" if exchange == "okx" else "marginMode")
        result.append(
            Position(
                instrument=identifier(row.get("instId" if exchange == "okx" else "symbol")),
                side=side,
                quantity=format(abs(quantity), "f"),
                quantity_unit="CONTRACT" if exchange == "okx" else "BASE",
                margin_asset=identifier(
                    row.get(
                        "ccy"
                        if exchange == "okx"
                        else "marginAsset"
                        if exchange == "binance"
                        else "marginCoin"
                    )
                )
                if row.get(
                    "ccy"
                    if exchange == "okx"
                    else "marginAsset"
                    if exchange == "binance"
                    else "marginCoin"
                )
                else None,
                margin_mode=margin if margin in {"cross", "crossed", "isolated"} else None,
                margin_ratio_definition=(
                    "OKX_NATIVE_MAINTENANCE_MARGIN_RATIO"
                    if exchange == "okx"
                    else "BITGET_NATIVE_MAINTENANCE_MARGIN_RATE"
                )
                if values.get("margin_ratio") is not None
                else None,
                **values,
            )
        )
    return result


def normalize(exchange: str, scope: str, body: Any) -> ScopeSnapshot:
    if exchange == "binance":
        if scope == "spot_balances":
            body = object_value(body)
            if body.get("accountType") != "SPOT":
                raise PrivateReadError("ACCOUNT_MODE_MISMATCH")
            return ScopeSnapshot(
                balances=[
                    Balance(
                        asset=identifier(row.get("asset")),
                        equity=total(row, "free", "locked"),
                        available=required_decimal(row.get("free")),
                        wallet_balance=total(row, "free", "locked"),
                        equity_definition="free_plus_locked",
                    )
                    for row in rows(body.get("balances"))
                ],
                metadata={
                    "mode_evidence": "SPOT_ACCOUNT_RESPONSE",
                    "api_key_permissions": "NOT_INSPECTED",
                },
            )
        if scope == "usdm_balances":
            body = object_value(body)
            return ScopeSnapshot(
                balances=[
                    Balance(
                        asset=identifier(row.get("asset")),
                        equity=required_decimal(row.get("marginBalance")),
                        wallet_balance=decimal_string(row.get("walletBalance")),
                        available=decimal_string(row.get("availableBalance")),
                        unrealized_pnl=decimal_string(row.get("unrealizedProfit")),
                        equity_definition="binance_margin_balance",
                    )
                    for row in rows(body.get("assets"))
                ],
                metadata={"coverage": "USD_M_ACCOUNT", "api_key_permissions": "NOT_INSPECTED"},
            )
        return ScopeSnapshot(
            positions=positions(body, exchange), metadata={"coverage": "USD_M_OPEN_POSITIONS"}
        )
    body = object_value(body)
    data = body.get("data")
    if exchange == "okx":
        if scope == "account_config":
            entries = rows(data)
            if len(entries) != 1 or entries[0].get("acctLv") not in {"1", "2", "3", "4"}:
                raise PrivateReadError("ACCOUNT_MODE_MISMATCH")
            row = entries[0]
            return ScopeSnapshot(
                metadata={
                    "account_level": row["acctLv"],
                    "position_mode": row.get("posMode")
                    if row.get("posMode") in {"net_mode", "long_short_mode"}
                    else None,
                    "permissions": sorted(
                        set(str(row.get("perm", "")).split(","))
                        & {"read_only", "trade", "withdraw"}
                    ),
                    "permissions_inspected": isinstance(row.get("perm"), str),
                }
            )
        if scope == "swap_positions":
            return ScopeSnapshot(
                positions=positions(data, exchange),
                metadata={"coverage": "SWAP_ONLY", "quantity_note": "native_contract_count"},
            )
        if scope == "funding_balances":
            return ScopeSnapshot(
                balances=[
                    Balance(
                        asset=identifier(row.get("ccy")),
                        equity=required_decimal(row.get("bal")),
                        wallet_balance=required_decimal(row.get("bal")),
                        available=decimal_string(row.get("availBal")),
                        equity_definition="funding_balance",
                    )
                    for row in rows(data)
                ]
            )
        entries = rows(data)
        if len(entries) != 1:
            raise PrivateReadError("INVALID_RESPONSE")
        row = entries[0]
        return ScopeSnapshot(
            balances=[
                Balance(
                    asset=identifier(item.get("ccy")),
                    equity=required_decimal(item.get("eq")),
                    wallet_balance=decimal_string(item.get("cashBal")),
                    available=decimal_string(item.get("availBal")),
                    unrealized_pnl=decimal_string(item.get("upl")),
                    equity_definition="okx_currency_equity",
                )
                for item in rows(row.get("details"))
            ],
            metadata={
                "native_total_equity_usd": decimal_string(row.get("totalEq")),
                "native_margin_ratio": decimal_string(row.get("mgnRatio")),
                "equity_scope": "UNIFIED_TRADING",
            },
        )
    if scope == "uta_config":
        row = object_value(data)
        # Endpoint compatibility is evidence; no inference of an undocumented mode value.
        if row.get("accountMode") in {"upgrading", "switching"}:
            raise PrivateReadError("ACCOUNT_MODE_TRANSITION")
        if row.get("accountMode") != "unified" or row.get("accountLevel") not in {
            "basic",
            "advanced",
            "isolated",
            "delta",
        }:
            raise PrivateReadError("ACCOUNT_MODE_MISMATCH")
        return ScopeSnapshot(
            metadata={
                "mode_evidence": "UTA_SETTINGS_ENDPOINT",
                "account_mode": "unified",
                "account_level": row["accountLevel"],
                "position_mode": row.get("holdMode")
                if row.get("holdMode") in {"one_way_mode", "hedge_mode"}
                else None,
                "api_key_permissions": "NOT_INSPECTED",
            }
        )
    if scope == "uta_balances":
        row = object_value(data)
        return ScopeSnapshot(
            balances=[
                Balance(
                    asset=identifier(item.get("coin")),
                    equity=required_decimal(item.get("equity")),
                    wallet_balance=decimal_string(item.get("balance")),
                    available=decimal_string(item.get("available")),
                    equity_definition="bitget_uta_coin_equity",
                )
                for item in rows(row.get("assets"))
            ],
            metadata={"equity_scope": "UTA_SHARED", "api_key_permissions": "NOT_INSPECTED"},
        )
    if scope == "uta_positions":
        row = object_value(data)
        if row.get("nextCursor") or row.get("nextPageCursor") or row.get("endId"):
            raise PrivateReadError("INCOMPLETE_RESPONSE")
        return ScopeSnapshot(
            positions=positions(row.get("list"), exchange, uta=True),
            metadata={"coverage": "USDT_FUTURES_ONLY"},
        )
    if scope == "usdt_futures_positions":
        return ScopeSnapshot(
            positions=positions(data, exchange), metadata={"coverage": "USDT_FUTURES_ONLY"}
        )
    if scope == "spot_balances":
        return ScopeSnapshot(
            balances=[
                Balance(
                    asset=identifier(row.get("coin")),
                    equity=total(row, "available", "frozen", "locked"),
                    available=required_decimal(row.get("available")),
                    wallet_balance=total(row, "available", "frozen", "locked"),
                    equity_definition="available_plus_frozen_plus_locked",
                )
                for row in rows(data)
            ],
            metadata={
                "mode_evidence": "CLASSIC_SPOT_ENDPOINT",
                "api_key_permissions": "NOT_INSPECTED",
            },
        )
    return ScopeSnapshot(
        balances=[
            Balance(
                asset=identifier(row.get("marginCoin")),
                equity=required_decimal(row.get("accountEquity")),
                available=decimal_string(row.get("available")),
                unrealized_pnl=decimal_string(row.get("unrealizedPL")),
                equity_definition="bitget_classic_account_equity",
            )
            for row in rows(data)
        ],
        metadata={"coverage": "USDT_FUTURES_ACCOUNT", "api_key_permissions": "NOT_INSPECTED"},
    )
