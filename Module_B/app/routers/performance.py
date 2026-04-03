from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
from app.auth.dependencies import get_current_user, require_admin_or_coach
from app.database import get_auth_db, get_track_db
from app.services.audit import write_audit_log
from app.services.id_generation import insert_with_generated_id
from app.services.rbac import assert_coach_manages_member
from app.services.validation import humanize_db_error, parse_iso_date, validate_not_future

router = APIRouter()


class PerfLogCreate(BaseModel):
    log_id:       Optional[int] = None
    member_id:    int
    sport_id:     int
    metric_name:  str
    metric_value: float
    record_date:  str


class PerfLogUpdate(BaseModel):
    sport_id:     Optional[int]   = None
    metric_name:  Optional[str]   = None
    metric_value: Optional[float] = None
    record_date:  Optional[str]   = None


def _validate_record_date(record_date: str) -> None:
    parsed_date = parse_iso_date(record_date, "Record date")
    validate_not_future(parsed_date, "Record date")



@router.get("/{log_id}", description="**Access:** Admin, Coach (restricted), Player (own only).\n\n"
    "- **Admin** can view any log.\n"
    "- **Coach** can only view logs for members on their teams.\n"
    "- **Player** can only view their own logs.")
def get_performance_log(
    log_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    track_db.execute(
        """
        SELECT pl.*, m.Name AS MemberName, s.SportName
        FROM PerformanceLog pl
        JOIN Member m ON pl.MemberID = m.MemberID
        JOIN Sport s ON pl.SportID = s.SportID
        WHERE pl.LogID = %s
        """,
        (log_id,),
    )
    log = track_db.fetchone()
    if not log:
        raise HTTPException(status_code=404, detail="Log not found")
    if current_user["role"] == "Coach":
        track_db.execute(
            """
            SELECT 1
            FROM TeamMember tm
            JOIN Team t ON tm.TeamID = t.TeamID
            WHERE tm.MemberID = %s AND t.CoachID = %s
            LIMIT 1
            """,
            (log["MemberID"], current_user["member_id"]),
        )
        if not track_db.fetchone():
            raise HTTPException(status_code=403, detail="Access denied")
    elif current_user["role"] == "Player" and current_user["member_id"] != log["MemberID"]:
        raise HTTPException(status_code=403, detail="Access denied")
    log["RecordDate"] = str(log["RecordDate"])
    write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                    "SELECT", "PerformanceLog", str(log_id), "SUCCESS", None, ip)
    return {"success": True, "data": log}


@router.get("", description="**Access:** Admin, Coach (filtered), Player (own only).\n\n"
    "- **Admin** sees all performance logs.\n"
    "- **Coach** sees logs only for members on their teams.\n"
    "- **Player** sees only their own logs.")
def list_performance_logs(
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    if current_user["role"] == "Admin":
        track_db.execute(
            """
            SELECT pl.*, m.Name AS MemberName, s.SportName
            FROM PerformanceLog pl
            JOIN Member m ON pl.MemberID = m.MemberID
            JOIN Sport  s ON pl.SportID  = s.SportID
            ORDER BY pl.RecordDate DESC
            """
        )
    elif current_user["role"] == "Coach":
        track_db.execute(
            """
            SELECT pl.*, m.Name AS MemberName, s.SportName
            FROM PerformanceLog pl
            JOIN Member m ON pl.MemberID = m.MemberID
            JOIN Sport  s ON pl.SportID  = s.SportID
            WHERE pl.MemberID IN (
                SELECT tm.MemberID FROM TeamMember tm
                JOIN Team t ON tm.TeamID = t.TeamID
                WHERE t.CoachID = %s
            )
            ORDER BY pl.RecordDate DESC
            """,
            (current_user["member_id"],),
        )
    else:
        track_db.execute(
            """
            SELECT pl.*, m.Name AS MemberName, s.SportName
            FROM PerformanceLog pl
            JOIN Member m ON pl.MemberID = m.MemberID
            JOIN Sport  s ON pl.SportID  = s.SportID
            WHERE pl.MemberID = %s
            ORDER BY pl.RecordDate DESC
            """,
            (current_user["member_id"],),
        )
    rows = track_db.fetchall()
    for r in rows:
        r["RecordDate"] = str(r["RecordDate"])
    write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                    "SELECT", "PerformanceLog", None, "SUCCESS", {"count": len(rows)}, ip)
    return {"success": True, "data": rows}


