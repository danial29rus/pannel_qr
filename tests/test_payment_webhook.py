from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.db.models import TransactionState
from app.payments.adapters.base import ProviderPayment
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
        id="transaction-1", project_id="project-1", amount=Decimal("50"), currency="RUB", state=TransactionState.pending,
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
    monkeypatch.setattr(OrderService, "sync_status_from_transaction", AsyncMock(return_value=None))
    monkeypatch.setattr(payment_service.registry, "get", lambda *_: Adapter())

    await PaymentService.process_webhook(session, "mulen-workkit", b'{"id":"external-1"}', {})

    assert events.index("rollback") < events.index("provider_status")
    assert transaction.state is TransactionState.succeeded
