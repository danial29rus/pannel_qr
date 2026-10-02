from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.api.schemas import ExternalOrderCreate
from app.services.orders import OrderService
import app.services.orders as orders_service


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
