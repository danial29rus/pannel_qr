import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import TransactionCreate
from app.dao.repositories import LimitDAO, ProjectDAO, ProviderDAO, ProviderRequestAttemptDAO, TransactionDAO, TransactionEventDAO, UserDAO
from app.db.models import LimitPeriod, ProviderRequestAttempt, Transaction, TransactionEvent, TransactionState
from app.payments.adapters.base import RetryableProviderError
from app.payments.adapters.base import CreatePaymentRequest, ProviderPayment
from app.payments.registry import registry
from app.services.policies import OperationalPolicyService
from app.services.routing import RoutingService
from app.services.external_platform import ExternalPlatformService

LIMIT_COUNTED_STATES = (TransactionState.created, TransactionState.pending, TransactionState.processing, TransactionState.succeeded)
VALID_TRANSITIONS: dict[TransactionState, set[TransactionState]] = {
    TransactionState.created: {TransactionState.pending, TransactionState.processing, TransactionState.failed, TransactionState.cancelled},
    TransactionState.pending: {TransactionState.processing, TransactionState.succeeded, TransactionState.failed, TransactionState.cancelled},
    TransactionState.processing: {TransactionState.succeeded, TransactionState.failed, TransactionState.cancelled},
    TransactionState.succeeded: {TransactionState.refunded},
    TransactionState.failed: set(),
    TransactionState.cancelled: set(),
    TransactionState.refunded: set(),
}


def period_start(period: LimitPeriod, now: datetime) -> datetime:
    now = now.astimezone(UTC)
    if period == LimitPeriod.daily:
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == LimitPeriod.weekly:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start - timedelta(days=start.weekday())
    if period == LimitPeriod.monthly:
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return datetime(1970, 1, 1, tzinfo=UTC)


async def assert_limits(session: AsyncSession, payload: TransactionCreate) -> None:
    """Called while the project is locked, serializing competing limit reservations."""
    limits = await LimitDAO.list_for_scope(session, payload.project_id, payload.direction, payload.currency.upper())
    now = datetime.now(UTC)
    for limit in limits:
        used = await TransactionDAO.amount_used(
            session, payload.project_id, payload.direction, payload.currency.upper(), period_start(limit.period, now), LIMIT_COUNTED_STATES,
        )
        if used + payload.amount > limit.amount:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "limit_exceeded",
                    "period": limit.period.value,
                    "limit": str(limit.amount),
                    "used": str(used),
                    "requested": str(payload.amount),
                },
            )


async def append_event(
    session: AsyncSession,
    transaction: Transaction,
    event_type: str,
    state: TransactionState,
    *,
    actor: str = "system",
    payload: dict | None = None,
) -> None:
    previous = transaction.state
    transaction.state = state
    await TransactionEventDAO.append(session, TransactionEvent(
        transaction_id=transaction.id,
        event_type=event_type,
        previous_state=previous if event_type != "transaction.created" else None,
        state=state,
        actor=actor,
        payload=payload or {},
    ))


async def create_transaction(session: AsyncSession, payload: TransactionCreate, idempotency_key: str) -> Transaction:
    # Project row lock makes calculate-and-reserve limits safe under concurrent requests.
    project = await ProjectDAO.get_for_update(session, payload.project_id)
    if not project or not project.is_active:
        raise HTTPException(status_code=404, detail="Active project not found")

    existing = await TransactionDAO.get_by_idempotency(session, payload.project_id, idempotency_key)
    if existing:
        return existing

    payload.currency = payload.currency.upper()
    provider = await RoutingService.resolve_provider(session, payload.project_id, payload.amount, payload.provider_code)
    await OperationalPolicyService.assert_allows(session, payload)
    await assert_limits(session, payload)
    transaction = Transaction(
        project_id=payload.project_id,
        user_id=payload.user_id,
        provider_id=provider.id,
        idempotency_key=idempotency_key,
        direction=payload.direction,
        amount=payload.amount,
        currency=payload.currency,
        description=payload.description,
        extra=payload.extra,
        state=TransactionState.created,
    )
    await TransactionDAO.create(session, transaction)
    await append_event(session, transaction, "transaction.created", TransactionState.created, payload={"amount": str(payload.amount), "currency": payload.currency})

    adapter = registry.get(provider.adapter_type, {**provider.settings, **provider.credentials_encrypted})
    customer_email = None
    if payload.user_id:
        customer = await UserDAO.get(session, payload.user_id)
        if not customer:
            raise HTTPException(status_code=404, detail="User not found")
        customer_email = customer.email
    if getattr(adapter, "requires_customer_email", False) and not customer_email:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This payment provider requires an email on the selected user",
        )
    request = CreatePaymentRequest(reference=str(transaction.id), amount=payload.amount, currency=payload.currency,
                                   direction=payload.direction, description=payload.description, extra=payload.extra,
                                   customer_email=customer_email)
    max_attempts = max(1, min(int(provider.settings.get("max_attempts", 3)), 8))
    for attempt in range(1, max_attempts + 1):
        try:
            provider_payment = await adapter.create_payment(request)
            await ProviderRequestAttemptDAO.append(session, ProviderRequestAttempt(transaction_id=transaction.id, operation="create_payment", attempt=attempt, outcome="success", request_payload={"reference": request.reference, "amount": str(request.amount), "currency": request.currency}, response_payload=provider_payment.payload, http_status=201, error=None))
            break
        except RetryableProviderError as exc:
            await ProviderRequestAttemptDAO.append(session, ProviderRequestAttempt(transaction_id=transaction.id, operation="create_payment", attempt=attempt, outcome="retryable_error", request_payload={"reference": request.reference}, response_payload=None, http_status=exc.status_code, error=str(exc)))
            if attempt == max_attempts: raise HTTPException(status_code=503, detail="Payment provider unavailable after retries") from exc
            await asyncio.sleep(min(2 ** (attempt - 1), 4))
    transaction.external_id = provider_payment.external_id
    transaction.payment_url = (provider_payment.payload or {}).get("payment_url")
    transaction.raw_provider_payload = provider_payment.payload
    transaction.settled_amount = provider_payment.settled_amount
    transaction.fee_amount = provider_payment.fee_amount
    await append_event(session, transaction, "provider.payment_created", provider_payment.state, payload=provider_payment.payload)
    return transaction


