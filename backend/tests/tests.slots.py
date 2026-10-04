import pytest

from app.errors import INVALID_ARGUMENTS, INVALID_DATE, INVALID_TIME, ToolError
from app.slots import (build_grid, filter_by_part_of_day, parse_date, parse_hhmm,
                       part_of_day_bounds, shift_days, to_hhmm, weekday_of)


def test_overlapping_monday_windows_collapse(store):
    """09:00-12:00 and 11:45-15:00 share 11:45. Per-window iteration gives 25."""
    grid = build_grid(store.windows_for("dr_rao", "Mon"), 15)
    assert len(grid) == 24
    assert len(grid) == len(set(grid))
    assert to_hhmm(grid[0]) == "09:00" and to_hhmm(grid[-1]) == "14:45"


def test_rao_has_no_monday_evening(store):
    """A consequence of the overlap: the second window ends at 15:00."""
    grid = [to_hhmm(m) for m in build_grid(store.windows_for("dr_rao", "Mon"), 15)]
    assert not [s for s in grid if s >= "16:00"]


def test_days_with_one_window_or_none(store):
    assert len(store.windows_for("dr_rao", "Sat")) == 1
    assert len(store.windows_for("dr_sethi", "Wed")) == 1
    assert store.windows_for("dr_rao", "Sun") == []
    assert store.windows_for("dr_sethi", "Sun") == []


def test_relative_dates_resolve_against_the_given_day():
    assert weekday_of("2026-10-01") == "Thu"
    assert shift_days("2026-10-01", 1) == "2026-10-02"   # kal
    assert shift_days("2026-10-01", 2) == "2026-10-03"   # parso


@pytest.mark.parametrize("bad", ["01-10-2026", "2026-13-01", "2026-10-32", "", "kal"])
def test_bad_dates_are_named_errors(bad):
    with pytest.raises(ToolError) as caught:
        parse_date(bad)
    assert caught.value.code == INVALID_DATE


@pytest.mark.parametrize("bad", ["9:30", "25:00", "09:60", "0930", ""])
def test_bad_times_are_named_errors(bad):
    with pytest.raises(ToolError) as caught:
        parse_hhmm(bad)
    assert caught.value.code == INVALID_TIME


def test_part_of_day():
    assert part_of_day_bounds("morning") == (0, 720)
    assert filter_by_part_of_day(["09:00", "13:00", "17:00"], "morning") == ["09:00"]
    assert filter_by_part_of_day(["09:00", "13:00", "17:00"], "evening") == ["17:00"]
    with pytest.raises(ToolError) as caught:
        part_of_day_bounds("raat")
    assert caught.value.code == INVALID_ARGUMENTS