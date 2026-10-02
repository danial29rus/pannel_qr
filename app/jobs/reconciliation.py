"""Periodic closure of pending checkout orders.

The loop is intentionally idempotent: an already terminal order is never
re-opened, and external callbacks use a stable idempotency key.
"""
from datetime import UTC, datetime, timedelta

from app.dao.repositories import OrderDAO, ProjectDAO, ProviderDAO, ProviderRequestAttemptDAO, TransactionDAO
from app.db.models import ProviderRequestAttempt, TransactionState
from app.db.session import SessionLocal
from app.payments.adapters.base import RetryableProviderError
from app.payments.registry import registry
from app.payments.service import apply_provider_update, append_event
from app.services.external_platform import ExternalPlatformService
from app.services.orders import OrderService

TERMINAL = {TransactionState.succeeded, TransactionState.failed, TransactionState.cancelled, TransactionState.refunded}


async def reconcile_open_orders() -> None:
    """Run one bounded reconciliation pass; safe to call repeatedly."""
    async with SessionLocal() as session:
        open_orders = await OrderDAO.list_open(session)
        callback_orders = await OrderDAO.list_requiring_callback(session)
        orders = {order.id: order for order in [*open_orders, *callback_orders]}.values()
    for order in orders:
        try:
            await reconcile_order(order.id)
        except Exception:
            # Individual order failures are recorded as request attempts where a
            # transaction exists; one bad provider must not stop the worker.
            continue


async def reconcile_order(order_id) -> None:
    callback = None
    async with SessionLocal() as session:
        async with session.begin():
            order = await OrderDAO.get(session, order_id)
            if not order or not order.transaction_id:
                return
            transaction = await TransactionDAO.get(session, order.transaction_id)
            project = await ProjectDAO.get(session, order.project_id)
            if not transaction or not project:
                return
            now = datetime.now(UTC)
            if transaction.state in TERMINAL:
                await OrderService.sync_status_from_transaction(session, transaction.id, transaction.state.value)
                callback = (project, order) if order.external_order_id else None
            elif order.created_at + timedelta(minutes=project.payment_expiry_minutes) <= now:
                await append_event(session, transaction, "payment.expired", TransactionState.failed, actor="reconciliation", payload={"expiry_minutes": project.payment_expiry_minutes})
                await OrderService.sync_status_from_transaction(session, transaction.id, TransactionState.failed.value)
                callback = (project, order) if order.external_order_id else None
            elif not order.last_status_checked_at or order.last_status_checked_at + timedelta(seconds=project.status_check_interval_seconds) <= now:
                provider = await ProviderDAO.get(session, transaction.provider_id)
                if not provider:
                    return
                order.last_status_checked_at = now
                attempt = 1
                try:
                    adapter = registry.get(provider.adapter_type, {**provider.settings, **provider.credentials_encrypted})
                    payment = await adapter.get_payment(transaction.external_id or "")
                    await ProviderRequestAttemptDAO.append(session, ProviderRequestAttempt(
                        transaction_id=transaction.id, operation="status_check", attempt=attempt, outcome="success",
                        request_payload={"external_id": transaction.external_id}, response_payload=payment.payload,
                        http_status=200, error=None,
                    ))
                    if payment.amount is not None and payment.amount != transaction.amount:
                        raise ValueError("Provider amount does not match local transaction")
                    if payment.currency and payment.currency.upper() != transaction.currency.upper():
                        raise ValueError("Provider currency does not match local transaction")
                    await apply_provider_update(session, transaction, payment)
                    await OrderService.sync_status_from_transaction(session, transaction.id, transaction.state.value)
                    if transaction.state in TERMINAL and order.external_order_id:
                        callback = (project, order)
                except RetryableProviderError as exc:
                    await ProviderRequestAttemptDAO.append(session, ProviderRequestAttempt(
                        transaction_id=transaction.id, operation="status_check", attempt=attempt, outcome="retryable_error",
                        request_payload={"external_id": transaction.external_id}, response_payload=None,
                        http_status=exc.status_code, error=str(exc),
                    ))
                except Exception as exc:
                    await ProviderRequestAttemptDAO.append(session, ProviderRequestAttempt(
                        transaction_id=transaction.id, operation="status_check", attempt=attempt, outcome="error",
                        request_payload={"external_id": transaction.external_id}, response_payload=None,
                        http_status=None, error=str(exc),
                    ))
        if callback:
            await ExternalPlatformService.deliver_final_status(session, *callback)
