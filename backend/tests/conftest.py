"""Isolated DB/Redis fixtures; no exchange or external service is contacted."""

from dataclasses import dataclass
from uuid import UUID

import httpx
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from fakeredis.aioredis import FakeRedis
from sqlalchemy import text

from app.core.config import SCHEMA_REVISION, Settings
from app.core.security import hash_password
from app.db import Base, Runtime, build_runtime
from app.main import create_app
from app.models.identity import Membership, Role, User, Workspace

PASSWORD = "Test-only-password-2026"


@dataclass
class Harness:
    client: httpx.AsyncClient
    runtime: Runtime
    workspace_id: UUID
    other_workspace_id: UUID

    async def login(self, role: str = "admin") -> httpx.Response:
        response = await self.client.post(
            "/api/v1/auth/login", json={"email": f"{role}@example.com", "password": PASSWORD}
        )
        assert response.status_code == 200, response.text
        self.client.headers["X-CSRF-Token"] = response.json()["data"]["csrf_token"]
        return response


@pytest.fixture(scope="session")
def encoded_password() -> str:
    return hash_password(PASSWORD)


@pytest_asyncio.fixture
async def harness(encoded_password):
    settings = Settings(
        app_env="test",
        database_url="sqlite+aiosqlite://",
        redis_url="redis://localhost:1/0",
        session_secret="test-only-signing-secret-32-characters",
        credential_encryption_key=Fernet.generate_key().decode(),
        allowed_origins=["http://testserver"],
        login_attempts_per_minute=100,
    )
    rt = build_runtime(settings, FakeRedis())
    async with rt.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        await conn.execute(
            text("INSERT INTO alembic_version VALUES (:revision)"), {"revision": SCHEMA_REVISION}
        )
    async with rt.sessions() as db:
        workspace, other = Workspace(name="Test workspace"), Workspace(name="Other workspace")
        db.add_all([workspace, other])
        await db.flush()
        for role in Role:
            user = User(email=f"{role.value.lower()}@example.com", password_hash=encoded_password)
            db.add(user)
            await db.flush()
            db.add(Membership(user_id=user.id, workspace_id=workspace.id, role=role.value))
        await db.commit()
        workspace_id, other_id = workspace.id, other.id
    app = create_app(settings, rt)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            trust_env=False,
            base_url="http://testserver",
            headers={"Origin": "http://testserver"},
        ) as client:
            yield Harness(client, rt, workspace_id, other_id)
