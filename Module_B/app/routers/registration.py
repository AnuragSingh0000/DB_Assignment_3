from fastapi import APIRouter, Depends, HTTPException, Request
from app.auth.dependencies import require_admin_or_coach
from app.database import get_auth_db, get_track_db
from app.services.audit import write_audit_log
from app.services.id_generation import insert_with_generated_id

router = APIRouter()


@router.post("/tournament/{tournament_id}/team/{team_id}", description="**Access:** Admin or Coach.\n\n"
    "- **Admin** can register any team.\n"
    "- **Coach** can only register teams they manage.")
def register_team_for_tournament(
    tournament_id: int,
    team_id: int,
    request: Request,
    current_user: dict = Depends(require_admin_or_coach),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    track_db.execute("SELECT TournamentID FROM Tournament WHERE TournamentID=%s", (tournament_id,))
    if not track_db.fetchone():
        raise HTTPException(status_code=404, detail="Tournament not found.")
    track_db.execute("SELECT TeamID, CoachID FROM Team WHERE TeamID=%s", (team_id,))
    team = track_db.fetchone()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found.")
    if current_user["role"] == "Coach" and team["CoachID"] != current_user["member_id"]:
        raise HTTPException(status_code=403, detail="Coach can only register their own teams.")
    track_db.execute(
        "SELECT RegID FROM TournamentRegistration WHERE TournamentID=%s AND TeamID=%s",
        (tournament_id, team_id),
    )
    if track_db.fetchone():
        raise HTTPException(status_code=409, detail="Team is already registered for this tournament.")
    next_id = insert_with_generated_id(
        track_db,
        requested_id=None,
        next_id_sql="SELECT COALESCE(MAX(RegID), 0) + 1 AS nid FROM TournamentRegistration",
        insert_fn=lambda reg_id: track_db.execute(
            "INSERT INTO TournamentRegistration (RegID, TournamentID, TeamID) VALUES (%s,%s,%s)",
            (reg_id, tournament_id, team_id),
        ),
    )
    write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                    "INSERT", "TournamentRegistration", str(next_id), "SUCCESS",
                    {"tournament_id": tournament_id, "team_id": team_id}, ip)
    return {"success": True, "message": "Team registered for tournament.", "data": {"reg_id": next_id}}


@router.delete("/tournament/{tournament_id}/team/{team_id}", description="**Access:** Admin or Coach.\n\n"
    "- **Admin** can unregister any team.\n"
    "- **Coach** can only unregister teams they manage.")
def unregister_team_from_tournament(
    tournament_id: int,
    team_id: int,
    request: Request,
    current_user: dict = Depends(require_admin_or_coach),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    track_db.execute("SELECT TeamID, CoachID FROM Team WHERE TeamID=%s", (team_id,))
    team = track_db.fetchone()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found.")
    if current_user["role"] == "Coach" and team["CoachID"] != current_user["member_id"]:
        raise HTTPException(status_code=403, detail="Coach can only unregister their own teams.")
    track_db.execute(
        "SELECT RegID FROM TournamentRegistration WHERE TournamentID=%s AND TeamID=%s",
        (tournament_id, team_id),
    )
    row = track_db.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Registration not found.")
    track_db.execute(
        "DELETE FROM TournamentRegistration WHERE TournamentID=%s AND TeamID=%s",
        (tournament_id, team_id),
    )
    write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                    "DELETE", "TournamentRegistration", str(row["RegID"]), "SUCCESS",
                    {"tournament_id": tournament_id, "team_id": team_id}, ip)
    return {"success": True, "message": "Team unregistered from tournament."}


@router.post("/event/{event_id}/team/{team_id}", description="**Access:** Admin or Coach.\n\n"
    "- **Admin** can add any team to an event.\n"
    "- **Coach** can only add teams they manage.\n\n"
    "Validates that the team's sport matches the event sport. "
    "If the event belongs to a tournament, the team must be registered for that tournament first.")
def add_team_to_event(
    event_id: int,
    team_id: int,
    request: Request,
    current_user: dict = Depends(require_admin_or_coach),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    track_db.execute("SELECT EventID, TournamentID, SportID FROM Event WHERE EventID=%s", (event_id,))
    event = track_db.fetchone()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found.")
    track_db.execute("SELECT TeamID, SportID, CoachID FROM Team WHERE TeamID=%s", (team_id,))
    team = track_db.fetchone()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found.")
    if current_user["role"] == "Coach" and team["CoachID"] != current_user["member_id"]:
        raise HTTPException(status_code=403, detail="Coach can only add their own teams to events.")
    if team["SportID"] != event["SportID"]:
        raise HTTPException(status_code=400, detail="Team sport does not match the event sport.")
    if event["TournamentID"]:
        track_db.execute(
            "SELECT RegID FROM TournamentRegistration WHERE TournamentID=%s AND TeamID=%s",
            (event["TournamentID"], team_id),
        )
        if not track_db.fetchone():
            raise HTTPException(
                status_code=400,
                detail="Team must be registered for the tournament before joining its events.",
            )
    track_db.execute(
        "SELECT ParticipationID FROM Participation WHERE EventID=%s AND TeamID=%s",
        (event_id, team_id),
    )
    if track_db.fetchone():
        raise HTTPException(status_code=409, detail="Team is already participating in this event.")
    next_id = insert_with_generated_id(
        track_db,
        requested_id=None,
        next_id_sql="SELECT COALESCE(MAX(ParticipationID), 0) + 1 AS nid FROM Participation",
        insert_fn=lambda participation_id: track_db.execute(
            "INSERT INTO Participation (ParticipationID, TeamID, EventID) VALUES (%s,%s,%s)",
            (participation_id, team_id, event_id),
        ),
    )
    write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                    "INSERT", "Participation", str(next_id), "SUCCESS",
                    {"event_id": event_id, "team_id": team_id}, ip)
    return {"success": True, "message": "Team added to event.", "data": {"participation_id": next_id}}


@router.delete("/event/{event_id}/team/{team_id}", description="**Access:** Admin or Coach.\n\n"
    "- **Admin** can remove any team from an event.\n"
    "- **Coach** can only remove teams they manage.")
def remove_team_from_event(
    event_id: int,
    team_id: int,
    request: Request,
    current_user: dict = Depends(require_admin_or_coach),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    if current_user["role"] == "Coach":
        track_db.execute("SELECT CoachID FROM Team WHERE TeamID=%s", (team_id,))
        team = track_db.fetchone()
        if not team:
            raise HTTPException(status_code=404, detail="Team not found.")
        if team["CoachID"] != current_user["member_id"]:
            raise HTTPException(status_code=403, detail="Coach can only remove their own teams from events.")
    track_db.execute(
        "SELECT ParticipationID FROM Participation WHERE EventID=%s AND TeamID=%s",
        (event_id, team_id),
    )
    row = track_db.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Participation record not found.")
    track_db.execute(
        "DELETE FROM Participation WHERE EventID=%s AND TeamID=%s",
        (event_id, team_id),
    )
    write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                    "DELETE", "Participation", str(row["ParticipationID"]), "SUCCESS",
                    {"event_id": event_id, "team_id": team_id}, ip)
    return {"success": True, "message": "Team removed from event."}
