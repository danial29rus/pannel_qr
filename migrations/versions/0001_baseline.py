"""Baseline schema for non-destructive production adoption.

This revision is intentionally idempotent. It creates a fresh schema from the
current metadata and upgrades the pre-Alembic MVP columns in place. It never
drops a table, column, or user data.
"""
from alembic import op

from app.db.models import Base

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=True)
    op.execute("ALTER TYPE limitperiod ADD VALUE IF NOT EXISTS 'weekly'")
    for statement in (
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(320)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(40)",
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS default_platform_fee_percent NUMERIC(7,4) NOT NULL DEFAULT 0",
        "ALTER TABLE payment_providers ADD COLUMN IF NOT EXISTS provider_fee_percent NUMERIC(7,4) NOT NULL DEFAULT 0",
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS external_callback_url TEXT",
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS external_incoming_token TEXT",
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS external_callback_secret TEXT",
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS status_check_interval_seconds INTEGER NOT NULL DEFAULT 30",
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS payment_expiry_minutes INTEGER NOT NULL DEFAULT 30",
        "ALTER TABLE project_operational_policies ADD COLUMN IF NOT EXISTS cooldown_minutes INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS payment_url TEXT",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_url TEXT",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS external_order_id VARCHAR(128)",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS external_status_notified_at TIMESTAMPTZ",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS last_status_checked_at TIMESTAMPTZ",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_users_email ON users(email) WHERE email IS NOT NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_orders_project_external_id ON orders(project_id, external_order_id) WHERE external_order_id IS NOT NULL",
    ):
        op.execute(statement)


def downgrade() -> None:
    # Baseline is deliberately irreversible: production data is never dropped.
    pass
