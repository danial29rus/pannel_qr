from datetime import time
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.schemas import ProviderRouteUpdate
from app.services.routing import RoutingService
import app.services.routing as routing_service
from app.services.routing import is_in_time_window


def test_route_window_handles_day_and_midnight_ranges():
    assert is_in_time_window(time(12, 0), time(9, 0), time(18, 0))
    assert not is_in_time_window(time(20, 0), time(9, 0), time(18, 0))
    assert is_in_time_window(time(23, 30), time(22, 0), time(2, 0))
    assert is_in_time_window(time(1, 30), time(22, 0), time(2, 0))
    assert not is_in_time_window(time(12, 0), time(22, 0), time(2, 0))


def test_route_velocity_and_queue_fields_are_optional():
    route = ProviderRouteUpdate(max_transactions_10m=4, max_transactions_hour=12, max_pending_transactions=3)

    assert route.max_transactions_10m == 4
    assert route.max_transactions_hour == 12
    assert route.max_pending_transactions == 3


@pytest.mark.asyncio
async def test_route_blocks_when_pending_queue_is_full(monkeypatch):
    route = SimpleNamespace(
        project_id="project-1", provider_id="provider-1", is_active=True,
        available_from=None, available_to=None, max_transactions_10m=10,
        max_transactions_hour=20, max_pending_transactions=2, min_amount=None,
        max_amount=None, daily_amount_limit=None, weekly_amount_limit=None,
        daily_transactions_limit=None, weekly_transactions_limit=None,
    )
    monkeypatch.setattr(routing_service.TransactionDAO, "provider_usage", AsyncMock(return_value=(Decimal("0"), 0)))
    monkeypatch.setattr(routing_service.TransactionDAO, "count_created_since", AsyncMock(side_effect=[0, 0]))
    monkeypatch.setattr(routing_service.TransactionDAO, "count_pending", AsyncMock(return_value=2))
    monkeypatch.setattr(routing_service.ProviderDAO, "get", AsyncMock(return_value=SimpleNamespace(is_active=True)))

    result = await RoutingService.evaluate(SimpleNamespace(), route, Decimal("100"))

    assert not result.available
    assert result.reason == "Лимит ожидающих платежей исчерпан"


@pytest.mark.asyncio
async def test_ten_requests_in_five_second_intervals_hit_route_ten_minute_limit(monkeypatch):
    route = SimpleNamespace(
        project_id="project-1", provider_id="provider-1", is_active=True,
        available_from=None, available_to=None, max_transactions_10m=10,
        max_transactions_hour=20, max_pending_transactions=3, min_amount=None,
        max_amount=None, daily_amount_limit=None, weekly_amount_limit=None,
        daily_transactions_limit=None, weekly_transactions_limit=None,
    )
    monkeypatch.setattr(routing_service.TransactionDAO, "provider_usage", AsyncMock(return_value=(Decimal("0"), 0)))
    monkeypatch.setattr(routing_service.TransactionDAO, "count_created_since", AsyncMock(side_effect=[10, 10]))
    monkeypatch.setattr(routing_service.TransactionDAO, "count_pending", AsyncMock(return_value=0))
    monkeypatch.setattr(routing_service.ProviderDAO, "get", AsyncMock(return_value=SimpleNamespace(is_active=True)))

    result = await RoutingService.evaluate(SimpleNamespace(), route, Decimal("100"))

    assert not result.available
    assert result.reason == "Лимит заявок за 10 минут исчерпан"
