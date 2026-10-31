"""Persist latest private read capability and per-scope snapshots.

Revision ID: 0003_account_read_state
Revises: 0002_market_watchlist
"""

import sqlalchemy as sa

from alembic import op

revision = "0003_account_read_state"
down_revision = "0002_market_watchlist"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account_read_states",
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("credential_version", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["account_connections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("account_id"),
    )


def downgrade() -> None:
    op.drop_table("account_read_states")
