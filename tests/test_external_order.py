from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.schemas import ExternalOrderCreate
from app.api.schemas import MerchantQrPaymentCreate
from app.payments.service import PaymentService
from app.services.orders import OrderService
import app.services.orders as orders_service
import app.payments.service as payments_service


class WriteSession:
    def __init__(self):
        self.refresh = AsyncMock()

    def begin(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


def test_merchant_qr_accepts_disabled_auto_amount_selection():
    payload = MerchantQrPaymentCreate(
        amount=Decimal("100"), currency="RUB", merchant_transaction_id="merchant-qr-auto-off",
        auto_amount_step=1, auto_amount_limit=0,
    )

    assert payload.auto_amount_limit == 0


@pytest.mark.asyncio
async def test_external_order_closes_read_transaction_before_creating_payment(monkeypatch):
    session = SimpleNamespace(rollback=AsyncMock())
    project_id = uuid4()
    product = SimpleNamespace(id=uuid4(), is_active=True, currency="RUB", price=Decimal("50"), sku="SKU-1")
    created_order = SimpleNamespace(id="order-1")
    create_order = AsyncMock(return_value=created_order)

    monkeypatch.setattr(orders_service.OrderDAO, "get_by_external_id", AsyncMock(return_value=None))
    monkeypatch.setattr(orders_service.ProductDAO, "get_by_project_sku", AsyncMock(return_value=product))
    monkeypatch.setattr(OrderService, "create_order", create_order)

    result = await OrderService.create_external_order(
        session,
        project_id,
        ExternalOrderCreate(
            external_order_id="external-1", user_id=uuid4(), product_sku="SKU-1",
            quantity=1, amount=Decimal("50"), currency="RUB",
        ),
    )

    assert result is created_order
    session.rollback.assert_awaited_once()
    assert create_order.await_args.args[1].product_id == product.id


@pytest.mark.asyncio
async def test_merchant_qr_uses_random_email_buyer(monkeypatch):
    session = WriteSession()
    project_id = uuid4()
    buyer_id = uuid4()
    transaction = SimpleNamespace(id=uuid4())
    create = AsyncMock(return_value=transaction)

    monkeypatch.setattr(payments_service.TransactionDAO, "get_by_idempotency", AsyncMock(return_value=None))
    monkeypatch.setattr(payments_service.UserDAO, "random_active_with_email", AsyncMock(return_value=SimpleNamespace(id=buyer_id)))
    monkeypatch.setattr(payments_service, "create_transaction", create)

    result = await PaymentService.create_merchant_qr_payment(
        session, project_id,
        MerchantQrPaymentCreate(amount=Decimal("25"), currency="RUB", merchant_transaction_id="merchant-qr-1"),
    )

    assert result is transaction
    session.refresh.assert_awaited_once_with(transaction)
    payload = create.await_args.args[1]
    assert payload.user_id == buyer_id
    assert payload.description == "QR payment merchant-qr-1"
    assert payload.extra["merchant_transaction_id"] == "merchant-qr-1"
    assert create.await_args.args[2] == "merchant-qr:merchant-qr-1"


@pytest.mark.asyncio
async def test_merchant_qr_reuses_existing_transaction_without_selecting_a_buyer(monkeypatch):
    session = WriteSession()
    project_id = uuid4()
    existing = SimpleNamespace(id=uuid4())
    select_buyer = AsyncMock()
    create = AsyncMock()

    monkeypatch.setattr(payments_service.TransactionDAO, "get_by_idempotency", AsyncMock(return_value=existing))
    monkeypatch.setattr(payments_service.UserDAO, "random_active_with_email", select_buyer)
    monkeypatch.setattr(payments_service, "create_transaction", create)

    result = await PaymentService.create_merchant_qr_payment(
        session, project_id,
        MerchantQrPaymentCreate(amount=Decimal("25"), currency="RUB", merchant_transaction_id="merchant-qr-repeat"),
    )

    assert result is existing
    select_buyer.assert_not_awaited()
    create.assert_not_awaited()
    session.refresh.assert_awaited_once_with(existing)


@pytest.mark.asyncio
async def test_merchant_qr_returns_503_when_buyer_pool_is_empty(monkeypatch):
    session = WriteSession()
    create = AsyncMock()
    monkeypatch.setattr(payments_service.TransactionDAO, "get_by_idempotency", AsyncMock(return_value=None))
    monkeypatch.setattr(payments_service.UserDAO, "random_active_with_email", AsyncMock(return_value=None))
    monkeypatch.setattr(payments_service, "create_transaction", create)

    with pytest.raises(HTTPException) as error:
        await PaymentService.create_merchant_qr_payment(
            session, uuid4(),
            MerchantQrPaymentCreate(amount=Decimal("25"), currency="RUB", merchant_transaction_id="merchant-qr-no-buyer"),
        )

    assert error.value.status_code == 503
    create.assert_not_awaited()
    session.refresh.assert_not_awaited()
