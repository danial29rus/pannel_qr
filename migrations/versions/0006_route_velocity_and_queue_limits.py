"""Add rolling request and pending-queue limits with success-only analytics."""
from alembic import op


revision = "0006_route_velocity"
down_revision = "0005_merchant_callback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep existing installations' former 15-minute setting as the initial
    # value for the new 10-minute control instead of silently widening rate.
    op.execute("ALTER TABLE project_operational_policies ADD COLUMN IF NOT EXISTS max_transactions_10m INTEGER NOT NULL DEFAULT 15")
    op.execute("UPDATE project_operational_policies SET max_transactions_10m = max_transactions_15m WHERE max_transactions_10m = 15 AND max_transactions_15m IS NOT NULL")
    op.execute("ALTER TABLE project_operational_policies ADD COLUMN IF NOT EXISTS max_pending_transactions INTEGER NOT NULL DEFAULT 50")
    op.execute("ALTER TABLE project_provider_routes ADD COLUMN IF NOT EXISTS max_transactions_10m INTEGER")
    op.execute("ALTER TABLE project_provider_routes ADD COLUMN IF NOT EXISTS max_transactions_hour INTEGER")
    op.execute("ALTER TABLE project_provider_routes ADD COLUMN IF NOT EXISTS max_pending_transactions INTEGER")
    op.execute("CREATE INDEX IF NOT EXISTS ix_transactions_project_provider_state_created ON transactions(project_id, provider_id, state, created_at)")


def downgrade() -> None:
    # Production migrations intentionally preserve audit and configuration data.
    pass
