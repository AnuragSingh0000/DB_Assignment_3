from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from app.auth.dependencies import get_current_user, require_admin, require_admin_or_coach
from app.database import get_auth_db, get_track_db
from app.services.audit import write_audit_log
from app.services.validation import humanize_db_error, parse_iso_date

router = APIRouter()


class TeamMemberEntry(BaseModel):
    member_id: int
    position: Optional[str] = None


class TeamCreate(BaseModel):
    team_id:    Optional[int] = None
    team_name:  str
    sport_id:   int
    formed_date: str
    coach_id:   Optional[int] = None
    captain_id: Optional[int] = None
    members: list[TeamMemberEntry] = Field(default_factory=list)


class TeamUpdate(BaseModel):
    team_name:  Optional[str] = None
    sport_id:   Optional[int] = None
    formed_date: Optional[str] = None
    coach_id:   Optional[int] = None
    captain_id: Optional[int] = None
    members: Optional[list[TeamMemberEntry]] = None


def _get_team_or_404(track_db, team_id: int) -> dict:
    track_db.execute("SELECT * FROM Team WHERE TeamID = %s", (team_id,))
    row = track_db.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Team not found")
    return row


def _validate_team_fields(track_db, sport_id=None, coach_id=None, formed_date=None):
    if coach_id:
        track_db.execute("SELECT Role FROM Member WHERE MemberID = %s", (coach_id,))
        coach = track_db.fetchone()
        if not coach or coach["Role"] != "Coach":
            raise HTTPException(status_code=400, detail="Selected coach is not valid.")
    if formed_date:
        formed = parse_iso_date(formed_date, "Formed date")
        if formed > datetime.now().date():
            raise HTTPException(status_code=400, detail="Formed date cannot be in the future.")
    if sport_id:
        track_db.execute("SELECT SportName FROM Sport WHERE SportID = %s", (sport_id,))
        if not track_db.fetchone():
            raise HTTPException(status_code=400, detail="Selected sport is not valid.")


def _normalize_members(members: Optional[list[TeamMemberEntry]]) -> list[TeamMemberEntry]:
    if not members:
        return []
    normalized = []
    seen = set()
    for entry in members:
        if entry.member_id in seen:
            raise HTTPException(status_code=400, detail="Duplicate member IDs are not allowed.")
        seen.add(entry.member_id)
        normalized.append(entry)
    return normalized


def _extract_member_ids(members: list[TeamMemberEntry]) -> list[int]:
    return [m.member_id for m in members]


def _validate_team_members(track_db, member_ids: list[int], captain_id: Optional[int]):
    if captain_id is not None and captain_id not in member_ids:
        raise HTTPException(status_code=400, detail="Captain ID must belong to a member in the team.")
    if not member_ids:
        return
    placeholders = ", ".join(["%s"] * len(member_ids))
    track_db.execute(
        f"SELECT MemberID, Role FROM Member WHERE MemberID IN ({placeholders})",
        tuple(member_ids),
    )
    rows = {row["MemberID"]: row for row in track_db.fetchall()}
    missing_ids = [member_id for member_id in member_ids if member_id not in rows]
    if missing_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid member ID(s): {', '.join(str(member_id) for member_id in missing_ids)}",
        )
    invalid_player_ids = [member_id for member_id in member_ids if rows[member_id]["Role"] != "Player"]
    if invalid_player_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Team members must be players. Invalid member ID(s): {', '.join(str(member_id) for member_id in invalid_player_ids)}",
        )


