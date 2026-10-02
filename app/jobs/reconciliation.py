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
        direct_transaction_ids = await TransactionDAO.list_open_without_order(session)
        merchant_callback_transaction_ids = await TransactionDAO.list_requiring_merchant_callback(session)
    for order in orders:
        try:
            await reconcile_order(order.id)
        except Exception:
            # Individual order failures are recorded as request attempts where a
            # transaction exists; one bad provider must not stop the worker.
            continue
    for transaction_id in direct_transaction_ids:
        try:
            await reconcile_direct_transaction(transaction_id)
        except Exception:
            # The next scheduled pass retries transient provider failures.
            continue
    for transaction_id in merchant_callback_transaction_ids:
        try:
            async with SessionLocal() as session:
                await ExternalPlatformService.deliver_merchant_status_for_transaction(session, transaction_id)
        except Exception:
            # A failed merchant endpoint is retried on the next pass and every
            # attempt remains in the transaction trace.
            continue


async def reconcile_direct_transaction(transaction_id) -> None:
    """Poll a pending payment created via /transactions, without an Order."""
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        async with session.begin():
            transaction = await TransactionDAO.get(session, transaction_id)
            if not transaction or transaction.state in TERMINAL:
                return
            project = await ProjectDAO.get(session, transaction.project_id)
            provider = await ProviderDAO.get(session, transaction.provider_id)
            if not project or not provider:
                return
            if transaction.created_at + timedelta(minutes=project.payment_expiry_minutes) <= now:
                await append_event(session, transaction, "payment.expired", TransactionState.failed, actor="reconciliation", payload={"expiry_minutes": project.payment_expiry_minutes})
                return
            if transaction.last_status_checked_at and transaction.last_status_checked_at + timedelta(seconds=project.status_check_interval_seconds) > now:
                return
            # Reserve this polling window before making the provider request so
            # parallel worker iterations cannot poll the same payment twice.
            transaction.last_status_checked_at = now
            provider_id = provider.id
            provider_config = {**provider.settings, **provider.credentials_encrypted}
            provider_type = provider.adapter_type
            external_id = transaction.external_id or ""

        try:
            adapter = registry.get(provider_type, provider_config)
            payment = await adapter.get_payment(external_id)
        except RetryableProviderError as exc:
            async with session.begin():
                await ProviderRequestAttemptDAO.append(session, ProviderRequestAttempt(
                    transaction_id=transaction_id, operation="status_check", attempt=1, outcome="retryable_error",
                    request_payload={"external_id": external_id}, response_payload=None, http_status=exc.status_code, error=str(exc),
                ))
            return
        except Exception as exc:
            async with session.begin():
                await ProviderRequestAttemptDAO.append(session, ProviderRequestAttempt(
                    transaction_id=transaction_id, operation="status_check", attempt=1, outcome="error",
                    request_payload={"external_id": external_id}, response_payload=None, http_status=None, error=str(exc),
                ))
            return

        async with session.begin():
            transaction = await TransactionDAO.get_by_provider_external_for_update(session, provider_id, payment.external_id)
            if not transaction or transaction.state in TERMINAL:
                return
            await ProviderRequestAttemptDAO.append(session, ProviderRequestAttempt(
                transaction_id=transaction.id, operation="status_check", attempt=1, outcome="success",
                request_payload={"external_id": external_id}, response_payload=payment.payload, http_status=200, error=None,
            ))
            if payment.amount is not None and payment.amount != transaction.amount:
                raise ValueError("Provider amount does not match local transaction")
            if payment.currency and payment.currency.upper() != transaction.currency.upper():
                raise ValueError("Provider currency does not match local transaction")
            await apply_provider_update(session, transaction, payment)


async def reconcile_order(order_id) -> None:
    """Reconcile an order-backed payment without holding a DB transaction during HTTP.

    A slow provider must never keep PostgreSQL locks open.  The first short
    transaction reserves the check window, the provider is queried outside the
    database transaction, and the second short transaction applies the result.
    """
    callback_order_id = None
    poll_context = None
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
                callback_order_id = order.id if order.external_order_id else None
            elif order.created_at + timedelta(minutes=project.payment_expiry_minutes) <= now:
                await append_event(session, transaction, "payment.expired", TransactionState.failed, actor="reconciliation", payload={"expiry_minutes": project.payment_expiry_minutes})
                await OrderService.sync_status_from_transaction(session, transaction.id, TransactionState.failed.value)
                callback_order_id = order.id if order.external_order_id else None
            elif not order.last_status_checked_at or order.last_status_checked_at + timedelta(seconds=project.status_check_interval_seconds) <= now:
                provider = await ProviderDAO.get(session, transaction.provider_id)
                if not provider:
                    return
                order.last_status_checked_at = now
                poll_context = {
                    "transaction_id": transaction.id,
                    "provider_id": provider.id,
                    "provider_type": provider.adapter_type,
                    "provider_config": {**provider.settings, **provider.credentials_encrypted},
                    "external_id": transaction.external_id or "",
                }

        if poll_context:
            try:
                adapter = registry.get(poll_context["provider_type"], poll_context["provider_config"])
                payment = await adapter.get_payment(poll_context["external_id"])
            except RetryableProviderError as exc:
                async with session.begin():
                    await ProviderRequestAttemptDAO.append(session, ProviderRequestAttempt(
                        transaction_id=poll_context["transaction_id"], operation="status_check", attempt=1,
                        outcome="retryable_error", request_payload={"external_id": poll_context["external_id"]},
                        response_payload=None, http_status=exc.status_code, error=str(exc),
                    ))
            except Exception as exc:
                async with session.begin():
                    await ProviderRequestAttemptDAO.append(session, ProviderRequestAttempt(
                        transaction_id=poll_context["transaction_id"], operation="status_check", attempt=1,
                        outcome="error", request_payload={"external_id": poll_context["external_id"]},
                        response_payload=None, http_status=None, error=str(exc),
                    ))
            else:
                async with session.begin():
                    transaction = await TransactionDAO.get_by_provider_external_for_update(
                        session, poll_context["provider_id"], payment.external_id,
                    )
                    if transaction and transaction.state not in TERMINAL:
                        await ProviderRequestAttemptDAO.append(session, ProviderRequestAttempt(
                            transaction_id=transaction.id, operation="status_check", attempt=1, outcome="success",
                            request_payload={"external_id": poll_context["external_id"]}, response_payload=payment.payload,
                            http_status=200, error=None,
                        ))
                        if payment.amount is not None and payment.amount != transaction.amount:
                            raise ValueError("Provider amount does not match local transaction")
                        if payment.currency and payment.currency.upper() != transaction.currency.upper():
                            raise ValueError("Provider currency does not match local transaction")
                        await apply_provider_update(session, transaction, payment)
                        order = await OrderService.sync_status_from_transaction(session, transaction.id, transaction.state.value)
                        if order and order.external_order_id and transaction.state in TERMINAL:
                            callback_order_id = order.id
        if callback_order_id:
            await ExternalPlatformService.deliver_final_status_for_order(session, callback_order_id)
