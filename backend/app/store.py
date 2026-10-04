"""SQLite storage for one clinic.

Two things this file exists to guarantee:

1. A slot cannot be double-booked, even under concurrent callers. That is a
   partial unique index plus BEGIN IMMEDIATE, not an application-level check —
   a read-then-write check has a race window by construction.
2. Each POST /agent/run starts from clinic.json exactly as shipped. The default
   is an in-memory database seeded per request, so nothing leaks between runs.

Needs SQLite 3.8.0+ for the partial index. Every Python 3.9+ ships far newer.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Sequence, Set, Tuple

SCHEMA = """
CREATE TABLE doctors (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    speciality  TEXT NOT NULL
);

CREATE TABLE doctor_windows (
    doctor_id   TEXT NOT NULL REFERENCES doctors(id),
    day         TEXT NOT NULL,
    start       TEXT NOT NULL,
    end         TEXT NOT NULL
);
CREATE INDEX ix_windows_doctor_day ON doctor_windows(doctor_id, day);

CREATE TABLE doctor_leave (
    doctor_id   TEXT NOT NULL REFERENCES doctors(id),
    date        TEXT NOT NULL,
    PRIMARY KEY (doctor_id, date)
);

CREATE TABLE holidays (
    date        TEXT PRIMARY KEY
);

CREATE TABLE patients (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    phone       TEXT NOT NULL,
    dob         TEXT NOT NULL
);
CREATE INDEX ix_patients_phone ON patients(phone);

CREATE TABLE guardianships (
    guardian_id TEXT NOT NULL REFERENCES patients(id),
    ward_id     TEXT NOT NULL REFERENCES patients(id),
    PRIMARY KEY (guardian_id, ward_id)
);

CREATE TABLE appointments (
    id          TEXT PRIMARY KEY,
    patient_id  TEXT NOT NULL REFERENCES patients(id),
    doctor_id   TEXT NOT NULL REFERENCES doctors(id),
    date        TEXT NOT NULL,
    start       TEXT NOT NULL,
    end         TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('booked', 'cancelled'))
);
CREATE INDEX ix_appt_patient ON appointments(patient_id, status);
CREATE INDEX ix_appt_slot ON appointments(doctor_id, date, status);

-- The double-booking guarantee. Two racing transactions cannot both land here;
-- the loser gets IntegrityError, which the tool layer turns into SLOT_TAKEN.
-- Partial, so a cancelled appointment frees its slot.
CREATE UNIQUE INDEX ux_active_slot
    ON appointments(doctor_id, date, start)
    WHERE status = 'booked';
