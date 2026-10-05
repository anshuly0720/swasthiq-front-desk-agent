"""The policy engine: what the agent does, decided in Python.

The model reports what it heard. This decides what happens. Two properties fall
out of that split, and both are graded:

  Determinism - the tool-name set is a function of the extracted state, not of
                a sample from a model, so three runs produce three identical
                fingerprints.
  Grounding   - every identifier in the response came back from a tool. There is
                no path from caller text to an id in the output.

Ordering is the other half. The clinical screen runs before any tool call, so a
red flag in the final turn still arrives before a booking could commit. That is
the brief's one hard rule, enforced by control flow rather than by instruction.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from . import replies
from .extract import extract
from .safety import screen


def _result(terminal_state: str, reply: str, escalation_reason: Optional[str] = None,
            patient_id: Optional[str] = None, appointment_id: Optional[str] = None,
            note: Optional[str] = None) -> Dict[str, Any]:
    return {"terminal_state": terminal_state, "escalation_reason": escalation_reason,
            "patient_id": patient_id, "appointment_id": appointment_id,
            "reply": reply, "note": note}


def _lookup(tools, name: Optional[str], phone: Optional[str]) -> Tuple[Optional[dict], str]:
    """-> (candidate, status) where status is resolved | ambiguous | unknown | none."""
    if not name and not phone:
        return None, "none"
    arguments: Dict[str, Any] = {}
    if name:
        arguments["name"] = name
    if phone:
        arguments["phone"] = phone
    outcome = tools.call("lookup_patient", arguments)
    if not outcome["ok"]:
        return None, "unknown"
    data = outcome["data"]
    if data["candidate_count"] == 1:
        return data["candidates"][0], "resolved"
    if data["candidate_count"] == 0:
        return None, "unknown"
    return None, "ambiguous"


def _escalate(tools, reason: str, detail: str, reply: str,
              patient_id: Optional[str] = None) -> Dict[str, Any]:
    tools.call("escalate_to_human", {"reason": reason, "detail": detail})
    return _result("escalated", reply, escalation_reason=reason, patient_id=patient_id)


def run_conversation(tools, turns: List[str], today: str,
                     extraction=None) -> Dict[str, Any]:
    found = screen(turns)
    state = extraction or extract(turns, today, tools.store)

    # 1. Anything clinical stops everything, at the turn it appears.
    if found and found["kind"] == "clinical_urgent":
        return _escalate(tools, "clinical_urgent",
                         "caller reports {} (turn {})".format(found["finding"],
                                                              found["turn_index"] + 1),
                         replies.EMERGENCY)

    # 2. Injected instructions and bulk operations: nothing for a human to pick
    #    up, so refused rather than escalated. No tool is called at all.
    if state.injection or state.bulk:
        return _result("refused", replies.REFUSED,
                       note="instructions in the caller turn, or a bulk operation")

    # 3. A clinical judgement the front desk cannot give.
    if found and found["kind"] == "medical_advice":
        return _escalate(tools, "medical_advice",
                         "caller {}".format(found["finding"]), replies.ADVICE)

    # 4. Nothing usable was ever said.
    if state.intent == "none" and not (state.caller_name or state.caller_phone):
        return _result("abandoned", replies.NOTHING_HEARD, note="no actionable content")

    # 5. Who is this, and who is it for.
    subject, subject_status = _lookup(tools, state.subject_name, None)
    caller, caller_status = _lookup(tools, state.caller_name, state.caller_phone)

    if "ambiguous" in (subject_status, caller_status):
        return _escalate(tools, "ambiguous_patient",
                         "more than one patient matches the name given",
                         replies.AMBIGUOUS)
    if "unknown" in (subject_status, caller_status):
        # A name was given and no record matched. No tool registers a patient,
        # so this needs a human rather than a guess. DECISIONS.md item 9.
        return _escalate(tools, "out_of_scope",
                         "named person is not in the clinic's records",
                         replies.OUT_OF_SCOPE)

    patient = subject or caller
    actor = caller or subject

    # 6. Acting on someone else's record needs a listed guardianship.
    if subject and caller and subject["patient_id"] != caller["patient_id"]:
        wards = {w["patient_id"] for w in caller["guardian_of"]}
        if subject["patient_id"] not in wards:
            return _escalate(tools, "not_authorised",
                             "caller is neither the patient nor a listed guardian",
                             replies.NOT_AUTHORISED)

    if state.intent in ("book", "ask_availability"):
        return _do_book(tools, state, patient, actor)
    if state.intent == "reschedule":
        return _do_move(tools, state, patient, actor)
    if state.intent == "cancel":
        return _do_cancel(tools, state, patient, actor)

    return _result("abandoned", replies.NOTHING_HEARD,
                   patient_id=patient["patient_id"] if patient else None,
                   note="no action the front desk can take")


def _do_book(tools, state, patient, actor) -> Dict[str, Any]:
    patient_id = patient["patient_id"] if patient else None
    if not state.doctor_id or not state.date:
        return _result("abandoned", replies.NOTHING_HEARD, patient_id=patient_id,
                       note="no doctor or no date")

    arguments = {"doctor_id": state.doctor_id, "date": state.date}
    if state.part_of_day:
        arguments["part_of_day"] = state.part_of_day
    search = tools.call("search_slots", arguments)
    if not search["ok"]:
        return _result("abandoned", replies.OUT_OF_SCOPE, patient_id=patient_id,
                       note=search["error"]["code"])

    data = search["data"]
    slots = data["slots"]
    if not slots:
        return _result("abandoned",
                       replies.no_slots(data["doctor_name"], data["date"], data["reason"]),
                       patient_id=patient_id, note=data["reason"])

    # An exact time the caller named is honoured or not at all. Quietly moving
    # them to a neighbouring slot is the agent inventing a booking they never
    # agreed to.
    if state.time:
        if state.time not in slots:
            return _result("abandoned",
                           replies.slot_not_free(data["doctor_name"], data["date"], state.time),
                           patient_id=patient_id, note="requested time not free")
        start = state.time
    else:
        start = slots[0]

    if patient is None:
        return _result("abandoned", replies.NOTHING_HEARD,
                       note="caller never identified themselves")

    booking = {"patient_id": patient_id, "doctor_id": state.doctor_id,
               "date": state.date, "start": start}
    if actor and actor["patient_id"] != patient_id:
        booking["booked_by"] = actor["patient_id"]
    outcome = tools.call("book_appointment", booking)
    if not outcome["ok"]:
        return _result("abandoned", replies.slot_not_free(
            data["doctor_name"], state.date, start), patient_id=patient_id,
            note=outcome["error"]["code"])

    appointment = outcome["data"]["appointment"]
    return _result("booked", replies.booked(appointment["doctor_name"], appointment["date"],
                                            appointment["start"]),
                   patient_id=patient_id, appointment_id=appointment["appointment_id"])


def _active(patient, date: Optional[str]) -> Optional[dict]:
    """The appointment the caller means, or None when it is not obvious."""
    appointments = patient["appointments"] if patient else []
    if not appointments:
        return None
    if len(appointments) == 1:
        return appointments[0]
    on_date = [a for a in appointments if a["date"] == date]
    return on_date[0] if len(on_date) == 1 else None


def _do_move(tools, state, patient, actor) -> Dict[str, Any]:
    patient_id = patient["patient_id"] if patient else None
    existing = _active(patient, None)
    if existing is None:
        return _escalate(tools, "out_of_scope",
                         "no single existing appointment to move",
                         replies.OUT_OF_SCOPE, patient_id=patient_id)
    if not state.date:
        return _result("abandoned", replies.NOTHING_HEARD, patient_id=patient_id,
                       note="no target date")

    start = state.time
    if start is None:
        search = tools.call("search_slots", {"doctor_id": existing["doctor_id"],
                                             "date": state.date,
                                             "part_of_day": state.part_of_day or "any"})
        slots = search["data"]["slots"] if search["ok"] else []
        if not slots:
            return _result("abandoned", replies.OUT_OF_SCOPE, patient_id=patient_id,
                           note="no slot to move to")
        start = slots[0]

    arguments = {"appointment_id": existing["appointment_id"], "date": state.date,
                 "start": start}
    if actor:
        arguments["requested_by"] = actor["patient_id"]
    outcome = tools.call("reschedule_appointment", arguments)
    if not outcome["ok"]:
        return _result("abandoned", replies.OUT_OF_SCOPE, patient_id=patient_id,
                       note=outcome["error"]["code"])
    appointment = outcome["data"]["appointment"]
    return _result("rescheduled", replies.rescheduled(appointment["doctor_name"],
                                                      appointment["date"],
                                                      appointment["start"]),
                   patient_id=patient_id, appointment_id=appointment["appointment_id"])


def _do_cancel(tools, state, patient, actor) -> Dict[str, Any]:
    patient_id = patient["patient_id"] if patient else None
    existing = _active(patient, state.date)
    if existing is None:
        return _escalate(tools, "out_of_scope",
                         "no single existing appointment to cancel",
                         replies.OUT_OF_SCOPE, patient_id=patient_id)
    arguments = {"appointment_id": existing["appointment_id"]}
    if actor:
        arguments["requested_by"] = actor["patient_id"]
    outcome = tools.call("cancel_appointment", arguments)
    if not outcome["ok"]:
        return _result("abandoned", replies.OUT_OF_SCOPE, patient_id=patient_id,
                       note=outcome["error"]["code"])
    appointment = outcome["data"]["appointment"]
    return _result("cancelled", replies.cancelled(appointment["doctor_name"],
                                                  appointment["date"],
                                                  appointment["start"]),
                   patient_id=patient_id, appointment_id=appointment["appointment_id"])