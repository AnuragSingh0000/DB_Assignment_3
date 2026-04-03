from __future__ import annotations
import re
from datetime import date, datetime, time
from typing import Optional

DEFAULT_COUNTRY_CODE = "+91"

COMMON_COUNTRY_CODES = ["+91", "+1", "+44", "+61", "+971", "+65"]


def parse_iso_date(value: str, label: str) -> date:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a valid date in YYYY-MM-DD format.") from exc


def parse_iso_time(value: str, label: str) -> time:
    try:
        return datetime.strptime(str(value), "%H:%M:%S").time()
    except ValueError:
        try:
            return datetime.strptime(str(value), "%H:%M").time()
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} must be a valid time.") from exc


def validate_not_future(value: date, label: str) -> None:
    if value > date.today():
        raise ValueError(f"{label} cannot be in the future.")


def validate_date_order(
    start_value: date,
    end_value: date,
    start_label: str,
    end_label: str,
) -> None:
    if start_value > end_value:
        raise ValueError(f"{start_label} cannot be after {end_label}.")


def validate_time_order(
    start_value: time,
    end_value: time,
    start_label: str,
    end_label: str,
) -> None:
    if start_value >= end_value:
        raise ValueError(f"{end_label} must be after {start_label}.")


def validate_member_name(name: str) -> str:
    normalized = " ".join((name or "").split())
    if not normalized:
        raise ValueError("Full name is required.")
    if any(ch.isdigit() for ch in normalized):
        raise ValueError("Full name cannot contain numbers.")
    return normalized


def normalize_country_code(country_code: Optional[str]) -> str:
    if not isinstance(country_code, str):
        return DEFAULT_COUNTRY_CODE
    normalized = country_code.strip()
    if not re.fullmatch(r"\+\d{1,3}", normalized):
        raise ValueError("Country code must be in the format +<digits>.")
    return normalized


def _parse_contact(raw: str) -> tuple[str, str]:
    value = str(raw or "").strip()
    if not value:
        raise ValueError("Contact number is required.")
    digits_only = re.sub(r"\D", "", value)
    if not value.startswith("+") and len(digits_only) != 10:
        raise ValueError("Contact number must include a country code and a 10-digit phone number.")
    if re.fullmatch(r"\d{10}", value):
        return DEFAULT_COUNTRY_CODE, value
    compact = re.sub(r"[\s()-]", "", value)
    if not re.fullmatch(r"\+\d{11,13}", compact):
        raise ValueError("Contact number must include a country code and a 10-digit phone number.")
    digits = compact[1:]
    for cc_len in range(1, 4):
        if len(digits) - cc_len == 10:
            return f"+{digits[:cc_len]}", digits[cc_len:]
    raise ValueError("Contact number must include a valid country code and a 10-digit phone number.")


def combine_contact_number(country_code: Optional[str], number: str) -> str:
    normalized_code = normalize_country_code(country_code)
    normalized_number = re.sub(r"\D", "", str(number or ""))
    if len(normalized_number) != 10:
        raise ValueError("Contact number must contain exactly 10 digits.")
    return f"{normalized_code}{normalized_number}"


def normalize_contact_number(contact_number: str) -> str:
    raw_value = str(contact_number or "").strip()
    digits_only = re.sub(r"\D", "", raw_value)
    if raw_value and not raw_value.startswith("+") and len(digits_only) != 10:
        return raw_value
    cc, num = _parse_contact(raw_value)
    return f"{cc}{num}"


def split_contact_number(contact_number: Optional[str]) -> tuple[str, str]:
    raw_value = (contact_number or "").strip()
    if not raw_value:
        return DEFAULT_COUNTRY_CODE, ""
    try:
        return _parse_contact(raw_value)
    except ValueError:
        return DEFAULT_COUNTRY_CODE, re.sub(r"\D", "", raw_value)[-10:]


def derive_tournament_status(start_date: date, end_date: date) -> str:
    today = date.today()
    if today < start_date:
        return "Upcoming"
    if today > end_date:
        return "Completed"
    return "Ongoing"


def derive_medical_status(requested_status: str, diagnosis_date: date, recovery_date: Optional[date]) -> str:
    validate_not_future(diagnosis_date, "Diagnosis date")
    if recovery_date is not None:
        validate_date_order(diagnosis_date, recovery_date, "Diagnosis date", "Recovery date")
        if recovery_date <= date.today():
            return "Recovered"
    return "Chronic" if requested_status == "Chronic" else "Active"


def humanize_db_error(exc: Exception) -> str:
    message = str(exc)
    lower = message.lower()
    if "duplicate entry" in lower:
        if "username" in lower:
            return f"Username already exists. ({message})"
        if "email" in lower:
            return f"Email address already exists. ({message})"
        if "tournamentname" in lower or "uq_tournament_name" in lower:
            return f"Tournament name must be unique. ({message})"
        if "primary" in lower:
            return f"That ID already exists. ({message})"
        return f"A record with the same unique value already exists. ({message})"
    if "foreign key constraint fails" in lower:
        return "One of the selected related records is invalid."
    if "check constraint" in lower:
        if "enddate" in lower or "startdate" in lower:
            return "End date cannot be before start date."
        if "endtime" in lower or "starttime" in lower:
            return "End time must be after start time."
        if "recoverydate" in lower or "diagnosisdate" in lower:
            return "Recovery date cannot be before diagnosis date."
        return "One of the provided values is invalid."
    return message
