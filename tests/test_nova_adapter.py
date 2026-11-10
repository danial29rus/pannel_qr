import json
from decimal import Decimal

import pytest

from app.db.models import TransactionDirection, TransactionState
from app.payments.adapters.base import CreatePaymentRequest
from app.payments.adapters.nova import NovaAdapter


class FakeResponse:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


def fake_client(routes):
    class Client:
        calls = []

        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def request(self, method, url, headers=None, json=None):
            Client.calls.append((method, url, headers, json))
            payload = routes[(method, url)]
            if isinstance(payload, list):
                return FakeResponse(payload.pop(0))
            return FakeResponse(payload)

        async def get(self, url, headers=None):
            return await self.request("GET", url, headers=headers)
    return Client


def request():
    return CreatePaymentRequest(
        reference="db1a1f42-c481-4b46-93b6-d7d06022db1d",
        amount=Decimal("500"), currency="RUB", direction=TransactionDirection.incoming,
        description=None, extra={"merchant_transaction_id": "3f1c2a9e-6b7d-4e21-9c55-0d8a1b2c3d4e"},
    )


@pytest.mark.asyncio
async def test_create_uses_merchant_uuid_and_prefers_direct_qr(monkeypatch):
    transaction_id = "3f1c2a9e-6b7d-4e21-9c55-0d8a1b2c3d4e"
    url = "https://24nova-ai.ru/api/v1/external/payments"
    client = fake_client({("POST", url): {"transaction_id": transaction_id, "amount_rub": 500, "status": "pending", "paid": False, "payment_url": "https://pay.example", "qr_url": "https://qr.nspk.ru/NOVA"}})
    monkeypatch.setattr("app.payments.adapters.nova.httpx.AsyncClient", client)

    payment = await NovaAdapter({"token": "secret"}).create_payment(request())

    method, called_url, headers, body = client.calls[0]
    assert (method, called_url, headers["Authorization"]) == ("POST", url, "Bearer secret")
    assert body == {"transaction_id": transaction_id, "user_id": 1, "amount_rub": 500}
    assert (payment.external_id, payment.state, payment.payload["payment_url"]) == (transaction_id, TransactionState.pending, "https://qr.nspk.ru/NOVA")


@pytest.mark.asyncio
async def test_status_returns_hosted_link_and_terminal_state(monkeypatch):
    transaction_id = "3f1c2a9e-6b7d-4e21-9c55-0d8a1b2c3d4e"
    url = f"https://24nova-ai.ru/api/v1/external/payments/{transaction_id}"
    client = fake_client({("GET", url): {"transaction_id": transaction_id, "amount_rub": 500, "status": "succeeded", "paid": True, "payment_url": None, "qr_url": None}})
    monkeypatch.setattr("app.payments.adapters.nova.httpx.AsyncClient", client)

    payment = await NovaAdapter({"token": "secret"}).get_payment(transaction_id)

    assert payment.state == TransactionState.succeeded
    assert payment.amount == Decimal("500")


@pytest.mark.asyncio
async def test_create_reads_qr_from_payhot_when_nova_has_no_qr(monkeypatch):
    transaction_id = "3f1c2a9e-6b7d-4e21-9c55-0d8a1b2c3d4e"
    public_id = "01a1c6d7-c40e-7542-bd98-28fdbbfd39b2"
    token = "phc_v2.test-token"
    nova_url = "https://24nova-ai.ru/api/v1/external/payments"
    payhot_url = f"https://go.pay.hot/api/v2/checkout-sessions/{public_id}"
    client = fake_client({
        ("POST", nova_url): {"transaction_id": transaction_id, "amount_rub": 500, "status": "pending", "paid": False, "payment_url": f"https://go.pay.hot/pay/{public_id}#token={token}", "qr_url": None},
        ("GET", payhot_url): {"next_action": {"type": "qr", "value": "https://qr.nspk.ru/NOVA-PAYHOT"}},
    })
    monkeypatch.setattr("app.payments.adapters.nova.httpx.AsyncClient", client)

    payment = await NovaAdapter({"token": "secret"}).create_payment(request())

    assert payment.state == TransactionState.pending
    assert payment.payload["payment_url"] == "https://qr.nspk.ru/NOVA-PAYHOT"
    assert client.calls[1][2]["X-Payhot-Checkout-Token"] == token


@pytest.mark.asyncio
async def test_create_retries_payhot_until_qr_is_ready(monkeypatch):
    transaction_id = "3f1c2a9e-6b7d-4e21-9c55-0d8a1b2c3d4e"
    public_id = "01a1c6d7-c40e-7542-bd98-28fdbbfd39b2"
    nova_url = "https://24nova-ai.ru/api/v1/external/payments"
    payhot_url = f"https://go.pay.hot/api/v2/checkout-sessions/{public_id}"
    client = fake_client({
        ("POST", nova_url): {"transaction_id": transaction_id, "amount_rub": 500, "status": "pending", "paid": False, "payment_url": f"https://go.pay.hot/pay/{public_id}#token=phc_v2.test", "qr_url": None},
        ("GET", payhot_url): [
            {"next_action": None},
            {"next_action": {"type": "qr", "value": "https://qr.nspk.ru/READY"}},
        ],
    })
    monkeypatch.setattr("app.payments.adapters.nova.httpx.AsyncClient", client)

    async def no_sleep(_):
        pass
    monkeypatch.setattr("app.payments.adapters.nova.asyncio.sleep", no_sleep)

    payment = await NovaAdapter({"token": "secret"}).create_payment(request())

    assert payment.payload["payment_url"] == "https://qr.nspk.ru/READY"
    assert len(payment.payload["payhot_checkout_attempts"]) == 2


@pytest.mark.asyncio
async def test_create_resolves_payhot_url_even_when_nova_puts_it_in_qr_url(monkeypatch):
    transaction_id = "3f1c2a9e-6b7d-4e21-9c55-0d8a1b2c3d4e"
    public_id = "01a1c6d7-c40e-7542-bd98-28fdbbfd39b2"
    nova_url = "https://24nova-ai.ru/api/v1/external/payments"
    payhot_url = f"https://go.pay.hot/api/v2/checkout-sessions/{public_id}"
    client = fake_client({
        ("POST", nova_url): {"transaction_id": transaction_id, "amount_rub": 500, "status": "pending", "paid": False, "payment_url": None, "qr_url": f"https://go.pay.hot/pay/{public_id}#token=phc_v2.test"},
        ("GET", payhot_url): {"next_action": {"type": "qr", "value": "https://qr.nspk.ru/FROM-QR-FIELD"}},
    })
    monkeypatch.setattr("app.payments.adapters.nova.httpx.AsyncClient", client)

    payment = await NovaAdapter({"token": "secret"}).create_payment(request())

    assert payment.payload["payment_url"] == "https://qr.nspk.ru/FROM-QR-FIELD"