"""


class ClinicStore:
    """One connection to one clinic database."""

    def __init__(
        self,
        clinic: Optional[Dict[str, Any]] = None,
        db_path: str = ":memory:",
        seed: bool = True,
    ) -> None:
        self.db_path = db_path
        self._conn = sqlite3.connect(
            db_path,
            check_same_thread=False,
            timeout=15.0,          # wait out a competing writer instead of failing
            isolation_level=None,  # autocommit; transactions are explicit below
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        if db_path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
        if seed:
            if clinic is None:
                raise ValueError("seed=True needs the clinic dict")
            self._conn.executescript(SCHEMA)
            self._seed(clinic)
        self.slot_minutes = int((clinic or {}).get("clinic", {}).get("slot_minutes", 15))

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """BEGIN IMMEDIATE takes the write lock up front, so two callers racing
        for the same slot are serialised rather than both reading 'free'."""
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        else:
            self._conn.execute("COMMIT")

    def _seed(self, clinic: Dict[str, Any]) -> None:
        cur = self._conn
        for doctor in clinic["doctors"]:
            cur.execute(
                "INSERT INTO doctors (id, name, speciality) VALUES (?, ?, ?)",
                (doctor["id"], doctor["name"], doctor["speciality"]),
            )
            for window in doctor.get("windows", []):
                cur.execute(
                    "INSERT INTO doctor_windows (doctor_id, day, start, end)"
                    " VALUES (?, ?, ?, ?)",
                    (doctor["id"], window["day"], window["start"], window["end"]),
                )
            for leave_date in doctor.get("leave_dates", []):
                cur.execute(
                    "INSERT INTO doctor_leave (doctor_id, date) VALUES (?, ?)",
                    (doctor["id"], leave_date),
                )

        for holiday in clinic.get("holidays", []):
            cur.execute("INSERT INTO holidays (date) VALUES (?)", (holiday,))

        for patient in clinic["patients"]:
            cur.execute(
                "INSERT INTO patients (id, name, phone, dob) VALUES (?, ?, ?, ?)",
                (patient["id"], patient["name"], patient["phone"], patient["dob"]),
            )
        # second pass: guardianships reference patients that must already exist
        for patient in clinic["patients"]:
            for ward_id in patient.get("guardian_of", []):
                cur.execute(
                    "INSERT INTO guardianships (guardian_id, ward_id) VALUES (?, ?)",
                    (patient["id"], ward_id),
                )

        for appointment in clinic["appointments"]:
            cur.execute(
                "INSERT INTO appointments"
                " (id, patient_id, doctor_id, date, start, end, status)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    appointment["id"],
                    appointment["patient_id"],
                    appointment["doctor_id"],
                    appointment["date"],
                    appointment["start"],
                    appointment["end"],
                    appointment["status"],
                ),
            )

    # -- reads -------------------------------------------------------------

    def get_doctor(self, doctor_id: str) -> Optional[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM doctors WHERE id = ?", (doctor_id,)
        ).fetchone()

    def all_doctors(self) -> List[sqlite3.Row]:
        return self._conn.execute("SELECT * FROM doctors ORDER BY id").fetchall()

    def windows_for(self, doctor_id: str, day: str) -> List[Tuple[str, str]]:
        rows = self._conn.execute(
            "SELECT start, end FROM doctor_windows WHERE doctor_id = ? AND day = ?"
            " ORDER BY start",
            (doctor_id, day),
        ).fetchall()
        return [(row["start"], row["end"]) for row in rows]

    def is_holiday(self, on_date: str) -> bool:
        return (
            self._conn.execute(
                "SELECT 1 FROM holidays WHERE date = ?", (on_date,)
            ).fetchone()
            is not None
        )

    def is_on_leave(self, doctor_id: str, on_date: str) -> bool:
        return (
            self._conn.execute(
                "SELECT 1 FROM doctor_leave WHERE doctor_id = ? AND date = ?",
                (doctor_id, on_date),
            ).fetchone()
            is not None
        )

    def get_patient(self, patient_id: str) -> Optional[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM patients WHERE id = ?", (patient_id,)
        ).fetchone()

    def all_patients(self) -> List[Dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM patients ORDER BY id").fetchall()
        return [dict(row) for row in rows]

    def patients_by_phone(self, phone: str) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM patients WHERE phone = ? ORDER BY id", (phone,)
        ).fetchall()
        return [dict(row) for row in rows]

    def ward_ids(self, guardian_id: str) -> List[str]:
        rows = self._conn.execute(
            "SELECT ward_id FROM guardianships WHERE guardian_id = ? ORDER BY ward_id",
            (guardian_id,),
        ).fetchall()
        return [row["ward_id"] for row in rows]

    def guardian_ids(self, ward_id: str) -> List[str]:
        rows = self._conn.execute(
            "SELECT guardian_id FROM guardianships WHERE ward_id = ?"
            " ORDER BY guardian_id",
            (ward_id,),
        ).fetchall()
        return [row["guardian_id"] for row in rows]

    def is_guardian_of(self, guardian_id: str, ward_id: str) -> bool:
        return (
            self._conn.execute(
                "SELECT 1 FROM guardianships WHERE guardian_id = ? AND ward_id = ?",
                (guardian_id, ward_id),
            ).fetchone()
            is not None
        )

    def booked_starts(
        self, doctor_id: str, on_date: str, exclude_appointment_id: Optional[str] = None
    ) -> Set[str]:
        sql = (
            "SELECT start FROM appointments"
            " WHERE doctor_id = ? AND date = ? AND status = 'booked'"
        )
        params: List[Any] = [doctor_id, on_date]
        if exclude_appointment_id:
            sql += " AND id != ?"
            params.append(exclude_appointment_id)
        return {row["start"] for row in self._conn.execute(sql, params).fetchall()}

    def get_appointment(self, appointment_id: str) -> Optional[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM appointments WHERE id = ?", (appointment_id,)
        ).fetchone()

    def appointments_for_patient(
        self, patient_id: str, active_only: bool = True
    ) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM appointments WHERE patient_id = ?"
        params: List[Any] = [patient_id]
        if active_only:
            sql += " AND status = 'booked'"
        sql += " ORDER BY date, start"
        return [dict(row) for row in self._conn.execute(sql, params).fetchall()]

    # -- writes ------------------------------------------------------------

    def next_appointment_id(self) -> str:
        row = self._conn.execute(
            "SELECT id FROM appointments ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return "ap_0001"
        return "ap_{:04d}".format(int(row["id"].split("_")[1]) + 1)

    def insert_appointment(
        self,
        patient_id: str,
        doctor_id: str,
        on_date: str,
        start: str,
        end: str,
    ) -> str:
        """Raises sqlite3.IntegrityError if the slot is already taken."""
        appointment_id = self.next_appointment_id()
        self._conn.execute(
            "INSERT INTO appointments"
            " (id, patient_id, doctor_id, date, start, end, status)"
            " VALUES (?, ?, ?, ?, ?, ?, 'booked')",
            (appointment_id, patient_id, doctor_id, on_date, start, end),
        )
        return appointment_id

    def move_appointment(
        self, appointment_id: str, on_date: str, start: str, end: str
    ) -> None:
        """Raises sqlite3.IntegrityError if the target slot is taken."""
        self._conn.execute(
            "UPDATE appointments SET date = ?, start = ?, end = ? WHERE id = ?",
            (on_date, start, end, appointment_id),
        )

    def set_cancelled(self, appointment_id: str) -> None:
        self._conn.execute(
            "UPDATE appointments SET status = 'cancelled' WHERE id = ?",
            (appointment_id,),
        )