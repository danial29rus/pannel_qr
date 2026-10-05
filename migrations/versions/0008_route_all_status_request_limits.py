"""Add per-route hard all-status request limits."""
from alembic import op


revision = "0008_route_all_limits"
down_revision = "0007_all_request_limits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE project_provider_routes ADD COLUMN IF NOT EXISTS max_all_transactions_hour INTEGER")
    op.execute("ALTER TABLE project_provider_routes ADD COLUMN IF NOT EXISTS max_all_transactions_day INTEGER")


def downgrade() -> None:
    # Production migrations intentionally preserve audit and configuration data.
    pass
