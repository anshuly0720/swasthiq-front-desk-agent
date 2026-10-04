import pytest

from app.matching import find_by_name, name_matches, normalise_phone, tokens


def ids(query, patients):
    return sorted(p["id"] for p in find_by_name(query, patients))


def test_surname_alone_returns_every_sharma(store):
    assert ids("Sharma", store.all_patients()) == ["pt_0001", "pt_0002", "pt_0003"]


def test_honorific_is_ignored(store):
    """cv_0007 says 'Sharma ji'."""
    assert ids("Sharma ji", store.all_patients()) == ["pt_0001", "pt_0002", "pt_0003"]


@pytest.mark.parametrize("query", ["Rajesh Kumar Sharma", "Rajesh Sharma", "R K Sharma"])
def test_abbreviated_and_expanded_names_reach_each_other(query, store):
    """Three records for what may be one person. Name alone cannot separate them;
    cv_0003 says the phone number is what does."""
    assert ids(query, store.all_patients()) == ["pt_0001", "pt_0002", "pt_0003"]


def test_sound_alike_names_are_different_people_and_both_come_back(store):
    assert ids("Imran Qureshi", store.all_patients()) == ["pt_0010", "pt_0011"]
    assert ids("Imraan Quraishi", store.all_patients()) == ["pt_0010", "pt_0011"]


def test_first_name_separates_the_identical_children(store):
    """Aarav and Arjun share a surname, a birthday and a phone number."""
    assert ids("Aarav", store.all_patients()) == ["pt_0006"]
    assert ids("Arjun", store.all_patients()) == ["pt_0007"]


def test_full_name_disambiguates_where_a_first_name_does_not(store):
    assert ids("Priya", store.all_patients()) == ["pt_0004", "pt_0005"]
    assert ids("Priya Nair", store.all_patients()) == ["pt_0004"]
    assert ids("Harpreet", store.all_patients()) == ["pt_0013", "pt_0014"]
    assert ids("Harpreet Singh", store.all_patients()) == ["pt_0013"]


@pytest.mark.parametrize("query", ["K", "R", "R. K.", "ji", "", "Zzz Qqq"])
def test_an_initial_alone_resolves_nobody(query, store):
    """Without this, 'K' resolves to 'R. K. Sharma' and the agent books a
    confidently wrong patient."""
    assert ids(query, store.all_patients()) == []


def test_every_patient_finds_themselves(store):
    patients = store.all_patients()
    for patient in patients:
        assert patient["id"] in ids(patient["name"], patients), patient["name"]


def test_phone_normalisation():
    assert normalise_phone("+91 98122 00011") == "9812200011"
    assert normalise_phone("09812200011") == "9812200011"
    assert normalise_phone("9812200011") == "9812200011"


def test_tokens_strip_punctuation():
    assert tokens("R. K. Sharma") == ["r", "k", "sharma"]