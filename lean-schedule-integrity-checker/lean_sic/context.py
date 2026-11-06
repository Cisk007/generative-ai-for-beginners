"""Analysis context shared by all checks (schedule + CPM + settings)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import cached_property

from .cpm import EPS, CpmResult
from .model import Activity, Relationship, Schedule
from .settings import Settings


@dataclass
class Context:
    schedule: Schedule
    cpm: CpmResult
    settings: Settings
    float_days: dict[str, float] = field(default_factory=dict)
    float_source: str = ""
    exempt_open_start: str | None = None
    exempt_open_finish: str | None = None

    @property
    def data_date(self) -> datetime:
        return self.schedule.data_date

    @cached_property
    def network(self) -> list[Activity]:
        return [a for a in self.schedule.activities.values() if a.in_network]

    @cached_property
    def incomplete(self) -> list[Activity]:
        """Tasks and milestones that still have work left (DCMA population)."""
        return [a for a in self.network if not a.is_complete]

    @cached_property
    def incomplete_tasks(self) -> list[Activity]:
        return [a for a in self.incomplete if a.is_task]

    def network_preds(self, uid: str) -> list[Relationship]:
        acts = self.schedule.activities
        return [r for r in self.schedule.predecessors(uid) if acts[r.pred].in_network]

    def network_succs(self, uid: str) -> list[Relationship]:
        acts = self.schedule.activities
        return [r for r in self.schedule.successors(uid) if acts[r.succ].in_network]

    def is_critical(self, uid: str) -> bool:
        value = self.float_days.get(uid)
        return value is not None and value <= self.schedule.critical_float + EPS

    @property
    def lookahead_end(self) -> datetime:
        return self.data_date + timedelta(weeks=self.settings.lookahead_weeks)

    def in_window(self, act: Activity, weeks: float) -> bool:
        """Incomplete work that is under way or starts within ``weeks``."""
        if act.is_complete:
            return False
        if act.is_started:
            return True
        start = act.start
        return start is not None and start < self.data_date + timedelta(weeks=weeks)

    def day_index(self, moment: datetime) -> int:
        """Working-day number of a date, counted from the data date."""
        return self.schedule.calendar.count(self.data_date.date(), moment.date())
