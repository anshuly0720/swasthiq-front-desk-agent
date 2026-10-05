"""Conversation log behind the two screens.

Deliberately a separate database from the clinic. Clinic state resets to
clinic.json on every POST /agent/run, because the starter README requires it;
the handoff queue has to survive that reset or the front desk would lose its
queue every call. Nothing here is ever read back into a tool.
"""

from __future__ import annotations

import json
import pathlib
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

DB_PATH = pathlib.Path(__file__).resolve().parent.parent / "data" / "conversations.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id  TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    today            TEXT,
    turns            TEXT NOT NULL,
    tool_calls       TEXT NOT NULL,
    terminal_state   TEXT NOT NULL,
    escalation_reason TEXT,
    patient_id       TEXT,
    appointment_id   TEXT,
    reply            TEXT,
    metrics          TEXT,
    trigger_turn     TEXT,
    fingerprint      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_runs_conversation ON runs(conversation_id, id);

CREATE TABLE IF NOT EXISTS handoffs (
    conversation_id  TEXT PRIMARY KEY,
    resolved         INTEGER NOT NULL DEFAULT 0,
    resolved_at      TEXT
);
"""


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def fingerprint(terminal_state: str, escalation_reason: Optional[str],
                tool_calls: List[Dict[str, Any]]) -> str:
    names = sorted({call["name"] for call in tool_calls})
    return "{}/{}/{}".format(terminal_state, escalation_reason, ",".join(names))


def record(conversation_id: str, today: str, turns: List[str], response: Dict[str, Any],
           trigger_turn: Optional[str]) -> None:
    conn = _connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO runs (conversation_id, created_at, today, turns, tool_calls,"
                " terminal_state, escalation_reason, patient_id, appointment_id, reply,"
                " metrics, trigger_turn, fingerprint)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (conversation_id,
                 datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 today,
                 json.dumps(turns, ensure_ascii=False),
                 json.dumps(response["tool_calls"], ensure_ascii=False),
                 response["terminal_state"], response["escalation_reason"],
                 response["patient_id"], response["appointment_id"], response["reply"],
                 json.dumps(response.get("metrics", {}), ensure_ascii=False),
                 trigger_turn,
                 fingerprint(response["terminal_state"], response["escalation_reason"],
                             response["tool_calls"])))
            if response["terminal_state"] == "escalated":
                conn.execute(
                    "INSERT OR IGNORE INTO handoffs (conversation_id, resolved)"
                    " VALUES (?, 0)", (conversation_id,))
    finally:
        conn.close()


def _latest_per_conversation(conn) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT r.* FROM runs r"
        " JOIN (SELECT conversation_id, MAX(id) AS top FROM runs GROUP BY conversation_id) m"
        "   ON r.id = m.top"
        " ORDER BY r.id DESC").fetchall()


def stats() -> Dict[str, Any]:
    conn = _connect()
    try:
        latest = _latest_per_conversation(conn)
        resolved = {row["conversation_id"] for row in conn.execute(
            "SELECT conversation_id FROM handoffs WHERE resolved = 1").fetchall()}

        total = len(latest)
        escalated = [r for r in latest if r["terminal_state"] == "escalated"]
        # Everything the agent finished without a human: booked, rescheduled,
        # cancelled, refused and abandoned all count. 31 of 37 is 84% in the
        # mockup, which only works if abandoned counts as completed.
        completed = total - len(escalated)
        still_open = [r for r in escalated if r["conversation_id"] not in resolved]
        urgent = [r for r in still_open if r["escalation_reason"] == "clinical_urgent"]
        return {
            "conversations": total,
            "completed": completed,
            "completed_pct": round(100 * completed / total) if total else 0,
            "escalated": len(escalated),
            "open": len(still_open),
            "urgent": len(urgent),
        }
    finally:
        conn.close()


def handoffs(include_resolved: bool = False) -> List[Dict[str, Any]]:
    conn = _connect()
    try:
        resolved = {row["conversation_id"] for row in conn.execute(
            "SELECT conversation_id FROM handoffs WHERE resolved = 1").fetchall()}
        out = []
        for row in _latest_per_conversation(conn):
            if row["terminal_state"] != "escalated":
                continue
            is_resolved = row["conversation_id"] in resolved
            if is_resolved and not include_resolved:
                continue
            turns = json.loads(row["turns"])
            out.append({
                "conversation_id": row["conversation_id"],
                "caller_said": row["trigger_turn"] or (turns[-1] if turns else ""),
                "reason": row["escalation_reason"],
                "at": row["created_at"],
                "resolved": is_resolved,
            })
        return out
    finally:
        conn.close()


def conversation(conversation_id: str) -> Optional[Dict[str, Any]]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM runs WHERE conversation_id = ? ORDER BY id",
            (conversation_id,)).fetchall()
        if not rows:
            return None
        latest = rows[-1]
        prints = {row["fingerprint"] for row in rows}
        resolved = conn.execute(
            "SELECT resolved FROM handoffs WHERE conversation_id = ?",
            (conversation_id,)).fetchone()
        return {
            "conversation_id": conversation_id,
            "at": latest["created_at"],
            "today": latest["today"],
            "turns": json.loads(latest["turns"]),
            "tool_calls": json.loads(latest["tool_calls"]),
            "terminal_state": latest["terminal_state"],
            "escalation_reason": latest["escalation_reason"],
            "patient_id": latest["patient_id"],
            "appointment_id": latest["appointment_id"],
            "reply": latest["reply"],
            "metrics": json.loads(latest["metrics"] or "{}"),
            "resolved": bool(resolved["resolved"]) if resolved else None,
            "runs": len(rows),
            # The visual proof of the determinism requirement: one fingerprint
            # across every recorded run means the same terminal state every time.
            "stable": len(prints) == 1,
            "fingerprints": sorted(prints),
        }
    finally:
        conn.close()


def resolve(conversation_id: str) -> bool:
    conn = _connect()
    try:
        with conn:
            changed = conn.execute(
                "UPDATE handoffs SET resolved = 1, resolved_at = ?"
                " WHERE conversation_id = ? AND resolved = 0",
                (datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 conversation_id)).rowcount
        return changed > 0
    finally:
        conn.close()
