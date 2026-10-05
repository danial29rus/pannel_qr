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
    def _sbp_url(payload: dict) -> str | None:
        """Return the direct NSPK QR URL only when MulenPay explicitly provides it."""
        candidate = payload.get("data", {}).get("qrpayload")
        if isinstance(candidate, str) and candidate.startswith("https://qr.nspk.ru/"):
            return candidate
        return None

    async def _get_sbp_url(self, hosted_payment_url: str) -> tuple[str | None, dict | None]:
        """Obtain the direct SBP QR URL from MulenPay's hosted checkout."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(f"{hosted_payment_url.rstrip('/')}/sbp")
            if response.status_code >= 400:
                return None, {"status_code": response.status_code, "body": response.text[:1000]}
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            return None, {"error": str(exc)}
        return self._sbp_url(payload), payload

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
        hold_time_seconds = request.extra.get("hold_time_seconds")
        if hold_time_seconds is not None:
            body["holdTime"] = int(hold_time_seconds)
        body["sign"] = hashlib.sha1(f"{currency}{amount}{self.shop_id}{request.reference}{self.secret_key}".encode()).hexdigest()
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(self.payments_url, headers=self._headers(), json=body)
        except httpx.RequestError as exc: raise RetryableProviderError(str(exc)) from exc
        if response.status_code in (408, 429) or response.status_code >= 500: raise RetryableProviderError(response.text, response.status_code)
        response.raise_for_status(); data = response.json()
        hosted_payment_url = data.get("paymentUrl")
        sbp_url = None
        sbp_payload = None
        if isinstance(hosted_payment_url, str) and hosted_payment_url.startswith("https://"):
            sbp_url, sbp_payload = await self._get_sbp_url(hosted_payment_url)
        if not sbp_url:
            # A hosted widget is not a valid substitute for the direct QR
            # contract exposed by /transactions/qr.  Keep the provider
            # response for the operator trace, but never hand that widget URL
            # to the external platform as if it were an NSPK payment link.
            return ProviderPayment(
                external_id=str(data["id"]), state=TransactionState.failed,
                amount=request.amount, currency=request.currency,
                payload={
                    "payment_url": None,
                    "hosted_payment_url": hosted_payment_url,
                    "sbp_payment_url": None,
                    "provider": data,
                    "sbp": sbp_payload,
                    "error": {
                        "code": "sbp_qr_unavailable",
                        "message": "MulenPay did not return a direct NSPK QR payment URL",
                    },
                },
            )
        return ProviderPayment(
            external_id=str(data["id"]), state=TransactionState.pending,
            amount=request.amount, currency=request.currency,
            payload={
                "payment_url": sbp_url,
                "hosted_payment_url": hosted_payment_url,
                "sbp_payment_url": sbp_url,
                "provider": data,
                "sbp": sbp_payload,
            },
        )

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
