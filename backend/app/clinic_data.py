"""Loads clinic.json. The only place that touches the file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

# backend/app/clinic_data.py -> backend/data/clinic.json
DEFAULT_CLINIC_PATH = Path(__file__).resolve().parent.parent / "data" / "clinic.json"

_REQUIRED_TOP_LEVEL = ("clinic", "doctors", "holidays", "patients", "appointments")


def load_clinic(path: Optional[Path] = None) -> Dict[str, Any]:
    """Read clinic.json into a plain dict, with a readable error if it is wrong.

    Called once per POST /agent/run. The file is ~13 KB, so re-reading it per
    request is cheaper than reasoning about shared mutable state — and the
    starter README requires each run to start from the file as shipped.
    """
    target = Path(path) if path is not None else DEFAULT_CLINIC_PATH
    if not target.is_file():
        raise FileNotFoundError(
            "clinic.json not found at {}. Copy it from the starter pack into "
            "backend/data/.".format(target)
        )

    with target.open(encoding="utf-8") as handle:
        data = json.load(handle)

    missing = [key for key in _REQUIRED_TOP_LEVEL if key not in data]
    if missing:
        raise ValueError(
            "clinic.json is missing top-level keys: {}".format(", ".join(missing))
        )
    return data