from fastapi import APIRouter, Depends, HTTPException, Request, Form, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
from urllib.parse import quote_plus
from datetime import date
import os
from app.auth.dependencies import get_current_user
from app.auth.router import LoginRequest, login as api_login
from app.database import get_auth_db, get_track_db, get_cross_db
from app.routers.admin import get_audit_log as api_get_audit_log, verify_audit as api_verify_audit, get_direct_modifications as api_get_direct_modifications
from app.routers.equipment import (
    EquipmentCreate,
    EquipmentUpdate,
    create_equipment as api_create_equipment,
    delete_equipment as api_delete_equipment,
    get_equipment as api_get_equipment,
    IssueCreate,
    issue_equipment as api_issue_equipment,
    list_equipment as api_list_equipment,
    list_issues as api_list_issues,
    return_equipment as api_return_equipment,
    update_equipment as api_update_equipment,
)

from app.routers.events import (
    EventCreate,
    EventUpdate,
    ParticipationUpdate,
    create_event as api_create_event,
    delete_event as api_delete_event,
    get_event as api_get_event,
    get_event_form_options as api_get_event_form_options,
    list_events as api_list_events,
    update_event as api_update_event,
    update_participation as api_update_participation,
)

from app.routers.medical import (
    MedicalCreate,
    MedicalUpdate,
    create_medical_record as api_create_medical_record,
    delete_medical_record as api_delete_medical_record,
    get_medical_record as api_get_medical_record,
    update_medical_record as api_update_medical_record,
)

from app.routers.members import (
    MemberCreate,
    MemberUpdate,
    create_member as api_create_member,
    delete_member as api_delete_member,
    get_member_portfolio as api_get_member_portfolio,
    list_members as api_list_members,
    update_member as api_update_member,
)

from app.routers.performance import (
    PerfLogCreate,
    PerfLogUpdate,
    create_performance_log as api_create_performance_log,
    delete_performance_log as api_delete_performance_log,
    get_performance_log as api_get_performance_log,
    update_performance_log as api_update_performance_log,
)

from app.routers.registration import (
    add_team_to_event as api_add_team_to_event,
    register_team_for_tournament as api_register_team_for_tournament,
    remove_team_from_event as api_remove_team_from_event,
    unregister_team_from_tournament as api_unregister_team_from_tournament,
)

from app.routers.teams import (
    TeamCreate,
    TeamMemberEntry,
    TeamUpdate,
    create_team as api_create_team,
    delete_team as api_delete_team,
    get_team as api_get_team,
    list_teams as api_list_teams,
    update_team as api_update_team,
)

from app.routers.tournaments import (
    TournamentCreate,
    TournamentUpdate,
    create_tournament as api_create_tournament,
    delete_tournament as api_delete_tournament,
    get_tournament as api_get_tournament,
    list_tournaments as api_list_tournaments,
    update_tournament as api_update_tournament,
)

from app.services.validation import COMMON_COUNTRY_CODES, combine_contact_number, split_contact_number

router = APIRouter()

_tmpl_dir = os.path.join(os.path.dirname(__file__), "..", "templates")

templates = Jinja2Templates(directory=os.path.abspath(_tmpl_dir))


def _ctx(request: Request, current_user: dict, **extra):
    flash = None
    success_msg = request.query_params.get("success")
    error_msg = request.query_params.get("error")
    if success_msg:
        flash = {"type": "success", "message": success_msg}
    elif error_msg:
        flash = {"type": "danger", "message": error_msg}
    return {"request": request, "current_user": current_user, "flash": flash, **extra}


def _flash_redirect(url: str, error: Optional[str] = None, success: Optional[str] = None) -> RedirectResponse:
    msg = error or success
    key = "error" if error else "success"
    return RedirectResponse(f"{url}?{key}={quote_plus(msg or '')}", status_code=303)


def _copy_set_cookie(source: Response, target: RedirectResponse) -> None:
    for header_name, header_value in source.raw_headers:
        if header_name.lower() == b"set-cookie":
            target.headers.append("set-cookie", header_value.decode("latin-1"))


def _get_event_lookups(request: Request, current_user: dict, track_db, auth_db) -> dict:
    return api_get_event_form_options(request, current_user, track_db, auth_db)["data"]


def _get_sports(track_db):
    track_db.execute("SELECT SportID, SportName FROM Sport ORDER BY SportName")
    return track_db.fetchall()


def _equipment_form_data(
    equipment_name: str = "",
    total_quantity: Optional[int] = None,
    equipment_condition: str = "New",
    sport_id: Optional[int] = None,
):
    return {
        "equipment_name": equipment_name,
        "total_quantity": total_quantity,
        "equipment_condition": equipment_condition,
        "sport_id": sport_id,
    }


def _parse_required_int(value, label: str) -> int:
    value = (value or "").strip()
    if not value:
        raise ValueError(f"{label} is required.")
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be a valid integer.") from exc


def _parse_optional_int(value, label: str) -> Optional[int]:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be a valid integer.") from exc


def _parse_members(form) -> list[TeamMemberEntry]:
    raw_ids = form.getlist("member_ids")
    raw_positions = form.getlist("member_positions")
    members = []
    for i, raw_id in enumerate(raw_ids):
        value = raw_id.strip()
        if not value:
            continue
        try:
            member_id = int(value)
        except ValueError as exc:
            raise ValueError("Each member ID must be a valid integer.") from exc
        position = raw_positions[i].strip() if i < len(raw_positions) and raw_positions[i].strip() else None
        members.append(TeamMemberEntry(member_id=member_id, position=position))
    return members


