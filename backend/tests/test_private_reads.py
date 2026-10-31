"""Offline signing, private scope contracts and authenticated persistence boundaries."""

import base64
import hashlib
import hmac
import logging
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest
from sqlalchemy import delete, select

from app.account_reads import render_state
from app.exchanges.private_adapter import normalize
from app.exchanges.private_contracts import PrivateReadError, decimal_string
from app.exchanges.private_http import PrivateHTTP, sign_get
from app.models.account_state import AccountReadState
from app.models.accounts import AccountConnection
from app.models.identity import AuditLog

CREDS = {
    "api_key": "fixture-public-only",
    "secret": "fixture-secret-only",
    "passphrase": "fixture-passphrase-only",
}


def response_body(exchange, path):
    now = str(int(time.time() * 1000))
    if path.endswith("/time"):
        if exchange == "binance":
            return {"serverTime": int(now)}
        return {
            "code": "00000" if exchange == "bitget" else "0",
            "data": {"serverTime": now} if exchange == "bitget" else [{"ts": now}],
        }
    if exchange == "binance":
        if path == "/api/v3/account":
            return {
                "accountType": "SPOT",
                "balances": [{"asset": "USDT", "free": "1000.123456789123456789", "locked": "2"}],
            }
        if path == "/fapi/v3/account":
            return {
                "assets": [
                    {
                        "asset": "USDT",
                        "marginBalance": "110",
                        "walletBalance": "100",
                        "availableBalance": "80",
                        "unrealizedProfit": "10",
                    }
                ]
            }
        return [
            {
                "symbol": "BTCUSDT",
                "positionAmt": "-0.5",
                "positionSide": "BOTH",
                "entryPrice": "100",
                "markPrice": "90",
                "liquidationPrice": "0",
                "unRealizedProfit": "5",
                "marginAsset": "USDT",
            }
        ]
    if exchange == "okx":
        data = (
            [{"acctLv": "2", "posMode": "net_mode", "perm": "read_only,trade"}]
            if path.endswith("/config")
            else [{"ccy": "USDT", "bal": "20", "availBal": "18"}]
            if path == "/api/v5/asset/balances"
            else [
                {
                    "totalEq": "1200.34",
                    "details": [
                        {
                            "ccy": "USDT",
                            "eq": "1200.34",
                            "cashBal": "1000",
                            "availBal": "900",
                            "upl": "200.34",
                        }
                    ],
                }
            ]
            if path.endswith("/balance")
            else [
                {
                    "instId": "BTC-USDT-SWAP",
                    "pos": "-2",
                    "posSide": "net",
                    "ccy": "USDT",
                    "avgPx": "50000",
                    "markPx": "49000",
                    "liqPx": "70000",
                    "upl": "20",
                    "lever": "5",
                    "mgnRatio": "12.5",
                    "mgnMode": "cross",
                }
            ]
        )
        return {"code": "0", "data": data}
    if path.endswith("/settings"):
        data = {"accountMode": "unified", "accountLevel": "advanced", "holdMode": "one_way_mode"}
    elif path == "/api/v3/account/assets":
        data = {
            "assets": [
                {"coin": "USDT", "equity": "105", "balance": "100", "available": "80", "debt": "0"}
            ]
        }
    elif path == "/api/v3/position/current-position":
        data = {
            "list": [
                {
                    "category": "USDT-FUTURES",
                    "symbol": "BTCUSDT",
                    "marginCoin": "USDT",
                    "posSide": "short",
                    "total": "0.02",
                    "avgPrice": "100",
                    "markPrice": "90",
                    "liquidationPrice": "0",
                    "unrealisedPnl": "0.2",
                    "leverage": "10",
                    "marginMode": "crossed",
                }
            ]
        }
    elif path == "/api/v2/spot/account/assets":
        data = [{"coin": "USDT", "available": "1", "frozen": "2", "locked": "3"}]
    elif path.endswith("/accounts"):
        data = [
            {"marginCoin": "USDT", "accountEquity": "105", "available": "80", "unrealizedPL": "5"}
        ]
    else:
        data = [
            {
                "symbol": "BTCUSDT",
                "marginCoin": "USDT",
                "holdSide": "short",
                "total": "0.02",
                "openPriceAvg": "100",
                "markPrice": "90",
                "liquidationPrice": "0",
                "unrealizedPL": "0.2",
                "leverage": "10",
                "marginMode": "crossed",
            }
        ]
    return {"code": "00000", "data": data}


