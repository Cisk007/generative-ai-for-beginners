"""Last Planner System (LPS) data: weekly work plans and the constraint log.

LPS has five conversations: master schedule -> phase (pull) planning ->
six-week lookahead with *make-ready* constraint removal -> weekly work plan
-> daily huddle, with learning from every missed promise. This module reads
two simple CSV files that most Lean teams already keep:

``weekly work plans`` - one row per weekly commitment::

    week, activity_id, task, trade, planned, completed, reason

``constraint log`` - one row per constraint found during make-ready::

    id, activity_id, description, category, owner, identified, need_by, status, closed
"""

from __future__ import annotations

import csv
import io
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from ..parsers.common import ScheduleParseError, decode_bytes, parse_bool, parse_datetime

WEEKLY_ALIASES = {
    "week": ["week", "week_ending", "week_start", "week_of", "period", "date"],
    "task": ["task", "description", "assignment", "commitment", "activity_name", "name"],
    "activity_id": ["activity_id", "activity", "schedule_id", "task_id", "activity_code"],
    "trade": [
        "trade",
        "responsible",
        "company",
        "crew",
        "last_planner",
        "subcontractor",
        "contractor",
    ],
    "planned": ["planned", "committed", "promised"],
    "completed": ["completed", "complete", "done", "status", "result"],
    "reason": [
        "reason",
        "rnc",
        "reason_for_non_completion",
        "variance_reason",
        "cause",
        "root_cause",
    ],
}
CONSTRAINT_ALIASES = {
    "id": ["id", "constraint_id", "ref", "reference", "no"],
    "activity_id": [
        "activity_id",
        "activity",
        "activities",
        "task_id",
        "schedule_id",
        "activity_code",
    ],
    "description": ["description", "constraint", "issue", "title", "summary"],
    "category": ["category", "type", "flow", "constraint_type", "precondition"],
    "owner": ["owner", "responsible", "assigned_to", "action_by", "action_owner"],
    "identified": ["identified", "date_identified", "raised", "created", "logged", "date_raised"],
    "need_by": ["need_by", "required_by", "due", "due_date", "need_date", "required_date"],
    "status": ["status", "state"],
    "closed": ["closed", "date_closed", "resolved", "removed", "cleared", "date_removed"],
}

# Reasons for non-completion (RNC) and constraints share one vocabulary based
# on Koskela's seven preconditions ("flows") of a construction task.
CATEGORIES = [
    (
        "Prerequisite work",
        [
            "prereq",
            "previous",
            "prior work",
            "predecessor",
            "upstream",
            "preceding",
            "not ready",
            "handover",
            "connecting",
        ],
    ),
    (
        "Information / design",
        [
            "design",
            "drawing",
            "rfi",
            "information",
            "spec",
            "submittal",
            "approval",
            "detail",
            "shop",
        ],
    ),
    ("Materials", ["material", "deliver", "supply", "procure", "component", "fabricat"]),
    (
        "Labour / crew",
        ["labour", "labor", "crew", "manpower", "worker", "staff", "absent", "sick", "resource"],
    ),
    ("Equipment", ["equipment", "plant", "crane", "tool", "machine", "hoist", "scaffold", "lift"]),
    (
        "Space / access",
        ["space", "access", "congest", "workface", "work face", "stacking", "obstruct", "area"],
    ),
    (
        "External / permits",
        [
            "weather",
            "rain",
            "wind",
            "snow",
            "storm",
            "permit",
            "authority",
            "inspect",
            "utility",
            "external",
            "neighbour",
            "neighbor",
        ],
    ),
    ("Safety", ["safety", "incident", "hazard", "accident"]),
    ("Planning / commitment", ["plan", "commit", "estimate", "underestim", "priorit", "sequence"]),
    ("Client / change", ["client", "owner", "change", "variation", "scope"]),
]
FLOW_CATEGORIES = [c for c, _ in CATEGORIES]


def categorize(text: str | None) -> str:
    value = (text or "").strip().lower()
    if not value:
        return ""
    for name, _ in CATEGORIES:  # an explicit category ("Materials: late delivery") wins
        if (
            value == name.lower()
            or value.startswith(name.lower() + ":")
            or value.startswith(name.lower() + " -")
        ):
            return name
    for name, keywords in CATEGORIES:
        if any(k in value for k in keywords):
            return name
    return "Other"