def _member_form_defaults(member=None, form_data=None) -> dict:
    prepared = dict(form_data or {})
    if "ContactCountryCode" in prepared and "ContactNumberLocal" in prepared:
        return prepared
    existing_contact = prepared.get("ContactNumber") or (member["ContactNumber"] if member else None)
    country_code, local_number = split_contact_number(existing_contact)
    prepared.setdefault("ContactCountryCode", country_code)
    prepared.setdefault("ContactNumberLocal", local_number)
    return prepared


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "auth/login.html", {"request": request})


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db=Depends(get_auth_db),
):
    api_response = Response()
    try:
        api_login(LoginRequest(username=username, password=password), request, api_response, db)
    except HTTPException:
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {"request": request, "error": "Invalid username or password", "username": username},
        )
    resp = RedirectResponse(url="/ui/dashboard", status_code=303)
    _copy_set_cookie(api_response, resp)
    return resp


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
):
    track_db.execute("SELECT COUNT(*) AS c FROM Member")
    members = track_db.fetchone()["c"]
    track_db.execute("SELECT Role, COUNT(*) AS c FROM Member GROUP BY Role")
    roles = {r["Role"]: r["c"] for r in track_db.fetchall()}
    track_db.execute("SELECT COUNT(*) AS c FROM Team")
    teams = track_db.fetchone()["c"]
    track_db.execute("SELECT COUNT(DISTINCT SportID) AS c FROM Team")
    sports = track_db.fetchone()["c"]
    track_db.execute("SELECT COUNT(*) AS c FROM Event WHERE Status='Scheduled'")
    upcoming = track_db.fetchone()["c"]
    track_db.execute("SELECT COUNT(*) AS c FROM Event WHERE Status='Ongoing'")
    ongoing = track_db.fetchone()["c"]
    track_db.execute("SELECT COUNT(*) AS c FROM Equipment")
    equip = track_db.fetchone()["c"]
    track_db.execute("SELECT COUNT(*) AS c FROM EquipmentIssue WHERE ReturnDate IS NULL")
    unreturned = track_db.fetchone()["c"]
    track_db.execute(
        """
        SELECT e.EventID, e.EventName, e.EventDate, e.Status, v.VenueName
        FROM Event e JOIN Venue v ON e.VenueID = v.VenueID
        WHERE e.Status IN ('Scheduled','Ongoing')
        ORDER BY e.EventDate ASC LIMIT 8
        """
    )
    recent_events = track_db.fetchall()
    for ev in recent_events:
        ev["EventDate"] = str(ev["EventDate"])
    track_db.execute("SELECT TournamentName, Status, EndDate FROM Tournament "
            "WHERE Status = 'Upcoming' or Status = 'Ongoing' ORDER BY StartDate DESC")
    tournaments = track_db.fetchall()
    for t in tournaments:
        t["EndDate"] = str(t["EndDate"])
    return templates.TemplateResponse(request, "dashboard.html", _ctx(
        request, current_user,
        active="dashboard",
        stats={
            "members": members, "players": roles.get("Player", 0),
            "coaches": roles.get("Coach", 0), "admins": roles.get("Admin", 0),
            "teams": teams, "sports": sports,
            "upcoming_events": upcoming, "ongoing_events": ongoing,
            "equipment": equip, "unreturned": unreturned,
        },
        recent_events=recent_events,
        tournaments=tournaments,
    ))


@router.get("/members", response_class=HTMLResponse)
def members_list(
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db)
):
    res = api_list_members(request, current_user, track_db, auth_db)
    if (res["success"]):
        return templates.TemplateResponse(request, "members/list.html",
                                      _ctx(request, current_user, active="members", members=res["data"]))


