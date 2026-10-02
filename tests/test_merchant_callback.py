import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.db.models import TransactionState
from app.services import external_platform
from app.services.external_platform import ExternalPlatformService


@pytest.mark.asyncio
async def test_paid_callback_matches_merchant_contract(monkeypatch):
    transaction_id = uuid4()
    transaction = SimpleNamespace(
        id=transaction_id,
        project_id=uuid4(),
        state=TransactionState.succeeded,
        amount=Decimal("25"),
        settled_amount=None,
        currency="RUB",
        merchant_callback_status=None,
        extra={"merchant_transaction_id": "order-25", "merchant_webhook_url": "https://merchant.example/hooks/status"},
    )
    project = SimpleNamespace(external_callback_url=None)
    session = SimpleNamespace(commit=AsyncMock())
    received = {}

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url, content, headers):
            received.update(url=url, content=content, headers=headers)
            return SimpleNamespace(status_code=204, content=b"", headers={}, text="")

    monkeypatch.setattr(external_platform.TransactionDAO, "get", AsyncMock(return_value=transaction))
    monkeypatch.setattr(external_platform.ProjectDAO, "get", AsyncMock(return_value=project))
    monkeypatch.setattr(external_platform.ProviderRequestAttemptDAO, "next_attempt_number", AsyncMock(return_value=1))
    append_attempt = AsyncMock()
    monkeypatch.setattr(external_platform.ProviderRequestAttemptDAO, "append", append_attempt)
    monkeypatch.setattr(external_platform.httpx, "AsyncClient", Client)

    assert await ExternalPlatformService.deliver_merchant_status_for_transaction(session, transaction_id)

    assert received["url"] == "https://merchant.example/hooks/status"
    assert json.loads(received["content"]) == {
        "merchant_transaction_id": "order-25",
        "paid_amount": "25",
        "status": "paid",
        "type": "in",
    }
    assert received["headers"] == {"Content-Type": "application/json"}
    assert append_attempt.await_args.args[1].request_payload == {
        "method": "POST",
        "url": "https://merchant.example/hooks/status",
        "headers": {"Content-Type": "application/json"},
        "body": json.loads(received["content"]),
    }
    assert transaction.merchant_callback_status == "succeeded"
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_merchant_422_is_logged_but_not_retried_forever(monkeypatch):
    transaction_id = uuid4()
    transaction = SimpleNamespace(
        id=transaction_id,
        project_id=uuid4(),
        state=TransactionState.succeeded,
        amount=Decimal("20"),
        settled_amount=None,
        currency="RUB",
        merchant_callback_status=None,
        extra={"merchant_transaction_id": "unknown-order", "merchant_webhook_url": "https://merchant.example/webhook"},
    )
    session = SimpleNamespace(commit=AsyncMock())
    attempt = AsyncMock()

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, *_args, **_kwargs):
            return SimpleNamespace(
                status_code=422, content=b'{"message":"Transaction not found"}',
                headers={"content-type": "application/json"}, text="",
                json=lambda: {"message": "Transaction not found"},
            )

    monkeypatch.setattr(external_platform.TransactionDAO, "get", AsyncMock(return_value=transaction))
    monkeypatch.setattr(external_platform.ProjectDAO, "get", AsyncMock(return_value=SimpleNamespace(external_callback_url=None)))
    monkeypatch.setattr(external_platform.ProviderRequestAttemptDAO, "next_attempt_number", AsyncMock(return_value=1))
    monkeypatch.setattr(external_platform.ProviderRequestAttemptDAO, "append", attempt)
    monkeypatch.setattr(external_platform.httpx, "AsyncClient", Client)

    assert not await ExternalPlatformService.deliver_merchant_status_for_transaction(session, transaction_id)
    assert attempt.await_args.args[1].outcome == "error"
    assert transaction.merchant_callback_status == "succeeded"


@pytest.mark.asyncio
async def test_retryable_merchant_error_stops_after_five_attempts(monkeypatch):
    transaction_id = uuid4()
    transaction = SimpleNamespace(
        id=transaction_id,
        project_id=uuid4(),
        state=TransactionState.succeeded,
        amount=Decimal("20"),
        settled_amount=None,
        currency="RUB",
        merchant_callback_status=None,
        extra={"merchant_transaction_id": "temporary-error", "merchant_webhook_url": "https://merchant.example/webhook"},
    )
    session = SimpleNamespace(commit=AsyncMock())
    append_attempt = AsyncMock()

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, *_args, **_kwargs):
            return SimpleNamespace(status_code=503, content=b"", headers={}, text="temporarily unavailable")

    monkeypatch.setattr(external_platform.TransactionDAO, "get", AsyncMock(return_value=transaction))
    monkeypatch.setattr(external_platform.ProjectDAO, "get", AsyncMock(return_value=SimpleNamespace(external_callback_url=None)))
    monkeypatch.setattr(external_platform.ProviderRequestAttemptDAO, "next_attempt_number", AsyncMock(return_value=5))
    monkeypatch.setattr(external_platform.ProviderRequestAttemptDAO, "append", append_attempt)
    monkeypatch.setattr(external_platform.httpx, "AsyncClient", Client)

    assert not await ExternalPlatformService.deliver_merchant_status_for_transaction(session, transaction_id)
    record = append_attempt.await_args.args[1]
    assert record.outcome == "error"
    assert "retry limit (5) reached" in record.error
    assert transaction.merchant_callback_status == "succeeded"