async def apply_provider_update(session: AsyncSession, transaction: Transaction, payment: ProviderPayment) -> Transaction:
    if payment.state != transaction.state and payment.state not in VALID_TRANSITIONS[transaction.state]:
        raise HTTPException(status_code=409, detail=f"Invalid state change: {transaction.state.value} -> {payment.state.value}")
    transaction.raw_provider_payload = payment.payload
    transaction.settled_amount = payment.settled_amount or transaction.settled_amount
    transaction.fee_amount = payment.fee_amount
    if payment.state != transaction.state:
        await append_event(session, transaction, "provider.status_changed", payment.state, payload=payment.payload)
    return transaction


class PaymentService:
    """Application service. It owns payment rules; DAOs only perform persistence."""

    @staticmethod
    async def create(session: AsyncSession, payload: TransactionCreate, idempotency_key: str) -> Transaction:
        async with session.begin():
            transaction = await create_transaction(session, payload, idempotency_key)
        await session.refresh(transaction)
        return transaction

    @staticmethod
    async def process_webhook(session: AsyncSession, provider_code: str, body: bytes, headers: dict[str, str]) -> None:
        # Local import avoids a service-layer cycle: order creation invokes the
        # payment service, while a provider update synchronizes its order.
        from app.services.orders import OrderService
        provider = await ProviderDAO.get_by_code(session, provider_code)
        if not provider or not provider.is_active:
            raise HTTPException(status_code=404, detail="Provider not found")
        adapter = registry.get(provider.adapter_type, {**provider.settings, **provider.credentials_encrypted})
        if not await adapter.verify_webhook(body, headers):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")
        callback_payment = await adapter.parse_webhook(body)
        # Callback is only a signal; fetch the authoritative provider state before changing local money status.
        payment = await adapter.get_payment(callback_payment.external_id)
        callback = None
        async with session.begin():
            transaction = await TransactionDAO.get_by_provider_external_for_update(session, provider.id, payment.external_id)
            if not transaction:
                raise HTTPException(status_code=404, detail="Transaction not found")
            await ProviderRequestAttemptDAO.append(session, ProviderRequestAttempt(
                transaction_id=transaction.id, operation="webhook_received", attempt=1, outcome="success",
                request_payload={"external_id": callback_payment.external_id}, response_payload=callback_payment.payload,
                http_status=204, error=None,
            ))
            if payment.amount is not None and payment.amount != transaction.amount:
                raise HTTPException(status_code=409, detail="Provider amount does not match local transaction")
            if payment.currency and payment.currency.upper() != transaction.currency.upper():
                raise HTTPException(status_code=409, detail="Provider currency does not match local transaction")
            await apply_provider_update(session, transaction, payment)
            order = await OrderService.sync_status_from_transaction(session, transaction.id, transaction.state.value)
            if order and order.external_order_id and transaction.state in (TransactionState.succeeded, TransactionState.failed, TransactionState.cancelled, TransactionState.refunded):
                project = await ProjectDAO.get(session, transaction.project_id)
                if project:
                    callback = (project, order)
        if callback:
            await ExternalPlatformService.deliver_final_status(session, *callback)

    @staticmethod
    async def events(session: AsyncSession, transaction_id) -> list[TransactionEvent]:
        if not await TransactionDAO.get(session, transaction_id):
            raise HTTPException(status_code=404, detail="Transaction not found")
        return await TransactionEventDAO.list_by_transaction(session, transaction_id)

    @staticmethod
    async def list(session: AsyncSession, project_id, limit: int) -> list[Transaction]:
        return await TransactionDAO.list_by_project(session, project_id, min(max(limit, 1), 200))
