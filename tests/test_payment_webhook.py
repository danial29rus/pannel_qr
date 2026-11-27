from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid

import pytest

from app.db.models import TransactionState
from app.api.schemas import TransactionCreate
from app.payments.adapters.base import ProviderPayment, RetryableProviderError
from app.payments.service import PaymentService
import app.payments.service as payment_service
from app.services.orders import OrderService


class Begin:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class Session:
    def __init__(self, events):
        self.events = events

    async def rollback(self):
        self.events.append("rollback")

    def begin(self):
        self.events.append("begin")
        return Begin()


@pytest.mark.asyncio
async def test_webhook_rolls_back_read_transaction_before_provider_status_check(monkeypatch):
    events = []
    session = Session(events)
    provider = SimpleNamespace(id="provider-1", is_active=True, adapter_type="demo", settings={}, credentials_encrypted={})
    transaction = SimpleNamespace(
        id="transaction-1", project_id="project-1", provider_id="provider-1", amount=Decimal("50"), currency="RUB", state=TransactionState.pending,
        raw_provider_payload=None, settled_amount=None, fee_amount=Decimal("0"),
    )

    class Adapter:
        async def verify_webhook(self, body, headers):
            return True

        async def parse_webhook(self, body):
            return ProviderPayment(
                external_id="external-1", state=TransactionState.succeeded,
                amount=Decimal("50"), currency="RUB", payload={},
            )

        async def get_payment(self, external_id):
            events.append("provider_status")
            return ProviderPayment(
                external_id="external-1", state=TransactionState.succeeded,
                amount=Decimal("50"), currency="RUB", payload={"status": "paid"},
            )

    monkeypatch.setattr(payment_service.ProviderDAO, "get_by_code", AsyncMock(return_value=provider))
    monkeypatch.setattr(payment_service.TransactionDAO, "get_by_provider_external_for_update", AsyncMock(return_value=transaction))
    monkeypatch.setattr(payment_service.ProviderRequestAttemptDAO, "append", AsyncMock())
    monkeypatch.setattr(payment_service.TransactionEventDAO, "append", AsyncMock())
    monkeypatch.setattr(payment_service.RoutingService, "schedule_post_terminal_cooldown", AsyncMock())
    monkeypatch.setattr(OrderService, "sync_status_from_transaction", AsyncMock(return_value=None))
    monkeypatch.setattr(payment_service.registry, "get", lambda *_: Adapter())

    await PaymentService.process_webhook(session, "mulen-workkit", b'{"id":"external-1"}', {})

    assert events.index("rollback") < events.index("provider_status")
    assert transaction.state is TransactionState.succeeded


@pytest.mark.asyncio
async def test_immediate_provider_failure_starts_route_cooldown(monkeypatch):
    provider = SimpleNamespace(
        id="provider-1", adapter_type="demo", settings={}, credentials_encrypted={},
    )

    class Adapter:
        async def create_payment(self, _request):
            return ProviderPayment(
                external_id="external-1", state=TransactionState.failed,
                payload={"error": {"message": "QR unavailable"}},
            )

    monkeypatch.setattr(payment_service.ProjectDAO, "get_for_update", AsyncMock(return_value=SimpleNamespace(is_active=True)))
    monkeypatch.setattr(payment_service.TransactionDAO, "get_by_idempotency", AsyncMock(return_value=None))
    monkeypatch.setattr(payment_service.TransactionDAO, "create", AsyncMock())
    monkeypatch.setattr(payment_service.ProviderRequestAttemptDAO, "append", AsyncMock())
    monkeypatch.setattr(payment_service.TransactionEventDAO, "append", AsyncMock())
    monkeypatch.setattr(payment_service.RoutingService, "resolve_provider", AsyncMock(return_value=provider))
    monkeypatch.setattr(payment_service.RoutingService, "schedule_post_terminal_cooldown", AsyncMock())
    monkeypatch.setattr(payment_service.OperationalPolicyService, "assert_allows", AsyncMock())
    monkeypatch.setattr(payment_service, "assert_limits", AsyncMock())
    monkeypatch.setattr(payment_service.registry, "get", lambda *_: Adapter())

    session = SimpleNamespace()
    transaction = await payment_service.create_transaction(
        session,
        TransactionCreate(project_id="00000000-0000-0000-0000-000000000001", amount=Decimal("50"), currency="RUB"),
        "immediately-failed-payment",
    )

    assert transaction.state is TransactionState.failed
    payment_service.RoutingService.schedule_post_terminal_cooldown.assert_awaited_once()


