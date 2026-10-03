import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import DashboardSummary
from app.dao.repositories import TransactionDAO


class DashboardService:
    @staticmethod
    async def summary(
        session: AsyncSession, project_id: uuid.UUID, currency: str, from_date: datetime | None, to_date: datetime | None,
    ) -> DashboardSummary:
        end = (to_date or datetime.now(UTC)).astimezone(UTC)
        start = (from_date or end - timedelta(days=30)).astimezone(UTC)
        paid, credited, margin, count, success_count, pending_count, failed_count, terminal_count = await TransactionDAO.dashboard_totals(
            session, project_id, currency.upper(), start, end,
        )
        return DashboardSummary(
            from_date=start, to_date=end, paid_by_clients=paid, credited_by_payments=credited,
            settlement_margin=margin, payment_count=count, success_count=success_count,
            pending_count=pending_count, failed_count=failed_count, terminal_count=terminal_count,
        )
