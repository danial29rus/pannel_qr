"""Track successful merchant status callbacks for QR API payments."""
from alembic import op


revision = "0005_merchant_callback"
down_revision = "0004_platform_fee"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS merchant_callback_status VARCHAR(32)")


def downgrade() -> None:
    # Production migrations are intentionally non-destructive.
    pass
