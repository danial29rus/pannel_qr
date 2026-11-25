"""Configurable JSON/HTTP payment adapter for standard create/status APIs."""
import hashlib
import hmac
import json
import re
import time
from decimal import Decimal, InvalidOperation
from urllib.parse import quote, urlsplit

import httpx

from app.db.models import TransactionDirection, TransactionState
from app.payments.adapters.base import CreatePaymentRequest, ProviderPayment, RetryableProviderError


_VARIABLE = re.compile(r"^\{\{([a-z_]+)\}\}$")
_HEADER_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_ALLOWED_VARIABLES = {"transaction_id", "email", "amount", "amount_rub", "currency", "description", "api_token", "secret_key"}
_TERMINAL_STATES = {state.value: state for state in TransactionState}


def _path_value(data: dict, path: str):
    value = data
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _render(value, context: dict):
    if isinstance(value, dict):
        return {key: _render(item, context) for key, item in value.items()}
    if isinstance(value, list):
        return [_render(item, context) for item in value]
    if isinstance(value, str):
        match = _VARIABLE.fullmatch(value)
        if match:
            name = match.group(1)
            if name not in context:
                raise ValueError(f"Unknown request template variable: {name}")
            return context[name]
        return value
    return value


def _validate_template(value) -> None:
    if isinstance(value, dict):
        for item in value.values():
            _validate_template(item)
    elif isinstance(value, list):
        for item in value:
            _validate_template(item)
    elif isinstance(value, str) and ("{{" in value or "}}" in value):
        match = _VARIABLE.fullmatch(value)
        if not match or match.group(1) not in _ALLOWED_VARIABLES:
            raise ValueError("request_template contains an unsupported variable")


