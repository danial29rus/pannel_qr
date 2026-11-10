"""Nova AI balance-top-up payment adapter.

Nova has no webhook in its partner contract, therefore pending payments are
completed by the application's normal reconciliation poller.
"""

import asyncio
import uuid
from decimal import Decimal
from urllib.parse import urlsplit

import httpx

from app.db.models import TransactionState
from app.payments.adapters.base import CreatePaymentRequest, ProviderPayment, RetryableProviderError


class NovaAdapter:
    requires_customer_email = False
    # PayHot can expose a checkout session before its SBP QR is generated.
    # Keep the merchant QR request responsive, but allow a few short polls for
    # that normal preparation race before treating the QR as unavailable.
    PAYHOT_QR_ATTEMPTS = 6
    PAYHOT_QR_RETRY_DELAY_SECONDS = 0.5

    STATES = {
        # A direct QR has already been handed to the merchant by the time a
        # Nova payment is created, so it is actively being processed rather
        # than merely waiting for a payment method to be selected.
        "pending": TransactionState.processing,
        "succeeded": TransactionState.succeeded,
        # PayHot/Nova report a user-aborted QR checkout as `failed`. The
        # merchant-facing contract treats both non-payment outcomes as a
        # cancellation rather than a processing error.
        "failed": TransactionState.cancelled,
        "canceled": TransactionState.cancelled,
    }

    def __init__(self, config: dict) -> None:
        self.token = str(config.get("token", ""))
        self.base_url = str(config.get("base_url", "https://24nova-ai.ru/api/v1/external")).rstrip("/")
        # Temporary test recipient. Once Nova user mapping is available, this
        # setting can be replaced with an ID supplied per transaction.
        self.user_id = int(config.get("user_id", 1))
        if not self.token:
            raise ValueError("Nova requires token")
        if self.user_id <= 0:
            raise ValueError("Nova user_id must be positive")

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    @staticmethod
    def _transaction_id(request: CreatePaymentRequest) -> str:
        # For merchant QR payments this is the UUID provided by the integrator.
        # Falling back to the panel transaction ID preserves support for direct
        # panel-created payments.
        value = request.extra.get("merchant_transaction_id", request.reference)
        try:
            return str(uuid.UUID(str(value)))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("Nova requires merchant_transaction_id to be a UUID") from exc

    @staticmethod
    def _amount_rub(request: CreatePaymentRequest) -> int:
        if request.currency.upper() != "RUB":
            raise ValueError("Nova supports RUB payments only")
        if request.amount != request.amount.to_integral_value():
            raise ValueError("Nova amount must be a whole number of rubles")
        amount = int(request.amount)
        if not 100 <= amount <= 500_000:
            raise ValueError("Nova amount must be between 100 and 500000 RUB")
        return amount

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.request(method, f"{self.base_url}{path}", headers=self._headers(), **kwargs)
        except httpx.RequestError as exc:
            raise RetryableProviderError(str(exc)) from exc
        if response.status_code in (408, 429, 502, 503, 504):
            raise RetryableProviderError(response.text, response.status_code)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _direct_nspk_url(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        parsed = urlsplit(value)
        if parsed.scheme == "https" and parsed.netloc == "qr.nspk.ru":
            return value
        return None

    async def _payhot_qr_url(self, payment_url: object) -> tuple[str | None, dict]:
        """Read a direct NSPK QR link from a Nova-hosted PayHot checkout.

        The checkout token is intentionally present only in the URL fragment.
        Browsers do not send fragments to the server, so it is extracted here
        and supplied through PayHot's documented checkout-token header.
        Strict URL validation prevents a provider response from turning this
        server-side request into a request to an arbitrary host.
        """
        if not isinstance(payment_url, str):
            return None, {"error": "Nova did not provide a payment_url"}
        parsed = urlsplit(payment_url)
        parts = parsed.path.rstrip("/").split("/")
        token = parsed.fragment.removeprefix("token=")
        if (
            parsed.scheme != "https"
            or parsed.netloc != "go.pay.hot"
            or len(parts) != 3
            or parts[1] != "pay"
            or not token
        ):
            return None, {"error": "Nova payment_url is not a supported PayHot checkout URL"}
        try:
            public_id = str(uuid.UUID(parts[2]))
        except ValueError:
            return None, {"error": "PayHot checkout public ID is invalid"}

        endpoint = f"https://go.pay.hot/api/v2/checkout-sessions/{public_id}"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(
                    endpoint,
                    headers={"Accept": "application/json", "X-Payhot-Checkout-Token": token},
                )
        except httpx.RequestError as exc:
            raise RetryableProviderError(str(exc)) from exc
        if response.status_code in (408, 429, 502, 503, 504):
            raise RetryableProviderError(response.text, response.status_code)
        if response.status_code >= 400:
            return None, {"status_code": response.status_code, "body": response.text[:1000]}
        try:
            payload = response.json()
        except ValueError:
            return None, {"status_code": response.status_code, "error": "PayHot returned invalid JSON"}
        qr_url = self._direct_nspk_url((payload.get("next_action") or {}).get("value"))
        if (payload.get("next_action") or {}).get("type") != "qr" or not qr_url:
            return None, {"status_code": response.status_code, "response": payload, "error": "PayHot did not return a direct NSPK QR URL"}
        return qr_url, {"status_code": response.status_code, "response": payload}

    @classmethod
    def _payment(cls, data: dict) -> ProviderPayment:
        transaction_id = str(data["transaction_id"])
        amount = data.get("amount_rub")
        direct_qr_url = cls._direct_nspk_url(data.get("qr_url"))
        hosted_payment_url = data.get("payment_url") or data.get("qr_url")
        return ProviderPayment(
            external_id=transaction_id,
            state=cls.STATES.get(str(data.get("status", "")).lower(), TransactionState.pending),
            amount=Decimal(str(amount)) if amount is not None else None,
            currency="RUB",
            payload={
                "payment_url": direct_qr_url or hosted_payment_url,
                # Nova occasionally returns a PayHot page in this field. Do
                # not expose it as a QR; only a real NSPK link belongs here.
                "qr_url": direct_qr_url,
                "hosted_payment_url": hosted_payment_url,
                "provider": data,
            },
        )

    async def create_payment(self, request: CreatePaymentRequest) -> ProviderPayment:
        transaction_id = self._transaction_id(request)
        data = await self._request(
            "POST",
            "/payments",
            json={"transaction_id": transaction_id, "user_id": self.user_id, "amount_rub": self._amount_rub(request)},
        )
        payment = self._payment(data)
        if payment.payload["qr_url"]:
            return payment

        payhot_attempts: list[dict] = []
        qr_url = None
        for attempt in range(1, self.PAYHOT_QR_ATTEMPTS + 1):
            qr_url, payhot_payload = await self._payhot_qr_url(payment.payload["hosted_payment_url"])
            payhot_attempts.append({"attempt": attempt, **payhot_payload})
            if qr_url:
                break
            if attempt < self.PAYHOT_QR_ATTEMPTS:
                await asyncio.sleep(self.PAYHOT_QR_RETRY_DELAY_SECONDS)
        payload = dict(payment.payload)
        payload["payhot_checkout"] = payhot_attempts[-1]
        payload["payhot_checkout_attempts"] = payhot_attempts
        if qr_url:
            payload["payment_url"] = qr_url
            payload["qr_url"] = qr_url
            return ProviderPayment(
                external_id=payment.external_id, state=payment.state, amount=payment.amount,
                currency=payment.currency, settled_amount=payment.settled_amount,
                fee_amount=payment.fee_amount, payload=payload,
            )
        payload["error"] = {
            "code": "sbp_qr_unavailable",
            "message": "Nova and its PayHot checkout did not return a direct NSPK QR payment URL",
        }
        return ProviderPayment(
            external_id=payment.external_id, state=TransactionState.failed, amount=payment.amount,
            currency=payment.currency, settled_amount=payment.settled_amount,
            fee_amount=payment.fee_amount, payload=payload,
        )

    async def get_payment(self, external_id: str) -> ProviderPayment:
        data = await self._request("GET", f"/payments/{external_id}")
        return self._payment(data)

    async def verify_webhook(self, body: bytes, headers: dict[str, str]) -> bool:
        # Nova's documented partner API uses polling, not inbound callbacks.
        return False

    async def parse_webhook(self, body: bytes) -> ProviderPayment:
        raise ValueError("Nova does not provide payment webhooks")