async def create_connection(harness, exchange="binance", mode="STANDARD", environment="LIVE"):
    await harness.login()
    response = await harness.client.post(
        "/api/v1/accounts",
        json={
            "label": "Offline fixture",
            "exchange": exchange,
            "environment": environment,
            "account_mode": mode,
            "region_profile": "GLOBAL",
        },
    )
    assert response.status_code == 201
    account_id = response.json()["data"]["id"]
    response = await harness.client.post(f"/api/v1/accounts/{account_id}/credentials", json=CREDS)
    assert response.status_code == 200
    return account_id


def service(harness):
    return harness.client._transport.app.state.private_read_service


@pytest.mark.parametrize("exchange", ["binance", "bitget", "okx"])
def test_exact_hmac_signatures(exchange):
    path = (
        "/api/v3/account"
        if exchange == "binance"
        else "/api/v3/position/current-position"
        if exchange == "bitget"
        else "/api/v5/account/positions"
    )
    params = (("category", "USDT-FUTURES"), ("symbol", "A/B"))
    url, headers = sign_get(exchange, path, params, CREDS, 1735689600123, "DEMO")
    if exchange == "binance":
        payload, signature = url.split("?", 1)[1].split("&signature=")
        assert (
            payload == "category=USDT-FUTURES&symbol=A%2FB&timestamp=1735689600123&recvWindow=5000"
        )
        assert (
            signature
            == hmac.new(b"fixture-secret-only", payload.encode(), hashlib.sha256).hexdigest()
        )
    else:
        stamp = "1735689600123" if exchange == "bitget" else "2025-01-01T00:00:00.123Z"
        payload = (stamp + "GET" + path + "?category=USDT-FUTURES&symbol=A%2FB").encode()
        expected = base64.b64encode(
            hmac.new(b"fixture-secret-only", payload, hashlib.sha256).digest()
        ).decode()
        assert headers["ACCESS-SIGN" if exchange == "bitget" else "OK-ACCESS-SIGN"] == expected
        assert headers["paptrading" if exchange == "bitget" else "x-simulated-trading"] == "1"


@pytest.mark.parametrize(
    "exchange,mode,environment",
    [
        ("binance", "STANDARD", "LIVE"),
        ("bitget", "CLASSIC", "LIVE"),
        ("bitget", "CLASSIC", "DEMO"),
        ("bitget", "UTA", "LIVE"),
        ("bitget", "UTA", "DEMO"),
        ("okx", "UNIFIED", "LIVE"),
        ("okx", "UNIFIED", "DEMO"),
    ],
)
async def test_complete_offline_read_and_persistence(harness, caplog, exchange, mode, environment):
    account_id = await create_connection(harness, exchange, mode, environment)
    requests = []

    def handler(request):
        requests.append(request)
        assert request.method == "GET"
        assert request.url.host in {
            "api.binance.com",
            "fapi.binance.com",
            "api.bitget.com",
            "www.okx.com",
        }
        if not request.url.path.endswith("/time") and exchange != "binance":
            key = "paptrading" if exchange == "bitget" else "x-simulated-trading"
            assert (request.headers.get(key) == "1") == (environment == "DEMO")
        return httpx.Response(200, json=response_body(exchange, request.url.path))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False) as client:
        service(harness).client = client
        with caplog.at_level(logging.INFO):
            response = await harness.client.post(f"/api/v1/accounts/{account_id}/verify")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["state"] == "VERIFIED" and data["trading_enabled"] is False
    assert all(item["freshness"] == "FRESH" for item in data["scopes"].values())
    position_rows = [p for s in data["scopes"].values() for p in s["data"]["positions"]]
    assert len(position_rows) == 1 and position_rows[0]["side"] == "SHORT"
    assert position_rows[0]["quantity_unit"] == ("CONTRACT" if exchange == "okx" else "BASE")
    if exchange == "binance":
        assert (
            data["scopes"]["spot_balances"]["data"]["balances"][0]["equity"]
            == "1002.123456789123456789"
        )
    before = len(requests)
    stored = await harness.client.get(f"/api/v1/accounts/{account_id}/snapshot")
    assert stored.json()["data"]["state"] == "VERIFIED" and len(requests) == before
    caps = (await harness.client.get(f"/api/v1/accounts/{account_id}/capabilities")).json()["data"]
    assert all("data" not in s for s in caps["scopes"].values())
    listed = (await harness.client.get("/api/v1/accounts")).json()["data"]
    assert listed[0]["capability_state"] == "VERIFIED"
    logs = (await harness.client.get("/api/v1/audit-logs")).text + caplog.text
    assert all(secret not in logs + response.text + stored.text for secret in CREDS.values())
    assert "signature=" not in logs and "1002.123456789123456789" not in logs
    assert (await harness.client.post(f"/api/v1/accounts/{account_id}/verify")).status_code == 429


