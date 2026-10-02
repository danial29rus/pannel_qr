from types import SimpleNamespace

from app.api import auth
from app.db.models import ActorRole


def test_admin_session_round_trip_and_tamper_rejection(monkeypatch):
    settings = SimpleNamespace(panel_session_secret="test-session-secret", panel_session_ttl_minutes=15)
    monkeypatch.setattr(auth, "get_settings", lambda: settings)

    token = auth.issue_admin_session()

    assert auth.session_role(token) is ActorRole.admin
    assert auth.session_role(f"{token}x") is None


def test_password_hash_verification():
    salt = b"1234567890123456"
    encoded = auth._b64(salt)
    import hashlib

    digest = hashlib.scrypt(b"correct horse", salt=salt, n=2**14, r=8, p=1)
    value = f"scrypt${encoded}${auth._b64(digest)}"

    assert auth.verify_password("correct horse", value)
    assert not auth.verify_password("wrong password", value)
