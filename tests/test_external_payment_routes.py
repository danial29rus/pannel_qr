import json
import logging
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import httpx
from fastapi import HTTPException
from starlette.requests import Request

from app.api.router import accept_external_payment, create_merchant_qr_payment, get_external_payment_status
from app.api.schemas import ExternalPaymentCreate, MerchantQrPaymentCreate
from app.db.models import TransactionState
import app.api.router as router_module
import app.services.external_platform as external_platform
from app.db.session import get_session
from app.main import app


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
async def test_legacy_qr_422_explains_missing_fields_without_echoing_body(caplog):
    caplog.set_level(logging.WARNING, logger="app.main")
    async def override_session():
        yield object()
    app.dependency_overrides[get_session] = override_session
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://panel.test") as client:
            response = await client.post(
                "/api/v1/transactions/qr",
                headers={"Authorization": "Bearer test-token"},
                json={"amount": "100", "currency": "RUB", "email": "private@example.com"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["code"] == "request_validation_error"
    fields = {detail["field"] for detail in payload["error"]["details"]}
    assert "body.merchant_transaction_id" in fields
    assert "body.merchant_transaction_id (missing): Field required" in caplog.text
    assert "private@example.com" not in response.text
    assert "private@example.com" not in caplog.text


@pytest.mark.asyncio
async def test_legacy_qr_business_422_is_written_to_api_logs(monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="app.api.router")
    project = SimpleNamespace(
        id=uuid4(), payment_expiry_minutes=30, default_platform_fee_percent=Decimal("14"),
        external_key="vitrina-studio",
    )

    class TransactionScope:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    class Session:
        def begin(self):
            return TransactionScope()

    monkeypatch.setattr(external_platform.ExternalPlatformService, "project_for_token", AsyncMock(return_value=project))
    monkeypatch.setattr(external_platform.ExternalPlatformService, "log_request", AsyncMock())
    monkeypatch.setattr(
        router_module.PaymentService, "create_merchant_qr_payment",
        AsyncMock(side_effect=HTTPException(status_code=422, detail={"code": "no_eligible_route"})),
    )

    with pytest.raises(HTTPException) as error:
        await create_merchant_qr_payment(
            MerchantQrPaymentCreate(
                amount=Decimal("3162"), currency="RUB", merchant_transaction_id=str(uuid4()),
            ),
            request_for("POST", "/api/v1/transactions/qr", headers={"Authorization": "Bearer test-auth-token"}),
            Session(),
        )

    assert error.value.status_code == 422
    assert "Merchant QR request rejected" in caplog.text
    assert "no_eligible_route" in caplog.text
    assert "test-auth-token" not in caplog.text


@pytest.mark.asyncio
async def test_external_payment_create_uses_signed_credentials_and_returns_direct_nspk_link(monkeypatch):
    external_key = "vitrina-studio"
    transaction_id = uuid4()
    path = f"/api/v1/external/{external_key}/payments"
    body = json.dumps({"transaction_id": str(transaction_id), "amount_rub": 500}, separators=(",", ":")).encode()
    timestamp = str(int(datetime.now(UTC).timestamp()))
    project = SimpleNamespace(id=uuid4(), external_callback_url=None, payment_expiry_minutes=30)
    transaction = SimpleNamespace(
        state=TransactionState.pending, raw_provider_payload={"qr_url": "https://qr.nspk.ru/ABCD1234"},
        payment_url="https://qr.nspk.ru/ABCD1234", amount=Decimal("500"), currency="RUB",
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
    assert response.payment_url == "https://qr.nspk.ru/ABCD1234"
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
async def test_external_payment_rejects_hosted_url_when_direct_nspk_is_required(monkeypatch):
    external_key = "vitrina-studio"
    transaction_id = uuid4()
    path = f"/api/v1/external/{external_key}/payments"
    body = json.dumps({"transaction_id": str(transaction_id), "amount_rub": 500}, separators=(",", ":")).encode()
    timestamp = str(int(datetime.now(UTC).timestamp()))
    project = SimpleNamespace(id=uuid4(), external_callback_url=None, payment_expiry_minutes=30)
    transaction = SimpleNamespace(
        state=TransactionState.pending, raw_provider_payload={"qr_url": "https://checkout.mulenpay.example/pay"},
        payment_url="https://checkout.mulenpay.example/pay", amount=Decimal("500"), currency="RUB",
        created_at=datetime.now(UTC),
    )
    monkeypatch.setattr(external_platform.ExternalPlatformService, "project_for_signed_payment_request", AsyncMock(return_value=project))
    monkeypatch.setattr(external_platform.ExternalPlatformService, "log_request", AsyncMock())
    monkeypatch.setattr(router_module.PaymentService, "create_external_platform_payment", AsyncMock(return_value=transaction))
    request = request_for("POST", path, body, {
        "X-Platform-Token": "partner-auth-token",
        "X-Platform-Timestamp": timestamp,
        "X-Platform-Signature": "signature",
    })

    with pytest.raises(HTTPException) as error:
        await accept_external_payment(
            external_key, ExternalPaymentCreate(transaction_id=transaction_id, amount_rub=500), request,
            AsyncMock(rollback=AsyncMock()),
        )
    assert error.value.status_code == 502
    assert "direct NSPK" in error.value.detail


@pytest.mark.asyncio
async def test_external_payment_returns_recorded_failed_status_after_provider_exhaustion(monkeypatch):
    external_key = "vitrina-studio"
    transaction_id = uuid4()
    path = f"/api/v1/external/{external_key}/payments"
    body = json.dumps({"transaction_id": str(transaction_id), "amount_rub": 500}, separators=(",", ":")).encode()
    timestamp = str(int(datetime.now(UTC).timestamp()))
    project = SimpleNamespace(id=uuid4(), external_callback_url="https://partner.example/callback", payment_expiry_minutes=30)
    transaction = SimpleNamespace(
        state=TransactionState.failed, raw_provider_payload={"error": {"code": "provider_create_failed"}},
        payment_url=None, amount=Decimal("500"), currency="RUB", created_at=datetime.now(UTC),
    )
    authenticate = AsyncMock(return_value=project)
    create = AsyncMock(return_value=transaction)
    log = AsyncMock()
    monkeypatch.setattr(external_platform.ExternalPlatformService, "project_for_signed_payment_request", authenticate)
    monkeypatch.setattr(external_platform.ExternalPlatformService, "log_request", log)
    monkeypatch.setattr(router_module.PaymentService, "create_external_platform_payment", create)
    request = request_for("POST", path, body, {
        "X-Platform-Token": "partner-auth-token",
        "X-Platform-Timestamp": timestamp,
        "X-Platform-Signature": "signature",
    })

    response = await accept_external_payment(
        external_key, ExternalPaymentCreate(transaction_id=transaction_id, amount_rub=500), request,
        AsyncMock(rollback=AsyncMock()),
    )

    assert response.transaction_id == transaction_id
    assert response.status == "failed" and response.paid is False
    assert response.payment_url is None and response.qr_url is None
    assert log.await_args.kwargs["outcome"] == "accepted"


@pytest.mark.asyncio
async def test_external_payment_status_requires_signed_path_and_returns_saved_state(monkeypatch):
    external_key = "vitrina-studio"
    transaction_id = uuid4()
    path = f"/api/v1/external/{external_key}/payments/{transaction_id}"
    timestamp = str(int(datetime.now(UTC).timestamp()))
    project = SimpleNamespace(id=uuid4(), payment_expiry_minutes=30)
    transaction = SimpleNamespace(
        state=TransactionState.succeeded, raw_provider_payload={"qr_url": "https://qr.nspk.ru/ABCD1234"},
        payment_url="https://qr.nspk.ru/ABCD1234", amount=Decimal("500"), currency="RUB",
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
