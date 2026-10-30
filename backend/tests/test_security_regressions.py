"""Regression coverage for request boundaries and changing permissions."""

from datetime import datetime

from sqlalchemy import select

from app.models.identity import Membership


async def test_origin_rejection_has_security_headers(harness):
    result = await harness.client.post(
        "/api/v1/auth/login", json={}, headers={"Origin": "https://untrusted.example"}
    )
    assert result.status_code == 403
    assert result.headers["x-content-type-options"] == "nosniff"
    assert result.headers["cache-control"] == "no-store"
    assert result.headers["x-request-id"] == result.json()["meta"]["request_id"]


async def test_non_ascii_csrf_is_rejected_without_server_error(harness):
    await harness.login()
    harness.client.headers.pop("X-CSRF-Token")
    response = await harness.client.post(
        "/api/v1/auth/logout", headers=[(b"X-CSRF-Token", b"invalid-\xff")]
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_REJECTED"


async def test_revoked_membership_invalidates_existing_session(harness):
    await harness.login()
    async with harness.runtime.sessions() as db:
        membership = await db.scalar(
            select(Membership).where(
                Membership.workspace_id == harness.workspace_id, Membership.role == "ADMIN"
            )
        )
        await db.delete(membership)
        await db.commit()
    assert (await harness.client.get("/api/v1/accounts")).status_code == 401


async def test_timestamps_are_explicit_utc_and_credentials_version_increments(harness):
    await harness.login()
    created = await harness.client.post(
        "/api/v1/accounts",
        json={
            "label": "Regression",
            "exchange": "binance",
            "environment": "DEMO",
            "account_mode": "STANDARD",
        },
    )
    account = created.json()["data"]
    assert datetime.fromisoformat(account["created_at"]).utcoffset().total_seconds() == 0
    for expected in (1, 2):
        response = await harness.client.post(
            "/api/v1/accounts/" + account["id"] + "/credentials",
            json={"api_key": "fixture-only", "secret": "fixture-only"},
        )
        assert response.status_code == 200
        assert response.json()["data"]["credential_version"] == expected
