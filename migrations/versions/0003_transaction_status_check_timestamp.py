"""Track reconciliation checks for payments created without an order."""
from alembic import op

revision = "0003_transaction_status_check_timestamp"
down_revision = "0002_simplify_operational_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS last_status_checked_at TIMESTAMPTZ")


def downgrade() -> None:
    # Production migrations are intentionally non-destructive.
    pass
