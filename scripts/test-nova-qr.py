#!/usr/bin/env python3
"""Create a disposable Nova test payment and resolve its direct NSPK QR URL.

Uses only Python's standard library; Docker and the panel API are not needed.
Set NOVA_TOKEN and optionally AMOUNT_RUB before running it.
"""

import json
import os
import sys
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


NOVA_URL = "https://24nova-ai.ru/api/v1/external/payments"
PAYHOT_QR_ATTEMPTS = 6
PAYHOT_QR_RETRY_DELAY_SECONDS = 0.5


def request_json(request: Request) -> tuple[dict, float]:
    started = time.perf_counter()
    with urlopen(request, timeout=20) as response:
        return json.load(response), time.perf_counter() - started


def main() -> None:
    token = os.environ.get("NOVA_TOKEN")
    if not token:
        raise SystemExit("NOVA_TOKEN is required")
    if token == "ВСТАВЬТЕ_ТОКЕН" or not token.isascii():
        raise SystemExit("Set NOVA_TOKEN to the real ASCII token issued by Nova, not the placeholder text")
    try:
        amount = int(os.environ.get("AMOUNT_RUB", "100"))
    except ValueError as exc:
        raise SystemExit("AMOUNT_RUB must be a whole number") from exc
    if not 100 <= amount <= 500_000:
        raise SystemExit("AMOUNT_RUB must be between 100 and 500000")

    transaction_id = str(uuid.uuid4())
    nova_request = Request(
        NOVA_URL,
        data=json.dumps({
            "transaction_id": transaction_id,
            "user_id": 1,
            "amount_rub": amount,
        }).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        nova, nova_time = request_json(nova_request)
    except HTTPError as exc:
        raise SystemExit(f"Nova HTTP {exc.code}: {exc.read().decode(errors='replace')}") from exc
    except URLError as exc:
        raise SystemExit(f"Nova network error: {exc.reason}") from exc

    raw_qr_url = nova.get("qr_url")
    qr_url = raw_qr_url if isinstance(raw_qr_url, str) and raw_qr_url.startswith("https://qr.nspk.ru/") else None
    payhot_attempts: list[dict] = []
    payhot_total_time = 0.0
    if not qr_url:
        # Nova sometimes puts its PayHot checkout page in qr_url instead of
        # payment_url. It is not a direct QR and must be resolved below.
        payment_url = nova.get("payment_url") or raw_qr_url
        parsed = urlsplit(payment_url or "")
        checkout_token = parsed.fragment.removeprefix("token=")
        path_parts = parsed.path.rstrip("/").split("/")
        if parsed.scheme != "https" or parsed.netloc != "go.pay.hot" or len(path_parts) != 3 or path_parts[1] != "pay" or not checkout_token:
            raise SystemExit("Nova did not return a supported PayHot payment URL")
        public_id = path_parts[2]

        for attempt in range(1, PAYHOT_QR_ATTEMPTS + 1):
            payhot_request = Request(
                f"https://go.pay.hot/api/v2/checkout-sessions/{public_id}",
                headers={
                    "Accept": "application/json",
                    "X-Payhot-Checkout-Token": checkout_token,
                },
            )
            try:
                payhot, elapsed = request_json(payhot_request)
            except HTTPError as exc:
                raise SystemExit(f"PayHot HTTP {exc.code}: {exc.read().decode(errors='replace')}") from exc
            except URLError as exc:
                raise SystemExit(f"PayHot network error: {exc.reason}") from exc
            payhot_total_time += elapsed
            next_action = payhot.get("next_action") or {}
            candidate = next_action.get("value")
            is_nspk = (
                next_action.get("type") == "qr"
                and isinstance(candidate, str)
                and candidate.startswith("https://qr.nspk.ru/")
            )
            payhot_attempts.append({
                "attempt": attempt,
                "time_seconds": round(elapsed, 3),
                "next_action_type": next_action.get("type"),
                "has_nspk_qr": is_nspk,
            })
            if is_nspk:
                qr_url = candidate
                break
            if attempt < PAYHOT_QR_ATTEMPTS:
                time.sleep(PAYHOT_QR_RETRY_DELAY_SECONDS)

    print(json.dumps({
        "transaction_id": transaction_id,
        "nova_status": nova.get("status"),
        "qr_nspk_url": qr_url,
        "nova_time_seconds": round(nova_time, 3),
        "payhot_total_time_seconds": round(payhot_total_time, 3),
        "payhot_attempts": payhot_attempts,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
