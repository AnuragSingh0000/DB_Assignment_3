from datetime import datetime, timedelta, timezone
import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from app.limiter import limiter
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from app.auth.dependencies import get_current_user, _hash_token
from app.auth.jwt_handler import create_access_token, create_refresh_token
from app.config import JWT_EXPIRY_HOURS, ACCESS_TOKEN_EXPIRY_MINUTES, SECURE_COOKIES
from app.database import get_auth_db
from app.services.audit import write_audit_log

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login", description="**Access:** Public (unauthenticated). Rate-limited to 100 requests/minute.")
@limiter.limit("100/minute")
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    db.execute(
        "SELECT user_id, username, password_hash, role, member_id, is_active "
        "FROM users WHERE username = %s",
        (body.username,),
    )
    user = db.fetchone()
    if not user or not user["is_active"]:
        write_audit_log(
            db, None, body.username, "LOGIN", "users", None,
            "FAILURE", {"reason": "user not found or inactive"}, ip,
        )
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not bcrypt.checkpw(body.password.encode(), user["password_hash"].encode()):
        write_audit_log(
            db, user["user_id"], body.username, "LOGIN", "users",
            str(user["user_id"]), "FAILURE", {"reason": "wrong password"}, ip,
        )
        raise HTTPException(status_code=401, detail="Invalid credentials")

    access = create_access_token(
        user["user_id"], user["username"], user["role"], user["member_id"]
    )
    refresh = create_refresh_token(user["user_id"])

    expires_at = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS)
    db.execute(
        "INSERT INTO sessions (user_id, token_hash, expires_at) VALUES (%s, %s, %s)",
        (user["user_id"], _hash_token(refresh), expires_at),
    )
    write_audit_log(
        db, user["user_id"], user["username"], "LOGIN", "sessions",
        str(user["user_id"]), "SUCCESS", None, ip,
    )
    response.set_cookie(
        key="access_token",
        value=access,
        httponly=True,
        max_age=ACCESS_TOKEN_EXPIRY_MINUTES * 60,
        samesite="lax",
        secure=SECURE_COOKIES,
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh,
        httponly=True,
        max_age=JWT_EXPIRY_HOURS * 3600,
        samesite="lax",
        secure=SECURE_COOKIES,
    )
    return {
        "success": True,
        "message": "Login successful",
        "data": {
            "user_id":   user["user_id"],
            "username":  user["username"],
            "role":      user["role"],
            "member_id": user["member_id"],
        },
    }


@router.post("/logout", description="**Access:** Any authenticated user (Admin, Coach, Player).")
def logout(
    request: Request,
    response: Response,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    refresh = request.cookies.get("refresh_token")
    if refresh:
        db.execute(
            "UPDATE sessions SET is_revoked = TRUE WHERE token_hash = %s",
            (_hash_token(refresh),),
        )
    write_audit_log(
        db, current_user["user_id"], current_user["username"],
        "LOGOUT", "sessions", str(current_user["user_id"]), "SUCCESS", None, ip,
    )
    resp = RedirectResponse(url="/ui/login", status_code=303)
    resp.delete_cookie("access_token")
    resp.delete_cookie("refresh_token")
    return resp


@router.get("/isAuth", description="**Access:** Any authenticated user (Admin, Coach, Player). Returns current user info.")
def is_auth(current_user: dict = Depends(get_current_user)):
    return {
        "success":    True,
        "data": {
            "user_id":   current_user["user_id"],
            "username":  current_user["username"],
            "role":      current_user["role"],
            "member_id": current_user["member_id"],
        },
    }
