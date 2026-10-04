"""Tool-layer failures.

Every way a tool can refuse has a code in here. The agent sees the code and a
message that says what to do about it. It never sees a traceback, and the HTTP
layer never turns one of these into a 500 — the brief asks for "a specific,
actionable error, not a generic 500".
"""

from __future__ import annotations

from typing import Any, Dict

# --- argument shape -------------------------------------------------------
INVALID_ARGUMENTS = "INVALID_ARGUMENTS"
UNKNOWN_TOOL = "UNKNOWN_TOOL"

# --- unknown references ---------------------------------------------------
UNKNOWN_DOCTOR = "UNKNOWN_DOCTOR"
UNKNOWN_PATIENT = "UNKNOWN_PATIENT"
UNKNOWN_APPOINTMENT = "UNKNOWN_APPOINTMENT"

# --- date and time --------------------------------------------------------
INVALID_DATE = "INVALID_DATE"
INVALID_TIME = "INVALID_TIME"
DATE_IN_PAST = "DATE_IN_PAST"

# --- the clinic is not open -----------------------------------------------
CLINIC_HOLIDAY = "CLINIC_HOLIDAY"
DOCTOR_ON_LEAVE = "DOCTOR_ON_LEAVE"
NO_WINDOW = "NO_WINDOW"

# --- the slot is not bookable ---------------------------------------------
OFF_GRID_TIME = "OFF_GRID_TIME"
SLOT_TAKEN = "SLOT_TAKEN"

# --- permission and state -------------------------------------------------
NOT_AUTHORISED = "NOT_AUTHORISED"
APPOINTMENT_NOT_ACTIVE = "APPOINTMENT_NOT_ACTIVE"
NOTHING_TO_CHANGE = "NOTHING_TO_CHANGE"
INVALID_ESCALATION_REASON = "INVALID_ESCALATION_REASON"


class ToolError(Exception):
    """A tool refused a call.

    `code` is matched on by the policy engine; `message` is for the human
    reading the trace; `details` carries whatever would let a caller fix the
    call — the valid options, the conflicting appointment, the nearest slots.
    """

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def as_dict(self) -> Dict[str, Any]:
        error: Dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            error["details"] = self.details
        return {"ok": False, "error": error}

    def __repr__(self) -> str:  # shows up in pytest failures
        return "ToolError({!r}, {!r})".format(self.code, self.message)