def _norm(header: str) -> str:
    return re.sub(r"[\s\-/]+", "_", header.strip().lower())


def _read_rows(
    data: bytes | str, aliases: dict[str, list[str]], required: list[str], label: str
) -> list[dict]:
    text = decode_bytes(data) if isinstance(data, bytes) else data
    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
    if not lines:
        raise ScheduleParseError(f"The {label} file is empty.")
    delimiter = max([",", ";", "\t"], key=lines[0].count)
    reader = csv.DictReader(io.StringIO("\n".join(lines)), delimiter=delimiter)
    columns = {_norm(h): h for h in reader.fieldnames or [] if h}
    mapping: dict[str, str] = {}
    for key, names in aliases.items():
        for name in names:
            if name in columns:
                mapping[key] = columns[name]
                break
    missing = [k for k in required if k not in mapping]
    if missing:
        raise ScheduleParseError(f"The {label} file needs column(s): {', '.join(missing)}.")
    rows = []
    for raw in reader:
        row = {k: (raw.get(col) or "").strip() for k, col in mapping.items()}
        if any(row.values()):
            rows.append(row)
    return rows


def parse_weekly_plans(data: bytes | str, dayfirst: bool = False) -> list[dict]:
    rows = []
    for r in _read_rows(data, WEEKLY_ALIASES, ["week", "completed"], "weekly work plan"):
        week = parse_datetime(r.get("week"), dayfirst=dayfirst)
        if week is None:
            continue
        status = r.get("completed", "")
        rows.append(
            {
                "week": week,
                "task": r.get("task") or r.get("activity_id") or "",
                "activity_id": r.get("activity_id", ""),
                "trade": r.get("trade") or "Unassigned",
                "planned": parse_bool(r.get("planned"), default=True),
                "completed": parse_bool(status),
                "reason_text": r.get("reason", ""),
                "reason": categorize(r.get("reason")),
            }
        )
    if not rows:
        raise ScheduleParseError("No dated rows found in the weekly work plan file.")
    return rows


def _slope(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    xs = list(range(len(values)))
    mx, my = statistics.fmean(xs), statistics.fmean(values)
    den = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, values, strict=True)) / den if den else 0.0


def analyze_weekly_plans(
    rows: list[dict], target: float, schedule_codes: set[str] | None = None
) -> dict:
    planned = [r for r in rows if r["planned"]]
    weeks: dict[datetime, list[dict]] = defaultdict(list)
    for r in planned:
        weeks[r["week"]].append(r)
    series = []
    for week in sorted(weeks):
        items = weeks[week]
        done = sum(1 for r in items if r["completed"])
        series.append(
            {
                "week": week.date().isoformat(),
                "planned": len(items),
                "completed": done,
                "ppc": round(100.0 * done / len(items), 1),
            }
        )
    for i, point in enumerate(series):
        window = series[max(0, i - 3) : i + 1]
        point["rolling4"] = round(
            100.0 * sum(w["completed"] for w in window) / sum(w["planned"] for w in window), 1
        )
    last = series[-4:]
    last4 = (
        round(100.0 * sum(w["completed"] for w in last) / sum(w["planned"] for w in last), 1)
        if last
        else None
    )
    overall = (
        round(100.0 * sum(1 for r in planned if r["completed"]) / len(planned), 1)
        if planned
        else None
    )
    recent_weeks = {datetime.fromisoformat(w["week"]) for w in last}
    trades = []
    by_trade: dict[str, list[dict]] = defaultdict(list)
    for r in planned:
        by_trade[r["trade"]].append(r)
    for trade, items in by_trade.items():
        recent = [r for r in items if r["week"] in recent_weeks]
        trades.append(
            {
                "trade": trade,
                "planned": len(items),
                "completed": sum(1 for r in items if r["completed"]),
                "ppc": round(100.0 * sum(1 for r in items if r["completed"]) / len(items), 1),
                "ppc_last4": (
                    round(100.0 * sum(1 for r in recent if r["completed"]) / len(recent), 1)
                    if recent
                    else None
                ),
            }
        )
    trades.sort(key=lambda t: t["ppc"])
    misses = [r for r in planned if not r["completed"]]
    reasons = Counter(r["reason"] or "Not recorded" for r in misses)
    pareto, running = [], 0
    for reason, count in reasons.most_common():
        running += count
        pareto.append(
            {
                "reason": reason,
                "count": count,
                "pct": round(100.0 * count / len(misses), 1),
                "cum_pct": round(100.0 * running / len(misses), 1),
            }
        )
    linked = sum(
        1
        for r in planned
        if r["activity_id"] and schedule_codes and r["activity_id"].lower() in schedule_codes
    )
    return {
        "weeks": series,
        "trades": trades,
        "reasons": pareto,
        "ppc_last4": last4,
        "ppc_overall": overall,
        "trend_per_week": round(_slope([w["ppc"] for w in series]), 1),
        "commitments": len(planned),
        "misses": len(misses),
        "linked": linked,
        "target": target,
    }