@router.get("/members/new", response_class=HTMLResponse)
def member_new_form(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    if current_user["role"] != "Admin":
        return RedirectResponse("/ui/members", status_code=303)
    return templates.TemplateResponse(request, "members/form.html",
                                      _ctx(request, current_user, active="members",
                                           member=None, form_data=_member_form_defaults(),
                                           country_codes=COMMON_COUNTRY_CODES, error=None))


@router.post("/members/new")
def member_create(
    request: Request,
    current_user: dict = Depends(get_current_user),
    cross_db=Depends(get_cross_db),
    member_id: Optional[int] = Form(None),
    name: str = Form(...),
    email: str = Form(...),
    age: int = Form(...),
    contact_country_code: Optional[str] = Form(None),
    contact_number: Optional[str] = Form(None),
    contact_number_local: Optional[str] = Form(None),
    gender: str = Form(...),
    role: str = Form(...),
    join_date: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    image: Optional[str] = Form(None),
):
    if current_user["role"] != "Admin":
        return RedirectResponse("/ui/members", status_code=303)
    if not isinstance(member_id, int):
        member_id = None
    image = image.strip() if isinstance(image, str) and image.strip() else None
    if not isinstance(contact_country_code, str):
        contact_country_code = None
    if not isinstance(contact_number_local, str):
        contact_number_local = None
    if not isinstance(contact_number, str):
        contact_number = None
    try:
        if contact_number_local is not None or contact_country_code is not None:
            contact_value = combine_contact_number(contact_country_code, contact_number_local or contact_number or "")
        else:
            contact_value = contact_number or ""
    except ValueError as exc:
        form_data = _member_form_defaults(form_data={
            "Name": name,
            "Email": email,
            "Age": age,
            "Gender": gender,
            "Role": role,
            "JoinDate": join_date,
            "Username": username,
            "Image": image or "",
            "ContactCountryCode": contact_country_code or COMMON_COUNTRY_CODES[0],
            "ContactNumberLocal": contact_number_local or contact_number or "",
        })
        return templates.TemplateResponse(request, "members/form.html",
                                          _ctx(request, current_user, active="members",
                                               member=None, form_data=form_data,
                                               country_codes=COMMON_COUNTRY_CODES, error=str(exc)))
    mem = MemberCreate(
        member_id=member_id,
        name=name,
        email=email,
        age=age,
        contact_number=contact_value,
        gender=gender,
        role=role,
        join_date=join_date,
        username=username,
        password=password,
        image=image,
    )
    res = api_create_member(mem, request, current_user, cross_db)
    if not res["success"]:
        form_data = _member_form_defaults(form_data={
            "Name": name,
            "Email": email,
            "Age": age,
            "Gender": gender,
            "Role": role,
            "JoinDate": join_date,
            "Username": username,
            "Image": image or "",
            "ContactCountryCode": contact_country_code or COMMON_COUNTRY_CODES[0],
            "ContactNumberLocal": contact_number_local or contact_number or "",
        })
        return templates.TemplateResponse(request, "members/form.html",
                                          _ctx(request, current_user, active="members",
                                               member=None, form_data=form_data,
                                               country_codes=COMMON_COUNTRY_CODES, error=res["message"]))
    return RedirectResponse(f"/ui/members/{res['data']['member_id']}", status_code=303)



@router.get("/members/{member_id}", response_class=HTMLResponse)
def member_portfolio(
    member_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    try:
        res = api_get_member_portfolio(member_id, request, current_user, track_db, auth_db)
    except HTTPException as exc:
        if exc.status_code == 403:
            return _flash_redirect("/ui/members", error="You are not authorized to view that member's profile.")
        return RedirectResponse("/ui/members", status_code=303)
    if (res["role"] == "Player"):
        portfolio = res["data"]
        member = portfolio["member"]
        teams = portfolio["teams"]
        performance = portfolio["performance"]
        medical = portfolio["medical"]
    elif (res["role"] == "Coach"):
        portfolio = res["data"]
        member = portfolio["member"]
        teams = portfolio["teams"]
        performance = []
        medical = []
    else:
        member = res["data"]["member"]
        teams = []
        performance = []
        medical = []
    member["JoinDate"] = str(member["JoinDate"])
    for p in performance:
        p["RecordDate"] = str(p["RecordDate"])
    for m2 in medical:
        m2["DiagnosisDate"] = str(m2["DiagnosisDate"])
        if m2.get("RecoveryDate"):
            m2["RecoveryDate"] = str(m2["RecoveryDate"])
    # determine whether the current user may see the medical section
    if current_user["role"] == "Admin" or current_user["member_id"] == member_id:
        can_view_medical = True
    elif current_user["role"] == "Coach":
        track_db.execute(
            """
            SELECT 1 FROM TeamMember tm
            JOIN Team t ON tm.TeamID = t.TeamID
            WHERE tm.MemberID = %s AND t.CoachID = %s
            LIMIT 1
            """,
            (member_id, current_user["member_id"]),
        )
        can_view_medical = track_db.fetchone() is not None
    else:
        can_view_medical = False
    track_db.execute("SELECT SportID, SportName FROM Sport ORDER BY SportName")
    sports = track_db.fetchall()
    return templates.TemplateResponse(request, "members/portfolio.html", _ctx(
        request, current_user, active="members",
        member=member, teams=teams, performance=performance, medical=medical,
        sports=sports, can_view_medical=can_view_medical,
    ))




@router.get("/members/{member_id}/edit", response_class=HTMLResponse)
def member_edit_form(
    member_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    if current_user["role"] != "Admin" and current_user["member_id"] != member_id:
        return RedirectResponse(f"/ui/members/{member_id}", status_code=303)
    try:
        res = api_get_member_portfolio(member_id, request, current_user, track_db, auth_db)
    except HTTPException:
        return RedirectResponse("/ui/members", status_code=303)
    member = res["data"]["member"]
    form_data = _member_form_defaults(member=member)
    return templates.TemplateResponse(request, "members/form.html",
                                      _ctx(request, current_user, active="members",
                                           member=member, form_data=form_data,
                                           country_codes=COMMON_COUNTRY_CODES, error=None))


@router.post("/members/{member_id}/edit")
def member_edit_submit(
    member_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
    name: str = Form(...),
    email: str = Form(...),
    age: int = Form(...),
    contact_country_code: Optional[str] = Form(None),
    contact_number: Optional[str] = Form(None),
    contact_number_local: Optional[str] = Form(None),
    image: Optional[str] = Form(None),
):
    if not isinstance(contact_country_code, str):
        contact_country_code = None
    if not isinstance(contact_number_local, str):
        contact_number_local = None
    if not isinstance(contact_number, str):
        contact_number = None
    image = image.strip() if isinstance(image, str) and image.strip() else None
    try:
        if contact_number_local is not None or contact_country_code is not None:
            contact_value = combine_contact_number(contact_country_code, contact_number_local or contact_number or "")
        else:
            contact_value = contact_number or ""
    except ValueError as exc:
        if current_user["role"] != "Admin" and current_user["member_id"] != member_id:
            raise HTTPException(status_code=403, detail="Access denied")
        form_data = _member_form_defaults(form_data={
            "Name": name,
            "Email": email,
            "Age": age,
            "Image": image or "",
            "ContactCountryCode": contact_country_code or COMMON_COUNTRY_CODES[0],
            "ContactNumberLocal": contact_number_local or contact_number or "",
        })
        track_db.execute("SELECT * FROM Member WHERE MemberID=%s", (member_id,))
        member = track_db.fetchone()
        return templates.TemplateResponse(
            request,
            "members/form.html",
            _ctx(
                request,
                current_user,
                active="members",
                member=member,
                form_data=form_data,
                country_codes=COMMON_COUNTRY_CODES,
                error=str(exc),
            ),
        )
    body = MemberUpdate(
        name=name,
        email=email,
        age=age,
        contact_number=contact_value,
        image=image,
    )
    try:
        api_update_member(member_id, body, request, current_user, track_db, auth_db)
    except HTTPException as exc:
        if exc.status_code == 403:
            return RedirectResponse(f"/ui/members/{member_id}", status_code=303)
        if exc.status_code == 404:
            return RedirectResponse("/ui/members", status_code=303)
        form_data = _member_form_defaults(form_data={
            "Name": name,
            "Email": email,
            "Age": age,
            "Image": image or "",
            "ContactCountryCode": contact_country_code or COMMON_COUNTRY_CODES[0],
            "ContactNumberLocal": contact_number_local or contact_number or "",
        })
        track_db.execute("SELECT * FROM Member WHERE MemberID=%s", (member_id,))
        member = track_db.fetchone()
        return templates.TemplateResponse(
            request,
            "members/form.html",
            _ctx(
                request,
                current_user,
                active="members",
                member=member,
                form_data=form_data,
                country_codes=COMMON_COUNTRY_CODES,
                error=exc.detail,
            ),
        )
    return RedirectResponse(f"/ui/members/{member_id}", status_code=303)


@router.post("/members/{member_id}/delete")
def member_delete(
    member_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    cross_db=Depends(get_cross_db),
):
    if current_user["role"] != "Admin":
        return RedirectResponse("/ui/members", status_code=303)
    try:
        api_delete_member(member_id, request, current_user, cross_db)
    except HTTPException:
        return RedirectResponse("/ui/members", status_code=303)
    return RedirectResponse("/ui/members", status_code=303)


@router.get("/teams", response_class=HTMLResponse)
def teams_list(
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    res = api_list_teams(request, current_user, track_db, auth_db)
    teams = res["data"]
    for t in teams:
        if t.get("FormedDate") is not None:
            t["FormedDate"] = str(t["FormedDate"])
    return templates.TemplateResponse(request, "teams/list.html",
                                      _ctx(request, current_user, active="teams", teams=teams))


@router.get("/teams/new", response_class=HTMLResponse)
def team_new_form(
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
):
    if current_user["role"] not in ("Admin", "Coach"):
        return RedirectResponse("/ui/teams", status_code=303)
    track_db.execute("SELECT SportID, SportName FROM Sport ORDER BY SportName")
    sports = track_db.fetchall()
    return templates.TemplateResponse(request, "teams/form.html",
                                      _ctx(request, current_user, form_data={"members": [{"member_id": "", "position": ""}]}, active="teams", error=None, sports=sports))


@router.post("/teams/new")
async def team_create(
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    if current_user["role"] not in ("Admin", "Coach"):
        return RedirectResponse("/ui/teams", status_code=303)
    form = await request.form()
    team_name = str(form.get("team_name") or "").strip()
    formed_date = str(form.get("formed_date") or "").strip()
    raw_ids = form.getlist("member_ids") or [""]
    raw_positions = form.getlist("member_positions") or [""]
    raw_members = [{"member_id": raw_ids[i], "position": raw_positions[i] if i < len(raw_positions) else ""}
                   for i in range(len(raw_ids))]
    raw_form_data = {
        "team_name": team_name,
        "sport_id": form.get("sport_id", ""),
        "coach_id": form.get("coach_id", ""),
        "captain_id": form.get("captain_id", ""),
        "members": raw_members,
        "formed_date": formed_date,
    }
    try:
        sport_id = _parse_required_int(form.get("sport_id"), "Sport ID")
        coach_id = _parse_optional_int(form.get("coach_id"), "Coach ID")
        captain_id = _parse_optional_int(form.get("captain_id"), "Captain ID")
        members = _parse_members(form)
    except ValueError as exc:
        track_db.execute("SELECT SportID, SportName FROM Sport ORDER BY SportName")
        sports = track_db.fetchall()
        return templates.TemplateResponse(
            request,
            "teams/form.html",
            _ctx(request, current_user, active="teams", form_data=raw_form_data, error=str(exc), sports=sports),
        )
    body = TeamCreate(
        team_name=team_name,
        sport_id=sport_id,
        coach_id=coach_id,
        captain_id=captain_id,
        members=members,
        formed_date=formed_date,
    )
    try:
        res = api_create_team(body, request, current_user, track_db, auth_db)
    except HTTPException as exc:
        track_db.execute("SELECT SportID, SportName FROM Sport ORDER BY SportName")
        sports = track_db.fetchall()
        return templates.TemplateResponse(request, "teams/form.html",
                                          _ctx(request, current_user, active="teams", form_data=raw_form_data, error=exc.detail, sports=sports))
    return RedirectResponse(f"/ui/teams/{res['data']['team_id']}", status_code=303)


@router.get("/teams/{team_id}/edit", response_class=HTMLResponse)
def team_edit_form(
    team_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    if current_user["role"] not in ("Admin", "Coach"):
        return RedirectResponse(f"/ui/teams/{team_id}", status_code=303)
    try:
        res = api_get_team(team_id, request, current_user, track_db, auth_db)
    except HTTPException:
        return RedirectResponse("/ui/teams", status_code=303)
    team = res["data"]["team"]
    if team["CoachID"] != current_user["member_id"] and current_user["role"] != "Admin":
        return RedirectResponse(f"/ui/teams/{team_id}", status_code=303)
    if team.get("FormedDate") is not None:
        team["FormedDate"] = str(team["FormedDate"])
    track_db.execute("SELECT SportID, SportName FROM Sport ORDER BY SportName")
    sports = track_db.fetchall()
    roster = res["data"]["roster"]
    form_data = {
        "team_name": team["TeamName"],
        "sport_id": team["SportID"],
        "coach_id": team["CoachID"],
        "captain_id": team["CaptainID"],
        "members": [{"member_id": m["MemberID"], "position": m.get("Position") or ""} for m in roster] or [{"member_id": "", "position": ""}],
        "formed_date": team["FormedDate"]
    }
    return templates.TemplateResponse(request, "teams/form.html",
                                      _ctx(request, current_user, active="teams", team=team, form_data=form_data, error=None, sports=sports))


@router.post("/teams/{team_id}/edit")
async def team_edit_submit(
    team_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    if current_user["role"] not in ("Admin", "Coach"):
        return RedirectResponse(f"/ui/teams/{team_id}", status_code=303)
    form = await request.form()
    team_name = str(form.get("team_name") or "").strip()
    formed_date = str(form.get("formed_date") or "").strip()
    raw_ids = form.getlist("member_ids") or [""]
    raw_positions = form.getlist("member_positions") or [""]
    raw_members = [{"member_id": raw_ids[i], "position": raw_positions[i] if i < len(raw_positions) else ""}
                   for i in range(len(raw_ids))]
    raw_form_data = {
        "team_name": team_name,
        "sport_id": form.get("sport_id", ""),
        "coach_id": form.get("coach_id", ""),
        "captain_id": form.get("captain_id", ""),
        "members": raw_members,
        "formed_date": formed_date,
    }
    try:
        sport_id = _parse_required_int(form.get("sport_id"), "Sport ID")
        coach_id = _parse_optional_int(form.get("coach_id"), "Coach ID")
        captain_id = _parse_optional_int(form.get("captain_id"), "Captain ID")
        members = _parse_members(form)
    except ValueError as exc:
        track_db.execute("SELECT SportID, SportName FROM Sport ORDER BY SportName")
        sports = track_db.fetchall()
        team = {
            "TeamID": team_id,
            "TeamName": team_name,
            "SportID": raw_form_data["sport_id"],
            "CoachID": raw_form_data["coach_id"],
            "CaptainID": raw_form_data["captain_id"],
            "FormedDate": formed_date,
        }
        return templates.TemplateResponse(
            request,
            "teams/form.html",
            _ctx(request, current_user, active="teams", team=team, form_data=raw_form_data, error=str(exc), sports=sports),
        )
    body = TeamUpdate(
        team_name=team_name,
        sport_id=sport_id,
        coach_id=coach_id,
        captain_id=captain_id,
        members=members,
        formed_date=formed_date,
    )
    try:
        api_update_team(team_id, body, request, current_user, track_db, auth_db)
        return RedirectResponse(f"/ui/teams/{team_id}", status_code=303)
    except HTTPException as exc:
        if exc.status_code in (403, 404):
            return RedirectResponse(f"/ui/teams/{team_id}" if exc.status_code == 403 else "/ui/teams", status_code=303)
        team = {
            "TeamID": team_id,
            "TeamName": team_name,
            "SportID": raw_form_data["sport_id"],
            "CoachID": raw_form_data["coach_id"],
            "CaptainID": raw_form_data["captain_id"],
            "FormedDate": formed_date,
        }
        track_db.execute("SELECT SportID, SportName FROM Sport ORDER BY SportName")
        sports = track_db.fetchall()
        return templates.TemplateResponse(request, "teams/form.html",
                                          _ctx(request, current_user, active="teams", team=team, form_data=raw_form_data, error=exc.detail, sports=sports))


@router.post("/teams/{team_id}/delete")
def team_delete(
    team_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    try:
        api_delete_team(team_id, request, current_user, track_db, auth_db)
    except HTTPException:
        return RedirectResponse(f"/ui/teams/{team_id}", status_code=303)
    return RedirectResponse("/ui/teams", status_code=303)


@router.get("/teams/{team_id}", response_class=HTMLResponse)
def team_detail(
    team_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    try:
        res = api_get_team(team_id, request, current_user, track_db, auth_db)
    except HTTPException:
        return RedirectResponse("/ui/teams", status_code=303)
    team = res["data"]["team"]
    roster = res["data"]["roster"]
    events = res["data"].get("events", [])
    if team.get("FormedDate") is not None:
        team["FormedDate"] = str(team["FormedDate"])
    for r in roster:
        if r.get("JoinDate") is not None:
            r["JoinDate"] = str(r["JoinDate"])
    for event in events:
        if event.get("EventDate") is not None:
            event["EventDate"] = str(event["EventDate"])
        if event.get("StartTime") is not None:
            event["StartTime"] = str(event["StartTime"])
        if event.get("EndTime") is not None:
            event["EndTime"] = str(event["EndTime"])
    return templates.TemplateResponse(request, "teams/detail.html",
                                      _ctx(request, current_user, active="teams",
                                           team=team, roster=roster, events=events))


@router.get("/tournaments", response_class=HTMLResponse)
def tournaments_list(
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    tournaments = api_list_tournaments(request, current_user, track_db, auth_db)["data"]
    return templates.TemplateResponse(request, "tournaments/list.html",
                                      _ctx(request, current_user, active="tournaments",
                                           tournaments=tournaments))


@router.get("/tournaments/new", response_class=HTMLResponse)
def tournament_new_form(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    if current_user["role"] != "Admin":
        return RedirectResponse("/ui/tournaments", status_code=303)
    return templates.TemplateResponse(request, "tournaments/form.html",
                                      _ctx(request, current_user, form_data={"status": "Upcoming"},
                                           active="tournaments", error=None))


@router.post("/tournaments/new")
def tournament_create(
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
    tournament_name: str = Form(...),
    start_date: str = Form(...),
    end_date: str = Form(...),
    description: Optional[str] = Form(None),
    status: str = Form(...),
):
    if current_user["role"] != "Admin":
        return RedirectResponse("/ui/tournaments", status_code=303)
    body = TournamentCreate(
        tournament_name=tournament_name,
        start_date=start_date,
        end_date=end_date,
        description=description or None,
        status=status,
    )
    try:
        api_create_tournament(body, request, current_user, track_db, auth_db)
    except HTTPException as exc:
        form_data = {
            "tournament_name": tournament_name,
            "start_date": start_date,
            "end_date": end_date,
            "description": description,
            "status": status,
        }
        return templates.TemplateResponse(request, "tournaments/form.html",
                                          _ctx(request, current_user, form_data=form_data, active="tournaments", error=exc.detail))
    return RedirectResponse("/ui/tournaments", status_code=303)


@router.get("/tournaments/{tournament_id}", response_class=HTMLResponse)
def tournament_detail(
    tournament_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    try:
        res = api_get_tournament(tournament_id, request, current_user, track_db, auth_db)
    except HTTPException:
        return RedirectResponse("/ui/tournaments", status_code=303)
    tournament = res["data"]["tournament"]
    events = res["data"]["events"]
    registered_teams = res["data"]["registered_teams"]
    all_teams = res["data"]["available_teams"]
    return templates.TemplateResponse(request, "tournaments/detail.html",
                                      _ctx(request, current_user, active="tournaments",
                                           tournament=tournament, events=events,
                                           registered_teams=registered_teams, all_teams=all_teams))


@router.get("/tournaments/{tournament_id}/edit", response_class=HTMLResponse)
def tournament_edit_form(
    tournament_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    if current_user["role"] != "Admin":
        return RedirectResponse(f"/ui/tournaments/{tournament_id}", status_code=303)
    from app.database import get_track_db as _get_track_db
    return RedirectResponse(f"/ui/tournaments/{tournament_id}/edit-form", status_code=303)


@router.get("/tournaments/{tournament_id}/edit-form", response_class=HTMLResponse)
def tournament_edit_page(
    tournament_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    if current_user["role"] != "Admin":
        return RedirectResponse(f"/ui/tournaments/{tournament_id}", status_code=303)
    try:
        res = api_get_tournament(tournament_id, request, current_user, track_db, auth_db)
    except HTTPException:
        return RedirectResponse("/ui/tournaments", status_code=303)
    tournament = res["data"]["tournament"]
    form_data = {
        "tournament_name": tournament["TournamentName"],
        "start_date": tournament["StartDate"],
        "end_date": tournament["EndDate"],
        "description": tournament["Description"],
        "status": tournament["Status"],
    }
    return templates.TemplateResponse(request, "tournaments/form.html",
                                      _ctx(request, current_user, form_data=form_data,active="tournaments",
                                           tournament=tournament, error=None))


@router.post("/tournaments/{tournament_id}/edit")
def tournament_edit_submit(
    tournament_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
    tournament_name: str = Form(...),
    start_date: str = Form(...),
    end_date: str = Form(...),
    description: Optional[str] = Form(None),
    status: str = Form(...),
):
    if current_user["role"] != "Admin":
        return RedirectResponse(f"/ui/tournaments/{tournament_id}", status_code=303)
    body = TournamentUpdate(
        tournament_name=tournament_name,
        start_date=start_date,
        end_date=end_date,
        description=description or None,
        status=status,
    )
    try:
        api_update_tournament(tournament_id, body, request, current_user, track_db, auth_db)
    except HTTPException as exc:
        tournament = {
            "TournamentID": tournament_id,
            "TournamentName": tournament_name,
            "StartDate": start_date,
            "EndDate": end_date,
            "Description": description,
            "Status": status,
        }
        form_data = {
            "tournament_name": tournament_name,
            "start_date": start_date,
            "end_date": end_date,
            "description": description,
            "status": status,
        }
        return templates.TemplateResponse(
            request,
            "tournaments/form.html",
            _ctx(request, current_user, form_data=form_data, active="tournaments",
                 tournament=tournament, error=exc.detail),
        )
    except Exception as exc:
        return _flash_redirect(f"/ui/tournaments/{tournament_id}/edit-form", error=str(exc))
    return RedirectResponse(f"/ui/tournaments/{tournament_id}", status_code=303)


@router.post("/tournaments/{tournament_id}/delete")
def tournament_delete(
    tournament_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    if current_user["role"] != "Admin":
        return RedirectResponse("/ui/tournaments", status_code=303)
    try:
        api_delete_tournament(tournament_id, request, current_user, track_db, auth_db)
    except HTTPException as exc:
        return _flash_redirect("/ui/tournaments", error=exc.detail)
    return _flash_redirect("/ui/tournaments", success="Tournament deleted.")


@router.post("/tournaments/{tournament_id}/register")
def tournament_register_team(
    tournament_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
    team_id: int = Form(...),
):
    if current_user["role"] not in ("Admin", "Coach"):
        return RedirectResponse(f"/ui/tournaments/{tournament_id}", status_code=303)
    try:
        api_register_team_for_tournament(tournament_id, team_id, request, current_user, track_db, auth_db)
    except HTTPException as exc:
        return _flash_redirect(f"/ui/tournaments/{tournament_id}", error=exc.detail)
    except Exception as exc:
        return _flash_redirect(f"/ui/tournaments/{tournament_id}", error=str(exc))
    return _flash_redirect(f"/ui/tournaments/{tournament_id}", success="Team registered.")


@router.post("/tournaments/{tournament_id}/unregister/{team_id}")
def tournament_unregister_team(
    tournament_id: int,
    team_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    if current_user["role"] != "Admin":
        return RedirectResponse(f"/ui/tournaments/{tournament_id}", status_code=303)
    try:
        api_unregister_team_from_tournament(tournament_id, team_id, request, current_user, track_db, auth_db)
    except HTTPException as exc:
        return _flash_redirect(f"/ui/tournaments/{tournament_id}", error=exc.detail)
    return _flash_redirect(f"/ui/tournaments/{tournament_id}", success="Team unregistered.")


@router.get("/events", response_class=HTMLResponse)
def events_list(
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    events = api_list_events(request, current_user, track_db, auth_db)["data"]
    return templates.TemplateResponse(request, "events/list.html",
                                      _ctx(request, current_user, active="events", events=events))


@router.get("/events/new", response_class=HTMLResponse)
def event_new_form(
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    if current_user["role"] != "Admin":
        return RedirectResponse("/ui/events", status_code=303)
    lookups = _get_event_lookups(request, current_user, track_db, auth_db)
    return templates.TemplateResponse(request, "events/form.html",
                                      _ctx(request, current_user, active="events",
                                           sports=lookups["sports"], venues=lookups["venues"],
                                           tournaments=lookups["tournaments"], form_data={}, error=None))


@router.post("/events/new")
def event_create(
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
    event_name: str = Form(...),
    tournament_id: Optional[int] = Form(None),
    event_date: str = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    venue_id: int = Form(...),
    sport_id: int = Form(...),
    status: str = Form(...),
    round_name: Optional[str] = Form(None),
):
    if current_user["role"] != "Admin":
        return RedirectResponse("/ui/events", status_code=303)
    form_data = {
        "event_name": event_name,
        "tournament_id": tournament_id,
        "event_date": event_date,
        "start_time": start_time,
        "end_time": end_time,
        "venue_id": venue_id,
        "sport_id": sport_id,
        "status": status,
        "round_name": round_name or "",
    }
    body = EventCreate(
        event_name=event_name,
        tournament_id=tournament_id,
        event_date=event_date,
        start_time=start_time,
        end_time=end_time,
        venue_id=venue_id,
        sport_id=sport_id,
        status=status,
        round=round_name or None,
    )
    try:
        res = api_create_event(body, request, current_user, track_db, auth_db)
    except HTTPException as exc:
        lookups = _get_event_lookups(request, current_user, track_db, auth_db)
        return templates.TemplateResponse(request, "events/form.html",
                                          _ctx(request, current_user, active="events",
                                               sports=lookups["sports"], venues=lookups["venues"],
                                               tournaments=lookups["tournaments"], form_data=form_data,
                                               error=exc.detail))
    return RedirectResponse(f"/ui/events/{res['data']['event_id']}", status_code=303)


@router.get("/events/{event_id}/edit", response_class=HTMLResponse)
def event_edit_form(
    event_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    if current_user["role"] != "Admin":
        return RedirectResponse(f"/ui/events/{event_id}", status_code=303)
    try:
        res = api_get_event(event_id, request, current_user, track_db, auth_db)
    except HTTPException:
        return RedirectResponse("/ui/events", status_code=303)
    event = res["data"]["event"]
    lookups = _get_event_lookups(request, current_user, track_db, auth_db)
    form_data = {
        "event_name": event["EventName"],
        "tournament_id": event["TournamentID"],
        "event_date": event["EventDate"],
        "start_time": event["StartTime"],
        "end_time": event["EndTime"],
        "venue_id": event["VenueID"],
        "sport_id": event["SportID"],
        "status": event["Status"],
        "round_name": event["Round"] or "",
    }
    return templates.TemplateResponse(request, "events/form.html",
                                      _ctx(request, current_user, active="events",
                                           event=event, sports=lookups["sports"], venues=lookups["venues"],
                                           tournaments=lookups["tournaments"], form_data=form_data, error=None))


@router.post("/events/{event_id}/edit")
def event_edit_submit(
    event_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
    event_name: str = Form(...),
    tournament_id: Optional[int] = Form(None),
    event_date: str = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    venue_id: int = Form(...),
    sport_id: int = Form(...),
    status: str = Form(...),
    round_name: Optional[str] = Form(None),
):
    if current_user["role"] != "Admin":
        return RedirectResponse(f"/ui/events/{event_id}", status_code=303)
    form_data = {
        "event_name": event_name,
        "tournament_id": tournament_id,
        "event_date": event_date,
        "start_time": start_time,
        "end_time": end_time,
        "venue_id": venue_id,
        "sport_id": sport_id,
        "status": status,
        "round_name": round_name or "",
    }
    body = EventUpdate(
        event_name=event_name,
        tournament_id=tournament_id,
        event_date=event_date,
        start_time=start_time,
        end_time=end_time,
        venue_id=venue_id,
        sport_id=sport_id,
        status=status,
        round=round_name or None,
    )
    try:
        api_update_event(event_id, body, request, current_user, track_db, auth_db)
    except HTTPException as exc:
        lookups = _get_event_lookups(request, current_user, track_db, auth_db)
        event = {
            "EventID": event_id,
            "EventName": event_name,
            "TournamentID": tournament_id,
            "EventDate": event_date,
            "StartTime": start_time,
            "EndTime": end_time,
            "VenueID": venue_id,
            "SportID": sport_id,
            "Status": status,
            "Round": round_name or None,
        }
        return templates.TemplateResponse(
            request,
            "events/form.html",
            _ctx(request, current_user, active="events", event=event,
                 sports=lookups["sports"], venues=lookups["venues"],
                 tournaments=lookups["tournaments"], form_data=form_data, error=exc.detail),
        )
    except Exception as exc:
        return _flash_redirect(f"/ui/events/{event_id}/edit", error=str(exc))
    return RedirectResponse(f"/ui/events/{event_id}", status_code=303)


@router.post("/events/{event_id}/delete")
def event_delete(
    event_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    if current_user["role"] != "Admin":
        return RedirectResponse("/ui/events", status_code=303)
    try:
        api_delete_event(event_id, request, current_user, track_db, auth_db)
    except HTTPException as exc:
        return _flash_redirect("/ui/events", error=exc.detail)
    return _flash_redirect("/ui/events", success="Event deleted.")


@router.post("/events/{event_id}/add-team")
def event_add_team(
    event_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
    team_id: int = Form(...),
):
    if current_user["role"] not in ("Admin", "Coach"):
        return RedirectResponse(f"/ui/events/{event_id}", status_code=303)
    try:
        api_add_team_to_event(event_id, team_id, request, current_user, track_db, auth_db)
    except HTTPException as exc:
        if exc.status_code == 404:
            return _flash_redirect("/ui/events", error=exc.detail)
        return _flash_redirect(f"/ui/events/{event_id}", error=exc.detail)
    return _flash_redirect(f"/ui/events/{event_id}", success="Team added to event.")


@router.post("/events/{event_id}/remove-team/{team_id}")
def event_remove_team(
    event_id: int,
    team_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    if current_user["role"] not in ("Admin", "Coach"):
        return RedirectResponse(f"/ui/events/{event_id}", status_code=303)
    try:
        api_remove_team_from_event(event_id, team_id, request, current_user, track_db, auth_db)
    except HTTPException as exc:
        return _flash_redirect(f"/ui/events/{event_id}", error=exc.detail)
    return _flash_redirect(f"/ui/events/{event_id}", success="Team removed from event.")


@router.post("/events/{event_id}/edit-participation/{team_id}")
async def event_edit_participation(
    event_id: int,
    team_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    if current_user["role"] not in ("Admin", "Coach"):
        return RedirectResponse(f"/ui/events/{event_id}", status_code=303)
    
    form = await request.form()
    
    # Get the raw string values
    score = str(form.get("score") or "").strip()
    event_rank = str(form.get("event_rank") or "").strip()
    result = str(form.get("result") or "").strip()
    remarks = str(form.get("remarks") or "").strip()
    
    # Parse rank (keep as integer), but leave score as a string
    parsed_rank = int(event_rank) if event_rank else None
    
    from app.routers.events import ParticipationUpdate
    body = ParticipationUpdate(
        score=score if score else None,  # Pass the string directly instead of float()
        event_rank=parsed_rank,
        result=result or None,
        remarks=remarks or None,
    )
    
    try:
        api_update_participation(event_id, team_id, body, request, current_user, track_db, auth_db)
    except HTTPException as exc:
        return _flash_redirect(f"/ui/events/{event_id}", error=exc.detail)
    
    return _flash_redirect(f"/ui/events/{event_id}", success="Participation updated.")


@router.get("/events/{event_id}", response_class=HTMLResponse)
def event_detail(
    event_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    try:
        res = api_get_event(event_id, request, current_user, track_db, auth_db)
    except HTTPException:
        return RedirectResponse("/ui/events", status_code=303)
    event = res["data"]["event"]
    participation = res["data"]["participation"]
    eligible_teams = res["data"]["eligible_teams"]
    return templates.TemplateResponse(request, "events/detail.html",
                                      _ctx(request, current_user, active="events",
                                           event=event, participation=participation,
                                           eligible_teams=eligible_teams))


@router.get("/equipment", response_class=HTMLResponse)
def equipment_list(
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    equipment = api_list_equipment(request, current_user, track_db, auth_db)["data"]
    issues = api_list_issues(request, current_user, track_db, auth_db, active_only=True)["data"]
    members = []
    if current_user["role"] == "Admin":
        members = api_list_members(request, current_user, track_db, auth_db)["data"]
    elif current_user["role"] == "Coach":
        track_db.execute(
            """
            SELECT DISTINCT m.MemberID, m.Name, m.Role, m.Gender, m.JoinDate
            FROM TeamMember tm
            JOIN Team t ON tm.TeamID = t.TeamID
            JOIN Member m ON tm.MemberID = m.MemberID
            WHERE t.CoachID = %s
            ORDER BY m.MemberID
            """,
            (current_user["member_id"],),
        )
        members = track_db.fetchall()
    return templates.TemplateResponse(request, "equipment/list.html",
                                      _ctx(request, current_user, active="equipment",
                                           equipment=equipment, issues=issues, members=members,
                                           now_date=date.today().isoformat()))


@router.get("/equipment/new", response_class=HTMLResponse)
def equipment_create_form(
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
):
    if current_user["role"] != "Admin":
        return RedirectResponse("/ui/equipment", status_code=303)
    return templates.TemplateResponse(
        request,
        "equipment/form.html",
        _ctx(
            request,
            current_user,
            active="equipment",
            equipment=None,
            sports=_get_sports(track_db),
            form_data=_equipment_form_data(),
            error=None,
        ),
    )


@router.post("/equipment/new")
def equipment_create(
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
    equipment_name: str = Form(...),
    total_quantity: int = Form(...),
    equipment_condition: str = Form(...),
    sport_id: Optional[str] = Form(None),
):
    if current_user["role"] != "Admin":
        return RedirectResponse("/ui/equipment", status_code=303)
    try:
        parsed_sport_id = _parse_optional_int(sport_id, "Sport ID")
    except ValueError as exc:
        return _flash_redirect("/ui/equipment", error=str(exc))
    body = EquipmentCreate(
        equipment_name=equipment_name,
        total_quantity=total_quantity,
        equipment_condition=equipment_condition,
        sport_id=parsed_sport_id,
    )
    try:
        api_create_equipment(body, request, current_user, track_db, auth_db)
    except HTTPException as exc:
        return _flash_redirect("/ui/equipment", error=exc.detail)
    return _flash_redirect("/ui/equipment", success="Equipment added successfully.")


@router.get("/equipment/{equipment_id}/edit", response_class=HTMLResponse)
def equipment_edit_form(
    equipment_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    if current_user["role"] != "Admin":
        return RedirectResponse("/ui/equipment", status_code=303)
    try:
        equipment = api_get_equipment(equipment_id, request, current_user, track_db, auth_db)["data"]
    except HTTPException:
        return _flash_redirect("/ui/equipment", error="Equipment item not found.")
    return templates.TemplateResponse(
        request,
        "equipment/form.html",
        _ctx(
            request,
            current_user,
            active="equipment",
            equipment=equipment,
            sports=_get_sports(track_db),
            form_data=_equipment_form_data(),
            error=None,
        ),
    )


@router.post("/equipment/{equipment_id}/edit")
def equipment_edit_submit(
    equipment_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
    equipment_name: str = Form(...),
    total_quantity: int = Form(...),
    equipment_condition: str = Form(...),
    sport_id: Optional[str] = Form(None),
):
    if current_user["role"] != "Admin":
        return RedirectResponse("/ui/equipment", status_code=303)
    try:
        equipment = api_get_equipment(equipment_id, request, current_user, track_db, auth_db)["data"]
    except HTTPException:
        return _flash_redirect("/ui/equipment", error="Equipment item not found.")
    try:
        parsed_sport_id = _parse_optional_int(sport_id, "Sport ID")
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "equipment/form.html",
            _ctx(
                request,
                current_user,
                active="equipment",
                equipment=equipment,
                sports=_get_sports(track_db),
                form_data=_equipment_form_data(
                    equipment_name=equipment_name,
                    total_quantity=total_quantity,
                    equipment_condition=equipment_condition,
                    sport_id=None,
                ),
                error=str(exc),
            ),
            status_code=400,
        )
    body = EquipmentUpdate(
        equipment_name=equipment_name,
        total_quantity=total_quantity,
        equipment_condition=equipment_condition,
        sport_id=parsed_sport_id,
    )
    try:
        api_update_equipment(equipment_id, body, request, current_user, track_db, auth_db)
    except HTTPException as exc:
        return templates.TemplateResponse(
            request,
            "equipment/form.html",
            _ctx(
                request,
                current_user,
                active="equipment",
                equipment=equipment,
                sports=_get_sports(track_db),
                form_data=_equipment_form_data(
                    equipment_name=equipment_name,
                    total_quantity=total_quantity,
                    equipment_condition=equipment_condition,
                    sport_id=parsed_sport_id,
                ),
                error=exc.detail,
            ),
            status_code=exc.status_code,
        )
    return _flash_redirect("/ui/equipment", success="Equipment updated successfully.")


@router.post("/equipment/{equipment_id}/delete")
def equipment_delete(
    equipment_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    if current_user["role"] != "Admin":
        return RedirectResponse("/ui/equipment", status_code=303)
    try:
        api_delete_equipment(equipment_id, request, current_user, track_db, auth_db)
    except HTTPException as exc:
        return _flash_redirect("/ui/equipment", error=exc.detail)
    return _flash_redirect("/ui/equipment", success="Equipment deleted successfully.")


@router.post("/equipment/issue")
def equipment_issue(
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
    equipment_id: int = Form(...),
    member_id: int = Form(...),
    issue_date: str = Form(...),
    quantity: int = Form(...),
):
    if current_user["role"] not in ("Admin", "Coach"):
        return RedirectResponse("/ui/equipment", status_code=303)
    body = IssueCreate(
        equipment_id=equipment_id,
        member_id=member_id,
        issue_date=issue_date,
        quantity=quantity,
    )
    try:
        api_issue_equipment(body, request, current_user, track_db, auth_db)
    except HTTPException as exc:
        return _flash_redirect("/ui/equipment", error=exc.detail)
    return _flash_redirect("/ui/equipment", success="Equipment issued successfully.")


@router.post("/equipment/issue/{issue_id}/return")
def equipment_return(
    issue_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
    return_date: str = Form(...),
):
    if current_user["role"] not in ("Admin", "Coach"):
        return RedirectResponse("/ui/equipment", status_code=303)
    try:
        api_return_equipment(issue_id, return_date, request, current_user, track_db, auth_db)
    except HTTPException as exc:
        return _flash_redirect("/ui/equipment", error=exc.detail)
    return RedirectResponse("/ui/equipment", status_code=303)


@router.get("/performance-logs/{log_id}/edit", response_class=HTMLResponse)
def perf_log_edit_form(
    log_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    if current_user["role"] not in ("Admin", "Coach"):
        return RedirectResponse("/ui/dashboard", status_code=303)
    try:
        log = api_get_performance_log(log_id, request, current_user, track_db, auth_db)["data"]
    except HTTPException:
        return RedirectResponse("/ui/members", status_code=303)
    track_db.execute("SELECT SportID, SportName FROM Sport ORDER BY SportName")
    sports = track_db.fetchall()
    return templates.TemplateResponse(request, "performance/form.html",
                                      _ctx(request, current_user, active="members",
                                           log=log, sports=sports, error=None))


@router.post("/performance-logs/{log_id}/edit")
def perf_log_edit_submit(
    log_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
    member_id: int = Form(...),
    sport_id: int = Form(...),
    metric_name: str = Form(...),
    metric_value: float = Form(...),
    record_date: str = Form(...),
):
    if current_user["role"] not in ("Admin", "Coach"):
        return RedirectResponse(f"/ui/members/{member_id}", status_code=303)
    body = PerfLogUpdate(
        sport_id=sport_id,
        metric_name=metric_name,
        metric_value=metric_value,
        record_date=record_date,
    )
    try:
        api_update_performance_log(log_id, body, request, current_user, track_db, auth_db)
    except HTTPException as exc:
        return _flash_redirect(f"/ui/members/{member_id}", error=exc.detail)
    return RedirectResponse(f"/ui/members/{member_id}", status_code=303)


@router.post("/performance-logs/{log_id}/delete")
def perf_log_delete(
    log_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
    member_id: int = Form(...),
):
    if current_user["role"] not in ("Admin", "Coach"):
        return RedirectResponse(f"/ui/members/{member_id}", status_code=303)
    try:
        api_delete_performance_log(log_id, request, current_user, track_db, auth_db)
    except HTTPException as exc:
        return _flash_redirect(f"/ui/members/{member_id}", error=exc.detail)
    return RedirectResponse(f"/ui/members/{member_id}", status_code=303)


@router.post("/performance-logs/new")
def performance_log_create(
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
    member_id: int = Form(...),
    sport_id: int = Form(...),
    metric_name: str = Form(...),
    metric_value: float = Form(...),
    record_date: str = Form(...),
):
    if current_user["role"] not in ("Admin", "Coach"):
        return RedirectResponse(f"/ui/members/{member_id}", status_code=303)
    body = PerfLogCreate(
        member_id=member_id,
        sport_id=sport_id,
        metric_name=metric_name,
        metric_value=metric_value,
        record_date=record_date,
    )
    try:
        api_create_performance_log(body, request, current_user, track_db, auth_db)
    except HTTPException as exc:
        return _flash_redirect(f"/ui/members/{member_id}", error=exc.detail)
    return RedirectResponse(f"/ui/members/{member_id}", status_code=303)


@router.post("/medical-records/new")
def medical_record_create(
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
    member_id: int = Form(...),
    medical_condition: str = Form(...),
    diagnosis_date: str = Form(...),
    recovery_date: Optional[str] = Form(None),
    status: str = Form(...),
):
    if current_user["role"] != "Admin":
        return RedirectResponse(f"/ui/members/{member_id}", status_code=303)
    body = MedicalCreate(
        member_id=member_id,
        medical_condition=medical_condition,
        diagnosis_date=diagnosis_date,
        recovery_date=recovery_date or None,
        status=status,
    )
    try:
        api_create_medical_record(body, request, current_user, track_db, auth_db)
    except HTTPException as exc:
        return _flash_redirect(f"/ui/members/{member_id}", error=exc.detail)
    return RedirectResponse(f"/ui/members/{member_id}", status_code=303)


@router.get("/medical-records/{record_id}/edit", response_class=HTMLResponse)
def medical_record_edit_form(
    record_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    if current_user["role"] != "Admin":
        return RedirectResponse("/ui/members", status_code=303)
    try:
        record = api_get_medical_record(record_id, request, current_user, track_db, auth_db)["data"]
    except HTTPException:
        return RedirectResponse("/ui/members", status_code=303)
    return templates.TemplateResponse(request, "medical/form.html",
                                      _ctx(request, current_user, active="members",
                                           record=record, error=None))


@router.post("/medical-records/{record_id}/edit")
def medical_record_edit_submit(
    record_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
    member_id: int = Form(...),
    medical_condition: str = Form(...),
    diagnosis_date: str = Form(...),
    recovery_date: Optional[str] = Form(None),
    status: str = Form(...),
):
    if current_user["role"] != "Admin":
        return RedirectResponse(f"/ui/members/{member_id}", status_code=303)
    body = MedicalUpdate(
        medical_condition=medical_condition,
        diagnosis_date=diagnosis_date,
        recovery_date=recovery_date or None,
        status=status,
    )
    try:
        api_update_medical_record(record_id, body, request, current_user, track_db, auth_db)
    except HTTPException as exc:
        return _flash_redirect(f"/ui/members/{member_id}", error=exc.detail)
    return RedirectResponse(f"/ui/members/{member_id}", status_code=303)


@router.post("/medical-records/{record_id}/delete")
def medical_record_delete(
    record_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
    member_id: int = Form(...),
):
    if current_user["role"] != "Admin":
        return RedirectResponse(f"/ui/members/{member_id}", status_code=303)
    try:
        api_delete_medical_record(record_id, request, current_user, track_db, auth_db)
    except HTTPException as exc:
        return _flash_redirect(f"/ui/members/{member_id}", error=exc.detail)
    return RedirectResponse(f"/ui/members/{member_id}", status_code=303)


@router.get("/admin/audit", response_class=HTMLResponse)
def audit_page(
    request: Request,
    current_user: dict = Depends(get_current_user),
    auth_db=Depends(get_auth_db),
):
    if current_user["role"] != "Admin":
        return RedirectResponse("/ui/dashboard", status_code=303)
    logs = api_get_audit_log(limit=100, current_user=current_user, db=auth_db)["data"]
    return templates.TemplateResponse(request, "admin/audit.html",
                                      _ctx(request, current_user, active="audit", logs=logs))


@router.post("/admin/verify-audit")
def verify_audit(
    request: Request,
    current_user: dict = Depends(get_current_user),
    auth_db=Depends(get_auth_db),
):
    if current_user["role"] != "Admin":
        return {"error": "Unauthorized"}
    return api_verify_audit(current_user=current_user, db=auth_db)


@router.get("/admin/direct-modifications", response_class=HTMLResponse)
def direct_modifications_page(
    request: Request,
    current_user: dict = Depends(get_current_user),
    auth_db=Depends(get_auth_db),
):
    if current_user["role"] != "Admin":
        return RedirectResponse("/ui/dashboard", status_code=303)
    entries = api_get_direct_modifications(limit=100, current_user=current_user, db=auth_db)["data"]
    return templates.TemplateResponse(request, "admin/direct_modifications.html",
                                      _ctx(request, current_user, active="tamper", entries=entries))


@router.get("/", response_class=HTMLResponse)
def root():
    return RedirectResponse("/ui/dashboard", status_code=303)
