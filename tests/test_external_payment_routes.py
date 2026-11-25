import json
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from starlette.requests import Request

from app.api.router import accept_external_payment, get_external_payment_status
from app.api.schemas import ExternalPaymentCreate
from app.db.models import TransactionState
import app.api.router as router_module
import app.services.external_platform as external_platform


def request_for(method, path, body=b"", headers=None):
    message = {"type": "http.request", "body": body, "more_body": False}
    async def receive():
        return message
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
        "scheme": "https", "path": path, "raw_path": path.encode(), "query_string": b"",
        "headers": [(key.lower().encode(), value.encode()) for key, value in (headers or {}).items()],
        "server": ("panel.example", 443), "client": ("127.0.0.1", 12345),
    }
    return Request(scope, receive)


@pytest.mark.asyncio
async def test_external_payment_create_uses_signed_credentials_and_returns_hosted_link(monkeypatch):
    external_key = "vitrina-studio"
    transaction_id = uuid4()
    path = f"/api/v1/external/{external_key}/payments"
    body = json.dumps({"transaction_id": str(transaction_id), "amount_rub": 500}, separators=(",", ":")).encode()
    timestamp = str(int(datetime.now(UTC).timestamp()))
    project = SimpleNamespace(id=uuid4(), external_callback_url=None, payment_expiry_minutes=30)
    transaction = SimpleNamespace(
        state=TransactionState.pending, raw_provider_payload={"qr_url": "https://checkout.example/pay/1"},
        payment_url="https://checkout.example/pay/1", amount=Decimal("500"), currency="RUB",
        created_at=datetime.now(UTC),
    )
    authenticate = AsyncMock(return_value=project)
    create = AsyncMock(return_value=transaction)
    log = AsyncMock()
    monkeypatch.setattr(external_platform.ExternalPlatformService, "project_for_signed_payment_request", authenticate)
    monkeypatch.setattr(external_platform.ExternalPlatformService, "log_request", log)
    monkeypatch.setattr(router_module.PaymentService, "create_external_platform_payment", create)
    monkeypatch.setattr(router_module.ExternalPlatformService, "log_request", log)
    request = request_for("POST", path, body, {
        "X-Platform-Token": "partner-auth-token",
        "X-Platform-Timestamp": timestamp,
        "X-Platform-Signature": "signature",
    })

    response = await accept_external_payment(
        external_key, ExternalPaymentCreate(transaction_id=transaction_id, amount_rub=500), request, AsyncMock(rollback=AsyncMock()),
    )

    assert response.transaction_id == transaction_id
    assert response.status == "pending" and response.paid is False
    assert response.payment_url == "https://checkout.example/pay/1"
    merchant_payload = create.await_args.args[2]
    assert merchant_payload.amount == Decimal("500")
    assert merchant_payload.currency == "RUB"
    assert merchant_payload.merchant_transaction_id == str(transaction_id)
    authenticate.assert_awaited_once()
    assert authenticate.await_args.args[1:] == (
        external_key, "partner-auth-token", timestamp, "signature", "POST", path, body,
    )
    log.assert_awaited_once()


@pytest.mark.asyncio
async def test_external_payment_status_requires_signed_path_and_returns_saved_state(monkeypatch):
    external_key = "vitrina-studio"
    transaction_id = uuid4()
    path = f"/api/v1/external/{external_key}/payments/{transaction_id}"
    timestamp = str(int(datetime.now(UTC).timestamp()))
    project = SimpleNamespace(id=uuid4(), payment_expiry_minutes=30)
    transaction = SimpleNamespace(
        state=TransactionState.succeeded, raw_provider_payload={"qr_url": "https://checkout.example/pay/1"},
        payment_url="https://checkout.example/pay/1", amount=Decimal("500"), currency="RUB",
        created_at=datetime.now(UTC),
    )
    authenticate = AsyncMock(return_value=project)
    get = AsyncMock(return_value=transaction)
    monkeypatch.setattr(external_platform.ExternalPlatformService, "project_for_signed_payment_request", authenticate)
    monkeypatch.setattr(router_module.TransactionDAO, "get_by_idempotency", get)
    request = request_for("GET", path, b"", {
        "Authorization": "Bearer partner-auth-token",
        "X-Platform-Timestamp": timestamp,
        "X-Platform-Signature": "signature",
    })

    response = await get_external_payment_status(external_key, transaction_id, request, AsyncMock())

    assert response.paid is True and response.status == "paid"
    assert response.amount_rub == 500
    authenticate.assert_awaited_once()
    assert authenticate.await_args.args[1:] == (
        external_key, "partner-auth-token", timestamp, "signature", "GET", path, b"",
    )
    assert get.await_args.args[1:] == (project.id, f"external-api:{transaction_id}")
