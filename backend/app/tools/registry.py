"""The six tools, implemented against clinic.json.

Nothing in this package imports a model client. This layer is the ground truth
every claim the agent makes gets checked against, so it cannot depend on the
thing being checked.

Every call goes through ToolLayer.call(), which appends to the trace *before*
running the tool — schema.md requires tool_calls to include failed calls, so
the record of the attempt must not depend on the attempt succeeding.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, ValidationError

from ..errors import (
    APPOINTMENT_NOT_ACTIVE,
    CLINIC_HOLIDAY,
    DATE_IN_PAST,
    DOCTOR_ON_LEAVE,
    INVALID_ARGUMENTS,
    INVALID_ESCALATION_REASON,
    NO_WINDOW,
    NOT_AUTHORISED,
    NOTHING_TO_CHANGE,
    OFF_GRID_TIME,
    SLOT_TAKEN,
    UNKNOWN_APPOINTMENT,
    UNKNOWN_DOCTOR,
    UNKNOWN_PATIENT,
    UNKNOWN_TOOL,
    ToolError,
)
from ..matching import find_by_name, normalise_phone
from ..slots import (
    build_grid,
    filter_by_part_of_day,
    parse_date,
    parse_hhmm,
    part_of_day_bounds,
    to_hhmm,
    weekday_of,
)

ESCALATION_REASONS = (
    "clinical_urgent",
    "medical_advice",
    "not_authorised",
    "ambiguous_patient",
    "out_of_scope",
)


# --------------------------------------------------------------------------
# Argument shapes. extra="forbid" so a hallucinated argument name is a named
# error rather than a silently ignored field.
# --------------------------------------------------------------------------

class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchSlotsArgs(_Args):
    doctor_id: str
    date: str
    part_of_day: str = "any"


class LookupPatientArgs(_Args):
    name: Optional[str] = None
    phone: Optional[str] = None
    patient_id: Optional[str] = None


class BookArgs(_Args):
    patient_id: str
    doctor_id: str
    date: str
    start: str
    booked_by: Optional[str] = None


class RescheduleArgs(_Args):
    appointment_id: str
    date: str
    start: str
    requested_by: Optional[str] = None


class CancelArgs(_Args):
    appointment_id: str
    requested_by: Optional[str] = None


class EscalateArgs(_Args):
    reason: str
    detail: str = ""


def _parse(model, tool_name: str, arguments: Any):
    """Validate arguments, or raise an error that says how to fix the call."""
    if not isinstance(arguments, dict):
        raise ToolError(
            INVALID_ARGUMENTS,
            "{} expects a JSON object of arguments, got {}".format(
                tool_name, type(arguments).__name__
            ),
            tool=tool_name,
            expected_fields=sorted(model.model_fields),
        )
    try:
        return model.model_validate(arguments)
    except ValidationError as exc:
        problems = [
            {
                "field": ".".join(str(part) for part in err["loc"]) or "(root)",
                "problem": err["msg"],
            }
            for err in exc.errors()
        ]
        raise ToolError(
            INVALID_ARGUMENTS,
            "{} was called with arguments it cannot use: {}".format(
                tool_name,
                "; ".join("{field}: {problem}".format(**p) for p in problems),
            ),
            tool=tool_name,
            problems=problems,
            expected_fields=sorted(model.model_fields),
        )


class ToolLayer:
    """The six tools, bound to one store and one `today`.

    `today` is a constructor argument rather than something a tool reads from
    the clock, so the same conversation resolves the same dates whenever it is
    replayed. Nothing below ever asks the operating system what day it is.
    """

    def __init__(self, store, today: str) -> None:
        parse_date(today, "today")
        self.store = store
        self.today = today
        self.calls: List[Dict[str, Any]] = []

    # -- entry point -------------------------------------------------------

    def call(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Run a tool by name. Never raises; failures come back as data."""
        arguments = {} if arguments is None else arguments
        self.calls.append({"name": name, "arguments": arguments})

        handler: Optional[Callable[[Any], Dict[str, Any]]] = {
            "search_slots": self.search_slots,
            "lookup_patient": self.lookup_patient,
            "book_appointment": self.book_appointment,
            "reschedule_appointment": self.reschedule_appointment,
            "cancel_appointment": self.cancel_appointment,
            "escalate_to_human": self.escalate_to_human,
        }.get(name)

        if handler is None:
            return ToolError(
                UNKNOWN_TOOL,
                "There is no tool called {!r}.".format(name),
                known_tools=[
                    "search_slots",
                    "lookup_patient",
                    "book_appointment",
                    "reschedule_appointment",
                    "cancel_appointment",
                    "escalate_to_human",
                ],
            ).as_dict()

        try:
            return {"ok": True, "data": handler(arguments)}
        except ToolError as error:
            return error.as_dict()

    # -- shared checks -----------------------------------------------------

    def _doctor_or_raise(self, doctor_id: str):
        doctor = self.store.get_doctor(doctor_id)
        if doctor is None:
            raise ToolError(
                UNKNOWN_DOCTOR,
                "No doctor with id {!r}.".format(doctor_id),
                known_doctors=[
                    {"doctor_id": row["id"], "name": row["name"]}
                    for row in self.store.all_doctors()
                ],
            )
        return doctor

    def _patient_or_raise(self, patient_id: str):
        patient = self.store.get_patient(patient_id)
        if patient is None:
            raise ToolError(
                UNKNOWN_PATIENT,
                "No patient with id {!r}. Resolve the caller with lookup_patient "
                "first; do not invent an id.".format(patient_id),
            )
        return patient

    def _appointment_or_raise(self, appointment_id: str):
        appointment = self.store.get_appointment(appointment_id)
        if appointment is None:
            raise ToolError(
                UNKNOWN_APPOINTMENT,
                "No appointment with id {!r}. Appointment ids come from "
                "lookup_patient; do not invent one.".format(appointment_id),
            )
        if appointment["status"] != "booked":
            raise ToolError(
                APPOINTMENT_NOT_ACTIVE,
                "Appointment {} is {}, so it cannot be changed.".format(
                    appointment_id, appointment["status"]
                ),
                status=appointment["status"],
            )
        return appointment

    def _require_authorised(self, actor_id: Optional[str], subject_id: str) -> None:
        """Who may act on whose record.

        `actor_id` of None means the patient is acting for themselves, which is
        the ordinary case. Anyone else must be a listed guardian. Knowing a
        name, sharing a phone number or holding an appointment id is not
        authorisation — Sanjay and Kavita Rawat share a number and have no
        guardian link between them.
        """
        if actor_id is None or actor_id == subject_id:
            return
        if self.store.is_guardian_of(actor_id, subject_id):
            return
        subject = self.store.get_patient(subject_id)
        raise ToolError(
            NOT_AUTHORISED,
            "{} is not the patient and is not a listed guardian of {}.".format(
                actor_id, subject["name"] if subject else subject_id
            ),
            actor_id=actor_id,
            subject_id=subject_id,
        )

    def _free_slots(self, doctor_id: str, on_date: str, exclude: Optional[str] = None):
        """(slots, reason). An empty list with a reason is an answer, not a failure."""
        if parse_date(on_date) < parse_date(self.today, "today"):
            return [], DATE_IN_PAST
        if self.store.is_holiday(on_date):
            return [], CLINIC_HOLIDAY
        if self.store.is_on_leave(doctor_id, on_date):
            return [], DOCTOR_ON_LEAVE
        grid = build_grid(
            self.store.windows_for(doctor_id, weekday_of(on_date)),
            self.store.slot_minutes,
        )
        if not grid:
            return [], NO_WINDOW
        taken = self.store.booked_starts(doctor_id, on_date, exclude_appointment_id=exclude)
        return [to_hhmm(m) for m in grid if to_hhmm(m) not in taken], None

    def _slot_or_raise(self, doctor_id: str, on_date: str, start: str,
                       exclude: Optional[str] = None) -> str:
        """Validate a specific slot and return its end time."""
        parse_hhmm(start, "start")
        free, reason = self._free_slots(doctor_id, on_date, exclude=exclude)
        doctor = self.store.get_doctor(doctor_id)

        if reason == DATE_IN_PAST:
            raise ToolError(DATE_IN_PAST,
                            "{} is before today ({}).".format(on_date, self.today),
                            today=self.today)
        if reason == CLINIC_HOLIDAY:
            raise ToolError(CLINIC_HOLIDAY,
                            "The clinic is closed on {}.".format(on_date), date=on_date)
        if reason == DOCTOR_ON_LEAVE:
            raise ToolError(DOCTOR_ON_LEAVE,
                            "{} is on leave on {}.".format(doctor["name"], on_date),
                            doctor_id=doctor_id, date=on_date)
        if reason == NO_WINDOW:
            raise ToolError(NO_WINDOW,
                            "{} does not work on {} ({}).".format(
                                doctor["name"], on_date, weekday_of(on_date)),
                            doctor_id=doctor_id, weekday=weekday_of(on_date))

        grid = [to_hhmm(m) for m in build_grid(
            self.store.windows_for(doctor_id, weekday_of(on_date)),
            self.store.slot_minutes)]
        if start not in grid:
            raise ToolError(
                OFF_GRID_TIME,
                "{} is not a slot start for {} on {}.".format(start, doctor["name"], on_date),
                nearest_free=free[:5],
            )
        if start not in free:
            raise ToolError(
                SLOT_TAKEN,
                "{} on {} is already booked with {}.".format(start, on_date, doctor["name"]),
                nearest_free=free[:5],
            )
        return to_hhmm(parse_hhmm(start) + self.store.slot_minutes)

    # -- serialisers -------------------------------------------------------

    def _appointment(self, row) -> Dict[str, Any]:
        doctor = self.store.get_doctor(row["doctor_id"])
        return {
            "appointment_id": row["id"],
            "patient_id": row["patient_id"],
            "doctor_id": row["doctor_id"],
            "doctor_name": doctor["name"] if doctor else None,
            "date": row["date"],
            "start": row["start"],
            "end": row["end"],
            "status": row["status"],
        }

    def _candidate(self, patient: Dict[str, Any]) -> Dict[str, Any]:
        def brief(patient_id):
            row = self.store.get_patient(patient_id)
            return {"patient_id": patient_id, "name": row["name"] if row else None}

        return {
            "patient_id": patient["id"],
            "name": patient["name"],
            "phone": patient["phone"],
            "dob": patient["dob"],
            "guardian_of": [brief(w) for w in self.store.ward_ids(patient["id"])],
            "guardians": [brief(g) for g in self.store.guardian_ids(patient["id"])],
            # No tool lists a patient's appointments, but cancel and reschedule
            # need an id that came from a tool. See DECISIONS.md item 9.
            "appointments": [
                self._appointment(self.store.get_appointment(a["id"]))
                for a in self.store.appointments_for_patient(patient["id"])
            ],
        }

    # -- the six tools -----------------------------------------------------

    def search_slots(self, arguments) -> Dict[str, Any]:
        args = _parse(SearchSlotsArgs, "search_slots", arguments)
        doctor = self._doctor_or_raise(args.doctor_id)
        parse_date(args.date)
        part_of_day_bounds(args.part_of_day)

        free, reason = self._free_slots(args.doctor_id, args.date)
        slots = filter_by_part_of_day(free, args.part_of_day) if free else []
        return {
            "doctor_id": args.doctor_id,
            "doctor_name": doctor["name"],
            "date": args.date,
            "weekday": weekday_of(args.date),
            "part_of_day": args.part_of_day,
            "available": bool(slots),
            # A closed day is an answer, not a failure. cv_0005 requires this
            # call to happen and to come back empty rather than error.
            "reason": reason or (None if slots else "FULLY_BOOKED"),
            "slots": slots,
            "slot_minutes": self.store.slot_minutes,
        }

    def lookup_patient(self, arguments) -> Dict[str, Any]:
        """Resolve a caller to patient records. Returns candidates, never a guess."""
        args = _parse(LookupPatientArgs, "lookup_patient", arguments)
        if not any([args.name, args.phone, args.patient_id]):
            raise ToolError(
                INVALID_ARGUMENTS,
                "lookup_patient needs at least one of name, phone or patient_id.",
                tool="lookup_patient",
            )

        if args.patient_id:
            found = self.store.get_patient(args.patient_id)
            candidates = [dict(found)] if found else []
            matched_on, note = "patient_id", None
        elif args.phone:
            pool = self.store.patients_by_phone(normalise_phone(args.phone))
            if args.name:
                narrowed = find_by_name(args.name, pool)
                if narrowed:
                    candidates, matched_on, note = narrowed, "phone+name", None
                else:
                    # The name and the number point at different people. Saying
                    # so without naming the others keeps the conflict visible
                    # and the unrelated records private.
                    candidates, matched_on = [], "phone"
                    note = ("no patient on this number matches that name; "
                            "{} other record(s) use it".format(len(pool)))
            else:
                candidates, matched_on, note = pool, "phone", None
        else:
            candidates = find_by_name(args.name, self.store.all_patients())
            matched_on, note = "name", None

        resolved = [self._candidate(c) for c in candidates]
        return {
            "query": {"name": args.name, "phone": args.phone, "patient_id": args.patient_id},
            "matched_on": matched_on,
            "candidate_count": len(resolved),
            # True only at exactly one. Two Sharmas is not "probably the first".
            "resolved": len(resolved) == 1,
            "candidates": resolved,
            "note": note,
        }

    def book_appointment(self, arguments) -> Dict[str, Any]:
        args = _parse(BookArgs, "book_appointment", arguments)
        self._patient_or_raise(args.patient_id)
        self._doctor_or_raise(args.doctor_id)
        parse_date(args.date)
        self._require_authorised(args.booked_by, args.patient_id)

        try:
            with self.store.transaction():
                # Inside the transaction, so two callers racing for this slot
                # are serialised rather than both reading it as free.
                end = self._slot_or_raise(args.doctor_id, args.date, args.start)
                appointment_id = self.store.insert_appointment(
                    args.patient_id, args.doctor_id, args.date, args.start, end
                )
        except sqlite3.IntegrityError:
            # The unique index caught what the check above could not. This is
            # the branch the 20-thread test exercises.
            raise ToolError(
                SLOT_TAKEN,
                "{} on {} was taken by another caller.".format(args.start, args.date),
                nearest_free=self._free_slots(args.doctor_id, args.date)[0][:5],
            )

        return {"booked": True,
                "appointment": self._appointment(self.store.get_appointment(appointment_id))}

    def reschedule_appointment(self, arguments) -> Dict[str, Any]:
        args = _parse(RescheduleArgs, "reschedule_appointment", arguments)
        appointment = self._appointment_or_raise(args.appointment_id)
        parse_date(args.date)
        self._require_authorised(args.requested_by, appointment["patient_id"])

        if appointment["date"] == args.date and appointment["start"] == args.start:
            raise ToolError(
                NOTHING_TO_CHANGE,
                "Appointment {} is already on {} at {}.".format(
                    args.appointment_id, args.date, args.start),
            )

        previous = {"date": appointment["date"], "start": appointment["start"]}
        try:
            with self.store.transaction():
                end = self._slot_or_raise(
                    appointment["doctor_id"], args.date, args.start,
                    exclude=args.appointment_id,
                )
                self.store.move_appointment(args.appointment_id, args.date, args.start, end)
        except sqlite3.IntegrityError:
            raise ToolError(
                SLOT_TAKEN,
                "{} on {} was taken by another caller.".format(args.start, args.date),
            )

        # Same id on purpose: schema.md calls this "moved", not replaced.
        return {"rescheduled": True, "from": previous,
                "appointment": self._appointment(self.store.get_appointment(args.appointment_id))}

    def cancel_appointment(self, arguments) -> Dict[str, Any]:
        args = _parse(CancelArgs, "cancel_appointment", arguments)
        appointment = self._appointment_or_raise(args.appointment_id)
        self._require_authorised(args.requested_by, appointment["patient_id"])
        with self.store.transaction():
            self.store.set_cancelled(args.appointment_id)
        return {"cancelled": True,
                "appointment": self._appointment(self.store.get_appointment(args.appointment_id))}

    def escalate_to_human(self, arguments) -> Dict[str, Any]:
        args = _parse(EscalateArgs, "escalate_to_human", arguments)
        if args.reason not in ESCALATION_REASONS:
            raise ToolError(
                INVALID_ESCALATION_REASON,
                "{!r} is not an escalation reason.".format(args.reason),
                allowed=list(ESCALATION_REASONS),
            )
        # Deliberately no generated handoff id: anything random here would
        # change between the three runs schema.md compares.
        return {"escalated": True, "reason": args.reason, "detail": args.detail}