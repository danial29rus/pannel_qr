import uuid
from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.schemas import ExternalOrderCreate, OrderCreate, ProductCreate
from app.dao.repositories import OrderDAO, ProductDAO, ProjectDAO, UserDAO
from app.db.models import Order, Product
from app.payments.service import create_transaction
from app.api.schemas import TransactionCreate

class OrderService:
    @staticmethod
    async def create_product(session: AsyncSession, payload: ProductCreate) -> Product:
        if not await ProjectDAO.get(session, payload.project_id): raise HTTPException(404, "Project not found")
        product = await ProductDAO.create(session, Product(**{**payload.model_dump(), "currency": payload.currency.upper()}))
        await session.commit(); await session.refresh(product); return product

    @staticmethod
    async def list_products(session: AsyncSession, project_id: uuid.UUID) -> list[Product]:
        return await ProductDAO.list_by_project(session, project_id)

    @staticmethod
    async def create_order(session: AsyncSession, payload: OrderCreate, idempotency_key: str, external_order_id: str | None = None) -> Order:
        async with session.begin():
            if existing := await OrderDAO.get_by_idempotency(session, payload.project_id, idempotency_key): return existing
            product = await ProductDAO.get(session, payload.product_id)
            if not product or product.project_id != payload.project_id or not product.is_active: raise HTTPException(422, "Active product for this project not found")
            if not await UserDAO.get(session, payload.user_id): raise HTTPException(404, "User not found")
            amount = product.price * payload.quantity; reference = f"ord_{uuid.uuid4().hex}"
            snapshot = {"sku": product.sku, "name": product.name, "price": str(product.price), "vat_code": product.vat_code, "payment_subject": product.payment_subject, "payment_mode": product.payment_mode, "measurement_unit": product.measurement_unit}
            order = await OrderDAO.create(session, Order(project_id=payload.project_id, user_id=payload.user_id, product_id=product.id, idempotency_key=idempotency_key, external_order_id=external_order_id, reference=reference, product_snapshot=snapshot, quantity=payload.quantity, amount=amount, currency=product.currency))
            tx = await create_transaction(session, TransactionCreate(project_id=payload.project_id, user_id=payload.user_id, provider_code=payload.provider_code, amount=amount, currency=product.currency, description=f"Заказ {reference}: {product.name}", extra={"website_url": payload.website_url, "language": payload.language, "items": [{"description": product.name, "quantity": payload.quantity, "price": float(product.price), "vat_code": product.vat_code, "payment_subject": product.payment_subject, "payment_mode": product.payment_mode, "product_code": product.sku, "measurement_unit": product.measurement_unit}]}), f"order:{idempotency_key}")
            order.transaction_id = tx.id
            order.payment_url = tx.payment_url
            order.status = tx.state.value
        await session.refresh(order); return order

    @staticmethod
    async def create_external_order(session: AsyncSession, project_id: uuid.UUID, payload: ExternalOrderCreate) -> Order:
        if existing := await OrderDAO.get_by_external_id(session, project_id, payload.external_order_id):
            return existing
        product = await ProductDAO.get_by_project_sku(session, project_id, payload.product_sku)
        if not product or not product.is_active:
            raise HTTPException(422, "Active product with this SKU was not found")
        if product.currency.upper() != payload.currency.upper():
            raise HTTPException(422, "Order currency does not match product currency")
        expected_amount = product.price * payload.quantity
        if expected_amount != payload.amount:
            raise HTTPException(422, {
                "code": "amount_mismatch",
                "expected_amount": str(expected_amount),
                "received_amount": str(payload.amount),
                "product_sku": product.sku,
            })
        return await OrderService.create_order(
            session,
            OrderCreate(project_id=project_id, user_id=payload.user_id, product_id=product.id, quantity=payload.quantity,
                        website_url=payload.website_url, language=payload.language),
            f"external:{payload.external_order_id}", payload.external_order_id,
        )

    @staticmethod
    async def sync_status_from_transaction(session: AsyncSession, transaction_id: uuid.UUID, status: str) -> Order | None:
        order = await OrderDAO.get_by_transaction(session, transaction_id)
        if not order:
            return None
        order.status = status
        await OrderDAO.save(session, order)
        return order