async def test_partial_failure_retains_successful_old_data_as_stale(harness):
    account_id = await create_connection(harness)
    fail = False

    def handler(request):
        if fail and not request.url.path.endswith("/time"):
            return httpx.Response(503, json={"msg": CREDS["secret"]})
        if request.url.path == "/fapi/v3/account":
            return httpx.Response(403, json={"code": -2015, "msg": CREDS["secret"]})
        return httpx.Response(200, json=response_body("binance", request.url.path))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False) as client:
        service(harness).client = client
        first = (await harness.client.post(f"/api/v1/accounts/{account_id}/verify")).json()["data"]
        assert first["state"] == "PARTIAL"
        assert first["scopes"]["usdm_balances"]["data"] is None
        await harness.runtime.redis.delete(f"private:cooldown:{harness.workspace_id}:{account_id}")
        fail = True
        response = await harness.client.post(f"/api/v1/accounts/{account_id}/verify")
    second = response.json()["data"]
    assert second["state"] == "FAILED"
    old = second["scopes"]["spot_balances"]
    assert old["freshness"] == "STALE" and old["data"] == first["scopes"]["spot_balances"]["data"]
    assert CREDS["secret"] not in response.text


@pytest.mark.parametrize("change", ["rotate", "archive"])
async def test_inflight_result_cannot_restore_rotated_or_archived_account(harness, change):
    account_id = await create_connection(harness)
    changed = False

    async def handler(request):
        nonlocal changed
        if not request.url.path.endswith("/time") and not changed:
            changed = True
            async with harness.runtime.sessions() as db:
                account = await db.get(AccountConnection, UUID(account_id))
                if change == "rotate":
                    account.credential_version += 1
                else:
                    account.status = "ARCHIVED"
                await db.execute(
                    delete(AccountReadState).where(AccountReadState.account_id == account.id)
                )
                await db.commit()
        return httpx.Response(200, json=response_body("binance", request.url.path))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False) as client:
        service(harness).client = client
        response = await harness.client.post(f"/api/v1/accounts/{account_id}/verify")
    assert response.status_code == 409 and response.json()["error"]["code"] == "ACCOUNT_CHANGED"
    async with harness.runtime.sessions() as db:
        assert await db.get(AccountReadState, UUID(account_id)) is None


@pytest.mark.parametrize("role", ["viewer", "trader"])
async def test_private_reads_require_admin_to_contact_exchange(harness, role):
    account_id = await create_connection(harness)
    await harness.login(role)
    assert (await harness.client.post(f"/api/v1/accounts/{account_id}/verify")).status_code == 403
    assert (await harness.client.get(f"/api/v1/accounts/{account_id}/snapshot")).status_code == 200


