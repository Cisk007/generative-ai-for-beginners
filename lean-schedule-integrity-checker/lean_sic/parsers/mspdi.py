"""Microsoft Project XML (MSPDI) reader.

In Microsoft Project use *File > Save As > XML Format (*.xml)*. Durations
are ISO-8601 strings such as ``PT40H0M0S`` and link lags are stored in
tenths of a minute.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET  # noqa: S405 - DTDs and entities are rejected before parsing
from datetime import date, datetime, timedelta

from ..calendar import WorkCalendar
from ..model import Activity, ActivityType, ConstraintType, Relationship, RelType, Schedule, Status
from .common import ScheduleParseError, parse_datetime, parse_float

# Microsoft Project honours constraint dates over links by default, so
# "Must Start/Finish On" behave like P6's mandatory constraints.
CONSTRAINTS = {
    0: ConstraintType.NONE,  # As Soon As Possible
    1: ConstraintType.AS_LATE_AS_POSSIBLE,
    2: ConstraintType.MANDATORY_START,  # Must Start On
    3: ConstraintType.MANDATORY_FINISH,  # Must Finish On
    4: ConstraintType.START_ON_OR_AFTER,  # Start No Earlier Than
    5: ConstraintType.START_ON_OR_BEFORE,  # Start No Later Than
    6: ConstraintType.FINISH_ON_OR_AFTER,  # Finish No Earlier Than
    7: ConstraintType.FINISH_ON_OR_BEFORE,  # Finish No Later Than
}
LINK_TYPES = {0: RelType.FF, 1: RelType.FS, 2: RelType.SF, 3: RelType.SS}
ELAPSED_FORMATS = {4, 6, 8, 10, 12, 36, 38, 40, 42, 44}
PERCENT_FORMATS = {19, 20, 51, 52}
ID_FIELD = re.compile(r"^(activity|act|task)[ _-]?(id|code)$", re.IGNORECASE)
_DURATION = re.compile(
    r"^P(?:(?P<y>[\d.]+)Y)?(?:(?P<mo>[\d.]+)M)?(?:(?P<d>[\d.]+)D)?"
    r"(?:T(?:(?P<h>[\d.]+)H)?(?:(?P<mi>[\d.]+)M)?(?:(?P<s>[\d.]+)S)?)?$"
)


def iso_duration_hours(value: str | None) -> float | None:
    if not value:
        return None
    m = _DURATION.match(value.strip())
    if not m:
        return None
    parts = {k: float(v) if v else 0.0 for k, v in m.groupdict().items()}
    return parts["d"] * 24 + parts["h"] + parts["mi"] / 60 + parts["s"] / 3600


def _date_range(start: datetime | None, end: datetime | None) -> list[date]:
    if not start:
        return []
    last = (end or start).date()
    days, day = [], start.date()
    while day <= last and len(days) < 400:
        days.append(day)
        day += timedelta(days=1)
    return days


def parse_mspdi(data: bytes | str, source_name: str = "") -> Schedule:
    raw = data.encode("utf-8") if isinstance(data, str) else data
    head = raw.upper()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in head:
        raise ScheduleParseError("XML files with DOCTYPE or ENTITY declarations are not accepted.")
    try:
        root = ET.fromstring(raw)  # noqa: S314 - safe: no DTD/entities allowed (checked above)
    except ET.ParseError as exc:
        raise ScheduleParseError(f"Invalid XML: {exc}") from exc
    ns = root.tag[: root.tag.index("}") + 1] if root.tag.startswith("{") else ""
    if root.tag[len(ns) :] != "Project":
        raise ScheduleParseError("This XML file is not a Microsoft Project (MSPDI) export.")

    def text(el: ET.Element, name: str, default: str | None = None) -> str | None:
        child = el.find(ns + name)
        return child.text.strip() if child is not None and child.text else default

    def section(name: str) -> list[ET.Element]:
        el = root.find(ns + name)
        return list(el) if el is not None else []

    warnings: list[str] = []
    minutes_per_day = parse_float(text(root, "MinutesPerDay")) or 480.0
    hours_per_day = minutes_per_day / 60.0

    # -- calendars: weekly pattern + non-working exceptions ------------------
    calendars: dict[str, dict] = {}
    for cal in section("Calendars"):
        workdays: set[int] = set()
        found = False
        holidays: list[date] = []
        weekdays = cal.find(ns + "WeekDays")
        for wd in list(weekdays) if weekdays is not None else []:
            day_type = int(text(wd, "DayType", "-1") or -1)
            working = text(wd, "DayWorking", "0") == "1"
            if 1 <= day_type <= 7:
                found = True
                if working:
                    workdays.add((day_type - 2) % 7)  # 1 = Sunday ... 7 = Saturday
            elif day_type == 0 and not working:
                period = wd.find(ns + "TimePeriod")
                if period is not None:
                    holidays += _date_range(
                        parse_datetime(text(period, "FromDate")),
                        parse_datetime(text(period, "ToDate")),
                    )
        exceptions = cal.find(ns + "Exceptions")
        for ex in list(exceptions) if exceptions is not None else []:
            period = ex.find(ns + "TimePeriod")
            if text(ex, "DayWorking", "0") != "1" and period is not None:
                holidays += _date_range(
                    parse_datetime(text(period, "FromDate")), parse_datetime(text(period, "ToDate"))
                )
        calendars[text(cal, "UID", "") or ""] = {
            "name": text(cal, "Name", "") or "",
            "workdays": frozenset(workdays) if found and workdays else None,
            "holidays": tuple(holidays),
            "base": text(cal, "BaseCalendarUID"),
        }
    for cal in calendars.values():  # derived calendars inherit their base pattern
        base = calendars.get(cal["base"] or "")
        if cal["workdays"] is None and base:
            cal["workdays"] = base["workdays"]
            cal["holidays"] = cal["holidays"] + base["holidays"]
    proj_cal = calendars.get(text(root, "CalendarUID", "") or "")
    if proj_cal and proj_cal["workdays"]:
        calendar = WorkCalendar(proj_cal["workdays"], proj_cal["holidays"], proj_cal["name"])
    else:
        calendar = WorkCalendar()

    # -- custom fields, resources, assignments --------------------------------
    field_names = {
        text(ea, "FieldID", "") or "": text(ea, "Alias") or text(ea, "FieldName") or ""
        for ea in section("ExtendedAttributes")
    }
    resource_names = {
        text(r, "UID", "") or "": text(r, "Name", "") or "" for r in section("Resources")
    }
    task_resources: dict[str, list[str]] = {}
    for a in section("Assignments"):
        name = resource_names.get(text(a, "ResourceUID", "") or "")
        if name:
            task_resources.setdefault(text(a, "TaskUID", "") or "", []).append(name)

    # -- tasks ------------------------------------------------------------------
    activities: dict[str, Activity] = {}
    links: list[tuple[str, str, int, float, int]] = []
    outline_names: dict[str, str] = {}
    outlines: dict[str, str] = {}
    for t in section("Tasks"):
        uid = text(t, "UID")
        if uid is None or uid == "0" or text(t, "IsNull") == "1" or text(t, "Active", "1") == "0":
            continue
        name = text(t, "Name", "") or ""
        outline = text(t, "OutlineNumber", "") or ""
        summary = text(t, "Summary") == "1"
        if summary:
            outline_names[outline] = name
        outlines[uid] = outline
        actual_start = parse_datetime(text(t, "ActualStart"))
        actual_finish = parse_datetime(text(t, "ActualFinish"))
        pct = parse_float(text(t, "PercentComplete"))
        if actual_finish or (pct is not None and pct >= 100):
            status = Status.COMPLETE
        elif actual_start or (pct or 0) > 0:
            status = Status.IN_PROGRESS
        else:
            status = Status.NOT_STARTED
        duration = (iso_duration_hours(text(t, "Duration")) or 0.0) / hours_per_day
        remaining_h = iso_duration_hours(text(t, "RemainingDuration"))
        remaining = (
            0.0
            if status == Status.COMPLETE
            else (remaining_h / hours_per_day if remaining_h is not None else None)
        )
        slack = parse_float(text(t, "TotalSlack"))
        free = parse_float(text(t, "FreeSlack"))
        if summary:
            kind = ActivityType.SUMMARY
        elif text(t, "Milestone") == "1":
            kind = (
                ActivityType.FINISH_MILESTONE
                if t.find(ns + "PredecessorLink") is not None
                else ActivityType.START_MILESTONE
            )
        else:
            kind = ActivityType.TASK
        act = Activity(
            uid=uid,
            code=text(t, "ID", uid) or uid,
            name=name,
            type=kind,
            status=status,
            duration=duration,
            remaining=remaining,
            percent_complete=pct,
            early_start=parse_datetime(text(t, "EarlyStart")) or parse_datetime(text(t, "Start")),
            early_finish=parse_datetime(text(t, "EarlyFinish"))
            or parse_datetime(text(t, "Finish")),
            late_start=parse_datetime(text(t, "LateStart")),
            late_finish=parse_datetime(text(t, "LateFinish")),
            actual_start=actual_start if status != Status.NOT_STARTED else None,
            actual_finish=actual_finish if status == Status.COMPLETE else None,
            total_float=slack / 10.0 / minutes_per_day if slack is not None else None,
            free_float=free / 10.0 / minutes_per_day if free is not None else None,
            constraint=CONSTRAINTS.get(
                int(text(t, "ConstraintType", "0") or 0), ConstraintType.NONE
            ),
            constraint_date=parse_datetime(text(t, "ConstraintDate")),
            resources=task_resources.get(uid, []),
        )
        if act.constraint == ConstraintType.NONE:
            act.constraint_date = None
        act.deadline = parse_datetime(text(t, "Deadline"))
        cal = calendars.get(text(t, "CalendarUID", "") or "")
        if cal and cal["workdays"]:
            act.calendar, act.calendar_days_per_week = cal["name"], len(cal["workdays"])
        for b in t.findall(ns + "Baseline"):
            if text(b, "Number", "0") == "0":
                act.baseline_start = parse_datetime(text(b, "Start"))
                act.baseline_finish = parse_datetime(text(b, "Finish"))
                hours = iso_duration_hours(text(b, "Duration"))
                act.baseline_duration = hours / hours_per_day if hours is not None else None
        for ea in t.findall(ns + "ExtendedAttribute"):
            fid, value = text(ea, "FieldID", "") or "", text(ea, "Value")
            if value:
                label = field_names.get(fid) or f"Field {fid}"
                if ID_FIELD.search(label):
                    act.code = value  # e.g. P6 activity IDs kept in a text field
                else:
                    act.codes[label] = value
        for link in t.findall(ns + "PredecessorLink"):
            if text(link, "CrossProject") == "1":
                continue
            links.append(
                (
                    text(link, "PredecessorUID", "") or "",
                    uid,
                    int(text(link, "Type", "1") or 1),
                    parse_float(text(link, "LinkLag")) or 0.0,
                    int(text(link, "LagFormat", "7") or 7),
                )
            )
        activities[uid] = act

    if not activities:
        raise ScheduleParseError("The Microsoft Project file contains no tasks.")

    for uid, outline in outlines.items():  # WBS path from the outline structure
        parts = outline.split(".")
        names = [outline_names.get(".".join(parts[:i])) for i in range(1, len(parts))]
        activities[uid].wbs = " > ".join(n for n in names if n)

    relationships = []
    for pred, succ, kind, lag, fmt in links:
        if pred not in activities:
            continue
        if fmt in PERCENT_FORMATS:
            lag_days = activities[pred].duration * lag / 100.0
        elif fmt in ELAPSED_FORMATS:
            lag_days = lag / 10.0 / 1440.0 * calendar.days_per_week / 7.0
        else:
            lag_days = lag / 10.0 / minutes_per_day
        relationships.append(Relationship(pred, succ, LINK_TYPES.get(kind, RelType.FS), lag_days))

    data_date = parse_datetime(text(root, "StatusDate")) or parse_datetime(
        text(root, "CurrentDate")
    )
    if data_date is None:
        data_date = parse_datetime(text(root, "StartDate")) or datetime.now()
        warnings.append("No status date in the file; used the project start date as the data date.")
    has_baseline = any(a.baseline_finish for a in activities.values())
    task_deadlines = [a.deadline for a in activities.values() if a.deadline]
    if task_deadlines:
        warnings.append(
            f"{len(task_deadlines)} task deadline(s) are applied to late dates like 'finish on or before'."
        )
    return Schedule(
        name=text(root, "Title")
        or text(root, "Name")
        or source_name
        or "Microsoft Project schedule",
        data_date=data_date,
        activities=activities,
        relationships=relationships,
        source_format="mspdi",
        source_name=source_name,
        calendar=calendar,
        planned_start=parse_datetime(text(root, "StartDate")),
        scheduled_finish=parse_datetime(text(root, "FinishDate")),
        baseline_source="Microsoft Project Baseline (0)" if has_baseline else None,
        code_fields=sorted({k for a in activities.values() for k in a.codes}),
        warnings=warnings,
    )
