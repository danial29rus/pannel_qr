import asyncio
import hashlib
import hmac
import json
from decimal import Decimal

import httpx

from app.db.models import TransactionState
from app.payments.adapters.base import CreatePaymentRequest, ProviderPayment, RetryableProviderError


class AIPayAdapter:
    # AI Pay accepts only amount and currency; no customer context is sent.
    requires_customer_email = False

    STATES = {
        1: TransactionState.pending,     # waiting for payment method selection
        2: TransactionState.pending,     # payment method selected
        3: TransactionState.succeeded,
        4: TransactionState.failed,
        5: TransactionState.cancelled,
        6: TransactionState.pending,     # hold
    }

    # The checkout page (no api-key) lists methods and, after selection,
    # returns payment_attributes.qr_code with the direct NSPK link.
    SBP_QR_ATTEMPTS = 2
    SBP_QR_RETRY_DELAY_SECONDS = 1

    def __init__(self, config: dict) -> None:
        self.api_key = str(config.get("api_key", ""))
        self.base_url = str(config.get("base_url", "https://ads.aipay.onl/api")).rstrip("/")
        # Orders are always created in RUB unless the provider settings say otherwise.
        self.currency = str(config.get("currency") or "RUB").upper()
        # Optional explicit method id; otherwise the SBP/NSPK method is detected by name.
        self.payment_method_id = config.get("payment_method_id")
        if not self.api_key:
            raise ValueError("AI Pay requires api_key")

    def _headers(self) -> dict[str, str]:
        return {"api-key": self.api_key, "Content-Type": "application/json"}

    @staticmethod
    def _sbp_url(url: object) -> str | None:
        if isinstance(url, str) and url.startswith("https://qr.nspk.ru/"):
            return url
        return None

    @classmethod
    def _state(cls, status: dict | None) -> TransactionState:
        try:
            return cls.STATES.get(int((status or {}).get("id")), TransactionState.pending)
        except (TypeError, ValueError):
            return TransactionState.pending

    async def _request(self, method: str, url: str, **kwargs) -> dict:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.request(method, url, headers=self._headers(), **kwargs)
        except httpx.RequestError as exc:
            raise RetryableProviderError(str(exc)) from exc
        if response.status_code in (408, 429) or response.status_code >= 500:
            raise RetryableProviderError(response.text, response.status_code)
        response.raise_for_status()
        return response.json()

    def _pick_method(self, details: dict) -> int | None:
        if self.payment_method_id:
            return int(self.payment_method_id)
        methods = details.get("payment_methods") or []
        for method in methods:
            names = " ".join([str(method.get("name", "")), *map(str, (method.get("translation") or {}).values())]).upper()
            if "НСПК" in names or "NSPK" in names or "СБП" in names or "SBP" in names:
                return int(method["id"])
        return int(methods[0]["id"]) if len(methods) == 1 else None

    async def _get_sbp_url(self, uid: str) -> tuple[str | None, dict]:
        """Select the SBP method on the checkout API and read the NSPK link."""
        attempts: list[dict] = []
        for attempt in range(1, self.SBP_QR_ATTEMPTS + 1):
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    details_response = await client.get(f"{self.base_url}/v2/order/get-order-details/{uid}")
                    details_response.raise_for_status()
                    details = details_response.json()
                    sbp_url = self._sbp_url((details.get("payment_attributes") or {}).get("qr_code"))
                    selected = None
                    if not sbp_url:
                        method_id = self._pick_method(details)
                        if method_id is None:
                            raise ValueError("No SBP payment method offered")
                        select_response = await client.post(
                            f"{self.base_url}/v2/order/select-payment-method",
                            json={"uid": uid, "payment_method_id": method_id},
                        )
                        select_response.raise_for_status()
                        selected = select_response.json() or {}
                        attributes = selected.get("payment_attributes") or selected.get("paymentAttributes") or {}
                        sbp_url = self._sbp_url(attributes.get("qr_code"))
                if sbp_url:
                    return sbp_url, {"attempt": attempt, "failed_attempts": attempts, "details": details, "selected": selected}
                attempts.append({"attempt": attempt, "details": details, "selected": selected,
                                 "error": "Direct NSPK QR URL is absent in the checkout response"})
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                status_code = getattr(getattr(exc, "response", None), "status_code", None)
                attempts.append({"attempt": attempt, "status_code": status_code, "error": str(exc)})
            if attempt < self.SBP_QR_ATTEMPTS:
                await asyncio.sleep(self.SBP_QR_RETRY_DELAY_SECONDS)
        result = dict(attempts[-1])
        result["failed_attempts"] = attempts
        return None, result

    async def create_payment(self, request: CreatePaymentRequest) -> ProviderPayment:
        body = {"amount": float(f"{request.amount:.2f}"), "currency": self.currency}
        data = await self._request("POST", f"{self.base_url}/v2/order/create", json=body)
        uid = str(data["uid"])
        hosted_payment_url = data.get("payment_url")
        sbp_url, sbp_payload = await self._get_sbp_url(uid)
        payload = {
            "payment_url": sbp_url,
            "hosted_payment_url": hosted_payment_url,
            "sbp_payment_url": sbp_url,
            "provider": data,
            "sbp": sbp_payload,
        }
        if not sbp_url:
            # Same contract as MulenPay: the hosted checkout is not an NSPK link.
            payload["error"] = {
                "code": "sbp_qr_unavailable",
                "message": "AI Pay did not return a direct NSPK QR payment URL",
            }
        return ProviderPayment(
            external_id=uid,
            state=TransactionState.pending if sbp_url else TransactionState.failed,
            amount=request.amount, currency=self.currency, payload=payload,
        )

    async def get_payment(self, external_id: str) -> ProviderPayment:
        data = await self._request("GET", f"{self.base_url}/v2/order/status/{external_id}")
        currency = (data.get("currency") or {}).get("name") or ""
        amount = data.get("amount")
        return ProviderPayment(
            external_id=str(data["uid"]), state=self._state(data.get("status")),
            amount=Decimal(str(amount)) if amount is not None else None,
            currency=currency.upper() or None, payload=data,
        )

    async def verify_webhook(self, body: bytes, headers: dict[str, str]) -> bool:
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return False
        uid, signature = data.get("uid"), data.get("signature")
        if not isinstance(uid, str) or not isinstance(signature, str):
            return False
        expected = hashlib.md5(f"{uid}:{self.api_key}".encode()).hexdigest()
        return hmac.compare_digest(signature.lower(), expected)

    async def parse_webhook(self, body: bytes) -> ProviderPayment:
        data = json.loads(body)
        return ProviderPayment(external_id=str(data["uid"]), state=self._state(data.get("status")), payload=data)
