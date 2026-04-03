from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
from app.auth.dependencies import get_current_user, require_admin
from app.database import get_auth_db, get_track_db
from app.services.audit import write_audit_log
from app.services.id_generation import insert_with_generated_id
from app.services.validation import (
    derive_tournament_status,
    humanize_db_error,
    parse_iso_date,
    validate_date_order,
)

router = APIRouter()


class TournamentCreate(BaseModel):
    tournament_id:   Optional[int] = None
    tournament_name: str
    start_date:      str
    end_date:        str
    status:          str
    description:     Optional[str] = None


class TournamentUpdate(BaseModel):
    tournament_name: Optional[str] = None
    start_date:      Optional[str] = None
    end_date:        Optional[str] = None
    status:          Optional[str] = None
    description:     Optional[str] = None


def _get_tournament_or_404(track_db, tournament_id: int) -> dict:
    track_db.execute("SELECT * FROM Tournament WHERE TournamentID = %s", (tournament_id,))
    tournament = track_db.fetchone()
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    return tournament


def _validate_tournament_fields(
    track_db,
    tournament_name: str,
    start_date: str,
    end_date: str,
    *,
    exclude_id: int | None = None,
    check_unique: bool = True,
) -> str:
    parsed_start = parse_iso_date(start_date, "Start date")
    parsed_end = parse_iso_date(end_date, "End date")
    validate_date_order(parsed_start, parsed_end, "Start date", "End date")
    if check_unique:
        params = [tournament_name.strip()]
        query = "SELECT TournamentID FROM Tournament WHERE TournamentName = %s"
        if exclude_id is not None:
            query += " AND TournamentID <> %s"
            params.append(exclude_id)
        track_db.execute(query, tuple(params))
        existing_rows = track_db.fetchall()
        if existing_rows:
            raise HTTPException(status_code=400, detail="Tournament name must be unique.")
    return derive_tournament_status(parsed_start, parsed_end)


@router.get("", description="**Access:** Any authenticated user (Admin, Coach, Player). Lists all tournaments.")
def list_tournaments(
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    track_db.execute("SELECT * FROM Tournament ORDER BY StartDate DESC")
    rows = track_db.fetchall()
    for r in rows:
        r["StartDate"] = str(r["StartDate"])
        r["EndDate"]   = str(r["EndDate"])
    write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                    "SELECT", "Tournament", None, "SUCCESS", {"count": len(rows)}, ip)
    return {"success": True, "data": rows}


@router.get("/{tournament_id}", description="**Access:** Any authenticated user (Admin, Coach, Player).\n\n"
    "Returns tournament details, events, and registered teams. "
    "**Coach** sees only their own teams as available for registration; Admin/Player see all teams.")
def get_tournament(
    tournament_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    tournament = _get_tournament_or_404(track_db, tournament_id)
    tournament["StartDate"] = str(tournament["StartDate"])
    tournament["EndDate"] = str(tournament["EndDate"])
    track_db.execute(
        """
        SELECT e.*, s.SportName, v.VenueName
        FROM Event e
        JOIN Sport s ON e.SportID = s.SportID
        JOIN Venue v ON e.VenueID = v.VenueID
        WHERE e.TournamentID = %s
        ORDER BY e.EventDate
        """,
        (tournament_id,),
    )
    events = track_db.fetchall()
    for event in events:
        event["EventDate"] = str(event["EventDate"])
        event["StartTime"] = str(event["StartTime"])
        event["EndTime"] = str(event["EndTime"])
    track_db.execute(
        """
        SELECT tr.RegID, t.TeamID, t.TeamName, s.SportName
        FROM TournamentRegistration tr
        JOIN Team t ON tr.TeamID = t.TeamID
        JOIN Sport s ON t.SportID = s.SportID
        WHERE tr.TournamentID = %s
        ORDER BY t.TeamName
        """,
        (tournament_id,),
    )
    registered_teams = track_db.fetchall()
    registered_ids = {team["TeamID"] for team in registered_teams}
    if current_user["role"] == "Coach":
        track_db.execute(
            "SELECT TeamID, TeamName FROM Team WHERE CoachID = %s ORDER BY TeamName",
            (current_user["member_id"],),
        )
    else:
        track_db.execute("SELECT TeamID, TeamName FROM Team ORDER BY TeamName")
    available_teams = [
        team for team in track_db.fetchall()
        if team["TeamID"] not in registered_ids
    ]
    write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                    "SELECT", "Tournament", str(tournament_id), "SUCCESS", None, ip)
    return {
        "success": True,
        "data": {
            "tournament": tournament,
            "events": events,
            "registered_teams": registered_teams,
            "available_teams": available_teams,
        },
    }


