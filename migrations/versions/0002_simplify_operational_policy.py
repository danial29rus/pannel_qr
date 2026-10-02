"""Add calendar-day policy limits without removing historical configuration."""
from alembic import op

revision = "0002_simplify_operational_policy"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE project_operational_policies ADD COLUMN IF NOT EXISTS max_transactions_day INTEGER NOT NULL DEFAULT 300")
    op.execute("ALTER TABLE project_operational_policies ADD COLUMN IF NOT EXISTS daily_amount_limit NUMERIC(20,4) NOT NULL DEFAULT 100000")


def downgrade() -> None:
    pass
