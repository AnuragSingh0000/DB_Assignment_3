import hashlib
import jwt as pyjwt
from fastapi import Depends, HTTPException, Cookie, Request
from app.auth.jwt_handler import decode_token, create_access_token
from app.database import get_auth_db


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def get_current_user(
    request: Request,
    access_token: str = Cookie(default=None),
    refresh_token: str = Cookie(default=None),
    db=Depends(get_auth_db),
) -> dict:
    # 1. Try access token (stateless — no DB)
    if access_token:
        try:
            payload = decode_token(access_token)
            if payload.get("type") == "access":
                return payload
        except pyjwt.ExpiredSignatureError:
            pass  # fall through to refresh
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid token")

    # 2. Try refresh token (DB-validated)
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        ref_payload = decode_token(refresh_token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    if ref_payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type")

    db.execute(
        "SELECT is_revoked FROM sessions WHERE token_hash = %s AND expires_at > NOW()",
        (_hash_token(refresh_token),),
    )
    session = db.fetchone()
    if not session or session["is_revoked"]:
        raise HTTPException(status_code=401, detail="Session expired or revoked")

    db.execute(
        "SELECT user_id, username, role, member_id, is_active FROM users WHERE user_id = %s",
        (ref_payload["user_id"],),
    )
    user = db.fetchone()
    if not user or not user["is_active"]:
        raise HTTPException(status_code=401, detail="Account disabled")

    # Issue new access token and stash it for middleware
    new_access = create_access_token(
        user["user_id"], user["username"], user["role"], user["member_id"],
    )
    request.state.new_access_token = new_access

    # Return same shape as access token payload
    new_payload = decode_token(new_access)
    return new_payload


def require_role(*allowed_roles: str):
    """
    Factory that returns a FastAPI dependency enforcing role membership.
    Usage: Depends(require_role("Admin"))
           Depends(require_role("Admin", "Coach"))
    """
    async def _checker(current_user: dict = Depends(get_current_user)) -> dict:
        if current_user["role"] not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"Access denied. Required role(s): {list(allowed_roles)}",
            )
        return current_user
    return _checker
require_admin           = require_role("Admin")

require_admin_or_coach  = require_role("Admin", "Coach")
