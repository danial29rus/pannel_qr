import hashlib
import json
from collections import Counter
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.db.models import TransactionDirection, TransactionState
from app.payments.adapters.aipay import AIPayAdapter
from app.payments.adapters.base import CreatePaymentRequest
from app.services.routing import RoutingService


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code, self._payload, self.text = status_code, payload, json.dumps(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


def fake_client(routes):
    """routes: {(method, url_suffix): payload}"""
    class Client:
        calls = []

        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass

        async def request(self, method, url, headers=None, json=None):
            Client.calls.append((method, url, headers, json))
            for (m, suffix), payload in routes.items():
                if m == method and url.endswith(suffix):
                    return FakeResponse(200, payload)
            raise AssertionError(url)

        async def get(self, url):
            return await self.request("GET", url)

        async def post(self, url, json=None):
            return await self.request("POST", url, json=json)
    return Client


def request():
    return CreatePaymentRequest(reference="ref-1", amount=Decimal("120.5"), currency="usd",
                                direction=TransactionDirection.incoming, description=None, extra={})


DETAILS = {"uid": "abc", "payment_methods": [{"id": 17, "name": "СБП QR (НСПК)"}], "payment_attributes": None}
CREATED = {"payment_url": "https://pay.aipay.onl/checkout/abc", "uid": "abc"}


async def no_sleep(_):
    pass


@pytest.mark.asyncio
async def test_create_selects_sbp_and_returns_nspk(monkeypatch):
    client = fake_client({
        ("POST", "/v2/order/create"): CREATED,
        ("GET", "/v2/order/get-order-details/abc"): DETAILS,
        ("POST", "/v2/order/select-payment-method"): {"payment_attributes": {"qr_code": "https://qr.nspk.ru/AD1"}},
    })
    monkeypatch.setattr("app.payments.adapters.aipay.httpx.AsyncClient", client)
    payment = await AIPayAdapter({"api_key": "k"}).create_payment(request())
    method, url, headers, body = client.calls[0]
    assert (method, url, headers["api-key"], body) == ("POST", "https://ads.aipay.onl/api/v2/order/create", "k", {"amount": 120.5, "currency": "RUB"})
    assert client.calls[2][3] == {"uid": "abc", "payment_method_id": 17}
    assert payment.external_id == "abc"
    assert payment.state == TransactionState.pending
    assert payment.payload["payment_url"] == "https://qr.nspk.ru/AD1"
    assert payment.payload["hosted_payment_url"] == CREATED["payment_url"]


@pytest.mark.asyncio
async def test_create_fails_without_nspk(monkeypatch):
    client = fake_client({
        ("POST", "/v2/order/create"): CREATED,
        ("GET", "/v2/order/get-order-details/abc"): DETAILS,
        ("POST", "/v2/order/select-payment-method"): {"payment_attributes": {}},
    })
    monkeypatch.setattr("app.payments.adapters.aipay.httpx.AsyncClient", client)
    monkeypatch.setattr("app.payments.adapters.aipay.asyncio.sleep", no_sleep)
    payment = await AIPayAdapter({"api_key": "k"}).create_payment(request())
    assert payment.state == TransactionState.failed
    assert payment.payload["payment_url"] is None
    assert payment.payload["error"]["code"] == "sbp_qr_unavailable"
    assert len(payment.payload["sbp"]["failed_attempts"]) == 2


@pytest.mark.asyncio
async def test_status_and_webhook(monkeypatch):
    client = fake_client({("GET", "/v2/order/status/abc"): {"uid": "abc", "amount": "100.0000000000", "currency": {"id": 3, "name": "RUB"}, "status": {"id": 3}}})
    monkeypatch.setattr("app.payments.adapters.aipay.httpx.AsyncClient", client)
    adapter = AIPayAdapter({"api_key": "k"})
    payment = await adapter.get_payment("abc")
    assert (payment.state, payment.amount, payment.currency) == (TransactionState.succeeded, Decimal("100"), "RUB")
    good = json.dumps({"uid": "abc", "signature": hashlib.md5(b"abc:k").hexdigest(), "status": {"id": 5}}).encode()
    assert await adapter.verify_webhook(good, {})
    assert not await adapter.verify_webhook(json.dumps({"uid": "abc", "signature": "x"}).encode(), {})
    assert (await adapter.parse_webhook(good)).state == TransactionState.cancelled


def test_weighted_pick_splits_best_priority_only():
    def item(name, priority, weight):
        return SimpleNamespace(priority=priority, weight=weight), name, None
    candidates = [item("mulen", 100, 70), item("aipay", 100, 30), item("backup", 200, 1000)]
    counts = Counter(RoutingService.pick_weighted(candidates)[1] for _ in range(5000))
    assert counts["backup"] == 0
    assert 0.6 < counts["mulen"] / 5000 < 0.8
