from fastapi import HTTPException


def assert_coach_manages_member(
    track_db,
    current_user: dict,
    member_id: int,
    detail: str = "Coach can only access players on their teams.",
) -> None:
    """Raises 403 if current_user is a Coach not managing member_id. No-op for non-Coach roles."""
    if current_user["role"] != "Coach":
        return
    track_db.execute(
        """
        SELECT 1
        FROM TeamMember tm
        JOIN Team t ON tm.TeamID = t.TeamID
        WHERE tm.MemberID = %s AND t.CoachID = %s
        LIMIT 1
        """,
        (member_id, current_user["member_id"]),
    )
    if not track_db.fetchone():
        raise HTTPException(status_code=403, detail=detail)
