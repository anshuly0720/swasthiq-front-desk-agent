"""Tool-layer behaviour, including the non-happy paths the brief asks for."""

import pytest

from app.errors import (CLINIC_HOLIDAY, DATE_IN_PAST, DOCTOR_ON_LEAVE, INVALID_ARGUMENTS,
                        INVALID_DATE, INVALID_ESCALATION_REASON, NOT_AUTHORISED, NO_WINDOW,
                        OFF_GRID_TIME, SLOT_TAKEN, UNKNOWN_APPOINTMENT, UNKNOWN_DOCTOR,
                        UNKNOWN_PATIENT, UNKNOWN_TOOL)


def code(result):
    return result["error"]["code"]


# -- search_slots ----------------------------------------------------------

def test_search_returns_free_slots(tools):
    out = tools.call("search_slots", {"doctor_id": "dr_rao", "date": "2026-10-03"})
    assert out["ok"] and out["data"]["available"]
    assert "09:15" not in out["data"]["slots"]      # ap_0006 holds it
    assert "09:00" in out["data"]["slots"]


def test_part_of_day_narrows(tools):
    out = tools.call("search_slots", {"doctor_id": "dr_sethi", "date": "2026-10-08",
                                      "part_of_day": "evening"})
    assert out["data"]["slots"][0] == "17:00"       # 17:30 is ap_0014


@pytest.mark.parametrize("date,reason", [
    ("2026-10-04", NO_WINDOW),         # Sunday, nobody works
    ("2026-10-02", CLINIC_HOLIDAY),    # clinic closed
    ("2026-10-09", DOCTOR_ON_LEAVE),   # Dr. Rao on leave
    ("2026-09-30", DATE_IN_PAST),
])
def test_closed_days_are_answers_not_failures(tools, date, reason):
    """cv_0005 needs this call to succeed and come back empty. An error here
    would push the agent toward inventing a slot to stay helpful."""
    out = tools.call("search_slots", {"doctor_id": "dr_rao", "date": date})
    assert out["ok"] is True
    assert out["data"]["available"] is False
    assert out["data"]["slots"] == []
    assert out["data"]["reason"] == reason


# -- lookup_patient --------------------------------------------------------

def test_ambiguous_lookup_returns_candidates_not_a_guess(tools):
    out = tools.call("lookup_patient", {"name": "Sharma ji"})
    assert out["data"]["candidate_count"] == 3
    assert out["data"]["resolved"] is False


def test_phone_disambiguates_the_sharmas(tools):
    out = tools.call("lookup_patient", {"name": "Rajesh Kumar Sharma",
                                        "phone": "9812200011"})
    assert out["data"]["resolved"] is True
    assert out["data"]["candidates"][0]["patient_id"] == "pt_0001"


def test_shared_phone_returns_the_whole_household(tools):
    out = tools.call("lookup_patient", {"phone": "9812200166"})
    assert {c["patient_id"] for c in out["data"]["candidates"]} == {
        "pt_0006", "pt_0007", "pt_0008"}


def test_name_and_phone_pointing_at_different_people_resolves_nobody(tools):
    out = tools.call("lookup_patient", {"name": "Lakshmi Iyer", "phone": "9812200497"})
    assert out["data"]["candidate_count"] == 0
    assert "does not match" in out["data"]["note"] or "no patient" in out["data"]["note"]


def test_candidates_carry_guardianships_and_appointments(tools):
    out = tools.call("lookup_patient", {"name": "Sunita Gupta", "phone": "9812200166"})
    sunita = out["data"]["candidates"][0]
    assert {w["patient_id"] for w in sunita["guardian_of"]} == {"pt_0006", "pt_0007"}

    out = tools.call("lookup_patient", {"patient_id": "pt_0001"})
    appointments = out["data"]["candidates"][0]["appointments"]
    assert [a["appointment_id"] for a in appointments] == ["ap_0001"]


def test_lookup_needs_something_to_go_on(tools):
    assert code(tools.call("lookup_patient", {})) == INVALID_ARGUMENTS


# -- book_appointment ------------------------------------------------------

def test_booking_a_free_slot(tools):
    out = tools.call("book_appointment", {"patient_id": "pt_0013", "doctor_id": "dr_rao",
                                          "date": "2026-10-03", "start": "09:00"})
    assert out["ok"]
    assert out["data"]["appointment"]["appointment_id"] == "ap_0026"
    assert out["data"]["appointment"]["end"] == "09:15"


def test_double_booking_is_refused(tools):
    """cv_0015: 09:00 on 2026-10-08 is ap_0015. The tool layer must refuse even
    if the agent asks politely."""
    out = tools.call("book_appointment", {"patient_id": "pt_0027", "doctor_id": "dr_rao",
                                          "date": "2026-10-08", "start": "09:00"})
    assert code(out) == SLOT_TAKEN
    assert out["error"]["details"]["nearest_free"]        # actionable, not just "no"


def test_off_grid_time_is_refused_with_alternatives(tools):
    out = tools.call("book_appointment", {"patient_id": "pt_0027", "doctor_id": "dr_rao",
                                          "date": "2026-10-03", "start": "09:07"})
    assert code(out) == OFF_GRID_TIME
    assert out["error"]["details"]["nearest_free"]


@pytest.mark.parametrize("date,expected", [
    ("2026-10-02", CLINIC_HOLIDAY),
    ("2026-10-04", NO_WINDOW),
    ("2026-09-30", DATE_IN_PAST),
])
def test_cannot_book_when_the_clinic_is_shut(tools, date, expected):
    out = tools.call("book_appointment", {"patient_id": "pt_0027", "doctor_id": "dr_rao",
                                          "date": date, "start": "09:00"})
    assert code(out) == expected


