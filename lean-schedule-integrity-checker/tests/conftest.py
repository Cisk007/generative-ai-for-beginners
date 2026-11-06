"""Shared helpers for the Lean Schedule Integrity Checker tests."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

TOOL_ROOT = Path(__file__).resolve().parent.parent
if str(TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOL_ROOT))

from lean_sic.calendar import WorkCalendar  # noqa: E402
from lean_sic.model import Activity, ActivityType, Relationship, RelType, Schedule  # noqa: E402

SAMPLES = TOOL_ROOT / "samples"
DATA_DATE = datetime(2026, 3, 2, 8)  # a Monday


def make_schedule(acts: list[Activity], rels: list[tuple], **kwargs) -> Schedule:
    """Build a schedule from activities and (pred, succ[, type[, lag]]) tuples."""
    relationships = []
    for rel in rels:
        pred, succ, kind, lag = (list(rel) + ["FS", 0.0][len(rel) - 2 :])[:4]
        relationships.append(Relationship(pred, succ, RelType(kind), float(lag)))
    kwargs.setdefault("calendar", WorkCalendar())
    return Schedule(
        "Test project",
        kwargs.pop("data_date", DATA_DATE),
        {a.uid: a for a in acts},
        relationships,
        "test",
        **kwargs,
    )


def task(uid: str, duration: float, **kwargs) -> Activity:
    return Activity(uid=uid, code=uid, name=f"Task {uid}", duration=duration, **kwargs)


def milestone(uid: str, start: bool = False, **kwargs) -> Activity:
    kind = ActivityType.START_MILESTONE if start else ActivityType.FINISH_MILESTONE
    return Activity(uid=uid, code=uid, name=f"Milestone {uid}", type=kind, **kwargs)


@pytest.fixture
def samples() -> Path:
    return SAMPLES