@router.post("", description="**Access:** Admin only.")
def create_tournament(
    body: TournamentCreate,
    request: Request,
    current_user: dict = Depends(require_admin),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    tournament_id = body.tournament_id
    body.status = _validate_tournament_fields(
        track_db,
        body.tournament_name,
        body.start_date,
        body.end_date,
        check_unique=False,
    )
    try:
        tournament_id = insert_with_generated_id(
            track_db,
            requested_id=tournament_id,
            next_id_sql="SELECT COALESCE(MAX(TournamentID), 0) + 1 AS nid FROM Tournament",
            insert_fn=lambda tournament_id: track_db.execute(
                "INSERT INTO Tournament (TournamentID, TournamentName, StartDate, EndDate, Description, Status) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (tournament_id, body.tournament_name, body.start_date,
                 body.end_date, body.description, body.status),
            ),
        )
    except Exception as e:
        write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                        "INSERT", "Tournament", str(tournament_id), "FAILURE", {"error": str(e)}, ip)
        raise HTTPException(status_code=400, detail=humanize_db_error(e)) from e
    write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                    "INSERT", "Tournament", str(tournament_id), "SUCCESS",
                    {"name": body.tournament_name}, ip)
    return {"success": True, "message": "Tournament created",
            "data": {"tournament_id": tournament_id}}


@router.put("/{tournament_id}", description="**Access:** Admin only.")
def update_tournament(
    tournament_id: int,
    body: TournamentUpdate,
    request: Request,
    current_user: dict = Depends(require_admin),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    tournament = _get_tournament_or_404(track_db, tournament_id)
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    if any(key in fields for key in ("tournament_name", "start_date", "end_date")) or all(
        key in tournament for key in ("TournamentName", "StartDate", "EndDate")
    ):
        derived_status = _validate_tournament_fields(
            track_db,
            fields.get("tournament_name") or tournament["TournamentName"],
            fields.get("start_date") or str(tournament["StartDate"]),
            fields.get("end_date") or str(tournament["EndDate"]),
            exclude_id=tournament_id,
        )
        fields["status"] = derived_status
    col_map = {
        "tournament_name": "TournamentName", "start_date": "StartDate",
        "end_date": "EndDate", "status": "Status", "description": "Description",
    }
    set_clause = ", ".join(f"{col_map[k]} = %s" for k in fields)
    try:
        track_db.execute(f"UPDATE Tournament SET {set_clause} WHERE TournamentID=%s",
                         list(fields.values()) + [tournament_id])
    except Exception as exc:
        raise HTTPException(status_code=400, detail=humanize_db_error(exc)) from exc
    write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                    "UPDATE", "Tournament", str(tournament_id), "SUCCESS", fields, ip)
    return {"success": True, "message": "Tournament updated"}


@router.delete("/{tournament_id}", description="**Access:** Admin only.")
def delete_tournament(
    tournament_id: int,
    request: Request,
    current_user: dict = Depends(require_admin),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    _get_tournament_or_404(track_db, tournament_id)
    track_db.execute("DELETE FROM Tournament WHERE TournamentID=%s", (tournament_id,))
    write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                    "DELETE", "Tournament", str(tournament_id), "SUCCESS", None, ip)
    return {"success": True, "message": f"Tournament {tournament_id} deleted"}
