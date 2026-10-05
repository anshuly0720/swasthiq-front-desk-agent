import pytest

from app.agent.dates import detect_part_of_day, resolve_date, resolve_time

TODAY = "2026-10-01"          # a Thursday


@pytest.mark.parametrize("phrase,expected", [
    ("aaj", "2026-10-01"),
    ("kal", "2026-10-02"),
    ("parso", "2026-10-03"),            # cv_0012
    ("shanivaar", "2026-10-03"),
    ("3 tareekh", "2026-10-03"),        # cv_0001
    ("Shanivaar subah, 3 tareekh", "2026-10-03"),
    ("mangalwar 6 tareekh", "2026-10-06"),
    ("budhwar, 7 tareekh", "2026-10-07"),   # cv_0002, after the correction
    ("somwar 5 tareekh", "2026-10-05"),     # cv_0006
    ("8 tareekh", "2026-10-08"),            # cv_0015
    ("Sunday, 4 tareekh", "2026-10-04"),    # cv_0005
    ("2026-10-10", "2026-10-10"),
])
def test_date_phrases(phrase, expected):
    assert resolve_date(phrase, TODAY)["date"] == expected


def test_day_number_rolls_into_next_month():
    """Said on 1 October, "30 tareekh" is this month; "1 tareekh" is November."""
    assert resolve_date("30 tareekh", TODAY)["date"] == "2026-10-30"
    assert resolve_date("1 tareekh", TODAY)["date"] == "2026-10-01"
    assert resolve_date("1 tareekh", "2026-10-02")["date"] == "2026-11-01"


def test_weekday_contradicting_the_date_is_reported_not_guessed():
    out = resolve_date("shukravar 3 tareekh", TODAY)
    assert out["date"] == "2026-10-03"      # the number wins
    assert out["conflict"] is not None      # and the disagreement is visible


def test_nothing_resolvable():
    assert resolve_date("jaldi", TODAY) is None
    assert resolve_date("", TODAY) is None


@pytest.mark.parametrize("phrase,expected", [
    ("gyarah baje", "11:00"),           # cv_0012
    ("subah 10 baje", "10:00"),         # cv_0003
    ("9:30", "09:30"),
    ("subah 9:30", "09:30"),
    ("saadhe das", "10:30"),
    ("sawa gyarah", "11:15"),
    ("paune gyarah", "10:45"),
    ("das baje subah", "10:00"),
])
def test_time_phrases(phrase, expected):
    assert resolve_time(phrase) == expected


def test_evening_hours_shift():
    assert resolve_time("shaam 5 baje") == "17:00"
    assert resolve_time("5 baje") == "17:00"        # clinic hours make this evening
    assert resolve_time("subah 9 baje") == "09:00"


def test_part_of_day():
    assert detect_part_of_day("Subah ka time theek rahega") == "morning"
    assert detect_part_of_day("8 tareekh ko shaam ko") == "evening"
    assert detect_part_of_day("koi bhi time chalega") is None



@pytest.mark.parametrize("phrase,expected", [
    ("३ तारीख", "2026-10-03"),
    ("8 तारीख", "2026-10-08"),
    ("कल", "2026-10-02"),
    ("परसों", "2026-10-03"),
    ("शनिवार", "2026-10-03"),
    ("आज", "2026-10-01"),
    ("बुधवार, 7 तारीख", "2026-10-07"),
])
def test_devanagari_dates(phrase, expected):
    """Devanagari digits are folded to ASCII, so the numeric rules work once."""
    assert resolve_date(phrase, TODAY)["date"] == expected


def test_devanagari_part_of_day():
    assert detect_part_of_day("सुबह को") == "morning"
    assert detect_part_of_day("शाम को") == "evening"
