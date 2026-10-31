"""Workspace watchlists refer to publicly verified instrument keys."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.identity import utcnow


class WatchlistEntry(Base):
    __tablename__ = "market_watchlist"
    __table_args__ = (UniqueConstraint("workspace_id", "instrument_key"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    instrument_key: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
