"""Set the client commission default for newly created projects."""
from alembic import op

revision = "0004_platform_fee"
down_revision = "0003_status_checks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing projects retain their explicitly configured rate.
    op.execute("ALTER TABLE projects ALTER COLUMN default_platform_fee_percent SET DEFAULT 13")


def downgrade() -> None:
    pass
