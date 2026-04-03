from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from fastapi.responses import RedirectResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.database import get_auth_db, get_track_db, _auth_pool
from app.limiter import limiter
from app.auth.router import router as auth_router
from app.routers.members import router as members_router
from app.routers.teams import router as teams_router
from app.routers.tournaments import router as tournaments_router
from app.routers.events import router as events_router
from app.routers.equipment import router as equipment_router
from app.routers.performance import router as performance_router
from app.routers.medical import router as medical_router
from app.routers.admin import router as admin_router
from app.routers.registration import router as registration_router
from app.ui.routes import router as ui_router
from app.middleware import RefreshCookieMiddleware

@asynccontextmanager
async def lifespan(_: FastAPI):
    conn = _auth_pool.get_connection()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM sessions WHERE expires_at <= NOW()")
        conn.commit()
        cur.close()
    finally:
        conn.close()
    yield


app = FastAPI(title="Olympia Track", version="1.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(RefreshCookieMiddleware)

app.include_router(auth_router,        prefix="/auth",                  tags=["auth"])

app.include_router(members_router,     prefix="/api/members",           tags=["members"])

app.include_router(teams_router,       prefix="/api/teams",             tags=["teams"])

app.include_router(tournaments_router, prefix="/api/tournaments",       tags=["tournaments"])

app.include_router(events_router,      prefix="/api/events",            tags=["events"])

app.include_router(equipment_router,   prefix="/api/equipment",         tags=["equipment"])

app.include_router(performance_router, prefix="/api/performance-logs",  tags=["performance"])

app.include_router(medical_router,     prefix="/api/medical-records",   tags=["medical"])

app.include_router(admin_router,        prefix="/admin",                tags=["admin"])

app.include_router(registration_router, prefix="/api/registrations",    tags=["registrations"])

app.include_router(ui_router,           prefix="/ui",                   tags=["ui"])


@app.get("/")
def root():
    return RedirectResponse(url="/ui/login", status_code=303)


@app.get("/health")
def health(
    auth_db=Depends(get_auth_db),
    track_db=Depends(get_track_db),
):
    auth_db.execute("SELECT 1")
    track_db.execute("SELECT 1")
    return {"olympia_auth": "ok", "olympia_track": "ok"}
