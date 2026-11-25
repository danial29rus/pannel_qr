"""HonestPlay partner API. Its worker owns MulenPay; this adapter only polls HonestPlay."""
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from app.db.models import TransactionDirection, TransactionState
from app.payments.adapters.base import CreatePaymentRequest, ProviderPayment, RetryableProviderError


class HonestPlayAdapter:
    requires_customer_email = True
    supports_direct_qr = False

    def __init__(self, config: dict) -> None:
        self.base_url = str(config.get("base_url", "https://2.27.42.108")).rstrip("/")
        self.api_key = str(config.get("api_key", ""))
        parsed = urlsplit(self.base_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("HonestPlay requires an HTTPS base_url without credentials, query or fragment")
        if not self.api_key.strip():
            raise ValueError("HonestPlay requires api_key")
        self.payments_url = f"{self.base_url}/api/public/payments"

    @staticmethod
    def payment_reference(idempotency_key: str, extra: dict) -> str:
        # Use the caller's durable UUID, rather than a new local transaction UUID.
        # A rolled-back local create must never turn a retry into another remote order.
        if extra.get("_require_direct_qr"):
            raise ValueError("HonestPlay returns hosted checkout URLs, not direct NSPK QR URLs; use /transactions")
        candidate = extra.get("payment_uuid") or idempotency_key
        try:
            value = UUID(str(candidate))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("HonestPlay requires a stable UUIDv4 in Idempotency-Key or extra.payment_uuid") from exc
        if value.version != 4:
            raise ValueError("HonestPlay payment UUID must be version 4")
        return str(value)

    @staticmethod
    def validate_payment_request(request: CreatePaymentRequest) -> None:
        if request.extra.get("_require_direct_qr"):
            raise ValueError("HonestPlay returns a hosted payment URL; /transactions/qr requires a direct NSPK URL. Use /transactions for hosted checkout.")
        if request.currency.upper() != "RUB" or request.direction != TransactionDirection.incoming:
            raise ValueError("HonestPlay supports incoming RUB payments only")
        if not request.amount.is_finite() or not Decimal("0") < request.amount <= Decimal("10000000") or request.amount != request.amount.quantize(Decimal("0.01")):
            raise ValueError("HonestPlay amount must be positive, at most 10000000, and have at most two decimal places")
        if not request.customer_email or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", request.customer_email):
            raise ValueError("HonestPlay requires a valid customer email")
        if len(request.description or "") > 255:
            raise ValueError("HonestPlay description must be at most 255 characters")
        try:
            reference = UUID(request.reference)
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("HonestPlay requires UUIDv4") from exc
        if reference.version != 4:
            raise ValueError("HonestPlay requires UUIDv4")

    async def _request(self, method: str, url: str, body: dict | None = None) -> dict:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.request(method, url, headers={"X-API-Key": self.api_key}, json=body)
        except httpx.RequestError as exc:
            # Avoid putting the API key, buyer email or request body into errors/logs.
            raise RetryableProviderError("HonestPlay request failed") from exc
        if response.status_code in (408, 429) or response.status_code >= 500:
            raise RetryableProviderError("HonestPlay temporarily unavailable", response.status_code)
        response.raise_for_status()
        try:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Expected an object")
            return data
        except ValueError as exc:
            raise RetryableProviderError("HonestPlay returned an invalid response") from exc

    @staticmethod
    def _state(data: dict) -> TransactionState:
        status, payment_status = data.get("status"), data.get("payment_status")
        if status == payment_status == "paid":
            return TransactionState.succeeded
        if status == "cancelled" and payment_status == "failed":
            return TransactionState.failed
        if status == "cancelled" and payment_status == "cancelled":
            return TransactionState.cancelled
        # Inconsistent, unknown and partially confirmed responses cannot release goods.
        return TransactionState.pending

    @staticmethod
    def _identity(data: dict, reference: str) -> str:
        try:
            remote = UUID(str(data["uuid"]))
            if str(remote) != reference:
                raise ValueError("Mismatched UUID")
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise RetryableProviderError("HonestPlay returned an unexpected payment UUID") from exc
        return reference

    async def create_payment(self, request: CreatePaymentRequest) -> ProviderPayment:
        self.validate_payment_request(request)
        body = {"amount": f"{request.amount:.2f}", "uuid":request.reference,
                "email":request.customer_email, "description":request.description or "Оплата заказа"}
        data = await self._request("POST", self.payments_url, body)
        self._identity(data, request.reference)
        try:
            amount = Decimal(str(data["amount"]))
            url = data.get("payment_url")
            parsed = urlsplit(url) if isinstance(url, str) else None
            if amount != request.amount or not parsed or parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Invalid checkout response")
        except (KeyError, ValueError, InvalidOperation) as exc:
            raise RetryableProviderError("HonestPlay returned an invalid amount or payment URL") from exc
        return ProviderPayment(external_id=request.reference, state=self._state(data), amount=amount, currency="RUB",
            payload={"payment_url":url, "provider_payment_id":data.get("provider_payment_id"),
                     "uuid":request.reference, "status":data.get("status"), "payment_status":data.get("payment_status")})

    async def get_payment(self, external_id: str) -> ProviderPayment:
        try:
            reference = str(UUID(external_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("Invalid HonestPlay payment UUID") from exc
        data = await self._request("GET", f"{self.payments_url}/{reference}")
        self._identity(data, reference)
        try:
            minor = Decimal(str(data["amount_minor"]))
            if not minor.is_finite() or minor != minor.to_integral_value() or minor <= 0 or data["currency"].upper() != "RUB":
                raise ValueError("Invalid amount or currency")
        except (KeyError, AttributeError, ValueError, InvalidOperation) as exc:
            raise RetryableProviderError("HonestPlay returned an invalid amount or currency") from exc
        return ProviderPayment(external_id=reference, state=self._state(data), amount=minor / 100, currency="RUB",
            payload={key:data.get(key) for key in ("uuid", "status", "payment_status", "provider_status", "amount_minor", "currency", "created_at", "confirmed_at")})

    async def verify_webhook(self, body: bytes, headers: dict[str, str]) -> bool:
        return False  # The documented API has no inbound webhook contract.

    async def parse_webhook(self, body: bytes) -> ProviderPayment:
        raise ValueError("HonestPlay uses status polling, not webhooks")
