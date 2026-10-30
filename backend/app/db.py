"""Async database runtime; migrations are explicit, never automatic at startup."""

from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import Settings


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


@dataclass
class Runtime:
    settings: Settings
    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    redis: Any


def build_runtime(settings: Settings, redis_client: Any = None) -> Runtime:
    engine = create_async_engine(settings.database_url.get_secret_value(), pool_pre_ping=True)
    redis = (
        redis_client
        if redis_client is not None
        else Redis.from_url(
            settings.redis_url.get_secret_value(),
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    )
    return Runtime(settings, engine, async_sessionmaker(engine, expire_on_commit=False), redis)
