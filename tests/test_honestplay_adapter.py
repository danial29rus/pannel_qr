import json
import uuid
from dataclasses import replace
from decimal import Decimal
from functools import partial

import httpx
import pytest

from app.db.models import TransactionDirection, TransactionState
from app.payments.adapters.base import CreatePaymentRequest, RetryableProviderError
from app.payments.adapters.honestplay import HonestPlayAdapter
from app.payments.registry import registry

REFERENCE = "550e8400-e29b-41d4-a716-446655440000"


def request():
    return CreatePaymentRequest(reference=REFERENCE, amount=Decimal("100.50"), currency="RUB",
        direction=TransactionDirection.incoming, description="Оплата заказа", extra={}, customer_email="buyer@example.com")


def adapter():
    return HonestPlayAdapter({"api_key":"test-api-key", "base_url":"https://honestplay.example.test"})


def transport(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr("app.payments.adapters.honestplay.httpx.AsyncClient", partial(original, transport=httpx.MockTransport(handler)))


@pytest.mark.asyncio
async def test_create_uses_partner_api_key_uuid_and_customer_email(monkeypatch):
    def handler(req):
        assert req.method == "POST"
        assert req.url.path == "/api/public/payments"
        assert req.headers["X-API-Key"] == "test-api-key"
        assert json.loads(req.content) == {"amount":"100.50", "uuid":REFERENCE, "email":"buyer@example.com", "description":"Оплата заказа"}
        return httpx.Response(201, json={"uuid":REFERENCE, "amount":"100.50", "status":"pending_payment", "payment_status":"pending", "payment_url":"https://api.mulenpay.com/payment/widget/example", "provider_payment_id":2275024})
    transport(monkeypatch, handler)
    result = await adapter().create_payment(request())
    assert result.external_id == REFERENCE
    assert result.amount == Decimal("100.50")
    assert result.state == TransactionState.pending
    assert result.payload["payment_url"].startswith("https://api.mulenpay.com/payment/widget/")
    assert "buyer@example.com" not in json.dumps(result.payload)
    assert "test-api-key" not in json.dumps(result.payload)


@pytest.mark.asyncio
@pytest.mark.parametrize("status, payment_status, provider_status, expected", [
    ("paid", "paid", 3, TransactionState.succeeded),
    ("paid", "pending", 3, TransactionState.pending),
    ("pending_payment", "paid", 3, TransactionState.pending),
    ("pending_payment", "pending", 3, TransactionState.pending),
    ("cancelled", "failed", 4, TransactionState.failed),
    ("cancelled", "cancelled", 2, TransactionState.cancelled),
    ("unknown", "unknown", 3, TransactionState.pending),
])
async def test_status_uses_both_honestplay_statuses_and_minor_units(monkeypatch, status, payment_status, provider_status, expected):
    def handler(req):
        assert req.method == "GET"
        assert req.url.path == f"/api/public/payments/{REFERENCE}"
        return httpx.Response(200, json={"uuid":REFERENCE, "status":status, "payment_status":payment_status,
            "provider_status":provider_status, "amount_minor":10050, "currency":"RUB"})
    transport(monkeypatch, handler)
    result = await adapter().get_payment(REFERENCE)
    assert result.amount == Decimal("100.50")
    assert result.state == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [429, 502, 503])
async def test_retry_preserves_uuid_after_network_or_upstream_error(monkeypatch, code):
    seen=[]
    def handler(req):
        seen.append(json.loads(req.content)["uuid"])
        return httpx.Response(code)
    transport(monkeypatch, handler)
    for _ in range(2):
        with pytest.raises(RetryableProviderError):
            await adapter().create_payment(request())
    assert seen == [REFERENCE, REFERENCE]


@pytest.mark.asyncio
async def test_conflict_is_not_retried_as_new_payment(monkeypatch):
    transport(monkeypatch, lambda req:httpx.Response(409, json={"detail":"UUID conflict"}))
    with pytest.raises(httpx.HTTPStatusError) as error:
        await adapter().create_payment(request())
    assert error.value.response.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"currency":"USD"}, {"amount":Decimal("1.001")}, {"amount":Decimal("10000000.01")},
    {"customer_email":None}, {"customer_email":"not-an-email"}, {"description":"x"*256},
    {"direction":TransactionDirection.outgoing}, {"extra":{"_require_direct_qr":True}},
    {"reference":str(uuid.uuid1())},
])
async def test_invalid_requests_never_reach_the_network(change):
    with pytest.raises(ValueError):
        await adapter().create_payment(replace(request(), **change))


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [
    {"uuid":str(uuid.uuid4()), "amount_minor":10050, "currency":"RUB"},
    {"uuid":REFERENCE, "amount_minor":10050.1, "currency":"RUB"},
    {"uuid":REFERENCE, "amount_minor":10050, "currency":"USD"},
    {"uuid":REFERENCE, "amount_minor":"NaN", "currency":"RUB"},
])
async def test_malformed_status_response_is_not_a_success(monkeypatch, data):
    transport(monkeypatch, lambda req:httpx.Response(200, json={**data, "status":"paid", "payment_status":"paid"}))
    with pytest.raises(RetryableProviderError):
        await adapter().get_payment(REFERENCE)


@pytest.mark.asyncio
async def test_webhooks_disabled_and_registry_config_validation():
    assert isinstance(registry.get("honestplay", {"api_key":"test"}), HonestPlayAdapter)
    assert not await adapter().verify_webhook(b'{"status":"paid"}', {})
    with pytest.raises(ValueError):
        HonestPlayAdapter({"base_url":"http://insecure.test", "api_key":"test"})
    with pytest.raises(ValueError):
        HonestPlayAdapter({})


def test_reference_is_durable_across_new_local_transaction_ids():
    assert adapter().payment_reference(REFERENCE, {}) == REFERENCE
    assert adapter().payment_reference("external-order-stable-key", {"payment_uuid":REFERENCE}) == REFERENCE
    with pytest.raises(ValueError):
        adapter().payment_reference("not-a-uuid", {})
    with pytest.raises(ValueError):
        adapter().payment_reference(str(uuid.uuid1()), {})
