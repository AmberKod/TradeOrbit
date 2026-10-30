"""Connection configuration is distinct from an externally verified wallet."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.identity import utcnow


class AccountConnection(Base):
    __tablename__ = "account_connections"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    label: Mapped[str] = mapped_column(String(80))
    exchange: Mapped[str] = mapped_column(String(12))
    environment: Mapped[str] = mapped_column(String(8))
    account_mode: Mapped[str] = mapped_column(String(16))
    region_profile: Mapped[str] = mapped_column(String(32), default="GLOBAL")
    status: Mapped[str] = mapped_column(String(20), default="CONFIGURED")
    credential_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class EncryptedCredential(Base):
    __tablename__ = "encrypted_credentials"
    account_id: Mapped[UUID] = mapped_column(ForeignKey("account_connections.id"), primary_key=True)
    ciphertext: Mapped[str] = mapped_column(Text)
    key_version: Mapped[str] = mapped_column(String(32))
    algorithm: Mapped[str] = mapped_column(String(20), default="fernet-v1")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
