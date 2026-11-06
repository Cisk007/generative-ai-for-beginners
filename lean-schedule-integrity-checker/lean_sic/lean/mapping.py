"""Find *who* (trade) and *where* (location / zone) for every activity.

Lean planning is organised by trade and by location: Last Planner commitments
are made by trades, and takt / location-based plans move trades through zones.
P6 schedules usually carry these as activity codes; CSV files as columns;
some schedules only encode location in the WBS. Field specs:

* ``"Trade"`` - an activity code / CSV column / custom field name
* ``"resource"`` - the first resource assigned to the activity
* ``"wbs"`` - auto-detect the WBS level that names locations; ``"wbs:2"`` - level 2
* ``"none"`` - disable
"""

from __future__ import annotations

import re
from collections import Counter

from ..model import Activity, Schedule

TRADE_FIELD = re.compile(
    r"trade|discipline|sub-?contractor|contractor|responsib|crew|company|package|craft|gang|planner",
    re.IGNORECASE,
)
LOCATION_FIELD = re.compile(
    r"zone|area|location|level|floor|stor(e)?y|building|block|sector|takt|room|grid|wing|lbs",
    re.IGNORECASE,
)
LOCATION_VALUE = re.compile(
    r"\b(level|lvl|floor|stor(e)?y|zone|area|block|building|bldg|wing|sector|basement|roof|podium|tower|unit)\b"
    r"|^[LBZF]\d+\b",
    re.IGNORECASE,
)


def _wbs_parts(act: Activity) -> list[str]:
    return [p.strip() for p in act.wbs.split(">") if p.strip()] if act.wbs else []


def _code_value(act: Activity, field: str) -> str | None:
    value = act.codes.get(field)
    return value.strip() if value and value.strip() else None


def _detect_wbs_level(tasks: list[Activity]) -> int | None:
    hits: Counter[int] = Counter()
    for a in tasks:
        for i, part in enumerate(_wbs_parts(a)):
            if LOCATION_VALUE.search(part):
                hits[i] += 1
    if not hits or not tasks:
        return None
    level, count = max(hits.items(), key=lambda kv: (kv[1], kv[0]))
    return level if count / len(tasks) >= 0.3 else None


def _wbs_location(act: Activity, level: int) -> str | None:
    parts = _wbs_parts(act)
    if len(parts) <= level:
        return None
    outer = [p for p in parts[:level] if LOCATION_VALUE.search(p)]
    return " / ".join([*outer, parts[level]])


def _match_field(fields: list[str], wanted: str) -> str | None:
    for f in fields:
        if f.lower() == wanted.lower():
            return f
    return None


def _getter(spec: str, fields: list[str], tasks: list[Activity]):
    """Return (label, function(activity) -> value) for a field spec."""
    key = spec.strip()
    low = key.lower()
    if low == "none":
        return None, None
    if low in ("resource", "resources"):
        return "First assigned resource", lambda a: a.resources[0] if a.resources else None
    if low.startswith("wbs"):
        level = None
        if ":" in low:
            try:
                level = max(0, int(low.split(":", 1)[1]) - 1)
            except ValueError:
                level = None
        level = level if level is not None else _detect_wbs_level(tasks)
        if level is None:
            return None, None
        return f"WBS level {level + 1}", lambda a, lv=level: _wbs_location(a, lv)
    field = _match_field(fields, key)
    if field is None:
        return None, None
    return f"Activity code '{field}'", lambda a, f=field: _code_value(a, f)


def _coverage(tasks: list[Activity], fn) -> float:
    if not tasks or fn is None:
        return 0.0
    return sum(1 for a in tasks if fn(a)) / len(tasks)


def resolve_mapping(
    schedule: Schedule, trade_field: str | None = None, location_field: str | None = None
) -> dict:
    """Assign ``Activity.trade`` / ``Activity.location`` and describe the mapping."""
    tasks = [a for a in schedule.activities.values() if a.is_task]
    fields = schedule.code_fields
    result: dict = {"available_fields": fields}

    for role, wanted, pattern in (
        ("trade", trade_field, TRADE_FIELD),
        ("location", location_field, LOCATION_FIELD),
    ):
        label, fn = (None, None)
        if wanted:
            label, fn = _getter(wanted, fields, tasks)
            spec = wanted
            if fn is None and wanted.lower() != "none":
                result.setdefault("warnings", []).append(
                    f"{role.title()} field '{wanted}' was not found."
                )
        else:
            candidates = [f for f in fields if pattern.search(f)]
            best = max(
                candidates,
                key=lambda f: _coverage(tasks, lambda a, f=f: _code_value(a, f)),
                default=None,
            )
            if best and _coverage(tasks, lambda a, b=best: _code_value(a, b)) > 0:
                spec = best
                label, fn = _getter(best, fields, tasks)
            elif role == "trade" and schedule.has_resources:
                spec = "resource"
                label, fn = _getter("resource", fields, tasks)
            elif role == "location":
                spec = "wbs"
                label, fn = _getter("wbs", fields, tasks)
            else:
                spec = ""
        for a in schedule.activities.values():
            setattr(a, role, fn(a) if fn else None)
        result[role] = {
            "spec": spec if fn else "",
            "label": label or "Not found",
            "coverage": round(100.0 * _coverage(tasks, fn), 1) if fn else 0.0,
            "values": len({getattr(a, role) for a in tasks if getattr(a, role)}),
        }
    return result
