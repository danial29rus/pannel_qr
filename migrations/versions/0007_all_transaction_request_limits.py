"""Add hard all-status request caps to project operational policies."""
from alembic import op


revision = "0007_all_request_limits"
down_revision = "0006_route_velocity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NULL deliberately means no hard cap, preserving current production
    # behaviour until an operator explicitly enables this protection.
    op.execute("ALTER TABLE project_operational_policies ADD COLUMN IF NOT EXISTS max_all_transactions_hour INTEGER")
    op.execute("ALTER TABLE project_operational_policies ADD COLUMN IF NOT EXISTS max_all_transactions_day INTEGER")


def downgrade() -> None:
    # Production migrations intentionally preserve audit and configuration data.
    pass
