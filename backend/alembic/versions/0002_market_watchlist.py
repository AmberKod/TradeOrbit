"""Persist workspace market watchlists independently from exchange accounts."""

import sqlalchemy as sa

from alembic import op

revision = "0002_market_watchlist"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_watchlist",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("instrument_key", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "instrument_key"),
    )
    op.create_index("ix_market_watchlist_workspace_id", "market_watchlist", ["workspace_id"])


def downgrade() -> None:
    op.drop_table("market_watchlist")
