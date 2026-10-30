"""Initial identity, encrypted connection and audit schema."""

import sqlalchemy as sa

from alembic import op

revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None


def stamp() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        stamp(),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        stamp(),
    )
    op.create_table(
        "memberships",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("role", sa.String(12), nullable=False),
        sa.UniqueConstraint("user_id", "workspace_id"),
    )
    op.create_table(
        "sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        stamp(),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])
    op.create_table(
        "account_connections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("exchange", sa.String(12), nullable=False),
        sa.Column("environment", sa.String(8), nullable=False),
        sa.Column("account_mode", sa.String(16), nullable=False),
        sa.Column("region_profile", sa.String(32), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("credential_version", sa.Integer(), nullable=False),
        stamp(),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_account_connections_workspace_id", "account_connections", ["workspace_id"])
    op.create_table(
        "encrypted_credentials",
        sa.Column(
            "account_id", sa.Uuid(), sa.ForeignKey("account_connections.id"), primary_key=True
        ),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("key_version", sa.String(32), nullable=False),
        sa.Column("algorithm", sa.String(20), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("target_id", sa.String(80), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        stamp(),
    )
    op.create_index("ix_audit_logs_workspace_id", "audit_logs", ["workspace_id"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])


def downgrade() -> None:
    for table in (
        "audit_logs",
        "encrypted_credentials",
        "account_connections",
        "sessions",
        "memberships",
        "users",
        "workspaces",
    ):
        op.drop_table(table)
