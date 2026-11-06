"""Core data model shared by every parser, check and report.

A construction schedule is a network: *activities* (work, milestones, hammocks)
joined by *relationships* (finish-to-start, start-to-start, ...). Every input
format (Primavera P6 XER, Microsoft Project XML, CSV) is converted into this
one model so the checks never need to know where the data came from.

All durations, lags and float values are stored in **working days**.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from .calendar import WorkCalendar


class ActivityType(str, Enum):
    TASK = "task"
    START_MILESTONE = "start_milestone"
    FINISH_MILESTONE = "finish_milestone"
    LOE = "level_of_effort"  # hammock: duration derived from other activities
    SUMMARY = "summary"  # WBS / outline summary bar


class Status(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"


class RelType(str, Enum):
    FS = "FS"  # finish-to-start
    SS = "SS"  # start-to-start
    FF = "FF"  # finish-to-finish
    SF = "SF"  # start-to-finish


class ConstraintType(str, Enum):
    NONE = "none"
    START_ON = "start_on"
    START_ON_OR_AFTER = "start_on_or_after"  # "Start No Earlier Than"
    START_ON_OR_BEFORE = "start_on_or_before"  # "Start No Later Than"
    FINISH_ON = "finish_on"
    FINISH_ON_OR_AFTER = "finish_on_or_after"  # "Finish No Earlier Than"
    FINISH_ON_OR_BEFORE = "finish_on_or_before"  # "Finish No Later Than"
    MANDATORY_START = "mandatory_start"  # overrides logic
    MANDATORY_FINISH = "mandatory_finish"  # overrides logic
    AS_LATE_AS_POSSIBLE = "as_late_as_possible"


# DCMA treats constraints that stop the dates from moving with the logic as
# "hard". Soft constraints (start/finish on or after, ALAP) are only flagged
# by the Lean "push planning" check.
HARD_CONSTRAINTS = frozenset(
    {
        ConstraintType.START_ON,
        ConstraintType.START_ON_OR_BEFORE,
        ConstraintType.FINISH_ON,
        ConstraintType.FINISH_ON_OR_BEFORE,
        ConstraintType.MANDATORY_START,
        ConstraintType.MANDATORY_FINISH,
    }
)

CONSTRAINT_LABELS = {
    ConstraintType.NONE: "",
    ConstraintType.START_ON: "Start On",
    ConstraintType.START_ON_OR_AFTER: "Start On or After",
    ConstraintType.START_ON_OR_BEFORE: "Start On or Before",
    ConstraintType.FINISH_ON: "Finish On",
    ConstraintType.FINISH_ON_OR_AFTER: "Finish On or After",
    ConstraintType.FINISH_ON_OR_BEFORE: "Finish On or Before",
    ConstraintType.MANDATORY_START: "Mandatory Start",
    ConstraintType.MANDATORY_FINISH: "Mandatory Finish",
    ConstraintType.AS_LATE_AS_POSSIBLE: "As Late As Possible",
}

TYPE_LABELS = {
    ActivityType.TASK: "Task",
    ActivityType.START_MILESTONE: "Start milestone",
    ActivityType.FINISH_MILESTONE: "Finish milestone",
    ActivityType.LOE: "Level of effort",
    ActivityType.SUMMARY: "Summary",
}

STATUS_LABELS = {
    Status.NOT_STARTED: "Not started",
    Status.IN_PROGRESS: "In progress",
    Status.COMPLETE: "Complete",
}


@dataclass
class Activity:
    """One schedule activity. Dates are as exported by the source tool."""

    uid: str  # internal unique key (P6 task_id, MS Project UID, CSV id)
    code: str  # the activity ID people recognise (P6 Activity ID, MSP ID)
    name: str
    type: ActivityType = ActivityType.TASK
    status: Status = Status.NOT_STARTED
    duration: float = 0.0  # original / planned duration
    remaining: float | None = None  # remaining duration (None = not supplied)
    percent_complete: float | None = None
    early_start: datetime | None = None
    early_finish: datetime | None = None
    late_start: datetime | None = None
    late_finish: datetime | None = None
    actual_start: datetime | None = None
    actual_finish: datetime | None = None
    baseline_start: datetime | None = None
    baseline_finish: datetime | None = None
    baseline_duration: float | None = None
    total_float: float | None = None  # as exported by the scheduling tool
    free_float: float | None = None
    constraint: ConstraintType = ConstraintType.NONE
    constraint_date: datetime | None = None
    constraint2: ConstraintType = ConstraintType.NONE
    constraint2_date: datetime | None = None
    deadline: datetime | None = None  # MS Project deadline: limits late finish only
    calendar: str = ""
    calendar_days_per_week: int | None = None
    wbs: str = ""
    codes: dict[str, str] = field(default_factory=dict)
    resources: list[str] = field(default_factory=list)
    trade: str | None = None  # resolved by lean.mapping
    location: str | None = None  # resolved by lean.mapping

    # -- convenience -------------------------------------------------------
    @property
    def is_milestone(self) -> bool:
        return self.type in (ActivityType.START_MILESTONE, ActivityType.FINISH_MILESTONE)

    @property
    def is_task(self) -> bool:
        return self.type == ActivityType.TASK

    @property
    def in_network(self) -> bool:
        """LOE and summary bars are excluded from the critical path network."""
        return self.type not in (ActivityType.LOE, ActivityType.SUMMARY)

    @property
    def is_complete(self) -> bool:
        return self.status == Status.COMPLETE

    @property
    def is_started(self) -> bool:
        return self.status != Status.NOT_STARTED

    @property
    def remaining_duration(self) -> float:
        if self.is_complete:
            return 0.0
        if self.remaining is not None:
            return max(0.0, self.remaining)
        return max(0.0, self.duration)

    @property
    def start(self) -> datetime | None:
        """Actual start if started, otherwise the forecast (early) start."""
        return self.actual_start or self.early_start

    @property
    def finish(self) -> datetime | None:
        """Actual finish if complete, otherwise the forecast (early) finish."""
        if self.is_complete:
            return self.actual_finish or self.early_finish
        return self.early_finish

    @property
    def constraints(self) -> list[tuple[ConstraintType, datetime | None]]:
        out = []
        if self.constraint != ConstraintType.NONE:
            out.append((self.constraint, self.constraint_date))
        if self.constraint2 != ConstraintType.NONE:
            out.append((self.constraint2, self.constraint2_date))
        return out

    @property
    def has_hard_constraint(self) -> bool:
        return any(c in HARD_CONSTRAINTS for c, _ in self.constraints)


@dataclass
class Relationship:
    pred: str  # predecessor uid
    succ: str  # successor uid
    type: RelType = RelType.FS
    lag: float = 0.0  # working days; negative = lead


@dataclass
class Schedule:
    """A parsed project schedule, independent of the source format."""

    name: str
    data_date: datetime
    activities: dict[str, Activity]
    relationships: list[Relationship]
    source_format: str  # "xer" | "mspdi" | "csv"
    source_name: str = ""
    project_code: str = ""
    calendar: WorkCalendar = field(default_factory=WorkCalendar)
    planned_start: datetime | None = None
    deadline: datetime | None = None  # "must finish by"
    scheduled_finish: datetime | None = None  # finish reported by the tool
    critical_float: float = 0.0  # float at or below which work is critical
    baseline_source: str | None = None
    code_fields: list[str] = field(default_factory=list)
    other_projects: list[str] = field(default_factory=list)
    external_links: int = 0
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._preds: dict[str, list[Relationship]] | None = None
        self._succs: dict[str, list[Relationship]] | None = None

    def _index(self) -> None:
        preds: dict[str, list[Relationship]] = {uid: [] for uid in self.activities}
        succs: dict[str, list[Relationship]] = {uid: [] for uid in self.activities}
        for rel in self.relationships:
            if rel.pred in succs and rel.succ in preds:
                succs[rel.pred].append(rel)
                preds[rel.succ].append(rel)
        self._preds, self._succs = preds, succs

    def predecessors(self, uid: str) -> list[Relationship]:
        if self._preds is None:
            self._index()
        assert self._preds is not None
        return self._preds.get(uid, [])

    def successors(self, uid: str) -> list[Relationship]:
        if self._succs is None:
            self._index()
        assert self._succs is not None
        return self._succs.get(uid, [])

    def invalidate(self) -> None:
        """Call after editing ``relationships`` so the indexes are rebuilt."""
        self._preds = self._succs = None

    @property
    def has_baseline(self) -> bool:
        return any(a.baseline_finish for a in self.activities.values())

    @property
    def has_resources(self) -> bool:
        return any(a.resources for a in self.activities.values())
