from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
from app.auth.dependencies import get_current_user, require_admin
from app.database import get_auth_db, get_track_db
from app.services.audit import write_audit_log
from app.services.id_generation import insert_with_generated_id
from app.services.validation import (
    humanize_db_error,
    parse_iso_date,
    parse_iso_time,
    validate_time_order,
)

router = APIRouter()


class EventCreate(BaseModel):
    event_id:      Optional[int] = None
    event_name:    str
    event_date:    str
    start_time:    str
    end_time:      str
    venue_id:      int
    sport_id:      int
    status:        str
    tournament_id: Optional[int] = None
    round:         Optional[str] = None


class EventUpdate(BaseModel):
    event_name:    Optional[str] = None
    event_date:    Optional[str] = None
    start_time:    Optional[str] = None
    end_time:      Optional[str] = None
    venue_id:      Optional[int] = None
    sport_id:      Optional[int] = None
    status:        Optional[str] = None
    tournament_id: Optional[int] = None
    round:         Optional[str] = None


class ParticipationUpdate(BaseModel):
    score:    Optional[str] = None
    event_rank: Optional[int] = None
    result:   Optional[str] = None
    remarks:  Optional[str] = None


def _get_event_or_404(track_db, event_id: int) -> dict:
    track_db.execute(
        """
        SELECT e.*, s.SportName, v.VenueName, t.TournamentName
        FROM Event e
        LEFT JOIN Sport s ON e.SportID = s.SportID
        LEFT JOIN Venue v ON e.VenueID = v.VenueID
        LEFT JOIN Tournament t ON e.TournamentID = t.TournamentID
        WHERE e.EventID = %s
        """,
        (event_id,),
    )
    event = track_db.fetchone()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


def _validate_event_payload(event_date: str, start_time: str, end_time: str) -> None:
    parse_iso_date(event_date, "Event date")
    parsed_start_time = parse_iso_time(start_time, "Start time")
    parsed_end_time = parse_iso_time(end_time, "End time")
    validate_time_order(parsed_start_time, parsed_end_time, "Start time", "End time")


@router.get("/lookups", description="**Access:** Any authenticated user (Admin, Coach, Player). Returns dropdown options (sports, venues, tournaments) for event forms.")
def get_event_form_options(
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    track_db.execute("SELECT SportID, SportName FROM Sport ORDER BY SportName")
    sports = track_db.fetchall()
    track_db.execute("SELECT VenueID, VenueName FROM Venue ORDER BY VenueName")
    venues = track_db.fetchall()
    track_db.execute("SELECT TournamentID, TournamentName FROM Tournament ORDER BY TournamentName")
    tournaments = track_db.fetchall()
    write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                    "SELECT", "Event", None, "SUCCESS", {"lookups": True}, ip)
    return {
        "success": True,
        "data": {
            "sports": sports,
            "venues": venues,
            "tournaments": tournaments,
        },
    }


@router.get("", description="**Access:** Any authenticated user (Admin, Coach, Player). Lists events with optional filters.")
def list_events(
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
    tournament_id: Optional[int] = None,
    sport_id:      Optional[int] = None,
    status:        Optional[str] = None,
):
    ip = request.client.host if request.client else "unknown"
    query = """
        SELECT e.*, s.SportName, v.VenueName, t.TournamentName
        FROM Event e
        JOIN Sport s ON e.SportID = s.SportID
        JOIN Venue v ON e.VenueID = v.VenueID
        LEFT JOIN Tournament t ON e.TournamentID = t.TournamentID
        WHERE 1=1
    """
    params = []
    if tournament_id:
        query += " AND e.TournamentID = %s"; params.append(tournament_id)
    if sport_id:
        query += " AND e.SportID = %s";      params.append(sport_id)
    if status:
        query += " AND e.Status = %s";       params.append(status)
    query += " ORDER BY e.EventDate DESC"
    track_db.execute(query, params)
    rows = track_db.fetchall()
    for r in rows:
        r["EventDate"]  = str(r["EventDate"])
        r["StartTime"]  = str(r["StartTime"])
        r["EndTime"]    = str(r["EndTime"])
    write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                    "SELECT", "Event", None, "SUCCESS", {"count": len(rows)}, ip)
    return {"success": True, "data": rows}


@router.get("/{event_id}", description="**Access:** Any authenticated user (Admin, Coach, Player).\n\n"
    "Returns event details and participating teams. "
    "**Coach** sees only their own teams as eligible; Admin/Player see all eligible teams.")
def get_event(
    event_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    event = _get_event_or_404(track_db, event_id)
    track_db.execute(
        """
        SELECT p.*, tm.TeamName, tm.CoachID
        FROM Participation p
        JOIN Team tm ON p.TeamID = tm.TeamID
        WHERE p.EventID = %s
        """,
        (event_id,),
    )
    participation = track_db.fetchall()
    participating_ids = {team["TeamID"] for team in participation}
    if event.get("TournamentID"):
        query = """
            SELECT t.TeamID, t.TeamName, t.CoachID
            FROM TournamentRegistration tr
            JOIN Team t ON tr.TeamID = t.TeamID
            WHERE tr.TournamentID = %s
              AND t.SportID = %s
        """
        params = [event["TournamentID"], event["SportID"]]
        if current_user["role"] == "Coach":
            query += " AND t.CoachID = %s"
            params.append(current_user["member_id"])
        query += " ORDER BY t.TeamName"
        track_db.execute(query, tuple(params))
    else:
        query = "SELECT TeamID, TeamName, CoachID FROM Team WHERE SportID = %s"
        params = [event["SportID"]]
        if current_user["role"] == "Coach":
            query += " AND CoachID = %s"
            params.append(current_user["member_id"])
        query += " ORDER BY TeamName"
        track_db.execute(query, tuple(params))
    eligible_teams = [
        team for team in track_db.fetchall()
        if team["TeamID"] not in participating_ids
    ]
    for k in ("EventDate", "StartTime", "EndTime"):
        if event.get(k):
            event[k] = str(event[k])
    write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                    "SELECT", "Event", str(event_id), "SUCCESS", None, ip)
    return {
        "success": True,
        "data": {
            "event": event,
            "participation": participation,
            "eligible_teams": eligible_teams,
        },
    }


