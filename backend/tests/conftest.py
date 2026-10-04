import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.clinic_data import load_clinic          # noqa: E402
from app.store import ClinicStore                # noqa: E402
from app.tools.registry import ToolLayer         # noqa: E402

TODAY = "2026-10-01"


@pytest.fixture
def clinic():
    return load_clinic()


@pytest.fixture
def store(clinic):
    s = ClinicStore(clinic)
    yield s
    s.close()


@pytest.fixture
def tools(store):
    return ToolLayer(store, today=TODAY)