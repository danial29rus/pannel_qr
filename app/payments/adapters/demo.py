import json
from decimal import Decimal

from app.db.models import TransactionState
from app.payments.adapters.base import CreatePaymentRequest, ProviderPayment


class DemoProcessorAdapter:
    """Local deterministic adapter. Replace with the processor contract after docs arrive."""
    requires_customer_email = False

    async def create_payment(self, request: CreatePaymentRequest) -> ProviderPayment:
        external_id = f"demo_{request.reference.replace('-', '')[:20]}"
        return ProviderPayment(
            external_id=external_id,
            state=TransactionState.pending,
            payload={"provider": "demo", "reference": request.reference, "payment_url": f"https://checkout.demo.localhost/pay/{external_id}"},
        )

    async def get_payment(self, external_id: str) -> ProviderPayment:
        return ProviderPayment(external_id=external_id, state=TransactionState.pending)

    async def verify_webhook(self, body: bytes, headers: dict[str, str]) -> bool:
        # Demo trusts a marker; a real adapter must validate the provider signature.
        return headers.get("x-demo-signature") == "demo"

    async def parse_webhook(self, body: bytes) -> ProviderPayment:
        data = json.loads(body)
        return ProviderPayment(
            external_id=data["external_id"],
            state=TransactionState(data["state"]),
            settled_amount=Decimal(str(data["settled_amount"])) if data.get("settled_amount") else None,
            fee_amount=Decimal(str(data.get("fee_amount", "0"))),
            payload=data,
        )
