from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
from app.auth.dependencies import get_current_user, require_admin
from app.database import get_auth_db, get_track_db, get_cross_db
from app.services.audit import write_audit_log
from app.services.id_generation import insert_with_generated_id
from app.services.validation import (
    humanize_db_error,
    normalize_contact_number,
    parse_iso_date,
    validate_member_name,
)

router = APIRouter()


class MemberCreate(BaseModel):
    member_id:      Optional[int] = None
    name:           str
    age:            int
    email:          str
    contact_number: str
    gender:         str
    role:           str
    join_date:      str
    image:          Optional[str] = None
    username:       str
    password:       str


class MemberUpdate(BaseModel):
    name:           Optional[str] = None
    age:            Optional[int] = None
    email:          Optional[str] = None
    contact_number: Optional[str] = None
    image:          Optional[str] = None


def _ensure_admin(current_user: dict) -> None:
    if current_user["role"] != "Admin":
        raise HTTPException(status_code=403, detail="Access denied")


def _get_member_or_404(track_db, member_id: int) -> dict:
    track_db.execute("SELECT * FROM Member WHERE MemberID = %s", (member_id,))
    row = track_db.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Member not found")
    return row


def _can_view_member(current_user: dict, member_role: str, member_id: int) -> bool:
    if current_user["role"] == "Admin":
        return True
    elif current_user["role"] == "Coach":
        if member_role == "Player":
            return True
        if member_role == "Coach":
            return current_user["member_id"] == member_id
        return False
    return current_user["member_id"] == member_id


@router.get("", description="**Access:** Admin, Coach, Player.\n\n"
    "- **Admin** sees all members with full details.\n"
    "- **Coach** sees all Players and Coaches (limited fields).\n"
    "- **Player** sees only other Players (limited fields).")