@pytest.mark.asyncio
async def test_unavailable_nspk_qr_starts_route_cooldown_even_with_pending_provider_status(monkeypatch):
    provider = SimpleNamespace(
        id="provider-1", adapter_type="demo", settings={}, credentials_encrypted={},
    )

    class Adapter:
        async def create_payment(self, _request):
            return ProviderPayment(
                external_id="external-qr-1", state=TransactionState.pending,
                payload={"error": {"code": "sbp_qr_unavailable", "message": "QR unavailable"}},
            )

    monkeypatch.setattr(payment_service.ProjectDAO, "get_for_update", AsyncMock(return_value=SimpleNamespace(is_active=True)))
    monkeypatch.setattr(payment_service.TransactionDAO, "get_by_idempotency", AsyncMock(return_value=None))
    monkeypatch.setattr(payment_service.TransactionDAO, "create", AsyncMock())
    monkeypatch.setattr(payment_service.ProviderRequestAttemptDAO, "append", AsyncMock())
    monkeypatch.setattr(payment_service.TransactionEventDAO, "append", AsyncMock())
    monkeypatch.setattr(payment_service.RoutingService, "resolve_provider", AsyncMock(return_value=provider))
    cooldown = AsyncMock()
    monkeypatch.setattr(payment_service.RoutingService, "schedule_post_terminal_cooldown", cooldown)
    monkeypatch.setattr(payment_service.OperationalPolicyService, "assert_allows", AsyncMock())
    monkeypatch.setattr(payment_service, "assert_limits", AsyncMock())
    monkeypatch.setattr(payment_service.registry, "get", lambda *_: Adapter())

    await payment_service.create_transaction(
        SimpleNamespace(),
        TransactionCreate(project_id="00000000-0000-0000-0000-000000000001", amount=Decimal("50"), currency="RUB"),
        "unavailable-nspk-qr",
    )

    cooldown.assert_awaited_once()


@pytest.mark.asyncio
async def test_external_provider_retries_are_persisted_as_failed_and_start_cooldown(monkeypatch):
    project_id = uuid.uuid4()
    user_id = uuid.uuid4()
    transaction_id = uuid.uuid4()
    provider = SimpleNamespace(id=uuid.uuid4(), adapter_type="json_api", settings={"max_attempts": 2}, credentials_encrypted={})
    customer = SimpleNamespace(id=user_id, email="buyer@example.com")
    created = []

    class Adapter:
        def payment_reference(self, _idempotency_key, extra):
            return extra["merchant_transaction_id"]

        async def create_payment(self, _request):
            raise RetryableProviderError("MulenPay /sbp did not return NSPK", 503)

    async def save_transaction(_session, transaction):
        transaction.id = uuid.uuid4()
        created.append(transaction)
        return transaction

    attempts = AsyncMock()
    events = AsyncMock()
    cooldown = AsyncMock()
    monkeypatch.setattr(payment_service.ProjectDAO, "get_for_update", AsyncMock(return_value=SimpleNamespace(is_active=True)))
    monkeypatch.setattr(payment_service.TransactionDAO, "get_by_idempotency", AsyncMock(return_value=None))
    monkeypatch.setattr(payment_service.TransactionDAO, "create", AsyncMock(side_effect=save_transaction))
    monkeypatch.setattr(payment_service.ProviderRequestAttemptDAO, "append", attempts)
    monkeypatch.setattr(payment_service.TransactionEventDAO, "append", events)
    monkeypatch.setattr(payment_service.RoutingService, "resolve_provider", AsyncMock(return_value=provider))
    monkeypatch.setattr(payment_service.RoutingService, "schedule_post_terminal_cooldown", cooldown)
    monkeypatch.setattr(payment_service.OperationalPolicyService, "assert_allows", AsyncMock())
    monkeypatch.setattr(payment_service, "assert_limits", AsyncMock())
    monkeypatch.setattr(payment_service.UserDAO, "get", AsyncMock(return_value=customer))
    monkeypatch.setattr(payment_service.registry, "get", lambda *_: Adapter())
    monkeypatch.setattr(payment_service.asyncio, "sleep", AsyncMock())

    session = SimpleNamespace()
    transaction = await payment_service.create_transaction(
        session,
        TransactionCreate(
            project_id=project_id,
            user_id=user_id,
            amount=Decimal("100"),
            currency="RUB",
            extra={"_signed_external_api": True, "_require_direct_qr": True, "merchant_transaction_id": str(transaction_id)},
        ),
        f"external-api:{transaction_id}",
    )

    assert transaction is created[0]
    assert transaction.state is TransactionState.failed
    assert transaction.external_id == str(transaction_id)
    assert transaction.payment_url is None
    assert transaction.raw_provider_payload["error"]["code"] == "provider_create_failed"
    assert attempts.await_count == 2
    assert events.await_args.args[1].event_type == "provider.create_failed"
    cooldown.assert_awaited_once()
    assert cooldown.await_args.args[:3] == (session, project_id, provider.id)
