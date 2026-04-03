from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
from app.auth.dependencies import get_current_user, require_admin, require_admin_or_coach
from app.database import get_auth_db, get_track_db
from app.services.audit import write_audit_log
from app.services.id_generation import insert_with_generated_id
from app.services.rbac import assert_coach_manages_member
from app.services.validation import humanize_db_error, parse_iso_date, validate_date_order, validate_not_future

router = APIRouter()


class EquipmentCreate(BaseModel):
    equipment_id: Optional[int] = None
    equipment_name: str
    total_quantity: int
    equipment_condition: str
    sport_id: Optional[int] = None


class EquipmentUpdate(BaseModel):
    equipment_name: Optional[str] = None
    total_quantity: Optional[int] = None
    equipment_condition: Optional[str] = None
    sport_id: Optional[int] = None


class IssueCreate(BaseModel):
    issue_id:     Optional[int] = None
    equipment_id: int
    member_id:    int
    issue_date:   str
    quantity:     int
    return_date:  Optional[str] = None



def _get_equipment_or_404(track_db, equipment_id: int) -> dict:
    track_db.execute(
        """
        SELECT e.*, s.SportName,
               COALESCE(issued.IssuedQuantity, 0) AS IssuedQuantity,
               e.TotalQuantity - COALESCE(issued.IssuedQuantity, 0) AS AvailableQuantity
        FROM Equipment e
        LEFT JOIN Sport s ON e.SportID = s.SportID
        LEFT JOIN (
            SELECT EquipmentID, SUM(Quantity) AS IssuedQuantity
            FROM EquipmentIssue
            WHERE ReturnDate IS NULL
            GROUP BY EquipmentID
        ) issued ON issued.EquipmentID = e.EquipmentID
        WHERE e.EquipmentID = %s
        """,
        (equipment_id,),
    )
    equipment = track_db.fetchone()
    if not equipment:
        raise HTTPException(status_code=404, detail="Equipment not found.")
    return equipment


def _validate_equipment_payload(
    track_db,
    total_quantity: Optional[int],
    sport_id: Optional[int],
    equipment_id: Optional[int] = None,
    validate_sport: bool = True,
) -> None:
    if total_quantity is not None and total_quantity < 0:
        raise HTTPException(status_code=400, detail="Total quantity cannot be negative.")
    if validate_sport and sport_id is not None:
        track_db.execute("SELECT SportID FROM Sport WHERE SportID = %s", (sport_id,))
        if not track_db.fetchone():
            raise HTTPException(status_code=400, detail="Selected sport is not valid.")
    if equipment_id is not None and total_quantity is not None:
        track_db.execute(
            """
            SELECT COALESCE(SUM(Quantity), 0) AS issued
            FROM EquipmentIssue
            WHERE EquipmentID = %s AND ReturnDate IS NULL
            """,
            (equipment_id,),
        )
        issued = track_db.fetchone()["issued"]
        if total_quantity < issued:
            raise HTTPException(
                status_code=400,
                detail=f"Total quantity cannot be less than currently issued quantity ({issued}).",
            )


