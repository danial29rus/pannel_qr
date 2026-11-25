import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.db.models import TransactionDirection, TransactionState
from app.payments.adapters.base import CreatePaymentRequest, RetryableProviderError
from app.payments.adapters.json_api import JsonApiAdapter


def vitrina_config():
    return {
        "base_url": "https://vitrina-studio.ru",
        "api_token": "test-vitrina-token",
        "request_template": {
            "transaction_id": "{{transaction_id}}",
            "email": "{{email}}",
            "amount_rub": "{{amount_rub}}",
        },
        "response_paths": {
            "id": "transaction_id",
            "request_id": "transaction_id",
            "status": "status",
            "amount": "amount_rub",
            "payment_url": "payment_url",
            "qr_url": "qr_url",
        },
        "status_map": {
            "pending": "pending",
            "succeeded": "succeeded",
            "failed": "failed",
            "canceled": "cancelled",
        },
    }


def payment_request(reference=None, amount=Decimal("500")):
    return CreatePaymentRequest(
        reference=str(reference or uuid4()), amount=amount, currency="RUB",
        direction=TransactionDirection.incoming, description="Test order", extra={},
        customer_email="buyer@example.com",
    )


class FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload

    def raise_for_status(self):
        return None


@pytest.mark.asyncio
async def test_vitrina_create_extracts_direct_nspk_url_from_mulen_checkout(monkeypatch):
    reference = str(uuid4())
    request = payment_request(reference)
    calls = []
    config = vitrina_config()
    config["extract_sbp_qr"] = True

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def request(self, method, url, **kwargs):
            calls.append((method, url, kwargs))
            if method == "GET":
                return FakeResponse({"data": {"qrpayload": "https://qr.nspk.ru/ABCD1234"}})
            return FakeResponse({
                "transaction_id": reference,
                "amount_rub": 500,
                "status": "pending",
                "payment_url": "https://checkout.mulenpay.example/pay/123",
                "qr_url": "https://checkout.mulenpay.example/pay/123",
            })

        async def get(self, url):
            return await self.request("GET", url)

    monkeypatch.setattr("app.payments.adapters.json_api.httpx.AsyncClient", FakeClient)
    adapter = JsonApiAdapter(config)
    payment = await adapter.create_payment(request)

    method, url, kwargs = calls[0]
    assert method == "POST"
    assert url == "https://vitrina-studio.ru/api/v1/external/payments"
    assert kwargs["headers"]["Authorization"] == "Bearer test-vitrina-token"
    body = json.loads(kwargs["content"])
    assert body == {"transaction_id": reference, "email": "buyer@example.com", "amount_rub": 500}
    assert payment.external_id == reference
    assert payment.state == TransactionState.pending
    assert calls[1][0:2] == ("GET", "https://checkout.mulenpay.example/pay/123/sbp")
    assert payment.payload["payment_url"] == "https://qr.nspk.ru/ABCD1234"
    assert payment.payload["qr_url"] == "https://qr.nspk.ru/ABCD1234"
    assert payment.payload["hosted_payment_url"] == "https://checkout.mulenpay.example/pay/123"


@pytest.mark.asyncio
async def test_vitrina_create_fails_if_mulen_does_not_return_direct_nspk(monkeypatch):
    config = vitrina_config()
    config["extract_sbp_qr"] = True
    calls = []

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def request(self, method, url, **kwargs):
            calls.append((method, url, kwargs))
            if method == "GET":
                return FakeResponse({"data": {"qrpayload": "https://checkout.mulenpay.example/not-nspk"}})
            return FakeResponse({
                "transaction_id": request.reference,
                "amount_rub": 500,
                "status": "pending",
                "payment_url": "https://checkout.mulenpay.example/pay/123",
                "qr_url": "https://checkout.mulenpay.example/pay/123",
            })

        async def get(self, url):
            return await self.request("GET", url)

    monkeypatch.setattr("app.payments.adapters.json_api.httpx.AsyncClient", FakeClient)
    monkeypatch.setattr("app.payments.adapters.mulenpay.asyncio.sleep", AsyncMock())
    request = payment_request()
    with pytest.raises(RetryableProviderError, match="direct https://qr.nspk.ru"):
        await JsonApiAdapter(config).create_payment(request)
    assert [call[0] for call in calls] == ["POST", "GET", "GET"]


@pytest.mark.asyncio
async def test_vitrina_status_maps_terminal_state_and_encodes_external_id(monkeypatch):
    reference = str(uuid4())
    calls = []

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def request(self, method, url, **kwargs):
            calls.append((method, url, kwargs))
            return FakeResponse({
                "transaction_id": reference, "amount_rub": 500,
                "status": "succeeded", "paid": True, "payment_url": None,
            })

    monkeypatch.setattr("app.payments.adapters.json_api.httpx.AsyncClient", FakeClient)
    payment = await JsonApiAdapter(vitrina_config()).get_payment(reference)

    assert calls[0][0:2] == ("GET", f"https://vitrina-studio.ru/api/v1/external/payments/{reference}")
    assert payment.state == TransactionState.succeeded
    assert payment.amount == Decimal("500")


def test_json_api_rejects_fractional_rubles_for_vitrina():
    adapter = JsonApiAdapter(vitrina_config())
    with pytest.raises(ValueError, match="whole-unit"):
        adapter.validate_payment_request(payment_request(amount=Decimal("500.50")))


def test_json_api_rejects_non_https_provider_url():
    config = vitrina_config()
    config["base_url"] = "http://vitrina-studio.ru"
    with pytest.raises(ValueError, match="HTTPS"):
        JsonApiAdapter(config)


def test_json_api_requires_safe_status_path_template():
    config = vitrina_config()
    config["status_path"] = "https://attacker.example/{transaction_id}"
    with pytest.raises(ValueError, match="relative absolute paths"):
        JsonApiAdapter(config)
