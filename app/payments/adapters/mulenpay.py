import hashlib
import hmac
import json
from decimal import Decimal

import httpx

from app.db.models import TransactionState
from app.payments.adapters.base import CreatePaymentRequest, ProviderPayment, RetryableProviderError


class MulenPayAdapter:
    # MulenPay sends the receipt/customer context using `client`.
    requires_customer_email = True

    def __init__(self, config: dict) -> None:
        self.api_key = str(config.get("api_key", ""))
        self.secret_key = str(config.get("secret_key", ""))
        self.shop_id = str(config.get("shop_id", ""))
        # The documented checkout API is /api/v2/payments.  Store the stable
        # API root in provider settings, rather than a versioned endpoint, so
        # both creation and status checks always address the same resource.
        self.base_url = str(config.get("base_url", "https://api.mulenpay.com/api")).rstrip("/")
        self.payments_url = (
            self.base_url
            if self.base_url.endswith("/v2/payments")
            else f"{self.base_url}/v2/payments"
        )
        self.callback_token = str(config.get("callback_token", ""))
        if not all((self.api_key, self.secret_key, self.shop_id)):
            raise ValueError("MulenPay requires api_key, secret_key, and shop_id")

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    @staticmethod
    def _state(value: int | str) -> TransactionState:
        return {0: TransactionState.created, 1: TransactionState.processing, 2: TransactionState.cancelled,
                3: TransactionState.succeeded, 4: TransactionState.failed, 5: TransactionState.pending, 6: TransactionState.pending}.get(int(value), TransactionState.pending)

    async def create_payment(self, request: CreatePaymentRequest) -> ProviderPayment:
        if not request.customer_email:
            raise ValueError("MulenPay requires a customer email")
        amount = f"{request.amount:.2f}"; currency = request.currency.lower()
        body = {"currency": currency, "amount": amount, "uuid": request.reference, "shopId": int(self.shop_id),
                "description": request.description or f"Заказ {request.reference}", "items": request.extra.get("items", []),
                "website_url": request.extra.get("website_url"), "language": request.extra.get("language", "ru"),
                "client": request.customer_email}
        body["sign"] = hashlib.sha1(f"{currency}{amount}{self.shop_id}{request.reference}{self.secret_key}".encode()).hexdigest()
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(self.payments_url, headers=self._headers(), json=body)
        except httpx.RequestError as exc: raise RetryableProviderError(str(exc)) from exc
        if response.status_code in (408, 429) or response.status_code >= 500: raise RetryableProviderError(response.text, response.status_code)
        response.raise_for_status(); data = response.json()
        return ProviderPayment(external_id=str(data["id"]), state=TransactionState.pending, amount=request.amount, currency=request.currency, payload={"payment_url": data.get("paymentUrl"), "provider": data})

    async def get_payment(self, external_id: str) -> ProviderPayment:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(f"{self.payments_url}/{external_id}", headers=self._headers())
        except httpx.RequestError as exc:
            raise RetryableProviderError(str(exc)) from exc
        if response.status_code in (408, 429) or response.status_code >= 500: raise RetryableProviderError(response.text, response.status_code)
        response.raise_for_status(); data = response.json()["payment"]
        return ProviderPayment(external_id=str(data["id"]), state=self._state(data["status"]), amount=Decimal(str(data["amount"])), currency=data["currency"].upper(), payload=data)

    async def verify_webhook(self, body: bytes, headers: dict[str, str]) -> bool:
        if self.callback_token: return hmac.compare_digest(headers.get("x-callback-token", ""), self.callback_token)
        try: return bool(json.loads(body).get("id"))
        except json.JSONDecodeError: return False

    async def parse_webhook(self, body: bytes) -> ProviderPayment:
        data = json.loads(body); state = TransactionState.succeeded if data.get("payment_status") == "success" else TransactionState.cancelled
        return ProviderPayment(external_id=str(data["id"]), state=state, amount=Decimal(str(data["amount"])), currency=data.get("currency", "").upper(), payload=data)
