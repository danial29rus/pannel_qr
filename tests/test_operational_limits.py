from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.schemas import TransactionCreate
from app.db.models import TransactionState
from app.payments.service import create_transaction
from app.services.policies import OperationalPolicyService
import app.payments.service as payments_service
import app.services.policies as policies_service


def policy(**overrides):
    values = {
        "is_active": True,
        "max_transactions_10m": 20,
        "max_transactions_hour": 30,
        "max_transactions_day": 300,
        "max_pending_transactions": 3,
        "daily_amount_limit": Decimal("100000"),
        "cooldown_minutes": 0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def payment_payload():
    return TransactionCreate(project_id=uuid4(), amount=Decimal("30"), currency="RUB")


@pytest.mark.asyncio
async def test_disabled_policy_does_not_block_payment_creation(monkeypatch):
    payload = payment_payload()
    count_requests = AsyncMock()
    monkeypatch.setattr(policies_service.OperationalPolicyDAO, "get", AsyncMock(return_value=policy(is_active=False)))
    monkeypatch.setattr(policies_service.TransactionDAO, "count_created_since", count_requests)

    await OperationalPolicyService.assert_allows(SimpleNamespace(), payload)

    count_requests.assert_not_awaited()


@pytest.mark.asyncio
async def test_three_pending_payments_block_the_next_request(monkeypatch):
    payload = payment_payload()
    monkeypatch.setattr(policies_service.OperationalPolicyDAO, "get", AsyncMock(return_value=policy(max_pending_transactions=3)))
    monkeypatch.setattr(policies_service.TransactionDAO, "count_created_since", AsyncMock(side_effect=[0, 0, 0]))
    monkeypatch.setattr(policies_service.TransactionDAO, "count_pending", AsyncMock(return_value=3))

    with pytest.raises(HTTPException) as error:
        await OperationalPolicyService.assert_allows(SimpleNamespace(), payload)

    assert error.value.status_code == 429
    assert error.value.detail == {"code": "pending_queue_limit", "limit": 3, "pending": 3}


@pytest.mark.asyncio
async def test_ten_minute_limit_blocks_before_provider_is_called(monkeypatch):
    payload = payment_payload()
    create = AsyncMock()
    monkeypatch.setattr(payments_service.ProjectDAO, "get_for_update", AsyncMock(return_value=SimpleNamespace(is_active=True)))
    monkeypatch.setattr(payments_service.TransactionDAO, "get_by_idempotency", AsyncMock(return_value=None))
    monkeypatch.setattr(payments_service.RoutingService, "resolve_provider", AsyncMock(side_effect=HTTPException(429, {"code": "frequency_limit_10m", "limit": 2})))
    monkeypatch.setattr(payments_service.TransactionDAO, "create", create)

    with pytest.raises(HTTPException) as error:
        await create_transaction(SimpleNamespace(), payload, "blocked-before-payment-url")

    assert error.value.status_code == 429
    assert error.value.detail["code"] == "frequency_limit_10m"
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_daily_amount_uses_only_successful_payments(monkeypatch):
    payload = payment_payload()
    amount_used = AsyncMock(return_value=Decimal("70"))
    monkeypatch.setattr(policies_service.OperationalPolicyDAO, "get", AsyncMock(return_value=policy(daily_amount_limit=Decimal("100"))))
    monkeypatch.setattr(policies_service.TransactionDAO, "count_created_since", AsyncMock(side_effect=[0, 0, 0]))
    monkeypatch.setattr(policies_service.TransactionDAO, "count_pending", AsyncMock(return_value=0))
    monkeypatch.setattr(policies_service.TransactionDAO, "amount_used", amount_used)

    await OperationalPolicyService.assert_allows(SimpleNamespace(), payload)

    assert amount_used.await_args.args[-1] == (TransactionState.succeeded,)
