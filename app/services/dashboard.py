import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import DashboardDay, DashboardSummary
from app.dao.repositories import TransactionDAO


class DashboardService:
    @staticmethod
    async def summary(
        session: AsyncSession, project_id: uuid.UUID, currency: str, from_date: datetime | None, to_date: datetime | None,
    ) -> DashboardSummary:
        for value in (from_date, to_date):
            if value is not None and value.utcoffset() is None:
                raise HTTPException(422, "Dates must include a timezone")
        end = (to_date or datetime.now(UTC)).astimezone(UTC)
        start = (from_date or end - timedelta(days=30)).astimezone(UTC)
        if start >= end:
            raise HTTPException(422, "from_date must be earlier than to_date")
        if end - start > timedelta(days=366):
            raise HTTPException(422, "Maximum reporting period is 366 days")
        rows = await TransactionDAO.dashboard_daily(session, project_id, currency.upper(), start, end)
        by_day = {row[0].date().isoformat(): row for row in rows}
        daily = []
        day = start.astimezone(ZoneInfo("Europe/Moscow")).date()
        last = (end - timedelta(microseconds=1)).astimezone(ZoneInfo("Europe/Moscow")).date()
        while day <= last:
            key = day.isoformat()
            row = by_day.get(key)
            daily.append(DashboardDay(date=key, amount=row[1] if row else 0, payment_count=row[2] if row else 0))
            day += timedelta(days=1)
        paid, credited, margin, count, success_count, pending_count, failed_count, terminal_count = await TransactionDAO.dashboard_totals(
            session, project_id, currency.upper(), start, end,
        )
        return DashboardSummary(
            daily=daily, from_date=start, to_date=end, paid_by_clients=paid, credited_by_payments=credited,
            settlement_margin=margin, payment_count=count, success_count=success_count,
            pending_count=pending_count, failed_count=failed_count, terminal_count=terminal_count,
        )
