#!/usr/bin/env python3
"""Simulate a signed partner client against the panel's external payment API."""
import argparse
import getpass
import hashlib
import hmac
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser


DEFAULT_URL = "https://panel.vitrina-studio.ru/api/v1/external/vitrina-studio/payments"
FINAL_STATES = {"paid", "failed", "canceled", "refunded"}


def signature(secret: str, timestamp: str, method: str, path: str, body: bytes) -> str:
    digest = hashlib.sha256(body).hexdigest()
    canonical = f"{timestamp}.{method.upper()}.{path}.{digest}".encode()
    return hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()


def request_json(url: str, method: str, body: bytes, token: str, secret: str) -> dict:
    timestamp = str(int(time.time()))
    path = urllib.parse.urlsplit(url).path
    headers = {
        "Accept": "application/json",
        "X-Platform-Token": token,
        "X-Platform-Timestamp": timestamp,
        "X-Platform-Signature": signature(secret, timestamp, method, path, body),
    }
    if method == "POST":
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body if method == "POST" else None, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        server = exc.headers.get("Server", "")
        content_type = exc.headers.get("Content-Type", "")
        metadata = f" (server={server}, content-type={content_type})" if server or content_type else ""
        raise RuntimeError(f"HTTP {exc.code}{metadata}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Request failed: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Panel returned a non-object JSON response")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL, help="Panel create-payment URL")
    parser.add_argument("--amount-rub", required=True, type=int, help="Integer RUB amount, 100..500000")
    parser.add_argument("--transaction-id", help="Reuse a UUID after a network timeout")
    parser.add_argument("--description", default="Integration test")
    parser.add_argument("--poll-seconds", type=int, default=10)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--open", action="store_true", dest="open_link", help="Open returned checkout URL")
    parser.add_argument("--create-only", action="store_true", help="Create and print the link without polling")
    args = parser.parse_args()

    if not 100 <= args.amount_rub <= 500_000:
        parser.error("--amount-rub must be between 100 and 500000")
    if args.poll_seconds < 1 or args.timeout_seconds < 1:
        parser.error("poll and timeout values must be positive")
    parsed = urllib.parse.urlsplit(args.url)
    if parsed.scheme != "https" or not parsed.netloc or not parsed.path.endswith("/payments"):
        parser.error("--url must be an HTTPS .../api/v1/external/{project_key}/payments URL")
    try:
        transaction_id = str(uuid.UUID(args.transaction_id)) if args.transaction_id else str(uuid.uuid4())
    except ValueError:
        parser.error("--transaction-id must be a UUID")

    token = getpass.getpass("Partner Auth token: ").strip()
    secret = getpass.getpass("Partner Secret key: ").strip()
    if len(token) < 16 or len(secret) < 16:
        parser.error("both partner keys must be at least 16 characters")

    payload = {
        "transaction_id": transaction_id,
        "amount_rub": args.amount_rub,
        "description": args.description,
    }
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    print(f"Transaction UUID: {transaction_id}", flush=True)
    print(f"POST {args.url}", flush=True)
    print("Creating payment…", flush=True)
    try:
        payment = request_json(args.url, "POST", body, token, secret)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        print(f"If the response was lost, retry with --transaction-id {transaction_id}", file=sys.stderr)
        return 1

    payment_url = payment.get("payment_url")
    qr_url = payment.get("qr_url")
    print(f"Status: {payment.get('status')}")
    print(f"Amount: {payment.get('amount_rub')} RUB")
    print(f"Payment URL: {payment_url or '(not returned)'}")
    print(f"QR URL: {qr_url or '(not returned)'}")
    if payment.get("status") == "pending" and (
        not isinstance(payment_url, str) or not payment_url.startswith("https://qr.nspk.ru/")
        or not isinstance(qr_url, str) or not qr_url.startswith("https://qr.nspk.ru/")
    ):
        print("ERROR: pending payment did not return both direct https://qr.nspk.ru/ URLs", file=sys.stderr)
        return 1
    checkout_url = payment_url or qr_url
    if not checkout_url:
        if payment.get("status") in FINAL_STATES and not payment.get("paid"):
            print("Payment was recorded as failed/canceled; inspect the panel trace and wait for its signed failure callback", file=sys.stderr)
            return 2
        print("No checkout link was returned", file=sys.stderr)
        return 1
    if args.open_link:
        webbrowser.open(checkout_url)
    if args.create_only:
        return 0

    status_url = f"{args.url.rstrip('/')}/{transaction_id}"
    deadline = time.monotonic() + args.timeout_seconds
    last_status = payment.get("status")
    print("Pay the checkout in the opened page; waiting for the final status…", flush=True)
    while time.monotonic() < deadline:
        time.sleep(args.poll_seconds)
        try:
            current = request_json(status_url, "GET", b"", token, secret)
        except RuntimeError as exc:
            print(f"Status check failed: {exc}", file=sys.stderr)
            continue
        current_status = current.get("status")
        if current_status != last_status:
            print(f"Status: {current_status} (paid={current.get('paid')})", flush=True)
            last_status = current_status
        if current_status in FINAL_STATES:
            return 0 if current.get("paid") else 2
    print("Timed out waiting for a final status; rerun with the same UUID to check the same operation", file=sys.stderr)
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
