"""Boundary for the external order platform.

The platform is authenticated before an order reaches payment routing.  Its
success/failure callbacks are signed and each delivery is auditable/retryable.
"""
import hashlib
import hmac
import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.dao.repositories import (
    ExternalCallbackAttemptDAO, IntegrationRequestLogDAO, OrderDAO, ProjectDAO,
    ProviderRequestAttemptDAO, TransactionDAO,
)
from app.db.models import (
    ExternalCallbackAttempt, IntegrationRequestLog, Order, Project,
    ProviderRequestAttempt, TransactionState,
)


PAYGATE_TERMINAL_STATUSES = {
    TransactionState.succeeded: "paid",
    TransactionState.failed: "failed",
    TransactionState.cancelled: "cancelled",
    TransactionState.refunded: "refunded",
}
# Prevent a broken merchant endpoint from being hit indefinitely. Every
# delivery is still recorded, including the final capped attempt.
MAX_MERCHANT_CALLBACK_ATTEMPTS = 5


class ExternalPlatformService:
    @staticmethod
    async def project_for_request(session: AsyncSession, external_key: str, supplied_token: str | None) -> Project:
        project = await ProjectDAO.get_by_external_key(session, external_key)
        if not project or not project.is_active:
            raise HTTPException(status_code=404, detail="Active project not found")
        if not project.external_incoming_token or not supplied_token or not hmac.compare_digest(project.external_incoming_token, supplied_token):
            raise HTTPException(status_code=401, detail="Invalid external platform token")
        if not project.external_callback_url or not project.external_callback_secret:
            raise HTTPException(status_code=503, detail="External platform callback is not configured")
        return project

    @staticmethod
    async def project_for_token(session: AsyncSession, supplied_token: str | None) -> Project:
        """Resolve a merchant project for the PayGateCore-compatible endpoint."""
        if not supplied_token:
            raise HTTPException(status_code=401, detail="Invalid external platform token")
        project = await ProjectDAO.get_by_external_incoming_token(session, supplied_token)
        if (
            not project
            or not project.is_active
            or not project.external_incoming_token
            or not hmac.compare_digest(project.external_incoming_token, supplied_token)
        ):
            raise HTTPException(status_code=401, detail="Invalid external platform token")
        return project

    @staticmethod
    async def log_request(
        session: AsyncSession, project_id, external_order_id: str | None, request_payload: dict,
        *, outcome: str, http_status: int, response_payload: dict | None = None, error: str | None = None,
    ) -> None:
        await IntegrationRequestLogDAO.append(session, IntegrationRequestLog(
            project_id=project_id, external_order_id=external_order_id, request_payload=request_payload,
            response_payload=response_payload, http_status=http_status, outcome=outcome, error=error,
        ))
        await session.commit()

    @staticmethod
    async def deliver_final_status(session: AsyncSession, project: Project, order: Order) -> bool:
        if order.external_status_notified_at:
            return True
        payload = {
            "external_order_id": order.external_order_id,
            "order_id": str(order.id),
            "transaction_id": str(order.transaction_id) if order.transaction_id else None,
            "status": order.status,
            "amount": str(order.amount),
            "currency": order.currency,
            "payment_url": order.payment_url,
        }
        raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        timestamp = str(int(datetime.now(UTC).timestamp()))
        signature = hmac.new(project.external_callback_secret.encode(), f"{timestamp}.".encode() + raw, hashlib.sha256).hexdigest()
        attempt = await ExternalCallbackAttemptDAO.next_attempt_number(session, order.id)
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(project.external_callback_url, content=raw, headers={
                    "Content-Type": "application/json", "Idempotency-Key": f"order-status:{order.id}:{order.status}",
                    "X-Panel-Timestamp": timestamp, "X-Panel-Signature": signature,
                })
            try:
                response_data = response.json() if response.content and "json" in response.headers.get("content-type", "") else {"body": response.text[:1000]}
            except ValueError:
                response_data = {"body": response.text[:1000]}
            successful = 200 <= response.status_code < 300
            await ExternalCallbackAttemptDAO.append(session, ExternalCallbackAttempt(
                order_id=order.id, attempt=attempt, outcome="success" if successful else "retryable_error",
                request_payload=payload, response_payload=response_data, http_status=response.status_code,
                error=None if successful else f"HTTP {response.status_code}",
            ))
            if successful:
                order.external_status_notified_at = datetime.now(UTC)
        except httpx.HTTPError as exc:
            await ExternalCallbackAttemptDAO.append(session, ExternalCallbackAttempt(
                order_id=order.id, attempt=attempt, outcome="retryable_error", request_payload=payload,
                response_payload=None, http_status=None, error=str(exc),
            ))
            successful = False
        await session.commit()
        return successful

    @staticmethod
    async def deliver_final_status_for_order(session: AsyncSession, order_id) -> bool:
        """Load fresh ORM rows after a status-update transaction has committed."""
        order = await OrderDAO.get(session, order_id)
        if not order:
            return False
        project = await ProjectDAO.get(session, order.project_id)
        if not project:
            return False
        return await ExternalPlatformService.deliver_final_status(session, project, order)

    @staticmethod
    async def deliver_merchant_status_for_transaction(session: AsyncSession, transaction_id) -> bool:
        """Send the provider-compatible merchant status callback for a QR payment.

        Only a successful 2xx response marks the current state as delivered;
        the reconciliation worker retries failed deliveries and keeps every
        attempt in the transaction trace.
        """
        transaction = await TransactionDAO.get(session, transaction_id)
        if not transaction or not transaction.extra.get("merchant_transaction_id"):
            return True
        status = PAYGATE_TERMINAL_STATUSES.get(transaction.state)
        if not status or transaction.merchant_callback_status == transaction.state.value:
            return True

        project = await ProjectDAO.get(session, transaction.project_id)
        if not project:
            return False
        callback_url = transaction.extra.get("merchant_webhook_url") or project.external_callback_url
        # A URL is optional in the create request. If it was not configured at
        # either level there is intentionally no callback to retry.
        if not callback_url:
            transaction.merchant_callback_status = transaction.state.value
            await session.commit()
            return True

        operation = "merchant_status_webhook"
        attempt = await ProviderRequestAttemptDAO.next_attempt_number(session, transaction.id, operation)
        paid_amount = transaction.settled_amount
        if paid_amount is None:
            paid_amount = transaction.amount if transaction.state == TransactionState.succeeded else Decimal("0")
        payload = {
            "merchant_transaction_id": transaction.extra["merchant_transaction_id"],
            "paid_amount": str(paid_amount),
            "status": status,
            "type": "in",
        }
        raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(callback_url, content=raw, headers={
                    "Content-Type": "application/json",
                })
            try:
                response_payload = response.json() if response.content and "json" in response.headers.get("content-type", "") else {"body": response.text[:1000]}
            except ValueError:
                response_payload = {"body": response.text[:1000]}
            successful = 200 <= response.status_code < 300
            # A malformed/unknown merchant transaction (4xx other than a
            # timeout or rate limit) cannot become valid by retrying every
            # worker pass. Preserve the error in the trace and stop retries;
            # transport errors, 429 and 5xx remain retryable.
            retryable = response.status_code in (408, 425, 429) or response.status_code >= 500
            will_retry = retryable and attempt < MAX_MERCHANT_CALLBACK_ATTEMPTS
            error = None if successful else (
                f"HTTP {response.status_code}" if will_retry
                else f"HTTP {response.status_code}; retry limit ({MAX_MERCHANT_CALLBACK_ATTEMPTS}) reached" if retryable
                else f"HTTP {response.status_code}"
            )
            await ProviderRequestAttemptDAO.append(session, ProviderRequestAttempt(
                transaction_id=transaction.id, operation=operation, attempt=attempt,
                outcome="success" if successful else "retryable_error" if will_retry else "error", request_payload={
                    "method": "POST",
                    "url": callback_url,
                    "headers": {"Content-Type": "application/json"},
                    "body": payload,
                },
                response_payload=response_payload, http_status=response.status_code,
                error=error,
            ))
            if successful or not will_retry:
                transaction.merchant_callback_status = transaction.state.value
        except httpx.HTTPError as exc:
            will_retry = attempt < MAX_MERCHANT_CALLBACK_ATTEMPTS
            await ProviderRequestAttemptDAO.append(session, ProviderRequestAttempt(
                transaction_id=transaction.id, operation=operation, attempt=attempt,
                outcome="retryable_error" if will_retry else "error", request_payload={
                    "method": "POST",
                    "url": callback_url,
                    "headers": {"Content-Type": "application/json"},
                    "body": payload,
                }, response_payload=None,
                http_status=None,
                error=str(exc) if will_retry else f"{exc}; retry limit ({MAX_MERCHANT_CALLBACK_ATTEMPTS}) reached",
            ))
            if not will_retry:
                transaction.merchant_callback_status = transaction.state.value
            successful = False
        await session.commit()
        return successful
