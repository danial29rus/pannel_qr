"""Add a per-route pause after every terminal payment result."""
from alembic import op


revision = "0009_route_terminal_cooldown"
down_revision = "0008_route_all_limits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE project_provider_routes ADD COLUMN IF NOT EXISTS post_terminal_cooldown_seconds INTEGER")


def downgrade() -> None:
    # Production migrations intentionally preserve audit and configuration data.
    pass
