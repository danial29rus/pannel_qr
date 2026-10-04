from decimal import Decimal

import httpx
import pytest

from app.db.models import TransactionDirection, TransactionState
from app.payments.adapters.base import CreatePaymentRequest, RetryableProviderError
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


@pytest.mark.asyncio
async def test_create_payment_returns_hosted_url_without_opening_payment_widget(monkeypatch):
    hosted_url = "https://api.mulenpay.com/payment/widget/widget-id"

    class PaymentClient(FakeClient):
        requested_urls = []
        requested_json = None

        async def post(self, url, **kwargs):
            type(self).requested_urls.append(url)
            type(self).requested_json = kwargs["json"]
            return FakeResponse({"id": 42, "paymentUrl": hosted_url})

    monkeypatch.setattr("app.payments.adapters.mulenpay.httpx.AsyncClient", PaymentClient)

    payment = await adapter().create_payment(CreatePaymentRequest(
        reference="merchant-order-1", amount=Decimal("10"), currency="RUB",
        direction=TransactionDirection.incoming, description="Test", extra={"hold_time_seconds": 900}, customer_email="buyer@example.com",
    ))

    assert PaymentClient.requested_urls == ["https://api.mulenpay.com/api/v2/payments"]
    assert PaymentClient.requested_json["holdTime"] == 900
    assert payment.payload["payment_url"] == hosted_url