async def test_foreign_workspace_and_csrf_are_rejected(harness):
    account_id = await create_connection(harness)
    harness.client.headers.pop("X-CSRF-Token")
    assert (await harness.client.post(f"/api/v1/accounts/{account_id}/verify")).status_code == 403
    await harness.login()
    async with harness.runtime.sessions() as db:
        account = await db.get(AccountConnection, UUID(account_id))
        account.workspace_id = harness.other_workspace_id
        await db.commit()
    for path in ("snapshot", "capabilities"):
        assert (
            await harness.client.get(f"/api/v1/accounts/{account_id}/{path}")
        ).status_code == 404
    assert (await harness.client.post(f"/api/v1/accounts/{account_id}/verify")).status_code == 404


async def test_successful_credential_rotation_invalidates_saved_snapshots(harness):
    account_id = await create_connection(harness)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json=response_body("binance", r.url.path))
        ),
        trust_env=False,
    ) as client:
        service(harness).client = client
        assert (await harness.client.post(f"/api/v1/accounts/{account_id}/verify")).json()["data"][
            "state"
        ] == "VERIFIED"
    assert (
        await harness.client.post(f"/api/v1/accounts/{account_id}/credentials", json=CREDS)
    ).status_code == 200
    data = (await harness.client.get(f"/api/v1/accounts/{account_id}/snapshot")).json()["data"]
    assert (
        data["state"] == "NOT_VERIFIED" and data["scopes"] == {} and data["credential_version"] == 2
    )


@pytest.mark.parametrize(
    "environment,mode,region,code",
    [
        ("DEMO", "STANDARD", "GLOBAL", "BINANCE_DEMO_NOT_SUPPORTED"),
        ("LIVE", "UNKNOWN", "GLOBAL", "ACCOUNT_MODE_REQUIRED"),
        ("LIVE", "STANDARD", "EU", "UNSUPPORTED_REGION"),
    ],
)
async def test_unsupported_profiles_fail_before_network(environment, mode, region, code):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: pytest.fail("must not contact a host"))
    ) as client:
        with pytest.raises(PrivateReadError, match=code):
            PrivateHTTP(client, "binance", environment, mode, region, CREDS.copy())


async def test_allowlist_clock_retry_and_rate_limit_stop(harness):
    account_id = await create_connection(harness)
    signed = 0
    clock = 0

    def handler(request):
        nonlocal signed, clock
        if request.url.path.endswith("/time"):
            clock += 1
            return httpx.Response(200, json=response_body("binance", request.url.path))
        signed += 1
        if signed == 1:
            return httpx.Response(400, json={"code": -1021})
        return httpx.Response(429, json={"code": -1003}, headers={"Retry-After": "259200"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False) as client:
        transport = PrivateHTTP(client, "binance", "LIVE", "STANDARD", "GLOBAL", CREDS.copy())
        with pytest.raises(PrivateReadError, match="READ_ROUTE_NOT_ALLOWED"):
            await transport.get("/api/v3/order")
        assert signed == clock == 0
        service(harness).client = client
        response = await harness.client.post(f"/api/v1/accounts/{account_id}/verify")
    data = response.json()["data"]
    assert signed == 2 and clock == 2
    assert await harness.runtime.redis.ttl("private:blocked:binance") >= 259190
    assert all(s["error_code"] == "RATE_LIMITED" for s in data["scopes"].values())
    await harness.runtime.redis.delete(f"private:cooldown:{harness.workspace_id}:{account_id}")
    assert (await harness.client.post(f"/api/v1/accounts/{account_id}/verify")).status_code == 429


@pytest.mark.parametrize(
    "value",
    ["NaN", "Infinity", "-Infinity", "1e10000000", "1e-10000000", "0e-10000000", True, "wrong"],
)
def test_bad_decimal_cannot_be_saved_or_expand_memory(value):
    with pytest.raises(PrivateReadError):
        decimal_string(value, required=True)


def test_empty_response_is_not_a_zero_balance():
    with pytest.raises(PrivateReadError):
        normalize("okx", "trading_balances", {"data": []})
    with pytest.raises(PrivateReadError):
        normalize("bitget", "uta_positions", {"data": {"list": [], "nextCursor": "another-page"}})


async def test_age_is_visible_without_contacting_exchange(harness):
    account_id = await create_connection(harness)
    async with harness.runtime.sessions() as db:
        account = await db.get(AccountConnection, UUID(account_id))
        state = AccountReadState(
            account_id=account.id,
            credential_version=1,
            state="VERIFIED",
            scopes={
                "spot_balances": {
                    "status": "OK",
                    "error_code": None,
                    "observed_at": (datetime.now(UTC) - timedelta(minutes=6)).isoformat(),
                    "data": {"balances": [], "positions": [], "metadata": {}},
                }
            },
            checked_at=datetime.now(UTC),
        )
        db.add(state)
        await db.commit()
        assert render_state(account, state)["scopes"]["spot_balances"]["freshness"] == "STALE"
    response = await harness.client.get(f"/api/v1/accounts/{account_id}/snapshot")
    assert response.json()["data"]["scopes"]["spot_balances"]["freshness"] == "STALE"
    async with harness.runtime.sessions() as db:
        assert not (
            await db.scalars(select(AuditLog).where(AuditLog.action == "account.read_sync"))
        ).all()


@pytest.mark.parametrize(
    "mode,code",
    [
        ("hybrid", "ACCOUNT_MODE_MISMATCH"),
        ("upgrading", "ACCOUNT_MODE_TRANSITION"),
        ("switching", "ACCOUNT_MODE_TRANSITION"),
    ],
)
async def test_uta_mode_mismatch_gates_other_reads(harness, mode, code):
    account_id = await create_connection(harness, "bitget", "UTA")
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/settings"):
            return httpx.Response(
                200,
                json={"code": "00000", "data": {"accountMode": mode, "accountLevel": "advanced"}},
            )
        return httpx.Response(200, json=response_body("bitget", request.url.path))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False) as client:
        service(harness).client = client
        data = (await harness.client.post(f"/api/v1/accounts/{account_id}/verify")).json()["data"]
    assert data["state"] == "FAILED"
    assert len(paths) == 2 and paths[-1] == "/api/v3/account/settings"
    assert all(s["error_code"] == code and s["data"] is None for s in data["scopes"].values())


