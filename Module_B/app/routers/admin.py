from fastapi import APIRouter, Depends, Request
from app.auth.dependencies import require_admin
from app.database import get_auth_db
from app.services.audit import verify_audit_chain

router = APIRouter()


@router.get("/audit-log", description="**Access:** Admin only. Returns the audit log entries (most recent first).")
def get_audit_log(
    limit: int = 100,
    current_user: dict = Depends(require_admin),
    db=Depends(get_auth_db),
):
    db.execute(
        "SELECT * FROM audit_log ORDER BY log_id DESC LIMIT %s", (limit,)
    )
    rows = db.fetchall()
    for row in rows:
        if row.get("timestamp"):
            row["timestamp"] = str(row["timestamp"])
    return {"success": True, "data": rows}


@router.get("/verify-audit", description="**Access:** Admin only. Verifies the integrity of the audit log hash chain.")
def verify_audit(
    current_user: dict = Depends(require_admin),
    db=Depends(get_auth_db),
):
    result = verify_audit_chain(db)
    return {"success": True, "data": result}


@router.get("/direct-modifications", description="**Access:** Admin only. Detects direct database modifications that bypassed the application layer.")
def get_direct_modifications(
    limit: int = 100,
    current_user: dict = Depends(require_admin),
    db=Depends(get_auth_db),
):
    db.execute(
        "SELECT * FROM direct_modification_log ORDER BY id DESC LIMIT %s", (limit,)
    )
    rows = db.fetchall()
    for row in rows:
        if row.get("detected_at"):
            row["detected_at"] = str(row["detected_at"])
    return {"success": True, "data": rows, "count": len(rows)}