def _sync_team_members(track_db, team_id: int, members: list[TeamMemberEntry], captain_id: Optional[int], join_date: str):
    track_db.execute(
        "SELECT MemberID, JoinDate, Position FROM TeamMember WHERE TeamID = %s",
        (team_id,),
    )
    existing_rows = {row["MemberID"]: row for row in track_db.fetchall()}
    member_ids = _extract_member_ids(members)
    members_to_remove = [mid for mid in existing_rows if mid not in member_ids]
    for mid in members_to_remove:
        track_db.execute(
            "DELETE FROM TeamMember WHERE TeamID = %s AND MemberID = %s",
            (team_id, mid),
        )
    for entry in members:
        is_captain = entry.member_id == captain_id
        position = entry.position.strip() if entry.position else None
        existing_row = existing_rows.get(entry.member_id)
        if existing_row:
            track_db.execute(
                "UPDATE TeamMember SET IsCaptain = %s, Position = %s WHERE TeamID = %s AND MemberID = %s",
                (is_captain, position, team_id, entry.member_id),
            )
            continue
        track_db.execute(
            """
            INSERT INTO TeamMember (TeamID, MemberID, JoinDate, Position, IsCaptain)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (team_id, entry.member_id, join_date, position, is_captain),
        )


@router.get("", description="**Access:** Any authenticated user (Admin, Coach, Player). Lists all teams.")
def list_teams(
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    track_db.execute(
        """
        SELECT t.*, s.SportName,
               m.Name AS CoachName
        FROM Team t
        JOIN Sport s ON t.SportID = s.SportID
        LEFT JOIN Member m ON t.CoachID = m.MemberID
        ORDER BY t.TeamID
        """
    )
    rows = track_db.fetchall()
    write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                    "SELECT", "Team", None, "SUCCESS", {"count": len(rows)}, ip)
    return {"success": True, "data": rows}


@router.get("/{team_id}", description="**Access:** Any authenticated user (Admin, Coach, Player).\n\n"
    "Returns team details, roster, and events. **Player** users cannot see other members' email addresses.")
def get_team(
    team_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    track_db.execute(
        """
        SELECT t.*, s.SportName, m.Name AS CoachName
        FROM Team t
        JOIN Sport s ON t.SportID = s.SportID
        LEFT JOIN Member m ON t.CoachID = m.MemberID
        WHERE t.TeamID = %s
        """,
        (team_id,),
    )
    team = track_db.fetchone()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    track_db.execute(
        """
        SELECT tm.*, m.Name, m.Role, m.Email
        FROM TeamMember tm
        JOIN Member m ON tm.MemberID = m.MemberID
        WHERE tm.TeamID = %s
        """,
        (team_id,),
    )
    roster = track_db.fetchall()
    if current_user["role"] == "Player":
        for row in roster:
            if row.get("MemberID") != current_user["member_id"]:
                row.pop("Email", None)
    track_db.execute(
        """
        SELECT e.EventID, e.EventName, e.EventDate, e.StartTime, e.EndTime, e.Status,
               e.Round, e.TournamentID, trn.TournamentName, v.VenueName
        FROM Participation p
        JOIN Event e ON p.EventID = e.EventID
        LEFT JOIN Tournament trn ON e.TournamentID = trn.TournamentID
        LEFT JOIN Venue v ON e.VenueID = v.VenueID
        WHERE p.TeamID = %s
        ORDER BY e.EventDate DESC, e.StartTime DESC
        """,
        (team_id,),
    )
    events = track_db.fetchall()
    write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                    "SELECT", "Team", str(team_id), "SUCCESS", None, ip)
    return {"success": True, "data": {"team": team, "roster": roster, "events": events}}


@router.post("", description="**Access:** Admin or Coach.\n\n"
    "- **Admin** can create a team with any coach.\n"
    "- **Coach** can only create teams assigned to themselves (coach_id must be self or omitted).")
def create_team(
    body: TeamCreate,
    request: Request,
    current_user: dict = Depends(require_admin_or_coach),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    if current_user["role"] == "Coach":
        if body.coach_id is None:
            body.coach_id = current_user["member_id"]
        elif body.coach_id != current_user["member_id"]:
            raise HTTPException(status_code=403, detail="Coach can only create teams assigned to themselves.")
    _validate_team_fields(track_db, sport_id=body.sport_id, coach_id=body.coach_id, formed_date=body.formed_date)
    members = _normalize_members(body.members)
    member_ids = _extract_member_ids(members)
    _validate_team_members(track_db, member_ids, body.captain_id)
    team_id = body.team_id
    if team_id is None:
        track_db.execute("SELECT COALESCE(MAX(TeamID), 0) + 1 AS nid FROM Team")
        team_id = track_db.fetchone()["nid"]
    try:
        track_db.execute(
            "INSERT INTO Team (TeamID, TeamName, CoachID, CaptainID, SportID, FormedDate) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (team_id, body.team_name, body.coach_id, body.captain_id,
             body.sport_id, body.formed_date),
        )
        _sync_team_members(track_db, team_id, members, body.captain_id, body.formed_date)
    except HTTPException:
        raise
    except Exception as e:
        write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                        "INSERT", "Team", str(team_id), "FAILURE", {"error": str(e)}, ip)
        raise HTTPException(status_code=400, detail=humanize_db_error(e)) from e
    write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                    "INSERT", "Team", str(team_id), "SUCCESS",
                    {"name": body.team_name}, ip)
    return {"success": True, "message": "Team created", "data": {"team_id": team_id}}


@router.put("/{team_id}", description="**Access:** Admin or Coach.\n\n"
    "- **Admin** can update any team.\n"
    "- **Coach** can only update teams they manage (team.CoachID must match the current user).")
def update_team(
    team_id: int,
    body: TeamUpdate,
    request: Request,
    current_user: dict = Depends(require_admin_or_coach),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    team = _get_team_or_404(track_db, team_id)
    if current_user["role"] == "Coach" and team["CoachID"] != current_user["member_id"]:
            raise HTTPException(status_code=403, detail="Coach can only update their own teams")
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    _validate_team_fields(
        track_db,
        sport_id=fields.get("sport_id"),
        coach_id=fields.get("coach_id"),
        formed_date=fields.get("formed_date"),
    )
    if "members" in fields:
        members = _normalize_members([TeamMemberEntry(**m) if isinstance(m, dict) else m for m in fields["members"]])
        member_ids = _extract_member_ids(members)
    else:
        members = None
        member_ids = None
    captain_id = fields.get("captain_id", team["CaptainID"])
    if member_ids is not None:
        _validate_team_members(track_db, member_ids, captain_id)
    elif "captain_id" in fields and captain_id is not None:
        track_db.execute("SELECT MemberID FROM TeamMember WHERE TeamID = %s", (team_id,))
        current_member_ids = [row["MemberID"] for row in track_db.fetchall()]
        _validate_team_members(track_db, current_member_ids, captain_id)
    col_map = {
        "team_name": "TeamName",
        "sport_id": "SportID",
        "formed_date": "FormedDate",
        "coach_id": "CoachID",
        "captain_id": "CaptainID",
    }
    db_fields = {k: v for k, v in fields.items() if k in col_map}
    if db_fields:
        set_clause = ", ".join(f"{col_map[k]} = %s" for k in db_fields)
        track_db.execute(
            f"UPDATE Team SET {set_clause} WHERE TeamID = %s",
            list(db_fields.values()) + [team_id],
        )
    if members is not None:
        _sync_team_members(
            track_db,
            team_id,
            members,
            captain_id,
            fields.get("formed_date") or str(team["FormedDate"]),
        )
    elif "captain_id" in fields:
        track_db.execute(
            "UPDATE TeamMember SET IsCaptain = FALSE WHERE TeamID = %s",
            (team_id,),
        )
        if captain_id is not None:
            track_db.execute(
                "UPDATE TeamMember SET IsCaptain = TRUE WHERE TeamID = %s AND MemberID = %s",
                (team_id, captain_id),
            )
    write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                    "UPDATE", "Team", str(team_id), "SUCCESS", fields, ip)
    return {"success": True, "message": "Team updated"}


@router.delete("/{team_id}", description="**Access:** Admin or Coach.\n\n"
    "- **Admin** can delete any team.\n"
    "- **Coach** can only delete teams they manage (team.CoachID must match the current user).")
def delete_team(
    team_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    team = _get_team_or_404(track_db, team_id)
    if current_user["role"] not in ("Admin", "Coach"):
        raise HTTPException(status_code=403, detail="Access denied")
    if current_user["role"] == "Coach" and team["CoachID"] != current_user["member_id"]:
        raise HTTPException(status_code=403, detail="Coach can only delete their own teams")
    track_db.execute("DELETE FROM Team WHERE TeamID = %s", (team_id,))
    write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                    "DELETE", "Team", str(team_id), "SUCCESS", None, ip)
    return {"success": True, "message": f"Team {team_id} deleted"}
