"""${message}"""
from alembic import op
import sqlalchemy as sa

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "raise RuntimeError('Empty migration must be reviewed')"}


def downgrade() -> None:
    ${downgrades if downgrades else "raise RuntimeError('Empty downgrade must be reviewed')"}