@router.post("", description="**Access:** Admin only.")
def create_equipment(
    body: EquipmentCreate,
    request: Request,
    current_user: dict = Depends(require_admin),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    _validate_equipment_payload(track_db, body.total_quantity, body.sport_id, validate_sport=False)
    equipment_id = body.equipment_id
    try:
        equipment_id = insert_with_generated_id(
            track_db,
            requested_id=equipment_id,
            next_id_sql="SELECT COALESCE(MAX(EquipmentID), 0) + 1 AS nid FROM Equipment",
            insert_fn=lambda generated_id: track_db.execute(
                """
                INSERT INTO Equipment (EquipmentID, EquipmentName, TotalQuantity, EquipmentCondition, SportID)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    generated_id,
                    body.equipment_name,
                    body.total_quantity,
                    body.equipment_condition,
                    body.sport_id,
                ),
            ),
        )
    except Exception as exc:
        write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                        "INSERT", "Equipment", str(equipment_id), "FAILURE", {"error": str(exc)}, ip)
        raise HTTPException(status_code=400, detail=humanize_db_error(exc)) from exc
    write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                    "INSERT", "Equipment", str(equipment_id), "SUCCESS",
                    {"name": body.equipment_name}, ip)
    return {"success": True, "message": "Equipment created", "data": {"equipment_id": equipment_id}}


@router.get("", description="**Access:** Any authenticated user (Admin, Coach, Player). Lists all equipment with availability info.")
def list_equipment(
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    track_db.execute(
        """
        SELECT e.*, s.SportName,
               COALESCE(issued.IssuedQuantity, 0) AS IssuedQuantity,
               e.TotalQuantity - COALESCE(issued.IssuedQuantity, 0) AS AvailableQuantity
        FROM Equipment e
        LEFT JOIN Sport s ON e.SportID = s.SportID
        LEFT JOIN (
            SELECT EquipmentID, SUM(Quantity) AS IssuedQuantity
            FROM EquipmentIssue
            WHERE ReturnDate IS NULL
            GROUP BY EquipmentID
        ) issued ON issued.EquipmentID = e.EquipmentID
        ORDER BY e.EquipmentID
        """
    )
    rows = track_db.fetchall()
    write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                    "SELECT", "Equipment", None, "SUCCESS", {"count": len(rows)}, ip)
    return {"success": True, "data": rows}


@router.get("/issues", description="**Access:** Admin, Coach, Player (filtered).\n\n"
    "- **Admin** sees all equipment issues.\n"
    "- **Coach** sees issues for members on their teams.\n"
    "- **Player** sees only their own issues.")
def list_issues(
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
    active_only: bool = False,
):
    ip = request.client.host if request.client else "unknown"
    active_clause = " AND ei.ReturnDate IS NULL" if active_only else ""
    if current_user["role"] == "Player":
        track_db.execute(
            """
            SELECT ei.*, e.EquipmentName, m.Name AS MemberName
            FROM EquipmentIssue ei
            JOIN Equipment e ON ei.EquipmentID = e.EquipmentID
            JOIN Member m    ON ei.MemberID    = m.MemberID
            WHERE ei.MemberID = %s
            """ + active_clause + """
            ORDER BY ei.IssueDate DESC
            """,
            (current_user["member_id"],),
        )
    elif current_user["role"] == "Coach":
        track_db.execute(
            """
            SELECT ei.*, e.EquipmentName, m.Name AS MemberName
            FROM EquipmentIssue ei
            JOIN Equipment e ON ei.EquipmentID = e.EquipmentID
            JOIN Member m    ON ei.MemberID    = m.MemberID
            WHERE EXISTS (
                SELECT 1
                FROM TeamMember tm
                JOIN Team t ON tm.TeamID = t.TeamID
                WHERE tm.MemberID = ei.MemberID
                  AND t.CoachID = %s
            )
            """ + active_clause + """
            ORDER BY ei.IssueDate DESC
            """,
            (current_user["member_id"],),
        )
    else:
        track_db.execute(
            """
            SELECT ei.*, e.EquipmentName, m.Name AS MemberName
            FROM EquipmentIssue ei
            JOIN Equipment e ON ei.EquipmentID = e.EquipmentID
            JOIN Member m    ON ei.MemberID    = m.MemberID
            WHERE 1 = 1
            """ + active_clause + """
            ORDER BY ei.IssueDate DESC
            """
        )
    rows = track_db.fetchall()
    for r in rows:
        r["IssueDate"]  = str(r["IssueDate"])
        if r.get("ReturnDate"):
            r["ReturnDate"] = str(r["ReturnDate"])
    write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                    "SELECT", "EquipmentIssue", None, "SUCCESS", {"count": len(rows)}, ip)
    return {"success": True, "data": rows}


@router.get("/{equipment_id}", description="**Access:** Any authenticated user (Admin, Coach, Player).")
def get_equipment(
    equipment_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    equipment = _get_equipment_or_404(track_db, equipment_id)
    write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                    "SELECT", "Equipment", str(equipment_id), "SUCCESS", None, ip)
    return {"success": True, "data": equipment}


@router.put("/{equipment_id}", description="**Access:** Admin only.")
def update_equipment(
    equipment_id: int,
    body: EquipmentUpdate,
    request: Request,
    current_user: dict = Depends(require_admin),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    _get_equipment_or_404(track_db, equipment_id)
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update.")
    _validate_equipment_payload(
        track_db,
        fields.get("total_quantity"),
        fields.get("sport_id"),
        equipment_id=equipment_id,
    )
    col_map = {
        "equipment_name": "EquipmentName",
        "total_quantity": "TotalQuantity",
        "equipment_condition": "EquipmentCondition",
        "sport_id": "SportID",
    }
    set_clause = ", ".join(f"{col_map[key]} = %s" for key in fields)
    try:
        track_db.execute(
            f"UPDATE Equipment SET {set_clause} WHERE EquipmentID = %s",
            list(fields.values()) + [equipment_id],
        )
    except Exception as exc:
        write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                        "UPDATE", "Equipment", str(equipment_id), "FAILURE", {"error": str(exc)}, ip)
        raise HTTPException(status_code=400, detail=humanize_db_error(exc)) from exc
    write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                    "UPDATE", "Equipment", str(equipment_id), "SUCCESS", fields, ip)
    return {"success": True, "message": "Equipment updated"}


@router.delete("/{equipment_id}", description="**Access:** Admin only. Deletion is blocked if the equipment has active (unreturned) issues.")
def delete_equipment(
    equipment_id: int,
    request: Request,
    current_user: dict = Depends(require_admin),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    equipment = _get_equipment_or_404(track_db, equipment_id)
    if equipment["IssuedQuantity"]:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete equipment while it has active issued items.",
        )
    track_db.execute("DELETE FROM Equipment WHERE EquipmentID = %s", (equipment_id,))
    write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                    "DELETE", "Equipment", str(equipment_id), "SUCCESS", None, ip)
    return {"success": True, "message": f"Equipment {equipment_id} deleted"}


@router.post("/issue", description="**Access:** Admin or Coach.\n\n"
    "- **Admin** can issue equipment to any member.\n"
    "- **Coach** can only issue equipment to members on their teams.")
def issue_equipment(
    body: IssueCreate,
    request: Request,
    current_user: dict = Depends(require_admin_or_coach),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    issue_id = body.issue_id
    if body.quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be a positive number.")
    assert_coach_manages_member(track_db, current_user, body.member_id)
    track_db.execute(
        """
        SELECT e.TotalQuantity,
               COALESCE(SUM(ei.Quantity), 0) AS issued
        FROM Equipment e
        LEFT JOIN EquipmentIssue ei
               ON e.EquipmentID = ei.EquipmentID AND ei.ReturnDate IS NULL
        WHERE e.EquipmentID = %s
        GROUP BY e.TotalQuantity
        FOR UPDATE
        """,
        (body.equipment_id,),
    )
    stock = track_db.fetchone()
    if not stock:
        raise HTTPException(status_code=404, detail="Equipment not found.")
    available = stock["TotalQuantity"] - stock["issued"]
    if body.quantity > available:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot issue {body.quantity} item(s). Only {available} available.",
        )
    try:
        parsed_issue = parse_iso_date(body.issue_date, "Issue date")
        validate_not_future(parsed_issue, "Issue date")
        if body.return_date:
            parsed_return = parse_iso_date(body.return_date, "Return date")
            validate_not_future(parsed_return, "Return date")
            validate_date_order(parsed_issue, parsed_return, "Issue date", "Return date")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        issue_id = insert_with_generated_id(
            track_db,
            requested_id=issue_id,
            next_id_sql="SELECT COALESCE(MAX(IssueID), 0) + 1 AS nid FROM EquipmentIssue",
            insert_fn=lambda issue_id: track_db.execute(
                "INSERT INTO EquipmentIssue (IssueID, EquipmentID, MemberID, IssueDate, ReturnDate, Quantity) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (issue_id, body.equipment_id, body.member_id,
                 body.issue_date, body.return_date, body.quantity),
            ),
        )
    except Exception as e:
        write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                        "INSERT", "EquipmentIssue", str(issue_id), "FAILURE", {"error": str(e)}, ip)
        raise HTTPException(status_code=400, detail=humanize_db_error(e)) from e
    write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                    "INSERT", "EquipmentIssue", str(issue_id), "SUCCESS",
                    {"equipment_id": body.equipment_id, "member_id": body.member_id}, ip)
    return {"success": True, "message": "Equipment issued", "data": {"issue_id": issue_id}}


@router.put("/issue/{issue_id}/return", description="**Access:** Admin or Coach.\n\n"
    "- **Admin** can process any return.\n"
    "- **Coach** can only process returns for members on their teams.")
def return_equipment(
    issue_id: int,
    return_date: str,
    request: Request,
    current_user: dict = Depends(require_admin_or_coach),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    track_db.execute(
        "SELECT IssueID, MemberID, IssueDate, ReturnDate FROM EquipmentIssue WHERE IssueID = %s",
        (issue_id,),
    )
    issue = track_db.fetchone()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue record not found")
    if current_user["role"] == "Coach":
        assert_coach_manages_member(track_db, current_user, issue["MemberID"])
    if issue.get("ReturnDate"):
        raise HTTPException(status_code=400, detail="This equipment issue has already been returned.")
    try:
        parsed_return_date = parse_iso_date(return_date, "Return date")
        validate_not_future(parsed_return_date, "Return date")
        if issue.get("IssueDate") is not None:
            parsed_issue_date = parse_iso_date(str(issue["IssueDate"]), "Issue date")
            validate_date_order(parsed_issue_date, parsed_return_date, "Issue date", "Return date")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    track_db.execute(
        "UPDATE EquipmentIssue SET ReturnDate = %s WHERE IssueID = %s",
        (return_date, issue_id),
    )
    write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                    "UPDATE", "EquipmentIssue", str(issue_id), "SUCCESS",
                    {"return_date": return_date}, ip)
    return {"success": True, "message": "Equipment returned"}
