import secrets

from fastapi import Header, HTTPException, status

from app.core.config import get_settings
from app.db.models import ActorRole
from app.api.auth import session_role


def require_roles(*roles: ActorRole):
    """API role guard. Local development is open; production must set ENFORCE_AUTH=true and tokens."""
    async def guard(
        x_panel_token: str | None = Header(default=None, alias="X-Panel-Token"),
        authorization: str | None = Header(default=None),
    ) -> ActorRole:
        settings = get_settings()
        if not settings.enforce_auth:
            return ActorRole.admin
        token = x_panel_token or (authorization.removeprefix("Bearer ") if authorization else "")
        tokens = {
            ActorRole.admin: settings.admin_token,
            ActorRole.operator: settings.operator_token,
            ActorRole.viewer: settings.viewer_token,
        }
        role = session_role(token) or next((role for role, configured in tokens.items() if configured and secrets.compare_digest(token, configured)), None)
        if not role:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid panel token")
        if role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return role
    return guard
