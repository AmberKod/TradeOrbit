"""Latest read-only state. Credentials and raw exchange bodies never enter this table."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.identity import utcnow


class AccountReadState(Base):
    __tablename__ = "account_read_states"

    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("account_connections.id", ondelete="CASCADE"), primary_key=True
    )
    credential_version: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(20))
    scopes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
