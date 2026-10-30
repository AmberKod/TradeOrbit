"""Authorization and account workflow integration tests against ASGI + database."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import select

from app.core.security import CredentialCipher
from app.models.accounts import AccountConnection, EncryptedCredential
from app.models.identity import AuditLog, Session

ACCOUNT = {
    "label": "Fixture account",
    "exchange": "binance",
    "environment": "DEMO",
    "account_mode": "STANDARD",
    "region_profile": "GLOBAL",
}


async def test_liveness_readiness_and_no_trading_route(harness):
    live = await harness.client.get("/api/v1/health/live")
    assert live.status_code == 200 and live.json()["data"]["trading_enabled"] is False
    assert (await harness.client.get("/api/v1/health/ready")).status_code == 200
    assert (await harness.client.post("/api/v1/orders", json={})).status_code == 404
    assert (await harness.client.get("/api/v1/accounts")).status_code == 401


async def test_cookie_login_csrf_and_logout_revoke_session(harness):
    login = await harness.login()
    assert "httponly" in login.headers["set-cookie"].lower()
    assert login.headers["cache-control"] == "no-store"
    saved = harness.client.cookies.get("tradeorbit_session")
    harness.client.headers.pop("X-CSRF-Token")
    assert (await harness.client.post("/api/v1/accounts", json=ACCOUNT)).status_code == 403
    session = (await harness.client.get("/api/v1/auth/session")).json()["data"]
    harness.client.headers["X-CSRF-Token"] = session["csrf_token"]
    assert (await harness.client.post("/api/v1/auth/logout")).status_code == 200
    harness.client.cookies.set("tradeorbit_session", saved)
    assert (await harness.client.get("/api/v1/auth/session")).status_code == 401


async def test_cross_origin_login_is_rejected(harness):
    response = await harness.client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "fixture"},
        headers={"Origin": "https://untrusted.example"},
    )
    assert response.status_code == 403 and response.json()["error"]["code"] == "ORIGIN_REJECTED"


@pytest.mark.parametrize("role", ["viewer", "trader"])
async def test_non_admin_cannot_change_configuration(harness, role):
    await harness.login(role)
    assert (await harness.client.get("/api/v1/accounts")).status_code == 200
    assert (await harness.client.post("/api/v1/accounts", json=ACCOUNT)).status_code == 403
    assert (await harness.client.get("/api/v1/audit-logs")).status_code == 403


async def test_account_workspace_isolation(harness):
    async with harness.runtime.sessions() as db:
        account = AccountConnection(workspace_id=harness.other_workspace_id, **ACCOUNT)
        db.add(account)
        await db.commit()
        foreign_id = account.id
    await harness.login()
    assert (await harness.client.get("/api/v1/accounts")).json()["data"] == []
    assert (await harness.client.get(f"/api/v1/accounts/{foreign_id}")).status_code == 404
    assert (
        await harness.client.patch(f"/api/v1/accounts/{foreign_id}", json={"label": "tamper"})
    ).status_code == 404


async def test_credentials_are_encrypted_and_never_returned(harness):
    await harness.login()
    created = await harness.client.post("/api/v1/accounts", json=ACCOUNT)
    assert created.status_code == 201
    account_id = created.json()["data"]["id"]
    payload = {"api_key": "fixture-public-key", "secret": "fixture-private-secret"}
    saved = await harness.client.post(f"/api/v1/accounts/{account_id}/credentials", json=payload)
    assert saved.status_code == 200 and saved.json()["data"]["credential_version"] == 1
    exposed = json.dumps((await harness.client.get(f"/api/v1/accounts/{account_id}")).json())
    logs = json.dumps((await harness.client.get("/api/v1/audit-logs")).json())
    assert all(value not in exposed + logs + saved.text for value in payload.values())
    async with harness.runtime.sessions() as db:
        record = await db.scalar(select(EncryptedCredential))
        assert record is not None
        settings = harness.runtime.settings
        decrypted = CredentialCipher(
            settings.credential_encryption_key.get_secret_value(), settings.encryption_key_version
        ).decrypt(record.ciphertext, record.key_version)
        assert decrypted == payload
        assert payload["secret"] not in record.ciphertext
        actions = (await db.scalars(select(AuditLog.action))).all()
        assert "account.credentials_saved" in actions
    updated = await harness.client.patch(
        f"/api/v1/accounts/{account_id}", json={"label": "Updated label"}
    )
    assert updated.json()["data"]["label"] == "Updated label"
    caps = (await harness.client.get(f"/api/v1/accounts/{account_id}/capabilities")).json()["data"]
    assert caps["state"] == "NOT_VERIFIED" and not caps["trading_enabled"]
    assert (await harness.client.delete(f"/api/v1/accounts/{account_id}")).status_code == 200
    assert (await harness.client.get("/api/v1/accounts")).json()["data"] == []
    assert (await harness.client.get(f"/api/v1/accounts/{account_id}")).status_code == 404


@pytest.mark.parametrize("exchange,mode", [("bitget", "UTA"), ("okx", "UNIFIED")])
async def test_passphrase_is_required_where_appropriate(harness, exchange, mode):
    await harness.login()
    response = await harness.client.post(
        "/api/v1/accounts", json={**ACCOUNT, "exchange": exchange, "account_mode": mode}
    )
    account_id = response.json()["data"]["id"]
    response = await harness.client.post(
        f"/api/v1/accounts/{account_id}/credentials", json={"api_key": "fake", "secret": "fake"}
    )
    assert response.status_code == 422 and response.json()["error"]["code"] == "PASSPHRASE_REQUIRED"


async def test_invalid_mode_and_validation_do_not_leak_secrets(harness):
    await harness.login()
    assert (
        await harness.client.post("/api/v1/accounts", json={**ACCOUNT, "account_mode": "UTA"})
    ).status_code == 422
    response = await harness.client.post(
        "/api/v1/auth/login",
        json={"email": "not-an-email", "password": {"secret": "fixture-should-not-leak"}},
    )
    assert response.status_code == 422 and "fixture-should-not-leak" not in response.text


async def test_expired_session_is_rejected(harness):
    await harness.login()
    async with harness.runtime.sessions() as db:
        session = await db.scalar(select(Session))
        session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()
    assert (await harness.client.get("/api/v1/auth/session")).status_code == 401


async def test_readiness_fails_if_cache_is_down(harness, monkeypatch):
    async def unavailable():
        raise RedisConnectionError("fixture failure")

    monkeypatch.setattr(harness.runtime.redis, "ping", unavailable)
    response = await harness.client.get("/api/v1/health/ready")
    assert (
        response.status_code == 503 and response.json()["data"]["checks"]["redis"] == "UNAVAILABLE"
    )


async def test_login_throttling_fails_closed(harness):
    harness.runtime.settings.login_attempts_per_minute = 2
    statuses = [
        (
            await harness.client.post(
                "/api/v1/auth/login", json={"email": "admin@example.com", "password": "wrong"}
            )
        ).status_code
        for _ in range(6)
    ]
    assert 429 in statuses and 200 not in statuses
