import hashlib
import hmac
import importlib.util
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.schemas import MerchantQrPaymentCreate
from app.db.models import ExternalPaymentRequest
from app.payments.service import PaymentService
import app.payments.service as payment_service
import app.services.external_platform as external_platform

_smoke_script_spec = importlib.util.spec_from_file_location(
    "test_partner_payment", Path(__file__).parents[1] / "scripts" / "test_partner_payment.py",
)
_smoke_script = importlib.util.module_from_spec(_smoke_script_spec)
_smoke_script_spec.loader.exec_module(_smoke_script)
smoke_script_signature = _smoke_script.signature


class WriteSession:
    def __init__(self):
        self.refresh = AsyncMock()

    def begin(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


@pytest.mark.asyncio
async def test_signed_payment_request_signature_binds_method_path_and_body(monkeypatch):
    timestamp = str(int(datetime.now(UTC).timestamp()))
    body = b'{"transaction_id":"a","amount_rub":500}'
    secret = "test-secret-key"
    project = SimpleNamespace(
        id=uuid4(), is_active=True, external_incoming_token="test-auth-token",
        external_callback_secret=secret,
    )
    monkeypatch.setattr(external_platform.ProjectDAO, "get_by_external_key", AsyncMock(return_value=project))
    signature = external_platform.sign_external_platform_request(
        secret, timestamp, "POST", "/api/v1/external/vitrina/payments", body,
    )
    assert smoke_script_signature(secret, timestamp, "POST", "/api/v1/external/vitrina/payments", body) == signature

    result = await external_platform.ExternalPlatformService.project_for_signed_payment_request(
        object(), "vitrina", "test-auth-token", timestamp, signature,
        "POST", "/api/v1/external/vitrina/payments", body,
    )
    assert result is project

    with pytest.raises(HTTPException) as error:
        await external_platform.ExternalPlatformService.project_for_signed_payment_request(
            object(), "vitrina", "test-auth-token", timestamp, signature,
            "POST", "/api/v1/external/other/payments", body,
        )
    assert error.value.status_code == 401


@pytest.mark.asyncio
async def test_signed_payment_reserves_same_pool_email_before_remote_create(monkeypatch):
    session = WriteSession()
    project_id = uuid4()
    buyer_id = uuid4()
    transaction_id = uuid4()
    buyer = SimpleNamespace(id=buyer_id)
    reservation = ExternalPaymentRequest(
        project_id=project_id, transaction_id=transaction_id, user_id=buyer_id,
        amount=Decimal("500"), currency="RUB",
    )
    transaction = SimpleNamespace(id=uuid4())
    get_reservation = AsyncMock(side_effect=[None, reservation])
    create_reservation = AsyncMock(side_effect=lambda _session, row: row)
    choose_buyer = AsyncMock(return_value=buyer)
    create_payment = AsyncMock(return_value=transaction)

    monkeypatch.setattr(payment_service.ProjectDAO, "get_for_update", AsyncMock(return_value=SimpleNamespace(is_active=True)))
    monkeypatch.setattr(payment_service.ExternalPaymentRequestDAO, "get", get_reservation)
    monkeypatch.setattr(payment_service.ExternalPaymentRequestDAO, "create", create_reservation)
    monkeypatch.setattr(payment_service.UserDAO, "random_active_with_email", choose_buyer)
    monkeypatch.setattr(PaymentService, "create", create_payment)
    payload = MerchantQrPaymentCreate(
        amount=Decimal("500"), currency="RUB", merchant_transaction_id=str(transaction_id),
    )

    first = await PaymentService.create_external_platform_payment(session, project_id, payload)
    second = await PaymentService.create_external_platform_payment(session, project_id, payload)

    assert first is transaction and second is transaction
    choose_buyer.assert_awaited_once()
    create_reservation.assert_awaited_once()
    assert create_payment.await_count == 2
    internal_payload = create_payment.await_args_list[0].args[1]
    assert internal_payload.user_id == buyer_id
    assert internal_payload.extra["_signed_external_api"] is True
    assert "_require_direct_qr" not in internal_payload.extra
    assert create_payment.await_args_list[0].args[2] == f"external-api:{transaction_id}"


@pytest.mark.asyncio
async def test_signed_payment_rejects_same_uuid_with_changed_amount(monkeypatch):
    session = WriteSession()
    project_id = uuid4()
    transaction_id = uuid4()
    reservation = SimpleNamespace(amount=Decimal("500"), currency="RUB", user_id=uuid4())
    monkeypatch.setattr(payment_service.ProjectDAO, "get_for_update", AsyncMock(return_value=SimpleNamespace(is_active=True)))
    monkeypatch.setattr(payment_service.ExternalPaymentRequestDAO, "get", AsyncMock(return_value=reservation))
    create_payment = AsyncMock()
    monkeypatch.setattr(PaymentService, "create", create_payment)

    with pytest.raises(HTTPException) as error:
        await PaymentService.create_external_platform_payment(
            session, project_id,
            MerchantQrPaymentCreate(amount=Decimal("501"), currency="RUB", merchant_transaction_id=str(transaction_id)),
        )

    assert error.value.status_code == 409
    create_payment.assert_not_awaited()


@pytest.mark.asyncio
async def test_external_payment_callback_is_signed_with_project_secret(monkeypatch):
    transaction_id = uuid4()
    secret = "partner-secret-key"
    transaction = SimpleNamespace(
        id=transaction_id,
        project_id=uuid4(),
        state=external_platform.TransactionState.succeeded,
        amount=Decimal("500"),
        settled_amount=None,
        currency="RUB",
        merchant_callback_status=None,
        payment_url="https://checkout.example/pay/123",
        extra={
            "_signed_external_api": True,
            "merchant_transaction_id": str(uuid4()),
            "merchant_webhook_url": "https://partner.example/callback",
        },
    )
    project = SimpleNamespace(external_callback_url=None, external_callback_secret=secret)
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

    assert await external_platform.ExternalPlatformService.deliver_merchant_status_for_transaction(session, transaction_id)

    timestamp = received["headers"]["X-Panel-Timestamp"]
    body = json.loads(received["content"])
    assert body["transaction_id"] == transaction.extra["merchant_transaction_id"]
    assert body["status"] == "paid" and body["paid"] is True
    expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + received["content"], hashlib.sha256).hexdigest()
    assert hmac.compare_digest(received["headers"]["X-Panel-Signature"], expected)
    assert "external_callback_secret" not in json.dumps(append_attempt.await_args.args[1].request_payload)
