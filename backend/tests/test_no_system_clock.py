"""The starter README is explicit: use datetime.now() in date handling and the
submission starts failing the day after it is written."""

from pathlib import Path

BANNED = ("datetime.now(", "date.today(", "datetime.today(", "utcnow(", "time.time(")

APP = Path(__file__).resolve().parents[1] / "app"


def test_no_module_reads_the_system_clock():
    offenders = []
    for path in sorted(APP.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for token in BANNED:
            if token in text:
                offenders.append("{}: {}".format(path.name, token))
    assert not offenders, "date handling must use the request's `today`: " + \
        ", ".join(offenders)