def test_guardian_may_book_for_a_ward(tools):
    """cv_0008: Sunita is listed for both children, so she is authorised."""
    out = tools.call("book_appointment", {"patient_id": "pt_0006", "doctor_id": "dr_sethi",
                                          "date": "2026-10-08", "start": "17:00",
                                          "booked_by": "pt_0008"})
    assert out["ok"]
    assert out["data"]["appointment"]["patient_id"] == "pt_0006"


def test_a_shared_phone_is_not_a_guardianship(tools):
    """Sanjay and Kavita Rawat share 9812200466 and have no guardian link."""
    out = tools.call("book_appointment", {"patient_id": "pt_0018", "doctor_id": "dr_rao",
                                          "date": "2026-10-03", "start": "09:00",
                                          "booked_by": "pt_0019"})
    assert code(out) == NOT_AUTHORISED


# -- reschedule and cancel -------------------------------------------------

def test_reschedule_keeps_the_same_id(tools):
    """cv_0003: today's 09:30 moves to Saturday 10:00."""
    out = tools.call("reschedule_appointment", {"appointment_id": "ap_0001",
                                                "date": "2026-10-03", "start": "10:00",
                                                "requested_by": "pt_0001"})
    assert out["ok"]
    assert out["data"]["appointment"]["appointment_id"] == "ap_0001"
    assert out["data"]["from"] == {"date": "2026-10-01", "start": "09:30"}


def test_reschedule_onto_a_taken_slot_is_refused(tools):
    out = tools.call("reschedule_appointment", {"appointment_id": "ap_0001",
                                                "date": "2026-10-03", "start": "09:15"})
    assert code(out) == SLOT_TAKEN


def test_cancel_frees_the_slot(tools):
    assert tools.call("cancel_appointment", {"appointment_id": "ap_0001",
                                             "requested_by": "pt_0001"})["ok"]
    again = tools.call("book_appointment", {"patient_id": "pt_0005", "doctor_id": "dr_rao",
                                            "date": "2026-10-01", "start": "09:30"})
    assert again["ok"]


def test_cancelling_twice_is_refused(tools):
    tools.call("cancel_appointment", {"appointment_id": "ap_0001"})
    assert code(tools.call("cancel_appointment", {"appointment_id": "ap_0001"})) == \
        "APPOINTMENT_NOT_ACTIVE"


def test_a_neighbour_cannot_cancel_your_appointment(tools):
    """cv_0009: Mohit Negi wants to cancel Lakshmi Iyer's ap_0003."""
    out = tools.call("cancel_appointment", {"appointment_id": "ap_0003",
                                            "requested_by": "pt_0020"})
    assert code(out) == NOT_AUTHORISED
    assert tools.store.get_appointment("ap_0003")["status"] == "booked"


# -- escalate --------------------------------------------------------------

def test_escalation_reasons_are_the_five_in_the_schema(tools):
    out = tools.call("escalate_to_human", {"reason": "clinical_urgent",
                                           "detail": "caller reports chest pain"})
    assert out["ok"] and out["data"]["reason"] == "clinical_urgent"
    assert code(tools.call("escalate_to_human", {"reason": "urgent"})) == \
        INVALID_ESCALATION_REASON


def test_escalation_is_deterministic(tools):
    first = tools.call("escalate_to_human", {"reason": "out_of_scope", "detail": "billing"})
    second = tools.call("escalate_to_human", {"reason": "out_of_scope", "detail": "billing"})
    assert first == second


# -- malformed calls -------------------------------------------------------

def test_unknown_ids_are_specific(tools):
    assert code(tools.call("search_slots", {"doctor_id": "dr_who",
                                            "date": "2026-10-03"})) == UNKNOWN_DOCTOR
    assert code(tools.call("book_appointment", {"patient_id": "pt_9999",
                                                "doctor_id": "dr_rao", "date": "2026-10-03",
                                                "start": "09:00"})) == UNKNOWN_PATIENT
    assert code(tools.call("cancel_appointment",
                           {"appointment_id": "ap_9999"})) == UNKNOWN_APPOINTMENT


def test_malformed_arguments_name_the_problem(tools):
    missing = tools.call("book_appointment", {"patient_id": "pt_0013"})
    assert code(missing) == INVALID_ARGUMENTS
    assert {p["field"] for p in missing["error"]["details"]["problems"]} >= {
        "doctor_id", "date", "start"}

    extra = tools.call("search_slots", {"doctor_id": "dr_rao", "date": "2026-10-03",
                                        "urgency": "high"})
    assert code(extra) == INVALID_ARGUMENTS

    assert code(tools.call("search_slots", {"doctor_id": "dr_rao",
                                            "date": "kal"})) == INVALID_DATE
    assert code(tools.call("search_slots", "dr_rao")) == INVALID_ARGUMENTS


def test_an_invented_tool_name_is_refused(tools):
    assert code(tools.call("cancel_all_appointments", {"date": "2026-10-02"})) == UNKNOWN_TOOL


# -- the trace -------------------------------------------------------------

def test_failed_calls_are_still_recorded(tools):
    """schema.md: tool_calls includes failed calls."""
    tools.call("search_slots", {"doctor_id": "dr_rao", "date": "2026-10-03"})
    tools.call("book_appointment", {"patient_id": "pt_0027", "doctor_id": "dr_rao",
                                    "date": "2026-10-08", "start": "09:00"})
    assert [c["name"] for c in tools.calls] == ["search_slots", "book_appointment"]