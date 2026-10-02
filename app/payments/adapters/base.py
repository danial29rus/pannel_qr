from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from app.db.models import TransactionDirection, TransactionState


@dataclass(frozen=True)
class CreatePaymentRequest:
    reference: str
    amount: Decimal
    currency: str
    direction: TransactionDirection
    description: str | None
    extra: dict[str, Any]
    # Contact data is passed in-memory only. An adapter decides whether it needs it.
    customer_email: str | None = None


@dataclass(frozen=True)
class ProviderPayment:
    external_id: str
    state: TransactionState
    settled_amount: Decimal | None = None
    fee_amount: Decimal = Decimal("0")
    amount: Decimal | None = None
    currency: str | None = None
    payload: dict[str, Any] | None = None


class PaymentAdapter(Protocol):
    """A processor-specific boundary. No FastAPI or database code belongs here."""

    async def create_payment(self, request: CreatePaymentRequest) -> ProviderPayment: ...
    async def get_payment(self, external_id: str) -> ProviderPayment: ...
    async def verify_webhook(self, body: bytes, headers: dict[str, str]) -> bool: ...
    async def parse_webhook(self, body: bytes) -> ProviderPayment: ...


class RetryableProviderError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(message)