def parse_constraints(data: bytes | str, dayfirst: bool = False) -> list[dict]:
    rows = []
    for i, r in enumerate(
        _read_rows(data, CONSTRAINT_ALIASES, ["description"], "constraint log"), start=1
    ):
        status = (r.get("status") or "").lower()
        closed = parse_datetime(r.get("closed"), dayfirst=dayfirst)
        is_open = not (
            closed
            or status
            in {"closed", "removed", "resolved", "done", "cleared", "complete", "completed"}
        )
        rows.append(
            {
                "id": r.get("id") or f"C{i:03d}",
                "activity_ids": [
                    x.strip() for x in re.split(r"[;,]", r.get("activity_id", "")) if x.strip()
                ],
                "description": r.get("description", ""),
                "category": categorize(r.get("category"))
                or categorize(r.get("description"))
                or "Other",
                "owner": r.get("owner") or "Unassigned",
                "identified": parse_datetime(r.get("identified"), dayfirst=dayfirst),
                "need_by": parse_datetime(r.get("need_by"), dayfirst=dayfirst),
                "open": is_open,
                "closed": closed,
            }
        )
    return rows


def analyze_constraints(rows: list[dict], data_date: datetime, soon_weeks: int = 2) -> dict:
    dd = data_date
    open_rows = [r for r in rows if r["open"]]
    overdue = [r for r in open_rows if r["need_by"] and r["need_by"].date() < dd.date()]
    soon_end = dd + timedelta(weeks=soon_weeks)
    due_soon = [
        r for r in open_rows if r["need_by"] and dd.date() <= r["need_by"].date() < soon_end.date()
    ]
    closed = [r for r in rows if not r["open"]]
    lead = [(r["closed"] - r["identified"]).days for r in closed if r["closed"] and r["identified"]]
    on_time = [
        r
        for r in closed
        if r["closed"] and r["need_by"] and r["closed"].date() <= r["need_by"].date()
    ]
    by_category: dict[str, dict] = {}
    for r in rows:
        c = by_category.setdefault(
            r["category"], {"category": r["category"], "open": 0, "closed": 0, "overdue": 0}
        )
        c["open" if r["open"] else "closed"] += 1
    for r in overdue:
        by_category[r["category"]]["overdue"] += 1
    overdue_ids = {id(r) for r in overdue}
    by_owner: dict[str, dict] = {}
    for r in open_rows:
        o = by_owner.setdefault(r["owner"], {"owner": r["owner"], "open": 0, "overdue": 0})
        o["open"] += 1
        if id(r) in overdue_ids:
            o["overdue"] += 1
    return {
        "total": len(rows),
        "open": len(open_rows),
        "closed": len(closed),
        "overdue": len(overdue),
        "due_soon": len(due_soon),
        "avg_days_to_remove": round(statistics.fmean(lead), 1) if lead else None,
        "removed_on_time_pct": round(100.0 * len(on_time) / len(closed), 1) if closed else None,
        "by_category": sorted(by_category.values(), key=lambda c: -(c["open"] + c["closed"])),
        "by_owner": sorted(by_owner.values(), key=lambda o: (-o["overdue"], -o["open"])),
        "overdue_rows": [
            {
                "id": r["id"],
                "description": r["description"],
                "category": r["category"],
                "owner": r["owner"],
                "need_by": r["need_by"].date().isoformat() if r["need_by"] else "",
            }
            for r in sorted(overdue, key=lambda r: r["need_by"] or dd)
        ],
    }
