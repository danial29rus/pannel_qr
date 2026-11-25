"""Persist selected buyer for signed external payment idempotency."""
from alembic import op


revision = "0011_external_payment_request"
down_revision = "0010_route_random_cooldown"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS external_payment_requests (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES projects(id),
            transaction_id UUID NOT NULL,
            user_id UUID NOT NULL REFERENCES users(id),
            amount NUMERIC(20, 4) NOT NULL,
            currency VARCHAR(8) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_external_payment_project_transaction UNIQUE (project_id, transaction_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_external_payment_requests_project_id ON external_payment_requests(project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_external_payment_requests_user_id ON external_payment_requests(user_id)")


def downgrade() -> None:
    # Keep idempotency records during rollback to avoid losing buyer bindings.
    pass
