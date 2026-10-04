"""Two conversations racing for the same slot must not both succeed.

Each thread opens its own connection to one on-disk database, which is the only
honest way to test this — a single shared connection would prove nothing about
concurrency.
"""

import threading

from app.clinic_data import load_clinic
from app.store import ClinicStore
from app.tools.registry import ToolLayer

THREADS = 20
SLOT = {"doctor_id": "dr_rao", "date": "2026-10-03", "start": "09:00"}
PATIENTS = ["pt_{:04d}".format(n) for n in range(5, 5 + THREADS)]


def test_only_one_of_twenty_callers_gets_the_slot(tmp_path):
    db_path = str(tmp_path / "clinic.db")
    seeder = ClinicStore(load_clinic(), db_path=db_path)

    results = []
    guard = threading.Lock()
    start_together = threading.Barrier(THREADS)

    def attempt(patient_id):
        store = ClinicStore(db_path=db_path, seed=False)
        try:
            tools = ToolLayer(store, today="2026-10-01")
            start_together.wait()          # maximise the overlap
            outcome = tools.call("book_appointment", dict(SLOT, patient_id=patient_id))
            with guard:
                results.append(outcome)
        finally:
            store.close()

    threads = [threading.Thread(target=attempt, args=(p,)) for p in PATIENTS]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(results) == THREADS
    winners = [r for r in results if r["ok"]]
    assert len(winners) == 1, "{} callers got the same slot".format(len(winners))
    assert all(r["error"]["code"] == "SLOT_TAKEN" for r in results if not r["ok"])

    rows = [a for a in seeder.appointments_for_patient(winners[0]["data"]["appointment"]
                                                       ["patient_id"])
            if a["date"] == SLOT["date"] and a["start"] == SLOT["start"]]
    assert len(rows) == 1
    seeder.close()


def test_state_does_not_leak_between_runs():
    """Each POST /agent/run starts from clinic.json as shipped."""
    first = ClinicStore(load_clinic())
    tools = ToolLayer(first, today="2026-10-01")
    assert tools.call("book_appointment", dict(SLOT, patient_id="pt_0005"))["ok"]

    second = ClinicStore(load_clinic())
    assert "09:00" in ToolLayer(second, today="2026-10-01").call(
        "search_slots", {"doctor_id": "dr_rao", "date": "2026-10-03"})["data"]["slots"]
    first.close()
    second.close()