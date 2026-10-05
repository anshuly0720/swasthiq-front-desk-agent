"""The starter README is explicit: use datetime.now() in date handling and the
submission starts failing the day after it is written.

Scoped to the modules that resolve dates and act on the clinic. ui_store.py is
excluded on purpose and by name: it timestamps conversation log entries, which
is a record of when a call actually happened in the real world, not a date
derived from the caller's words. Excluding the whole file rather than silencing
the rule keeps the guard meaningful everywhere it matters.
"""

from pathlib import Path

BANNED = ("datetime.now(", "date.today(", "datetime.today(", "utcnow(", "time.time(")

APP = Path(__file__).resolve().parents[1] / "app"
ALLOWED = {"ui_store.py"}


def test_no_module_reads_the_system_clock():
    offenders = []
    for path in sorted(APP.rglob("*.py")):
        if path.name in ALLOWED:
            continue
        text = path.read_text(encoding="utf-8")
        for token in BANNED:
            if token in text:
                offenders.append("{}: {}".format(path.name, token))
    assert not offenders, "date handling must use the request's `today`: " + \
        ", ".join(offenders)


def test_the_agent_and_tool_layers_are_covered_by_that_guard():
    """A guard that excludes everything proves nothing."""
    checked = [p.name for p in APP.rglob("*.py")
               if p.name not in ALLOWED and p.stat().st_size > 0]
    for required in ("dates.py", "slots.py", "policy.py", "registry.py", "store.py"):
        assert required in checked, required
