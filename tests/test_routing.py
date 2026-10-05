from datetime import UTC, datetime, time, timedelta
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
    route = ProviderRouteUpdate(
        max_transactions_10m=4, max_transactions_hour=12,
        max_all_transactions_hour=5, max_all_transactions_day=50,
        post_terminal_cooldown_min_seconds=30, post_terminal_cooldown_max_seconds=180,
        max_pending_transactions=3,
    )

    assert route.max_transactions_10m == 4
    assert route.max_transactions_hour == 12
    assert route.max_all_transactions_hour == 5
    assert route.max_all_transactions_day == 50
    assert route.post_terminal_cooldown_min_seconds == 30
    assert route.post_terminal_cooldown_max_seconds == 180
    assert route.max_pending_transactions == 3


@pytest.mark.asyncio
async def test_route_blocks_when_pending_queue_is_full(monkeypatch):
    route = SimpleNamespace(
        project_id="project-1", provider_id="provider-1", is_active=True,
        available_from=None, available_to=None, max_transactions_10m=10,
        max_transactions_hour=20, max_all_transactions_hour=None, max_all_transactions_day=None,
        post_terminal_cooldown_until=None, max_pending_transactions=2, min_amount=None,
        max_amount=None, daily_amount_limit=None, weekly_amount_limit=None,
        daily_transactions_limit=None, weekly_transactions_limit=None,
    )
    monkeypatch.setattr(routing_service.TransactionDAO, "provider_usage", AsyncMock(return_value=(Decimal("0"), 0)))
    monkeypatch.setattr(routing_service.TransactionDAO, "count_succeeded_since", AsyncMock(side_effect=[0, 0]))
    monkeypatch.setattr(routing_service.TransactionDAO, "count_all_created_since", AsyncMock(return_value=0))
    monkeypatch.setattr(routing_service.TransactionDAO, "count_pending", AsyncMock(return_value=2))
    monkeypatch.setattr(routing_service.ProviderDAO, "get", AsyncMock(return_value=SimpleNamespace(is_active=True)))

    result = await RoutingService.evaluate(SimpleNamespace(), route, Decimal("100"))

    assert not result.available
    assert result.reason == "Лимит ожидающих платежей исчерпан"


@pytest.mark.asyncio
async def test_ten_successful_payments_in_five_second_intervals_hit_route_ten_minute_limit(monkeypatch):
    route = SimpleNamespace(
        project_id="project-1", provider_id="provider-1", is_active=True,
        available_from=None, available_to=None, max_transactions_10m=10,
        max_transactions_hour=20, max_all_transactions_hour=None, max_all_transactions_day=None,
        post_terminal_cooldown_until=None, max_pending_transactions=3, min_amount=None,
        max_amount=None, daily_amount_limit=None, weekly_amount_limit=None,
        daily_transactions_limit=None, weekly_transactions_limit=None,
    )
    monkeypatch.setattr(routing_service.TransactionDAO, "provider_usage", AsyncMock(return_value=(Decimal("0"), 0)))
    monkeypatch.setattr(routing_service.TransactionDAO, "count_succeeded_since", AsyncMock(side_effect=[10, 10]))
    monkeypatch.setattr(routing_service.TransactionDAO, "count_all_created_since", AsyncMock(return_value=0))
    monkeypatch.setattr(routing_service.TransactionDAO, "count_pending", AsyncMock(return_value=0))
    monkeypatch.setattr(routing_service.ProviderDAO, "get", AsyncMock(return_value=SimpleNamespace(is_active=True)))

    result = await RoutingService.evaluate(SimpleNamespace(), route, Decimal("100"))

    assert not result.available
    assert result.reason == "Лимит успешных платежей за 10 минут исчерпан"


@pytest.mark.asyncio
async def test_route_blocks_all_status_volume_even_when_payments_were_cancelled(monkeypatch):
    route = SimpleNamespace(
        project_id="project-1", provider_id="provider-1", is_active=True,
        available_from=None, available_to=None, max_transactions_10m=None,
        max_transactions_hour=None, max_all_transactions_hour=5, max_all_transactions_day=50,
        post_terminal_cooldown_until=None, max_pending_transactions=None, min_amount=None, max_amount=None,
        daily_amount_limit=None, weekly_amount_limit=None,
        daily_transactions_limit=None, weekly_transactions_limit=None,
    )
    monkeypatch.setattr(routing_service.TransactionDAO, "provider_usage", AsyncMock(return_value=(Decimal("0"), 0)))
    monkeypatch.setattr(routing_service.TransactionDAO, "count_succeeded_since", AsyncMock(return_value=0))
    monkeypatch.setattr(routing_service.TransactionDAO, "count_all_created_since", AsyncMock(side_effect=[5, 5]))
    monkeypatch.setattr(routing_service.TransactionDAO, "count_pending", AsyncMock(return_value=0))
    monkeypatch.setattr(routing_service.ProviderDAO, "get", AsyncMock(return_value=SimpleNamespace(is_active=True)))

    result = await RoutingService.evaluate(SimpleNamespace(), route, Decimal("100"))

    assert not result.available
    assert result.reason == "Лимит всех заявок за час исчерпан"


@pytest.mark.asyncio
async def test_route_blocks_new_order_for_persisted_random_pause_after_terminal_result(monkeypatch):
    route = SimpleNamespace(
        project_id="project-1", provider_id="provider-1", is_active=True,
        available_from=None, available_to=None, max_transactions_10m=None,
        max_transactions_hour=None, max_all_transactions_hour=None, max_all_transactions_day=None,
        post_terminal_cooldown_until=datetime.now(UTC) + timedelta(seconds=30), max_pending_transactions=None,
        min_amount=None, max_amount=None, daily_amount_limit=None, weekly_amount_limit=None,
        daily_transactions_limit=None, weekly_transactions_limit=None,
    )
    monkeypatch.setattr(routing_service.TransactionDAO, "provider_usage", AsyncMock(return_value=(Decimal("0"), 0)))
    monkeypatch.setattr(routing_service.TransactionDAO, "count_succeeded_since", AsyncMock(return_value=0))
    monkeypatch.setattr(routing_service.TransactionDAO, "count_all_created_since", AsyncMock(return_value=0))
    monkeypatch.setattr(routing_service.TransactionDAO, "count_pending", AsyncMock(return_value=0))
    monkeypatch.setattr(routing_service.ProviderDAO, "get", AsyncMock(return_value=SimpleNamespace(is_active=True)))

    result = await RoutingService.evaluate(SimpleNamespace(), route, Decimal("100"))

    assert not result.available
    assert result.reason == "Случайная пауза между заявками после завершения платежа"
    assert 1 <= result.retry_after_seconds <= 30


@pytest.mark.asyncio
async def test_terminal_result_persists_one_random_route_cooldown(monkeypatch):
    route = SimpleNamespace(
        provider_id="provider-1", post_terminal_cooldown_min_seconds=30,
        post_terminal_cooldown_max_seconds=180, post_terminal_cooldown_until=None,
    )
    save = AsyncMock()
    monkeypatch.setattr(routing_service.ProviderRouteDAO, "list_by_project", AsyncMock(return_value=[route]))
    monkeypatch.setattr(routing_service.ProviderRouteDAO, "save", save)
    monkeypatch.setattr(routing_service, "randbelow", lambda upper: 150)
    ended_at = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)

    await RoutingService.schedule_post_terminal_cooldown(
        SimpleNamespace(), "project-1", "provider-1", ended_at,
    )

    assert route.post_terminal_cooldown_until == ended_at + timedelta(seconds=180)
    save.assert_awaited_once()
