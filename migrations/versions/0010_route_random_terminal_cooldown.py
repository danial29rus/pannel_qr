"""Add persisted random terminal cooldown bounds for provider routes."""
from alembic import op


revision = "0010_route_random_cooldown"
down_revision = "0009_route_terminal_cooldown"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE project_provider_routes ADD COLUMN IF NOT EXISTS post_terminal_cooldown_min_seconds INTEGER")
    op.execute("ALTER TABLE project_provider_routes ADD COLUMN IF NOT EXISTS post_terminal_cooldown_max_seconds INTEGER")
    op.execute("ALTER TABLE project_provider_routes ADD COLUMN IF NOT EXISTS post_terminal_cooldown_until TIMESTAMPTZ")


def downgrade() -> None:
    # Production migrations intentionally preserve audit and configuration data.
    pass