@router.post("", description="**Access:** Admin or Coach.\n\n"
    "- **Admin** can create logs for any member.\n"
    "- **Coach** can only create logs for members on their teams.")
def create_performance_log(
    body: PerfLogCreate,
    request: Request,
    current_user: dict = Depends(require_admin_or_coach),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    log_id = body.log_id
    try:
        _validate_record_date(body.record_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    assert_coach_manages_member(track_db, current_user, body.member_id)
    try:
        log_id = insert_with_generated_id(
            track_db,
            requested_id=log_id,
            next_id_sql="SELECT COALESCE(MAX(LogID), 0) + 1 AS nid FROM PerformanceLog",
            insert_fn=lambda log_id: track_db.execute(
                "INSERT INTO PerformanceLog (LogID, MemberID, SportID, MetricName, MetricValue, RecordDate) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (log_id, body.member_id, body.sport_id,
                 body.metric_name, body.metric_value, body.record_date),
            ),
        )
    except Exception as e:
        write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                        "INSERT", "PerformanceLog", str(log_id), "FAILURE", {"error": str(e)}, ip)
        raise HTTPException(status_code=400, detail=humanize_db_error(e)) from e
    write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                    "INSERT", "PerformanceLog", str(log_id), "SUCCESS",
                    {"member_id": body.member_id, "metric": body.metric_name}, ip)
    return {"success": True, "message": "Performance log created", "data": {"log_id": log_id}}


@router.put("/{log_id}", description="**Access:** Admin or Coach.\n\n"
    "- **Admin** can update any log.\n"
    "- **Coach** can only update logs for members on their teams.")
def update_performance_log(
    log_id: int,
    body: PerfLogUpdate,
    request: Request,
    current_user: dict = Depends(require_admin_or_coach),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    track_db.execute("SELECT LogID, MemberID FROM PerformanceLog WHERE LogID=%s", (log_id,))
    row = track_db.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Log not found")
    if current_user["role"] == "Coach":
        assert_coach_manages_member(track_db, current_user, row["MemberID"])
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    if "record_date" in fields:
        try:
            _validate_record_date(fields["record_date"])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    col_map = {
        "sport_id": "SportID", "metric_name": "MetricName",
        "metric_value": "MetricValue", "record_date": "RecordDate",
    }
    set_clause = ", ".join(f"{col_map[k]} = %s" for k in fields)
    try:
        track_db.execute(f"UPDATE PerformanceLog SET {set_clause} WHERE LogID=%s",
                         list(fields.values()) + [log_id])
    except Exception as exc:
        raise HTTPException(status_code=400, detail=humanize_db_error(exc)) from exc
    write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                    "UPDATE", "PerformanceLog", str(log_id), "SUCCESS", fields, ip)
    return {"success": True, "message": "Performance log updated"}


@router.delete("/{log_id}", description="**Access:** Admin or Coach.\n\n"
    "- **Admin** can delete any log.\n"
    "- **Coach** can only delete logs for members on their teams.")
def delete_performance_log(
    log_id: int,
    request: Request,
    current_user: dict = Depends(require_admin_or_coach),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    track_db.execute("SELECT LogID, MemberID FROM PerformanceLog WHERE LogID=%s", (log_id,))
    row = track_db.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Log not found")
    if current_user["role"] == "Coach":
        assert_coach_manages_member(track_db, current_user, row["MemberID"])
    track_db.execute("DELETE FROM PerformanceLog WHERE LogID=%s", (log_id,))
    write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                    "DELETE", "PerformanceLog", str(log_id), "SUCCESS", None, ip)
    return {"success": True, "message": f"Log {log_id} deleted"}
