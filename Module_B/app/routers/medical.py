from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
from app.auth.dependencies import get_current_user, require_admin
from app.database import get_auth_db, get_track_db
from app.services.audit import write_audit_log
from app.services.id_generation import insert_with_generated_id
from app.services.rbac import assert_coach_manages_member
from app.services.validation import (
    derive_medical_status,
    humanize_db_error,
    parse_iso_date,
)

router = APIRouter()


class MedicalCreate(BaseModel):
    record_id:         Optional[int] = None
    member_id:         int
    medical_condition: str
    diagnosis_date:    str
    status:            str
    recovery_date:     Optional[str] = None


class MedicalUpdate(BaseModel):
    medical_condition: Optional[str] = None
    diagnosis_date:    Optional[str] = None
    recovery_date:     Optional[str] = None
    status:            Optional[str] = None


def _validate_medical_payload(diagnosis_date: str, recovery_date: Optional[str], requested_status: str) -> str:
    parsed_diagnosis = parse_iso_date(diagnosis_date, "Diagnosis date")
    parsed_recovery = parse_iso_date(recovery_date, "Recovery date") if recovery_date else None
    return derive_medical_status(requested_status, parsed_diagnosis, parsed_recovery)


@router.get("/record/{record_id}", description="**Access:** Admin, Coach (restricted), or the member themselves.\n\n"
    "- **Admin** can view any medical record.\n"
    "- **Coach** can only view records for members on their teams.\n"
    "- **Player** can only view their own medical records.")
def get_medical_record(
    record_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    track_db.execute("SELECT * FROM MedicalRecord WHERE RecordID = %s", (record_id,))
    record = track_db.fetchone()
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")
    if current_user["role"] == "Admin":
        pass
    elif current_user["member_id"] == record["MemberID"]:
        pass
    elif current_user["role"] == "Coach":
        assert_coach_manages_member(track_db, current_user, record["MemberID"],
                                    detail="Coach can only view medical records of players on their teams.")
    else:
        write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                        "SELECT", "MedicalRecord", str(record_id), "UNAUTHORIZED",
                        {"reason": "not admin, not own record, not coach of player"}, ip)
        raise HTTPException(status_code=403, detail="Access denied")
    record["DiagnosisDate"] = str(record["DiagnosisDate"])
    if record.get("RecoveryDate"):
        record["RecoveryDate"] = str(record["RecoveryDate"])
    write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                    "SELECT", "MedicalRecord", str(record_id), "SUCCESS", None, ip)
    return {"success": True, "data": record}


@router.get("/{member_id}", description="**Access:** Admin, Coach (restricted), or the member themselves.\n\n"
    "- **Admin** can view any member's medical records.\n"
    "- **Coach** can only view records for members on their teams.\n"
    "- **Player** can only view their own medical records.")
def get_medical_records(
    member_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    if current_user["role"] != "Admin" and current_user["member_id"] != member_id:
        if current_user["role"] == "Coach":
            assert_coach_manages_member(track_db, current_user, member_id,
                                        detail="Coach can only view medical records of players on their teams.")
        else:
            write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                            "SELECT", "MedicalRecord", str(member_id), "UNAUTHORIZED",
                            {"reason": "not admin, not own record, not coach of player"}, ip)
            raise HTTPException(status_code=403, detail="Access denied")
    track_db.execute(
        "SELECT * FROM MedicalRecord WHERE MemberID = %s ORDER BY DiagnosisDate DESC",
        (member_id,),
    )
    rows = track_db.fetchall()
    for r in rows:
        r["DiagnosisDate"] = str(r["DiagnosisDate"])
        if r.get("RecoveryDate"):
            r["RecoveryDate"] = str(r["RecoveryDate"])
    write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                    "SELECT", "MedicalRecord", str(member_id), "SUCCESS",
                    {"count": len(rows)}, ip)
    return {"success": True, "data": rows}


@router.post("", description="**Access:** Admin only.")
def create_medical_record(
    body: MedicalCreate,
    request: Request,
    current_user: dict = Depends(require_admin),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    record_id = body.record_id
    try:
        body.status = _validate_medical_payload(body.diagnosis_date, body.recovery_date, body.status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        record_id = insert_with_generated_id(
            track_db,
            requested_id=record_id,
            next_id_sql="SELECT COALESCE(MAX(RecordID), 0) + 1 AS nid FROM MedicalRecord",
            insert_fn=lambda record_id: track_db.execute(
                """
                INSERT INTO MedicalRecord
                    (RecordID, MemberID, MedicalCondition, DiagnosisDate, RecoveryDate, Status)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (record_id, body.member_id, body.medical_condition,
                 body.diagnosis_date, body.recovery_date, body.status),
            ),
        )
    except Exception as e:
        write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                        "INSERT", "MedicalRecord", str(record_id), "FAILURE",
                        {"error": str(e)}, ip)
        raise HTTPException(status_code=400, detail=humanize_db_error(e)) from e
    write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                    "INSERT", "MedicalRecord", str(record_id), "SUCCESS",
                    {"member_id": body.member_id, "condition": body.medical_condition}, ip)
    return {"success": True, "message": "Medical record created",
            "data": {"record_id": record_id}}


@router.put("/{record_id}", description="**Access:** Admin only.")
def update_medical_record(
    record_id: int,
    body: MedicalUpdate,
    request: Request,
    current_user: dict = Depends(require_admin),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    track_db.execute(
        "SELECT RecordID, DiagnosisDate, RecoveryDate, Status FROM MedicalRecord WHERE RecordID=%s",
        (record_id,),
    )
    record = track_db.fetchone()
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    if any(key in fields for key in ("diagnosis_date", "recovery_date")) or all(
        key in record for key in ("DiagnosisDate", "Status")
    ):
        try:
            fields["status"] = _validate_medical_payload(
                fields.get("diagnosis_date") or str(record.get("DiagnosisDate")),
                fields.get("recovery_date") if "recovery_date" in fields else (
                    str(record["RecoveryDate"]) if record.get("RecoveryDate") else None
                ),
                fields.get("status") or record.get("Status", "Active"),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    col_map = {
        "medical_condition": "MedicalCondition", "diagnosis_date": "DiagnosisDate",
        "recovery_date": "RecoveryDate", "status": "Status",
    }
    set_clause = ", ".join(f"{col_map[k]} = %s" for k in fields)
    try:
        track_db.execute(f"UPDATE MedicalRecord SET {set_clause} WHERE RecordID=%s",
                         list(fields.values()) + [record_id])
    except Exception as exc:
        raise HTTPException(status_code=400, detail=humanize_db_error(exc)) from exc
    write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                    "UPDATE", "MedicalRecord", str(record_id), "SUCCESS", fields, ip)
    return {"success": True, "message": "Medical record updated"}


@router.delete("/{record_id}", description="**Access:** Admin only.")
def delete_medical_record(
    record_id: int,
    request: Request,
    current_user: dict = Depends(require_admin),
    track_db=Depends(get_track_db),
    auth_db=Depends(get_auth_db),
):
    ip = request.client.host if request.client else "unknown"
    track_db.execute("SELECT RecordID, MemberID FROM MedicalRecord WHERE RecordID=%s", (record_id,))
    if not track_db.fetchone():
        raise HTTPException(status_code=404, detail="Record not found")
    track_db.execute("DELETE FROM MedicalRecord WHERE RecordID=%s", (record_id,))
    write_audit_log(auth_db, current_user["user_id"], current_user["username"],
                    "DELETE", "MedicalRecord", str(record_id), "SUCCESS", None, ip)
    return {"success": True, "message": f"Record {record_id} deleted"}
