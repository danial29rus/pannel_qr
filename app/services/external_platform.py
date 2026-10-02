"""Boundary for the external order platform.

The platform is authenticated before an order reaches payment routing.  Its
success/failure callbacks are signed and each delivery is auditable/retryable.
"""
import hashlib
import hmac
import json
from datetime import UTC, datetime

import httpx
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.dao.repositories import ExternalCallbackAttemptDAO, IntegrationRequestLogDAO, OrderDAO, ProjectDAO
from app.db.models import ExternalCallbackAttempt, IntegrationRequestLog, Order, Project


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