async def test_stale_sync_cannot_overwrite_a_newer_committed_snapshot(harness):
    account_id = await create_connection(harness)
    changed = False

    async def handler(request):
        nonlocal changed
        if not request.url.path.endswith("/time") and not changed:
            changed = True
            async with harness.runtime.sessions() as db:
                db.add(
                    AccountReadState(
                        account_id=UUID(account_id),
                        credential_version=1,
                        state="VERIFIED",
                        scopes={},
                        checked_at=datetime.now(UTC) + timedelta(seconds=2),
                    )
                )
                await db.commit()
        return httpx.Response(200, json=response_body("binance", request.url.path))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False) as client:
        service(harness).client = client
        response = await harness.client.post(f"/api/v1/accounts/{account_id}/verify")
    assert response.status_code == 409 and response.json()["error"]["code"] == "STALE_SYNC_RESULT"
    async with harness.runtime.sessions() as db:
        assert (await db.get(AccountReadState, UUID(account_id))).scopes == {}


async def test_private_transport_does_not_follow_redirects():
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/time"):
            return httpx.Response(200, json=response_body("binance", request.url.path))
        return httpx.Response(302, headers={"Location": "https://untrusted.example/collect"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=True, trust_env=False
    ) as client:
        transport = PrivateHTTP(client, "binance", "LIVE", "STANDARD", "GLOBAL", CREDS.copy())
        with pytest.raises(PrivateReadError, match="EXCHANGE_REJECTED"):
            await transport.get("spot_balances")
    assert paths == ["/api/v3/time", "/api/v3/account"]


def test_very_precise_spot_totals_remain_exact():
    value = normalize(
        "binance",
        "spot_balances",
        {
            "accountType": "SPOT",
            "balances": [
                {
                    "asset": "USDT",
                    "free": "1000000000000000000000000.123456789123456789",
                    "locked": "0.000000000000000001",
                }
            ],
        },
    )
    assert value.balances[0].equity == "1000000000000000000000000.123456789123456790"
