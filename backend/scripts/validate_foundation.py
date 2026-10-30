"""Opt-in real PostgreSQL/Redis validation using a newly created disposable database."""

import argparse
import asyncio
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import asyncpg
import httpx
from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.main import create_app

ROOT = Path(__file__).resolve().parents[2]


def command(arguments: list[str], env: dict[str, str], password: str | None = None) -> None:
    subprocess.run(
        [sys.executable, *arguments],
        cwd=ROOT / "backend",
        env=env,
        input=password + chr(10) if password else None,
        text=True,
        check=True,
    )


async def workflow(settings: Settings, env: dict[str, str], password: str) -> None:
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://validation",
            headers={"Origin": "http://validation"},
        ) as client:
            assert (await client.get("/api/v1/health/ready")).status_code == 200
            login = await client.post(
                "/api/v1/auth/login", json={"email": "validation@example.com", "password": password}
            )
            assert login.status_code == 200
            session = login.json()["data"]
            client.headers["X-CSRF-Token"] = session["csrf_token"]
            for exchange, mode in [("binance", "STANDARD"), ("bitget", "UTA"), ("okx", "UNIFIED")]:
                result = await client.post(
                    "/api/v1/accounts",
                    json={
                        "label": "Validation " + exchange,
                        "exchange": exchange,
                        "environment": "DEMO",
                        "account_mode": mode,
                    },
                )
                assert result.status_code == 201
                account_id = result.json()["data"]["id"]
                payload = {
                    "api_key": "fixture-only-key",
                    "secret": "fixture-only-secret",
                    "passphrase": "fixture-only-passphrase",
                }
                responses = await asyncio.gather(
                    *(
                        client.post("/api/v1/accounts/" + account_id + "/credentials", json=payload)
                        for _ in range(2)
                    )
                )
                assert all(response.status_code == 200 for response in responses)
                assert sorted(
                    response.json()["data"]["credential_version"] for response in responses
                ) == [1, 2]
                caps = (
                    await client.get("/api/v1/accounts/" + account_id + "/capabilities")
                ).json()["data"]
                assert caps["state"] == "NOT_VERIFIED" and caps["trading_enabled"] is False
                assert (await client.delete("/api/v1/accounts/" + account_id)).status_code == 200
            assert (await client.get("/api/v1/accounts")).json()["data"] == []
            audit = await client.get("/api/v1/audit-logs")
            assert audit.status_code == 200 and "fixture-only-secret" not in audit.text
            command(
                [
                    "-m",
                    "app.cli",
                    "create-user",
                    "--email",
                    "viewer@example.com",
                    "--workspace-id",
                    session["workspace"]["id"],
                    "--role",
                    "VIEWER",
                    "--password-stdin",
                ],
                env,
                password,
            )
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://validation",
                headers={"Origin": "http://validation"},
            ) as viewer:
                viewer_login = await viewer.post(
                    "/api/v1/auth/login", json={"email": "viewer@example.com", "password": password}
                )
                assert viewer_login.status_code == 200
                viewer.headers["X-CSRF-Token"] = viewer_login.json()["data"]["csrf_token"]
                assert (await viewer.get("/api/v1/accounts")).status_code == 200
                assert (await viewer.delete("/api/v1/accounts/" + account_id)).status_code == 403
                assert (await viewer.get("/api/v1/audit-logs")).status_code == 403
                assert (await viewer.post("/api/v1/auth/logout")).status_code == 200
            assert (await client.post("/api/v1/auth/logout")).status_code == 200
            assert (await client.get("/api/v1/auth/session")).status_code == 401
            assert (await client.post("/api/v1/orders", json={})).status_code == 404
    print(
        "PASS real DB/Redis API, bootstrap, roles, encryption flow and concurrent credential versions",
        flush=True,
    )


async def main(restart: bool) -> None:
    initial = Settings()
    source_url = make_url(initial.database_url.get_secret_value())
    if (
        source_url.host not in {"localhost", "127.0.0.1"}
        or source_url.drivername != "postgresql+asyncpg"
    ):
        raise SystemExit(
            "Validation accepts only local PostgreSQL; it never touches a remote database."
        )
    name = "tradeorbit_e01_validation_" + uuid4().hex[:8]
    assert re.fullmatch(r"tradeorbit_e01_validation_[a-f0-9]{8}", name)
    admin_dsn = source_url.set(drivername="postgresql").render_as_string(hide_password=False)
    target = source_url.set(database=name).render_as_string(hide_password=False)
    target_dsn = source_url.set(drivername="postgresql", database=name).render_as_string(
        hide_password=False
    )
    connection = await asyncpg.connect(admin_dsn, timeout=5)
    created = False
    try:
        await connection.execute("CREATE DATABASE " + name)
        created = True
        await connection.close()
        env = dict(
            os.environ,
            TRADEORBIT_APP_ENV="test",
            TRADEORBIT_DATABASE_URL=target,
            TRADEORBIT_ALLOWED_ORIGINS='["http://validation"]',
        )
        command(["-m", "alembic", "upgrade", "head"], env)
        command(["-m", "alembic", "check"], env)
        command(["-m", "alembic", "downgrade", "base"], env)
        command(["-m", "alembic", "upgrade", "head"], env)
        password = secrets.token_urlsafe(24)
        command(
            [
                "-m",
                "app.cli",
                "bootstrap-admin",
                "--email",
                "validation@example.com",
                "--password-stdin",
            ],
            env,
            password,
        )
        settings = Settings(
            app_env="test", database_url=target, allowed_origins=["http://validation"]
        )
        await workflow(settings, env, password)
        if restart:
            subprocess.run(["docker", "compose", "restart", "db", "cache"], cwd=ROOT, check=True)
            for attempt in range(45):
                try:
                    check = await asyncpg.connect(target_dsn, timeout=2)
                    assert await check.fetchval("SELECT count(*) FROM account_connections") == 3
                    assert await check.fetchval("SELECT count(*) FROM users") == 2
                    await check.close()
                    break
                except (OSError, asyncpg.PostgresError):
                    if attempt == 44:
                        raise
                    await asyncio.sleep(1)
            print("PASS restart persistence for TradeOrbit db/cache", flush=True)
        print(
            "PASS migrations upgrade/check/downgrade/upgrade; no orders or exchange traffic",
            flush=True,
        )
    finally:
        if not connection.is_closed():
            await connection.close()
        if created:
            cleanup = await asyncpg.connect(admin_dsn, timeout=5)
            try:
                await cleanup.execute("DROP DATABASE " + name + " WITH (FORCE)")
            finally:
                await cleanup.close()
            print(
                "Disposable validation database removed; application database unchanged.",
                flush=True,
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--restart-data-services",
        action="store_true",
        help="Restart ONLY the local TradeOrbit db/cache services to validate named-volume persistence",
    )
    asyncio.run(main(parser.parse_args().restart_data_services))
