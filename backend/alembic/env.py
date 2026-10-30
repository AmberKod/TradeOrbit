"""Async migration runner using the same validated settings as the API."""

import asyncio

from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from app import models
from app.core.config import Settings
from app.db import Base

TARGET_METADATA = Base.metadata
MODEL_REGISTRY = models.__all__


def migrate(connection) -> None:
    context.configure(connection=connection, target_metadata=TARGET_METADATA, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def online() -> None:
    engine = create_async_engine(Settings().database_url.get_secret_value())
    async with engine.connect() as connection:
        await connection.run_sync(migrate)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(
        url=Settings().database_url.get_secret_value(),
        target_metadata=TARGET_METADATA,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(online())
