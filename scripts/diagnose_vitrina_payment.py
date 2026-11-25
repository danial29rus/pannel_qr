#!/usr/bin/env python3
"""Inspect a Vitrina payment and its MulenPay direct NSPK QR response."""
import argparse
import getpass
import json
import urllib.error
import urllib.parse
import urllib.request
import uuid


def get_json(url: str, token: str | None = None) -> tuple[int, dict | None]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            status = response.status
            body = response.read()
    except urllib.error.HTTPError as exc:
        status, body = exc.code, exc.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Request failed: {exc}") from exc
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return status, None
    return status, payload if isinstance(payload, dict) else None


def host_label(value: object) -> str:
    if not isinstance(value, str):
        return "missing"
    parsed = urllib.parse.urlsplit(value)
    return parsed.netloc if parsed.scheme == "https" and parsed.netloc else "invalid URL"


def is_nspk(value: object) -> bool:
    return isinstance(value, str) and value.startswith("https://qr.nspk.ru/")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transaction_id", help="UUID printed by test_partner_payment.py")
    parser.add_argument("--api-url", default="https://vitrina-studio.ru/api/v1/external/payments")
    args = parser.parse_args()
    try:
        transaction_id = str(uuid.UUID(args.transaction_id))
    except ValueError:
        parser.error("transaction_id must be a UUID")

    token = getpass.getpass("Vitrina API bearer token: ").strip()
    status_url = f"{args.api_url.rstrip('/')}/{transaction_id}"
    try:
        status_code, payment = get_json(status_url, token)
    except RuntimeError as exc:
        print(exc)
        return 1
    print(f"Vitrina status endpoint: HTTP {status_code}")
    if not payment:
        print("Vitrina did not return a JSON payment object")
        return 1
    print(f"Payment status: {payment.get('status')}; paid={payment.get('paid')}")
    print(f"Payment URL host: {host_label(payment.get('payment_url'))}")
    print(f"QR URL host: {host_label(payment.get('qr_url'))}")

    direct = payment.get("qr_url") if is_nspk(payment.get("qr_url")) else payment.get("payment_url")
    if is_nspk(direct):
        print(f"Direct NSPK URL is already present: {direct}")
        return 0
    if not isinstance(direct, str) or not direct.startswith("https://"):
        print("No HTTPS checkout URL is available for MulenPay /sbp inspection")
        return 1

    sbp_url = f"{direct.rstrip('/')}/sbp"
    try:
        sbp_status, sbp = get_json(sbp_url)
    except RuntimeError as exc:
        print(f"MulenPay /sbp request failed: {exc}")
        return 1
    qrpayload = ((sbp or {}).get("data") or {}).get("qrpayload") if isinstance(sbp, dict) else None
    print(f"MulenPay /sbp endpoint: HTTP {sbp_status}")
    if is_nspk(qrpayload):
        print(f"Direct NSPK URL extracted successfully: {qrpayload}")
        return 0
    print("ERROR: MulenPay /sbp did not return data.qrpayload starting with https://qr.nspk.ru/")
    if isinstance(sbp, dict):
        print(f"Top-level response fields: {', '.join(sorted(sbp.keys()))}")
        data = sbp.get("data")
        if isinstance(data, dict):
            print(f"data fields: {', '.join(sorted(data.keys()))}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