class JsonApiAdapter:
    """A declarative adapter; provider-specific request/response shapes live in config."""

    requires_customer_email = True
    supports_direct_qr = False

    def __init__(self, config: dict) -> None:
        self.base_url = str(config.get("base_url", "")).rstrip("/")
        self.create_path = str(config.get("create_path", "/api/v1/external/payments"))
        self.status_path = str(config.get("status_path", "/api/v1/external/payments/{transaction_id}"))
        self.request_template = config.get("request_template", {
            "transaction_id": "{{transaction_id}}",
            "email": "{{email}}",
            "amount_rub": "{{amount_rub}}",
        })
        self.response_paths = config.get("response_paths", {
            "id": "transaction_id", "status": "status", "amount": "amount_rub",
            "currency": "currency", "payment_url": "payment_url", "qr_url": "qr_url",
        })
        self.status_map = config.get("status_map", {
            "pending": "pending", "succeeded": "succeeded", "failed": "failed", "canceled": "cancelled",
        })
        self.currency = str(config.get("currency", "RUB")).upper()
        self.amount_mode = str(config.get("amount_mode", "integer_major"))
        self.auth_header = str(config.get("auth_header", "Authorization"))
        self.auth_scheme = str(config.get("auth_scheme", "Bearer"))
        self.api_token = str(config.get("api_token", "")).strip()
        self.secret_key = str(config.get("secret_key", "")).strip()
        self.signature_header = str(config.get("signature_header", "")).strip()
        self.timestamp_header = str(config.get("timestamp_header", "")).strip()

        parsed = urlsplit(self.base_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("JSON API requires an HTTPS base_url without credentials, query or fragment")
        if not self._valid_path(self.create_path) or not self._valid_path(self.status_path):
            raise ValueError("JSON API paths must be relative absolute paths on the configured host")
        if "{transaction_id}" not in self.status_path and "{external_id}" not in self.status_path:
            raise ValueError("status_path must contain {transaction_id} or {external_id}")
        if not isinstance(self.request_template, dict) or not isinstance(self.response_paths, dict) or not isinstance(self.status_map, dict):
            raise ValueError("JSON API templates and mappings must be JSON objects")
        _validate_template(self.request_template)
        if any(value is not None and (not isinstance(value, str) or not value) for value in self.response_paths.values()):
            raise ValueError("response_paths values must be non-empty JSON paths or null")
        if any(not isinstance(key, str) or not isinstance(value, str) for key, value in self.status_map.items()):
            raise ValueError("status_map must map status strings to transaction states")
        if self.amount_mode not in {"integer_major", "decimal_major"}:
            raise ValueError("amount_mode must be integer_major or decimal_major")
        if self.auth_header and not _HEADER_NAME.fullmatch(self.auth_header):
            raise ValueError("auth_header must be a valid HTTP header name")
        if self.signature_header and not _HEADER_NAME.fullmatch(self.signature_header):
            raise ValueError("signature_header must be a valid HTTP header name")
        if self.timestamp_header and not _HEADER_NAME.fullmatch(self.timestamp_header):
            raise ValueError("timestamp_header must be a valid HTTP header name")
        if "\r" in self.auth_scheme or "\n" in self.auth_scheme:
            raise ValueError("auth_scheme contains invalid characters")
        if self.auth_header and not self.api_token:
            raise ValueError("JSON API requires api_token when auth_header is configured")
        if bool(self.signature_header) != bool(self.timestamp_header) or (self.signature_header and not self.secret_key):
            raise ValueError("JSON API signature headers require both header names and secret_key")
        if any(value not in _TERMINAL_STATES for value in self.status_map.values()):
            raise ValueError("status_map values must be transaction states")
        self.create_url = f"{self.base_url}{self.create_path}"

    @staticmethod
    def _valid_path(path: str) -> bool:
        if not path.startswith("/") or path.startswith("//") or "\\" in path:
            return False
        parsed = urlsplit(path)
        return not parsed.scheme and not parsed.netloc and not any(part == ".." for part in parsed.path.split("/"))

    @staticmethod
    def payment_reference(idempotency_key: str, extra: dict) -> str:
        return str(extra.get("merchant_transaction_id") or extra.get("payment_uuid") or idempotency_key)

    def validate_payment_request(self, request: CreatePaymentRequest) -> None:
        if request.direction != TransactionDirection.incoming or request.currency.upper() != self.currency:
            raise ValueError(f"JSON API supports incoming {self.currency} payments only")
        if not request.customer_email:
            raise ValueError("JSON API requires a selected user with an email")
        if request.extra.get("_require_direct_qr"):
            raise ValueError("JSON API returns hosted checkout links, not a direct NSPK QR URL")
        if self.amount_mode == "integer_major" and request.amount != request.amount.to_integral_value():
            raise ValueError("JSON API is configured for whole-unit amounts")

    def _context(self, request: CreatePaymentRequest) -> dict:
        amount_rub = None
        if request.amount == request.amount.to_integral_value():
            amount_rub = int(request.amount)
        return {
            "transaction_id": request.reference,
            "email": request.customer_email,
            "amount": format(request.amount, "f"),
            "amount_rub": amount_rub,
            "currency": request.currency.upper(),
            "description": request.description or "Payment",
            "api_token": self.api_token,
            "secret_key": self.secret_key,
        }

    def _headers(self, raw_body: bytes | None = None) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.auth_header:
            value = f"{self.auth_scheme} {self.api_token}".strip()
            headers[self.auth_header] = value
        if self.signature_header and raw_body is not None:
            timestamp = str(time.time_ns() // 1_000_000_000)
            digest = hmac.new(self.secret_key.encode(), f"{timestamp}.".encode() + raw_body, hashlib.sha256).hexdigest()
            headers[self.timestamp_header] = timestamp
            headers[self.signature_header] = digest
        return headers

    async def _request(self, method: str, url: str, *, body: dict | None = None) -> dict:
        raw_body = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode() if body is not None else b""
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
                response = await client.request(method, url, headers=self._headers(raw_body), content=raw_body or None)
        except httpx.RequestError as exc:
            raise RetryableProviderError("JSON API request failed") from exc
        if response.status_code in (408, 425, 429) or response.status_code >= 500:
            raise RetryableProviderError("JSON API temporarily unavailable", response.status_code)
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise RetryableProviderError("JSON API returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise RetryableProviderError("JSON API response must be an object")
        return payload

    def _mapped_state(self, payload: dict) -> TransactionState:
        value = _path_value(payload, str(self.response_paths.get("status", "status")))
        state = self.status_map.get(str(value))
        return _TERMINAL_STATES.get(state, TransactionState.pending)

    def _validate_amount(self, payload: dict, requested: Decimal | None = None) -> Decimal:
        raw = _path_value(payload, str(self.response_paths.get("amount", "amount")))
        try:
            amount = Decimal(str(raw)) if raw is not None else requested
            if amount is None or not amount.is_finite() or amount <= 0:
                raise ValueError("invalid amount")
            if self.amount_mode == "integer_major" and amount != amount.to_integral_value():
                raise ValueError("amount must be an integer")
            return amount
        except (InvalidOperation, ValueError) as exc:
            raise RetryableProviderError("JSON API returned an invalid amount") from exc

    def _payment_url(self, payload: dict) -> str:
        path = str(self.response_paths.get("payment_url", "payment_url"))
        value = _path_value(payload, path)
        parsed = urlsplit(value) if isinstance(value, str) else None
        if not parsed or parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise RetryableProviderError("JSON API returned an invalid HTTPS payment_url")
        return value

    async def create_payment(self, request: CreatePaymentRequest) -> ProviderPayment:
        self.validate_payment_request(request)
        body = _render(self.request_template, self._context(request))
        payload = await self._request("POST", self.create_url, body=body)
        id_path = self.response_paths.get("id", "transaction_id")
        external_id = _path_value(payload, str(id_path)) if id_path else None
        external_id = str(external_id or request.reference)
        request_id_path = self.response_paths.get("request_id")
        if request_id_path and str(_path_value(payload, str(request_id_path))) != request.reference:
            raise RetryableProviderError("JSON API returned an unexpected idempotency reference")
        amount = self._validate_amount(payload, request.amount)
        currency_path = self.response_paths.get("currency")
        remote_currency = _path_value(payload, str(currency_path)) if currency_path else request.currency
        if str(remote_currency).upper() != request.currency.upper():
            raise RetryableProviderError("JSON API returned an unexpected currency")
        payment_url = self._payment_url(payload)
        qr_path = self.response_paths.get("qr_url")
        qr_url = _path_value(payload, str(qr_path)) if qr_path else None
        if qr_url is not None:
            parsed = urlsplit(qr_url) if isinstance(qr_url, str) else None
            if not parsed or parsed.scheme != "https" or not parsed.hostname:
                qr_url = None
        return ProviderPayment(
            external_id=external_id,
            state=self._mapped_state(payload),
            amount=amount,
            currency=request.currency.upper(),
            payload={"payment_url": payment_url, "qr_url": qr_url, "remote": payload},
        )

    async def get_payment(self, external_id: str) -> ProviderPayment:
        encoded_id = quote(external_id, safe="")
        path = self.status_path.replace("{transaction_id}", encoded_id).replace("{external_id}", encoded_id)
        url = f"{self.base_url}{path}"
        payload = await self._request("GET", url)
        id_path = self.response_paths.get("id", "transaction_id")
        remote_id = _path_value(payload, str(id_path)) if id_path else None
        if id_path and str(remote_id) != external_id:
            raise RetryableProviderError("JSON API returned an unexpected transaction_id")
        amount = self._validate_amount(payload)
        currency_path = self.response_paths.get("currency")
        remote_currency = _path_value(payload, str(currency_path)) if currency_path else self.currency
        if str(remote_currency).upper() != self.currency:
            raise RetryableProviderError("JSON API returned an unexpected currency")
        payment_url = _path_value(payload, str(self.response_paths.get("payment_url", "payment_url")))
        if payment_url is not None:
            parsed = urlsplit(payment_url) if isinstance(payment_url, str) else None
            if not parsed or parsed.scheme != "https" or not parsed.hostname:
                payment_url = None
        return ProviderPayment(
            external_id=external_id,
            state=self._mapped_state(payload),
            amount=amount,
            currency=self.currency,
            payload={"payment_url": payment_url, "remote": payload},
        )

    async def verify_webhook(self, body: bytes, headers: dict[str, str]) -> bool:
        return False

    async def parse_webhook(self, body: bytes) -> ProviderPayment:
        raise ValueError("JSON API adapter uses status polling")