@router.post("", description="**Access:** Admin only.")
def create_event(
    body: EventCreate,
    request: Request,
    current_user: dict = Depends(require_admin),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    event_id = body.event_id
    try:
        _validate_event_payload(body.event_date, body.start_time, body.end_time)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        event_id = insert_with_generated_id(
            track_db,
            requested_id=event_id,
            next_id_sql="SELECT COALESCE(MAX(EventID), 0) + 1 AS nid FROM Event",
            insert_fn=lambda event_id: track_db.execute(
                """
                INSERT INTO Event
                    (EventID, EventName, TournamentID, EventDate, StartTime, EndTime,
                     VenueID, SportID, Status, Round)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (event_id, body.event_name, body.tournament_id, body.event_date,
                 body.start_time, body.end_time, body.venue_id, body.sport_id,
                 body.status, body.round),
            ),
        )
    except Exception as e:
        write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                        "INSERT", "Event", str(event_id), "FAILURE", {"error": str(e)}, ip)
        raise HTTPException(status_code=400, detail=humanize_db_error(e)) from e
    write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                    "INSERT", "Event", str(event_id), "SUCCESS",
                    {"name": body.event_name}, ip)
    return {"success": True, "message": "Event created", "data": {"event_id": event_id}}


@router.put("/{event_id}", description="**Access:** Admin only.")
def update_event(
    event_id: int,
    body: EventUpdate,
    request: Request,
    current_user: dict = Depends(require_admin),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    event = _get_event_or_404(track_db, event_id)
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    if any(key in fields for key in ("event_date", "start_time", "end_time")) or all(
        key in event for key in ("EventDate", "StartTime", "EndTime")
    ):
        try:
            _validate_event_payload(
                fields.get("event_date") or str(event.get("EventDate")),
                fields.get("start_time") or str(event.get("StartTime")),
                fields.get("end_time") or str(event.get("EndTime")),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    col_map = {
        "event_name": "EventName", "event_date": "EventDate", "start_time": "StartTime",
        "end_time": "EndTime", "venue_id": "VenueID", "sport_id": "SportID",
        "status": "Status", "tournament_id": "TournamentID", "round": "Round",
    }
    set_clause = ", ".join(f"{col_map[k]} = %s" for k in fields)
    try:
        track_db.execute(f"UPDATE Event SET {set_clause} WHERE EventID=%s",
                         list(fields.values()) + [event_id])
    except Exception as exc:
        raise HTTPException(status_code=400, detail=humanize_db_error(exc)) from exc
    write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                    "UPDATE", "Event", str(event_id), "SUCCESS", fields, ip)
    return {"success": True, "message": "Event updated"}


@router.delete("/{event_id}", description="**Access:** Admin only.")
def delete_event(
    event_id: int,
    request: Request,
    current_user: dict = Depends(require_admin),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    _get_event_or_404(track_db, event_id)
    track_db.execute("DELETE FROM Event WHERE EventID=%s", (event_id,))
    write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                    "DELETE", "Event", str(event_id), "SUCCESS", None, ip)
    return {"success": True, "message": f"Event {event_id} deleted"}


@router.put("/{event_id}/participation/{team_id}", description="**Access:** Admin or Coach of the team.\n\n"
    "- **Admin** can update any team's participation.\n"
    "- **Coach** can only update participation for teams they manage.")
def update_participation(
    event_id: int,
    team_id: int,
    body: ParticipationUpdate,
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    # Check if participation exists
    track_db.execute(
        "SELECT * FROM Participation WHERE EventID = %s AND TeamID = %s",
        (event_id, team_id),
    )
    participation = track_db.fetchone()
    if not participation:
        raise HTTPException(status_code=404, detail="Participation not found")
    
    # Check permissions: Admin or Coach of the team
    if current_user["role"] != "Admin":
        track_db.execute("SELECT CoachID FROM Team WHERE TeamID = %s", (team_id,))
        team = track_db.fetchone()
        if not team or team["CoachID"] != current_user["member_id"]:
            raise HTTPException(status_code=403, detail="Access denied")
    
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    
    col_map = {
        "score": "Score",
        "event_rank": "EventRank",
        "result": "Result",
        "remarks": "Remarks",
    }
    set_clause = ", ".join(f"{col_map[k]} = %s" for k in fields)
    try:
        track_db.execute(
            f"UPDATE Participation SET {set_clause} WHERE EventID = %s AND TeamID = %s",
            list(fields.values()) + [event_id, team_id]
        )
    except Exception as exc:
        write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                        "UPDATE", "Participation", f"{event_id}-{team_id}", "FAILURE", {"error": str(exc)}, ip)
        raise HTTPException(status_code=400, detail=humanize_db_error(exc)) from exc
    
    write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                    "UPDATE", "Participation", f"{event_id}-{team_id}", "SUCCESS", fields, ip)
    return {"success": True, "message": "Participation updated"}
