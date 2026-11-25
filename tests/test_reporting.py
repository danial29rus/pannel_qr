from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock
import uuid

import pytest
from fastapi import HTTPException

from app.services.routing import start_of_week
from app.services.dashboard import DashboardService
from app.dao.repositories import TransactionDAO


@pytest.mark.parametrize("instant, expected", [
    ("2026-11-15T20:59:59+00:00", "2026-11-08T21:00:00+00:00"),
    ("2026-11-15T21:00:00+00:00", "2026-11-15T21:00:00+00:00"),
    ("2026-11-22T20:59:59+00:00", "2026-11-15T21:00:00+00:00"),
    ("2026-11-22T21:00:00+00:00", "2026-11-22T21:00:00+00:00"),
])
def test_week_boundary_in_moscow(instant, expected):
    assert start_of_week(datetime.fromisoformat(instant)) == datetime.fromisoformat(expected)


@pytest.mark.asyncio
async def test_daily_report_fills_empty_days_and_excludes_next_monday(monkeypatch):
    monkeypatch.setattr(TransactionDAO, "dashboard_daily", AsyncMock(return_value=[(datetime(2026, 11, 17), Decimal("125"), 2)]))
    monkeypatch.setattr(TransactionDAO, "dashboard_totals", AsyncMock(return_value=(Decimal("125"), Decimal("125"), Decimal("125"), 2, 1, 1, 0, 1)))
    report = await DashboardService.summary(None, uuid.uuid4(), "rub", datetime.fromisoformat("2026-11-16T00:00:00+03:00"), datetime.fromisoformat("2026-11-23T00:00:00+03:00"))
    assert len(report.daily) == 7
    assert report.daily[0].date == "2026-11-16"
    assert report.daily[-1].date == "2026-11-22"
    assert report.daily[0].amount == 0
    assert report.daily[1].amount == Decimal("125")
    assert report.daily[1].payment_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("start, end", [
    (datetime(2026, 1, 1), datetime(2026, 1, 2, tzinfo=UTC)),
    (datetime(2026, 1, 2, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC)),
    (datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC)),
    (datetime(2026, 1, 1, tzinfo=UTC), datetime(2028, 1, 1, tzinfo=UTC)),
])
async def test_invalid_reporting_range_returns_422(start, end):
    with pytest.raises(HTTPException) as error:
        await DashboardService.summary(None, uuid.uuid4(), "RUB", start, end)
    assert error.value.status_code == 422


def test_financial_limits_use_moscow_calendar():
    from app.payments.service import period_start
    from app.db.models import LimitPeriod
    instant = datetime.fromisoformat("2026-11-30T21:00:00+00:00")
    assert period_start(LimitPeriod.daily, instant) == instant
    assert period_start(LimitPeriod.monthly, instant) == instant
    assert period_start(LimitPeriod.weekly, instant) == datetime.fromisoformat("2026-11-29T21:00:00+00:00")
