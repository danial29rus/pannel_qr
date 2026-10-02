from decimal import Decimal

import httpx
import pytest

from app.db.models import TransactionState
from app.payments.adapters.base import RetryableProviderError
from app.payments.adapters.mulenpay import MulenPayAdapter


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = "provider response"

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://example.test")
            raise httpx.HTTPStatusError("bad response", request=request, response=httpx.Response(self.status_code, request=request))

    def json(self):
        return self._payload


class FakeClient:
    response = FakeResponse({})
    requested_url = None
    requested_json = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, **kwargs):
        type(self).requested_url = url
        return type(self).response

    async def post(self, url, **kwargs):
        type(self).requested_url = url
        type(self).requested_json = kwargs["json"]
        return type(self).response


def adapter(base_url="https://api.mulenpay.com/api"):
    return MulenPayAdapter({"api_key": "api", "secret_key": "secret", "shop_id": "5", "base_url": base_url})


def test_uses_documented_v2_endpoint():
    assert adapter().payments_url == "https://api.mulenpay.com/api/v2/payments"
    assert adapter("https://api.mulenpay.com/api/v2/payments").payments_url == "https://api.mulenpay.com/api/v2/payments"


@pytest.mark.asyncio
async def test_get_payment_maps_success_state(monkeypatch):
    FakeClient.response = FakeResponse({"payment": {"id": 42, "status": 3, "amount": "50.00", "currency": "rub"}})
    monkeypatch.setattr("app.payments.adapters.mulenpay.httpx.AsyncClient", FakeClient)

    payment = await adapter().get_payment("42")

    assert FakeClient.requested_url.endswith("/v2/payments/42")
    assert payment.external_id == "42"
    assert payment.state is TransactionState.succeeded
    assert payment.amount == Decimal("50.00")
    assert payment.currency == "RUB"


@pytest.mark.asyncio
async def test_provider_timeout_is_retryable(monkeypatch):
    class BrokenClient(FakeClient):
        async def get(self, *args, **kwargs):
            raise httpx.ConnectError("offline", request=httpx.Request("GET", "https://example.test"))

    monkeypatch.setattr("app.payments.adapters.mulenpay.httpx.AsyncClient", BrokenClient)

    with pytest.raises(RetryableProviderError):
        await adapter().get_payment("42")
