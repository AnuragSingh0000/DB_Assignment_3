from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from app.config import ACCESS_TOKEN_EXPIRY_MINUTES, SECURE_COOKIES


class RefreshCookieMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        new_token = getattr(request.state, "new_access_token", None)
        if new_token:
            response.set_cookie(
                key="access_token",
                value=new_token,
                httponly=True,
                max_age=ACCESS_TOKEN_EXPIRY_MINUTES * 60,
                samesite="lax",
                secure=SECURE_COOKIES,
            )
        return response