def list_members(
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    if current_user["role"] == "Player":
        track_db.execute("SELECT MemberID, Name, Role, Gender, JoinDate FROM Member WHERE Role = 'Player' ORDER BY MemberID")
    elif current_user["role"] == "Coach":
        track_db.execute(
            "SELECT MemberID, Name, Role, Gender, JoinDate FROM Member "
            "WHERE Role = 'Coach' OR Role = 'Player' ORDER BY MemberID"
        )
    else:
        track_db.execute("SELECT * FROM Member ORDER BY MemberID")
    rows = track_db.fetchall()
    for row in rows:
        if row.get("JoinDate") is not None:
            row["JoinDate"] = str(row["JoinDate"])
    write_audit_log(
        auth_db, current_user["user_id"], current_user["username"],
        "SELECT", "Member", None, "SUCCESS", {"count": len(rows)}, ip,
    )
    return {"success": True, "data": rows}


@router.get("/me", description="**Access:** Any authenticated user (Admin, Coach, Player). Returns the caller's own profile.")
def get_my_profile(
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    member = _get_member_or_404(track_db, current_user["member_id"])
    write_audit_log(
        auth_db, current_user["user_id"], current_user["username"],
        "SELECT", "Member", str(current_user["member_id"]), "SUCCESS", None, ip,
    )
    return {"success": True, "data": member}


@router.get("/{member_id}", description="**Access:** Admin, Coach, Player (restricted).\n\n"
    "- **Admin** can view any member's full portfolio (teams, performance logs, medical records).\n"
    "- **Coach** can view any Player's profile; performance logs and medical records are only "
    "included if the member is on one of the coach's teams.\n"
    "- **Player** can only view their own portfolio.")
def get_member_portfolio(
    member_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    member = _get_member_or_404(track_db, member_id)
    if not _can_view_member(current_user, member["Role"], member_id):
        write_audit_log(
            auth_db, current_user["user_id"], current_user["username"],
            "SELECT", "Member", str(member_id), "UNAUTHORIZED",
            {"reason": "player accessing another member"}, ip,
        )
        raise HTTPException(status_code=403, detail="Access denied")
    
    teams = []
    perf_logs = []
    medical = []
    if member["Role"] == "Player":
        track_db.execute(
            """
            SELECT t.TeamID, t.TeamName, tm.Position, tm.IsCaptain, s.SportName
            FROM TeamMember tm
            JOIN Team t  ON tm.TeamID  = t.TeamID
            JOIN Sport s ON t.SportID  = s.SportID
            WHERE tm.MemberID = %s
            """,
            (member_id,),
        )
        teams = track_db.fetchall()
    elif member["Role"] == "Coach":
        track_db.execute(
            """
            SELECT t.TeamID, t.TeamName, s.SportName
            FROM Team t
            JOIN Sport s ON t.SportID = s.SportID
            WHERE t.CoachID = %s
            """,
            (member_id,),
        )
        teams = track_db.fetchall()
    if current_user["role"] == "Admin":
        track_db.execute(
            """
            SELECT pl.*, s.SportName FROM PerformanceLog pl
            JOIN Sport s ON pl.SportID = s.SportID
            WHERE pl.MemberID = %s ORDER BY pl.RecordDate DESC
            """,
            (member_id,),
        )
    elif current_user["role"] == "Coach":
        track_db.execute(
            """
            SELECT pl.*, s.SportName FROM PerformanceLog pl
            JOIN Sport s ON pl.SportID = s.SportID
            WHERE pl.MemberID = %s
              AND EXISTS (
                  SELECT 1 FROM TeamMember tm
                  JOIN Team t ON tm.TeamID = t.TeamID
                  WHERE tm.MemberID = %s AND t.CoachID = %s
              )
            ORDER BY pl.RecordDate DESC
            """,
            (member_id, member_id, current_user["member_id"]),
        )
    else:
        if current_user["member_id"] != member_id:
            track_db.execute("SELECT 1 WHERE FALSE")
        else:
            track_db.execute(
                """
                SELECT pl.*, s.SportName FROM PerformanceLog pl
                JOIN Sport s ON pl.SportID = s.SportID
                WHERE pl.MemberID = %s ORDER BY pl.RecordDate DESC
                """,
                (member_id,),
            )
    perf_logs = track_db.fetchall()
    if current_user["role"] == "Admin" or current_user["member_id"] == member_id:
        track_db.execute(
            "SELECT * FROM MedicalRecord WHERE MemberID = %s ORDER BY DiagnosisDate DESC",
            (member_id,),
        )
        medical = track_db.fetchall()
    elif current_user["role"] == "Coach":
        track_db.execute(
            """
            SELECT mr.* FROM MedicalRecord mr
            WHERE mr.MemberID = %s
              AND EXISTS (
                  SELECT 1 FROM TeamMember tm
                  JOIN Team t ON tm.TeamID = t.TeamID
                  WHERE tm.MemberID = %s AND t.CoachID = %s
              )
            ORDER BY mr.DiagnosisDate DESC
            """,
            (member_id, member_id, current_user["member_id"]),
        )
        medical = track_db.fetchall()
    else:
        medical = []
    write_audit_log(
        auth_db, current_user["user_id"], current_user["username"],
        "SELECT", "Member", str(member_id), "SUCCESS", None, ip,
    )
    if (member["Role"] == "Player"): 
        return {
            "success": True,
            "role": member["Role"],
            "data": {
                "member":       member,
                "teams":        teams,
                "performance":  perf_logs,
                "medical":      medical,
            },
        }
    else:
        return {
            "success": True,
            "role": member["Role"],
            "data": {
                "member":       member,
                "teams":        teams,
                "performance":  perf_logs,
                "medical":      medical,
            },
        }


@router.post("", description="**Access:** Admin only.\n\n"
    "Atomically creates a Member record and a linked User account (cross-DB transaction).")
def create_member(
    body: MemberCreate,
    request: Request,
    current_user: dict = Depends(require_admin),
    cross_db=Depends(get_cross_db),
):
    """Uses a single cross-DB connection for atomicity across olympia_track and olympia_auth."""
    import bcrypt
    ip = request.client.host if request.client else "unknown"
    _ensure_admin(current_user)
    if body.age <= 0:
        return {"success": False, "message": "Age must be a positive number.", "data": body}
    try:
        member_name = validate_member_name(body.name)
        contact_number = normalize_contact_number(body.contact_number)
        join_date = parse_iso_date(body.join_date, "Join date")
    except ValueError as exc:
        return {"success": False, "message": str(exc), "data": body}
    member_id = body.member_id
    try:
        member_id = insert_with_generated_id(
            cross_db,
            requested_id=member_id,
            next_id_sql="SELECT COALESCE(MAX(MemberID), 0) + 1 AS nid FROM olympia_track.Member",
            insert_fn=lambda generated_member_id: cross_db.execute(
                """
                INSERT INTO olympia_track.Member
                    (MemberID, Name, Image, Age, Email, ContactNumber, Gender, Role, JoinDate)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    generated_member_id,
                    member_name,
                    body.image,
                    body.age,
                    body.email,
                    contact_number,
                    body.gender,
                    body.role,
                    join_date.isoformat(),
                ),
            ),
        )
    except Exception as e:
        write_audit_log(
            cross_db, current_user["user_id"], current_user["username"],
            "INSERT", "Member", str(member_id), "FAILURE", {"error": str(e)}, ip,
        )
        return {"success": False, "message": humanize_db_error(e), "data": body}
    pw_hash = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode()
    try:
        cross_db.execute(
            "INSERT INTO users (username, password_hash, role, member_id) VALUES (%s, %s, %s, %s)",
            (body.username, pw_hash, body.role, member_id),
        )
    except Exception as e:
        write_audit_log(
            cross_db, current_user["user_id"], current_user["username"],
            "INSERT", "users", None, "FAILURE", {"error": str(e)}, ip,
        )
        return {"success": False, "message": humanize_db_error(e), "data": body}
    write_audit_log(
        cross_db, current_user["user_id"], current_user["username"],
        "INSERT", "Member", str(member_id), "SUCCESS",
        {"name": member_name, "role": body.role}, ip,
    )
    body.member_id = member_id
    body.name = member_name
    body.contact_number = contact_number
    body.join_date = join_date.isoformat()
    return {"success": True, "message": "Member created", "data": {"member_id": member_id, "member": body.model_dump()}}


@router.put("/{member_id}", description="**Access:** Admin or the member themselves.\n\n"
    "- **Admin** can update any member's profile.\n"
    "- **Non-Admin** users can only update their own profile.")
def update_member(
    member_id: int,
    body: MemberUpdate,
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    if current_user["role"] != "Admin" and current_user["member_id"] != member_id:
        write_audit_log(
            auth_db, current_user["user_id"], current_user["username"],
            "UPDATE", "Member", str(member_id), "UNAUTHORIZED",
            {"reason": "not admin and not own profile"}, ip,
        )
        raise HTTPException(status_code=403, detail="Access denied")
    _get_member_or_404(track_db, member_id)
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    if "age" in fields and fields["age"] <= 0:
        raise HTTPException(status_code=400, detail="Age must be a positive number.")
    if "name" in fields:
        try:
            fields["name"] = validate_member_name(fields["name"])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if "contact_number" in fields:
        try:
            fields["contact_number"] = normalize_contact_number(fields["contact_number"])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    col_map = {
        "name": "Name", "age": "Age", "email": "Email",
        "contact_number": "ContactNumber", "image": "Image",
    }
    set_clause = ", ".join(f"{col_map[k]} = %s" for k in fields)
    values = list(fields.values()) + [member_id]
    try:
        track_db.execute(f"UPDATE Member SET {set_clause} WHERE MemberID = %s", values)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=humanize_db_error(exc)) from exc
    write_audit_log(
        auth_db, current_user["user_id"], current_user["username"],
        "UPDATE", "Member", str(member_id), "SUCCESS", fields, ip,
    )
    return {"success": True, "message": "Member updated"}


@router.delete("/{member_id}", description="**Access:** Admin only.\n\n"
    "Atomically deletes the Member record and linked User account (cross-DB transaction).")
def delete_member(
    member_id: int,
    request: Request,
    current_user: dict = Depends(require_admin),
    cross_db=Depends(get_cross_db),
):
    """Uses a single cross-DB connection for atomicity across olympia_track and olympia_auth."""
    ip = request.client.host if request.client else "unknown"
    _ensure_admin(current_user)
    cross_db.execute("SELECT * FROM olympia_track.Member WHERE MemberID = %s", (member_id,))
    if not cross_db.fetchone():
        raise HTTPException(status_code=404, detail="Member not found")
    cross_db.execute("DELETE FROM users WHERE member_id = %s", (member_id,))
    cross_db.execute("DELETE FROM olympia_track.Member WHERE MemberID = %s", (member_id,))
    write_audit_log(
        cross_db, current_user["user_id"], current_user["username"],
        "DELETE", "Member", str(member_id), "SUCCESS", None, ip,
    )
    return {"success": True, "message": f"Member {member_id} deleted"}
