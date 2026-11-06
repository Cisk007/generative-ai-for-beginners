"""Simple CSV schedule reader, for spreadsheet-based or Lean planning teams.

Minimum columns: ``id``, ``name``, ``duration`` (working days) and
``predecessors`` (e.g. ``A1010; A1020SS+2; A1030FF-1``). Optional columns
include ``start``, ``finish``, ``actual_start``, ``actual_finish``,
``baseline_start``, ``baseline_finish``, ``percent_complete``, ``status``,
``type``, ``constraint``, ``constraint_date``, ``total_float``, ``wbs`` and
``resources``. Any other column (e.g. ``trade``, ``zone``) is kept as an
activity code so the Lean analysis can use it.

Project settings can be given as comment lines at the top of the file::

    # data_date: 2026-03-02
    # project: Harbourside Clinic
    # deadline: 2026-11-27
    # days_per_week: 5
    # holidays: 2026-04-03, 2026-04-06
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime, time, timedelta

from ..calendar import WorkCalendar
from ..model import Activity, ActivityType, ConstraintType, Relationship, RelType, Schedule, Status
from .common import ScheduleParseError, decode_bytes, parse_datetime, parse_float

ALIASES = {
    "id": ["id", "activity_id", "task_id", "code", "activity_code", "uid"],
    "name": ["name", "activity_name", "task_name", "description", "task", "activity"],
    "duration": ["duration", "original_duration", "duration_days", "od", "planned_duration"],
    "remaining": ["remaining_duration", "remaining", "rd"],
    "type": ["type", "activity_type", "task_type"],
    "status": ["status", "activity_status"],
    "percent": ["percent_complete", "pct_complete", "%_complete", "complete_pct", "progress"],
    "start": ["start", "early_start", "forecast_start"],
    "finish": ["finish", "early_finish", "forecast_finish"],
    "late_start": ["late_start"],
    "late_finish": ["late_finish"],
    "actual_start": ["actual_start"],
    "actual_finish": ["actual_finish"],
    "baseline_start": ["baseline_start", "bl_start", "planned_start"],
    "baseline_finish": ["baseline_finish", "bl_finish", "planned_finish"],
    "baseline_duration": ["baseline_duration", "bl_duration"],
    "total_float": ["total_float", "tf", "float", "total_slack"],
    "predecessors": ["predecessors", "predecessor", "preds", "depends_on", "dependencies"],
    "constraint": ["constraint", "constraint_type"],
    "constraint_date": ["constraint_date"],
    "wbs": ["wbs", "wbs_path", "wbs_name", "phase"],
    "resources": ["resources", "resource", "resource_names"],
    "deadline": ["deadline", "due_date"],
}

TYPES = {
    "task": ActivityType.TASK,
    "activity": ActivityType.TASK,
    "milestone": ActivityType.FINISH_MILESTONE,
    "finish milestone": ActivityType.FINISH_MILESTONE,
    "start milestone": ActivityType.START_MILESTONE,
    "loe": ActivityType.LOE,
    "level of effort": ActivityType.LOE,
    "hammock": ActivityType.LOE,
    "summary": ActivityType.SUMMARY,
    "wbs": ActivityType.SUMMARY,
}

CONSTRAINTS = {
    "snet": ConstraintType.START_ON_OR_AFTER,
    "start no earlier than": ConstraintType.START_ON_OR_AFTER,
    "start on or after": ConstraintType.START_ON_OR_AFTER,
    "snlt": ConstraintType.START_ON_OR_BEFORE,
    "start no later than": ConstraintType.START_ON_OR_BEFORE,
    "start on or before": ConstraintType.START_ON_OR_BEFORE,
    "fnet": ConstraintType.FINISH_ON_OR_AFTER,
    "finish no earlier than": ConstraintType.FINISH_ON_OR_AFTER,
    "finish on or after": ConstraintType.FINISH_ON_OR_AFTER,
    "fnlt": ConstraintType.FINISH_ON_OR_BEFORE,
    "finish no later than": ConstraintType.FINISH_ON_OR_BEFORE,
    "finish on or before": ConstraintType.FINISH_ON_OR_BEFORE,
    "mso": ConstraintType.START_ON,
    "must start on": ConstraintType.START_ON,
    "start on": ConstraintType.START_ON,
    "mfo": ConstraintType.FINISH_ON,
    "must finish on": ConstraintType.FINISH_ON,
    "finish on": ConstraintType.FINISH_ON,
    "mandatory start": ConstraintType.MANDATORY_START,
    "mandatory finish": ConstraintType.MANDATORY_FINISH,
    "alap": ConstraintType.AS_LATE_AS_POSSIBLE,
    "as late as possible": ConstraintType.AS_LATE_AS_POSSIBLE,
    "asap": ConstraintType.NONE,
    "none": ConstraintType.NONE,
}

FINISH_CONSTRAINTS = {
    ConstraintType.FINISH_ON,
    ConstraintType.FINISH_ON_OR_AFTER,
    ConstraintType.FINISH_ON_OR_BEFORE,
    ConstraintType.MANDATORY_FINISH,
}

_LAG = r"(?P<lag>[+-]\s*\d+(?:\.\d+)?)"
_PRED_PATTERNS = [
    re.compile(r"^(?P<id>.+)\s*(?P<type>FS|SS|FF|SF)\s*" + _LAG + r"?$", re.IGNORECASE),
    re.compile(r"^(?P<id>.+?)\s*(?P<type>FS|SS|FF|SF)\s*" + _LAG + r"?$", re.IGNORECASE),
    re.compile(r"^(?P<id>.+)\s*" + _LAG + r"$"),
    re.compile(r"^(?P<id>.+?)\s*" + _LAG + r"$"),
]


def _norm(header: str) -> str:
    return re.sub(r"[\s\-/]+", "_", header.strip().lower())


def parse_duration_days(value: str | None, days_per_week: int = 5) -> float | None:
    """Read ``10``, ``10d``, ``2w`` or ``16h`` as working days."""
    if value is None or str(value).strip() == "":
        return None
    m = re.match(r"^\s*(-?\d+(?:\.\d+)?)\s*([a-z]*)\s*$", str(value).lower())
    if not m:
        return None
    number, unit = float(m.group(1)), m.group(2)
    if unit.startswith("w"):
        return number * days_per_week
    if unit.startswith("h"):
        return number / 8.0
    return number


def parse_predecessors(text: str, known_ids: set[str]) -> list[tuple[str, RelType, float]]:
    """Parse ``A1010; A1020SS+2; A1030 FF -1d`` into (id, type, lag) tuples.

    Several splits are tried and the one whose id is a known activity wins, so
    ids that contain dashes or digits (``L1-020``) are not mistaken for lags.
    """
    out: list[tuple[str, RelType, float]] = []
    for token in re.split(r"[;,]", text or ""):
        token = token.strip()
        if not token:
            continue
        if token in known_ids:
            out.append((token, RelType.FS, 0.0))
            continue
        token = re.sub(r"(?<=\d)\s*(?:days?|wd|d)$", "", token, flags=re.IGNORECASE)
        candidates: list[tuple[str, RelType, float]] = [(token, RelType.FS, 0.0)]
        for pattern in _PRED_PATTERNS:
            m = pattern.match(token)
            if m:
                kind = RelType((m.groupdict().get("type") or "FS").upper())
                lag = float(m.group("lag").replace(" ", "")) if m.group("lag") else 0.0
                candidates.append((m.group("id").strip(), kind, lag))
        known = [c for c in candidates if c[0] in known_ids]
        out.append(known[0] if known else candidates[min(1, len(candidates) - 1)])
    return out


def parse_csv_schedule(
    data: bytes | str,
    source_name: str = "",
    data_date: datetime | None = None,
    dayfirst: bool = False,
) -> Schedule:
    text = decode_bytes(data) if isinstance(data, bytes) else data
    meta: dict[str, str] = {}
    lines = text.splitlines()
    while lines and lines[0].lstrip().startswith("#"):
        key, _, value = lines.pop(0).lstrip("# ").partition(":")
        meta[_norm(key)] = value.strip()
    header_line = lines[0] if lines else ""
    delimiter = max([",", ";", "\t"], key=header_line.count) if header_line else ","
    reader = csv.DictReader(io.StringIO("\n".join(lines)), delimiter=delimiter)
    if not reader.fieldnames:
        raise ScheduleParseError("The CSV file has no header row.")
    columns = {_norm(h): h for h in reader.fieldnames if h}
    mapping: dict[str, str] = {}
    for key, names in ALIASES.items():
        for name in names:
            if name in columns:
                mapping[key] = columns[name]
                break
    if "id" not in mapping or "name" not in mapping:
        raise ScheduleParseError(
            "The CSV needs at least 'id' and 'name' columns (plus duration and predecessors)."
        )
    used = set(mapping.values())
    code_columns = [h for h in reader.fieldnames if h and h not in used]

    days_per_week = int(parse_float(meta.get("days_per_week")) or 5)
    holidays = tuple(
        d.date()
        for d in (
            parse_datetime(x, dayfirst=dayfirst)
            for x in re.split(r"[;,\s]+", meta.get("holidays", ""))
        )
        if d
    )
    calendar = WorkCalendar.from_days_per_week(days_per_week, holidays)
    rows = list(reader)
    known = {(r.get(mapping["id"]) or "").strip() for r in rows}

    def get(row: dict, key: str) -> str | None:
        col = mapping.get(key)
        value = row.get(col) if col else None
        return value.strip() if isinstance(value, str) and value.strip() else None

    def when(row: dict, key: str, finish: bool = False) -> datetime | None:
        value = parse_datetime(get(row, key), dayfirst=dayfirst)
        if value and finish and value.time() == time(0, 0):
            value = value.replace(hour=17)  # a bare date means "end of that day"
        return value

    activities: dict[str, Activity] = {}
    pending_links: list[tuple[str, str]] = []
    warnings: list[str] = []
    for i, row in enumerate(rows, start=2):
        uid = get(row, "id")
        if not uid:
            continue
        if uid in activities:
            warnings.append(f"Duplicate activity id '{uid}' on line {i} was skipped.")
            continue
        kind = TYPES.get((get(row, "type") or "task").lower(), ActivityType.TASK)
        duration = parse_duration_days(get(row, "duration"), days_per_week) or 0.0
        if duration == 0 and kind == ActivityType.TASK and get(row, "type") is None:
            kind = ActivityType.FINISH_MILESTONE  # zero duration without a type = milestone
        pct = parse_float((get(row, "percent") or "").rstrip("%"))
        actual_start, actual_finish = when(row, "actual_start"), when(row, "actual_finish", True)
        status_text = (get(row, "status") or "").lower()
        if (
            status_text in {"complete", "completed", "done", "finished"}
            or actual_finish
            or (pct or 0) >= 100
        ):
            status = Status.COMPLETE
        elif (
            status_text in {"in progress", "in_progress", "active", "started"}
            or actual_start
            or (pct or 0) > 0
        ):
            status = Status.IN_PROGRESS
        else:
            status = Status.NOT_STARTED
        remaining = parse_duration_days(get(row, "remaining"), days_per_week)
        if remaining is None and status == Status.IN_PROGRESS and pct is not None:
            remaining = duration * (1 - pct / 100.0)
        constraint = CONSTRAINTS.get(
            (get(row, "constraint") or "none").lower(), ConstraintType.NONE
        )
        act = Activity(
            uid=uid,
            code=uid,
            name=get(row, "name") or uid,
            type=kind,
            status=status,
            duration=duration,
            remaining=0.0 if status == Status.COMPLETE else remaining,
            percent_complete=pct,
            early_start=when(row, "start"),
            early_finish=when(row, "finish", True),
            late_start=when(row, "late_start"),
            late_finish=when(row, "late_finish", True),
            actual_start=actual_start if status != Status.NOT_STARTED else None,
            actual_finish=actual_finish if status == Status.COMPLETE else None,
            baseline_start=when(row, "baseline_start"),
            baseline_finish=when(row, "baseline_finish", True),
            baseline_duration=parse_duration_days(get(row, "baseline_duration"), days_per_week),
            total_float=parse_float(get(row, "total_float")),
            constraint=constraint,
            constraint_date=when(row, "constraint_date", constraint in FINISH_CONSTRAINTS),
            wbs=get(row, "wbs") or "",
            deadline=when(row, "deadline", True),
            resources=[
                r.strip() for r in re.split(r"[;,]", get(row, "resources") or "") if r.strip()
            ],
        )
        for col in code_columns:
            value = (row.get(col) or "").strip()
            if value:
                act.codes[col.strip()] = value
        if act.baseline_finish and act.baseline_duration is None:
            act.baseline_duration = duration
        activities[uid] = act
        if get(row, "predecessors"):
            pending_links.append((uid, get(row, "predecessors") or ""))

    if not activities:
        raise ScheduleParseError("No activities found in the CSV file.")

    relationships: list[Relationship] = []
    for succ, text_preds in pending_links:
        for pred, kind, lag in parse_predecessors(text_preds, known):
            if pred in activities:
                relationships.append(Relationship(pred, succ, kind, lag))
            else:
                warnings.append(f"Activity '{succ}' references unknown predecessor '{pred}'.")

    dd = data_date or parse_datetime(
        meta.get("data_date") or meta.get("status_date"), dayfirst=dayfirst
    )
    if dd is None:
        actuals = [d for a in activities.values() for d in (a.actual_start, a.actual_finish) if d]
        starts = [a.early_start for a in activities.values() if a.early_start]
        if actuals:
            dd = datetime.combine(max(actuals).date() + timedelta(days=1), time(8))
        elif starts:
            dd = min(starts)
        else:
            dd = datetime.combine(datetime.now().date(), time(8))
        warnings.append(
            f"No data date given; assumed {dd:%Y-%m-%d}. Add '# data_date: YYYY-MM-DD' to the CSV."
        )
    deadline = parse_datetime(meta.get("deadline"), dayfirst=dayfirst)
    if deadline and deadline.time() == time(0, 0):
        deadline = deadline.replace(hour=17)
    has_baseline = any(a.baseline_finish for a in activities.values())
    return Schedule(
        name=meta.get("project") or source_name or "CSV schedule",
        data_date=dd,
        activities=activities,
        relationships=relationships,
        source_format="csv",
        source_name=source_name,
        calendar=calendar,
        deadline=deadline,
        baseline_source="CSV baseline columns" if has_baseline else None,
        code_fields=sorted({k for a in activities.values() for k in a.codes}),
        warnings=warnings,
    )
