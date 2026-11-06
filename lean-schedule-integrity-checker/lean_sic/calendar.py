"""Working-day calendar arithmetic.

Schedules are measured in *working days*, not calendar days. This module
counts and steps working days for a weekly pattern (e.g. Monday to Friday)
plus a list of holidays. The critical path engine works in "working-day
offsets" measured from the data date (the date progress was last recorded).
"""

from __future__ import annotations

import math
from bisect import bisect_left
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

ONE_DAY = timedelta(days=1)
MIDDAY = time(12, 0)


@dataclass(frozen=True)
class WorkCalendar:
    """A weekly working pattern plus non-working holidays.

    ``workdays`` uses Python weekday numbers: Monday = 0 ... Sunday = 6.
    """

    workdays: frozenset[int] = frozenset({0, 1, 2, 3, 4})
    holidays: tuple[date, ...] = ()
    name: str = "Standard 5-day week"

    def __post_init__(self) -> None:
        workdays = frozenset(self.workdays) or frozenset({0, 1, 2, 3, 4})
        object.__setattr__(self, "workdays", workdays)
        clean = tuple(sorted({h for h in self.holidays if h.weekday() in workdays}))
        object.__setattr__(self, "holidays", clean)

    @classmethod
    def from_days_per_week(
        cls, days: int, holidays: tuple[date, ...] = (), name: str | None = None
    ) -> WorkCalendar:
        days = min(7, max(1, int(round(days))))
        return cls(frozenset(range(days)), holidays, name or f"{days}-day week")

    @property
    def days_per_week(self) -> int:
        return len(self.workdays)

    def is_workday(self, day: date) -> bool:
        if day.weekday() not in self.workdays:
            return False
        i = bisect_left(self.holidays, day)
        return not (i < len(self.holidays) and self.holidays[i] == day)

    def count(self, start: date, end: date) -> int:
        """Number of working days in ``[start, end)``; negative if end < start."""
        if end < start:
            return -self.count(end, start)
        weeks, rem = divmod((end - start).days, 7)
        total = weeks * len(self.workdays)
        first = start.weekday()
        total += sum(1 for i in range(rem) if (first + i) % 7 in self.workdays)
        total -= bisect_left(self.holidays, end) - bisect_left(self.holidays, start)
        return total

    def nth_workday(self, origin: date, index: int) -> date:
        """Date of working day number ``index`` counted from ``origin``.

        Index 0 is the first working day on or after ``origin``; -1 is the
        working day before that, and so on.
        """
        day = origin
        while not self.is_workday(day):
            day += ONE_DAY
        step = 1 if index > 0 else -1
        remaining = abs(index)
        per_week = len(self.workdays)
        while remaining > 0:
            if remaining > 2 * per_week:  # jump whole weeks to stay fast
                target = day + timedelta(days=7 * (remaining // per_week - 1) * step)
                passed = (
                    self.count(day + ONE_DAY, target + ONE_DAY)
                    if step > 0
                    else self.count(target, day)
                )
                if 0 < passed < remaining:
                    day, remaining = target, remaining - passed
                    continue
            day += timedelta(days=step)
            if self.is_workday(day):
                remaining -= 1
        return day

    # -- offsets relative to the data date ----------------------------------
    def offset(self, origin: datetime, moment: datetime) -> float:
        """Working-day offset of ``moment`` from the start of ``origin``'s day.

        A time at or after midday is read as the *end* of that working day, so
        an activity finishing at 17:00 today has an offset of 1.
        """
        value = self.count(origin.date(), moment.date())
        if moment.time() >= MIDDAY and self.is_workday(moment.date()):
            value += 1
        return float(value)

    def date_at(self, origin: datetime, offset: float, finish: bool = False) -> date:
        """Inverse of :meth:`offset` for a start (default) or finish offset."""
        if finish:
            index = math.ceil(offset - 1e-9) - 1
        else:
            index = math.floor(offset + 1e-9)
        return self.nth_workday(origin.date(), index)

    def datetime_at(self, origin: datetime, offset: float, finish: bool = False) -> datetime:
        day = self.date_at(origin, offset, finish)
        return datetime.combine(day, time(17, 0) if finish else time(8, 0))

    def describe(self) -> str:
        names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        days = ", ".join(names[d] for d in sorted(self.workdays))
        extra = f", {len(self.holidays)} holidays" if self.holidays else ""
        return f"{self.name} ({days}{extra})"
