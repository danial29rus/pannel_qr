import base64
import hashlib
import hmac
import json
import secrets
import time

from fastapi import HTTPException, status

from app.core.config import get_settings
from app.db.models import ActorRole


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def verify_password(password: str, encoded: str) -> bool:
    try:
        kind, salt, digest = encoded.split("$", 2)
        if kind != "scrypt": return False
        actual = hashlib.scrypt(password.encode(), salt=_unb64(salt), n=2**14, r=8, p=1)
        return hmac.compare_digest(actual, _unb64(digest))
    except (ValueError, TypeError):
        return False


def issue_admin_session() -> str:
    settings = get_settings()
    if not settings.panel_session_secret: raise HTTPException(503, "Panel session secret is not configured")
    body = _b64(json.dumps({"role": "admin", "exp": int(time.time()) + settings.panel_session_ttl_minutes * 60}, separators=(",", ":")).encode())
    signature = _b64(hmac.new(settings.panel_session_secret.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{signature}"


def session_role(token: str) -> ActorRole | None:
    settings = get_settings()
    try:
        body, signature = token.split(".", 1)
        expected = _b64(hmac.new(settings.panel_session_secret.encode(), body.encode(), hashlib.sha256).digest())
        data = json.loads(_unb64(body))
        if not hmac.compare_digest(signature, expected) or data["exp"] < time.time(): return None
        return ActorRole(data["role"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError): return None


def login(username: str, password: str) -> str:
    settings = get_settings()
    valid = settings.panel_admin_password_hash and secrets.compare_digest(username, settings.panel_admin_username) and verify_password(password, settings.panel_admin_password_hash)
    if not valid: raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid login or password")
    return issue_admin_session()
