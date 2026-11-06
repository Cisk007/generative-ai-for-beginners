"""Oracle Primavera P6 ``.xer`` reader.

An XER file is tab-separated text made of tables::

    ERMHDR  <version> ...          header line
    %T      TASK                   start of a table
    %F      task_id  task_code ... field names
    %R      1001     A1000     ... one record
    %E                             end of file

Durations, lags and float are stored in hours, so they are converted to
working days with the hours-per-day of each activity's calendar.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from ..calendar import WorkCalendar
from ..model import (
    Activity,
    ActivityType,
    ConstraintType,
    Relationship,
    RelType,
    Schedule,
    Status,
)
from .common import ScheduleParseError, decode_bytes, parse_datetime, parse_float

TASK_TYPES = {
    "TT_Task": ActivityType.TASK,
    "TT_Rsrc": ActivityType.TASK,  # resource dependent task
    "TT_Mile": ActivityType.START_MILESTONE,
    "TT_FinMile": ActivityType.FINISH_MILESTONE,
    "TT_LOE": ActivityType.LOE,
    "TT_WBS": ActivityType.SUMMARY,
}

STATUS = {
    "TK_NotStart": Status.NOT_STARTED,
    "TK_Active": Status.IN_PROGRESS,
    "TK_Complete": Status.COMPLETE,
}

CONSTRAINTS = {
    "CS_MSO": ConstraintType.START_ON,
    "CS_MSOA": ConstraintType.START_ON_OR_AFTER,
    "CS_MSOB": ConstraintType.START_ON_OR_BEFORE,
    "CS_MEO": ConstraintType.FINISH_ON,
    "CS_MEOA": ConstraintType.FINISH_ON_OR_AFTER,
    "CS_MEOB": ConstraintType.FINISH_ON_OR_BEFORE,
    "CS_MANDSTART": ConstraintType.MANDATORY_START,
    "CS_MANDFIN": ConstraintType.MANDATORY_FINISH,
    "CS_ALAP": ConstraintType.AS_LATE_AS_POSSIBLE,
}

REL_TYPES = {"PR_FS": RelType.FS, "PR_SS": RelType.SS, "PR_FF": RelType.FF, "PR_SF": RelType.SF}

EXCEL_EPOCH = date(1899, 12, 30)  # P6 calendar exceptions use Excel serial dates


def read_tables(text: str) -> tuple[list[str], dict[str, list[dict[str, str]]]]:
    """Split XER text into ``{table_name: [record_dict, ...]}``."""
    header: list[str] = []
    tables: dict[str, list[dict[str, str]]] = {}
    current: str | None = None
    fields: list[str] = []
    for raw in text.split("\n"):
        line = raw.rstrip("\r")
        if not line:
            continue
        tag, _, rest = line.partition("\t")
        if tag == "ERMHDR":
            header = rest.split("\t")
        elif tag == "%T":
            current = rest.strip()
            tables.setdefault(current, [])
            fields = []
        elif tag == "%F":
            fields = rest.split("\t")
        elif tag == "%R" and current is not None and fields:
            values = rest.split("\t")
            if len(values) < len(fields):
                values += [""] * (len(fields) - len(values))
            tables[current].append(dict(zip(fields, values, strict=False)))
        elif tag == "%E":
            break
    return header, tables


def parse_calendar_data(clndr_data: str) -> tuple[frozenset[int] | None, tuple[date, ...]]:
    """Best-effort decode of P6's nested ``clndr_data`` text.

    Returns the working weekdays (Monday=0) and the non-working exception
    dates (holidays). ``None`` workdays means the pattern could not be read.
    """
    if not clndr_data:
        return None, ()
    workdays: set[int] = set()
    found_week = False
    start = clndr_data.find("DaysOfWeek()")
    if start >= 0:
        ends = [
            i
            for i in (clndr_data.find("VIEW", start), clndr_data.find("Exceptions", start))
            if i > 0
        ]
        block = clndr_data[start : min(ends) if ends else len(clndr_data)]
        # Splitting on the day markers gives [prefix, day, body, day, body, ...]
        parts = re.split(r"\(0\|\|([1-7])\(\)", block)
        for i in range(1, len(parts) - 1, 2):
            found_week = True
            if "s|" in parts[i + 1]:  # the day has at least one work period
                workdays.add((int(parts[i]) - 2) % 7)  # P6: 1=Sunday ... 7=Saturday
    holidays: list[date] = []
    ex = clndr_data.find("Exceptions()")
    if ex >= 0:
        for match in re.finditer(r"\(d\|(\d+)\)(\(\))?", clndr_data[ex:]):
            if match.group(2):  # an empty work-period list = non-working day
                holidays.append(EXCEL_EPOCH + timedelta(days=int(match.group(1))))
    return (frozenset(workdays) if found_week and workdays else None), tuple(holidays)


def _pick_project(projects: list[dict[str, str]], tasks: list[dict[str, str]], wanted: str | None):
    if not projects:
        raise ScheduleParseError("The XER file has no PROJECT table.")
    if wanted:
        for p in projects:
            if wanted in (p.get("proj_id"), p.get("proj_short_name")):
                return p
        names = ", ".join(p.get("proj_short_name", "?") for p in projects)
        raise ScheduleParseError(f"Project '{wanted}' not found. Projects in file: {names}")
    # A baseline exported alongside the current schedule is referenced by the
    # current project's sum_base_proj_id, so prefer projects nobody points to.
    baseline_ids = {p.get("sum_base_proj_id") for p in projects if p.get("sum_base_proj_id")}
    candidates = [p for p in projects if p.get("proj_id") not in baseline_ids] or projects
    counts: dict[str, int] = {}
    for t in tasks:
        counts[t.get("proj_id", "")] = counts.get(t.get("proj_id", ""), 0) + 1
    return max(candidates, key=lambda p: counts.get(p.get("proj_id", ""), 0))


def _read_calendars(rows: list[dict[str, str]]) -> dict[str, dict]:
    calendars: dict[str, dict] = {}
    for row in rows:
        hpd = parse_float(row.get("day_hr_cnt")) or 8.0
        hpw = parse_float(row.get("week_hr_cnt"))
        workdays, holidays = parse_calendar_data(row.get("clndr_data", ""))
        if workdays is None:
            per_week = int(round(hpw / hpd)) if hpw else 5
            workdays = frozenset(range(min(7, max(1, per_week))))
        calendars[row.get("clndr_id", "")] = {
            "name": row.get("clndr_name", ""),
            "hpd": hpd,
            "workdays": workdays,
            "holidays": holidays,
            "default": row.get("default_flag") == "Y",
        }
    return calendars


def parse_xer(data: bytes | str, source_name: str = "", project: str | None = None) -> Schedule:
    text = decode_bytes(data) if isinstance(data, bytes) else data
    header, tables = read_tables(text)
    if not header and "TASK" not in tables:
        raise ScheduleParseError("This does not look like a Primavera P6 XER file.")
    tasks_all = tables.get("TASK", [])
    proj = _pick_project(tables.get("PROJECT", []), tasks_all, project)
    proj_id = proj.get("proj_id", "")
    warnings: list[str] = []

    # -- calendars ----------------------------------------------------------
    calendars = _read_calendars(tables.get("CALENDAR", []))
    default_cal = calendars.get(proj.get("clndr_id", "")) or next(
        (c for c in calendars.values() if c["default"]), next(iter(calendars.values()), None)
    )
    if default_cal:
        project_calendar = WorkCalendar(
            default_cal["workdays"], default_cal["holidays"], default_cal["name"]
        )
        project_hpd = default_cal["hpd"]
    else:
        project_calendar, project_hpd = WorkCalendar(), 8.0
        warnings.append("No calendar found; assumed Monday-Friday, 8 hours per day.")

    def hpd_of(clndr_id: str) -> float:
        cal = calendars.get(clndr_id)
        return cal["hpd"] if cal else project_hpd

    # -- WBS paths ----------------------------------------------------------
    wbs_rows = {
        r.get("wbs_id", ""): r for r in tables.get("PROJWBS", []) if r.get("proj_id") == proj_id
    }
    wbs_cache: dict[str, str] = {}

    def wbs_path(wbs_id: str) -> str:
        if wbs_id not in wbs_cache:
            names: list[str] = []
            seen: set[str] = set()
            node = wbs_rows.get(wbs_id)
            while node and node.get("proj_node_flag") != "Y" and node.get("wbs_id") not in seen:
                seen.add(node.get("wbs_id", ""))
                names.append(node.get("wbs_name") or node.get("wbs_short_name", ""))
                node = wbs_rows.get(node.get("parent_wbs_id", ""))
            wbs_cache[wbs_id] = " > ".join(reversed(names))
        return wbs_cache[wbs_id]

    # -- activity codes and user-defined fields -----------------------------
    code_types = {
        r.get("actv_code_type_id", ""): r.get("actv_code_type", "")
        for r in tables.get("ACTVTYPE", [])
    }
    code_values = {
        r.get("actv_code_id", ""): (r.get("short_name") or r.get("actv_code_name", ""))
        for r in tables.get("ACTVCODE", [])
    }
    task_codes: dict[str, dict[str, str]] = {}
    for r in tables.get("TASKACTV", []):
        type_name = code_types.get(r.get("actv_code_type_id", ""))
        value = code_values.get(r.get("actv_code_id", ""))
        if type_name and value:
            task_codes.setdefault(r.get("task_id", ""), {})[type_name] = value
    udf_types = {
        r.get("udf_type_id", ""): r.get("udf_type_label") or r.get("udf_type_name", "")
        for r in tables.get("UDFTYPE", [])
        if r.get("table_name") == "TASK"
    }
    for r in tables.get("UDFVALUE", []):
        label = udf_types.get(r.get("udf_type_id", ""))
        value = r.get("udf_text") or r.get("udf_number") or r.get("udf_date", "")
        if label and value:
            task_codes.setdefault(r.get("fk_id", ""), {})[f"UDF: {label}"] = value

    # -- resources ----------------------------------------------------------
    rsrc_names = {
        r.get("rsrc_id", ""): r.get("rsrc_name") or r.get("rsrc_short_name", "")
        for r in tables.get("RSRC", [])
    }
    role_names = {r.get("role_id", ""): r.get("role_name", "") for r in tables.get("ROLES", [])}
    task_rsrc: dict[str, list[str]] = {}
    for r in tables.get("TASKRSRC", []):
        name = rsrc_names.get(r.get("rsrc_id", "")) or role_names.get(r.get("role_id", ""))
        if name:
            names = task_rsrc.setdefault(r.get("task_id", ""), [])
            if name not in names:
                names.append(name)

    # -- baseline: a baseline project exported in the same file, if any -----
    base_id = proj.get("sum_base_proj_id", "")
    baseline_rows: dict[str, dict[str, str]] = {}
    if base_id and base_id != proj_id:
        baseline_rows = {
            t.get("task_code", ""): t for t in tasks_all if t.get("proj_id") == base_id
        }

    # -- activities -----------------------------------------------------------
    activities: dict[str, Activity] = {}
    task_hpd: dict[str, float] = {}
    for t in tasks_all:
        if t.get("proj_id") != proj_id:
            continue
        uid = t.get("task_id", "")
        clndr_id = t.get("clndr_id", "")
        hpd = hpd_of(clndr_id) or 8.0
        task_hpd[uid] = hpd
        cal = calendars.get(clndr_id)
        status = STATUS.get(t.get("status_code", ""), Status.NOT_STARTED)
        duration = (parse_float(t.get("target_drtn_hr_cnt")) or 0.0) / hpd
        remaining_hr = parse_float(t.get("remain_drtn_hr_cnt"))
        if status == Status.COMPLETE:
            remaining: float | None = 0.0
        else:
            remaining = remaining_hr / hpd if remaining_hr is not None else None
        tf = parse_float(t.get("total_float_hr_cnt"))
        ff = parse_float(t.get("free_float_hr_cnt"))
        if t.get("complete_pct_type") == "CP_Drtn" and duration > 0 and remaining is not None:
            pct = round(100.0 * (1.0 - remaining / duration), 1)
        else:
            pct = parse_float(t.get("phys_complete_pct"))
        act = Activity(
            uid=uid,
            code=t.get("task_code") or uid,
            name=t.get("task_name", ""),
            type=TASK_TYPES.get(t.get("task_type", ""), ActivityType.TASK),
            status=status,
            duration=duration,
            remaining=remaining,
            percent_complete=pct,
            early_start=parse_datetime(t.get("early_start_date"))
            or parse_datetime(t.get("restart_date")),
            early_finish=parse_datetime(t.get("early_end_date"))
            or parse_datetime(t.get("reend_date")),
            late_start=parse_datetime(t.get("late_start_date")),
            late_finish=parse_datetime(t.get("late_end_date")),
            actual_start=(
                parse_datetime(t.get("act_start_date")) if status != Status.NOT_STARTED else None
            ),
            actual_finish=(
                parse_datetime(t.get("act_end_date")) if status == Status.COMPLETE else None
            ),
            total_float=tf / hpd if tf is not None else None,
            free_float=ff / hpd if ff is not None else None,
            constraint=CONSTRAINTS.get(t.get("cstr_type", ""), ConstraintType.NONE),
            constraint_date=parse_datetime(t.get("cstr_date")),
            constraint2=CONSTRAINTS.get(t.get("cstr_type2", ""), ConstraintType.NONE),
            constraint2_date=parse_datetime(t.get("cstr_date2")),
            calendar=cal["name"] if cal else "",
            calendar_days_per_week=len(cal["workdays"]) if cal else None,
            wbs=wbs_path(t.get("wbs_id", "")),
            codes=task_codes.get(uid, {}),
            resources=list(task_rsrc.get(uid, [])),
        )
        primary = rsrc_names.get(t.get("rsrc_id", ""))
        if primary and primary not in act.resources:
            act.resources.insert(0, primary)
        base = baseline_rows.get(act.code)
        if base:
            act.baseline_start = (
                parse_datetime(base.get("act_start_date"))
                or parse_datetime(base.get("early_start_date"))
                or parse_datetime(base.get("target_start_date"))
            )
            act.baseline_finish = (
                parse_datetime(base.get("act_end_date"))
                or parse_datetime(base.get("early_end_date"))
                or parse_datetime(base.get("target_end_date"))
            )
            act.baseline_duration = (parse_float(base.get("target_drtn_hr_cnt")) or 0.0) / hpd
        elif not baseline_rows:
            act.baseline_start = parse_datetime(t.get("target_start_date"))
            act.baseline_finish = parse_datetime(t.get("target_end_date"))
            act.baseline_duration = duration
        activities[uid] = act

    if not activities:
        raise ScheduleParseError(
            f"Project '{proj.get('proj_short_name', proj_id)}' has no activities."
        )

    data_date = parse_datetime(proj.get("last_recalc_date")) or parse_datetime(
        proj.get("plan_start_date")
    )
    if data_date is None:
        starts = [a.start for a in activities.values() if a.start]
        data_date = (
            min(starts)
            if starts
            else datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)
        )
        warnings.append(
            "The project has no data date (last_recalc_date); used the earliest start instead."
        )

    # -- relationships --------------------------------------------------------
    relationships: list[Relationship] = []
    external = 0
    for r in tables.get("TASKPRED", []):
        succ, pred = r.get("task_id", ""), r.get("pred_task_id", "")
        if succ not in activities and pred not in activities:
            continue  # belongs to another project in the file
        if succ not in activities or pred not in activities:
            external += 1
            continue
        lag_days = (parse_float(r.get("lag_hr_cnt")) or 0.0) / task_hpd.get(pred, project_hpd)
        relationships.append(
            Relationship(pred, succ, REL_TYPES.get(r.get("pred_type", ""), RelType.FS), lag_days)
        )
    if external:
        warnings.append(
            f"{external} relationships link to activities in other projects and were ignored."
        )

    if baseline_rows:
        base_proj = next((p for p in tables.get("PROJECT", []) if p.get("proj_id") == base_id), {})
        baseline_source = (
            f"Baseline project '{base_proj.get('proj_short_name', base_id)}' from the XER file"
        )
    else:
        baseline_source = "P6 planned dates (a proxy; export the baseline project in the same XER for a true baseline)"

    # P6 keeps the project's long name on the root (project) node of the WBS.
    root = next((r for r in wbs_rows.values() if r.get("proj_node_flag") == "Y"), {})
    return Schedule(
        name=root.get("wbs_name") or proj.get("proj_short_name") or proj_id,
        data_date=data_date,
        activities=activities,
        relationships=relationships,
        source_format="xer",
        source_name=source_name,
        project_code=proj.get("proj_short_name", ""),
        calendar=project_calendar,
        planned_start=parse_datetime(proj.get("plan_start_date")),
        deadline=parse_datetime(proj.get("plan_end_date")),
        scheduled_finish=parse_datetime(proj.get("scd_end_date")),
        critical_float=(parse_float(proj.get("critical_drtn_hr_cnt")) or 0.0) / project_hpd,
        baseline_source=baseline_source,
        code_fields=sorted({k for a in activities.values() for k in a.codes}),
        other_projects=[
            p.get("proj_short_name", "")
            for p in tables.get("PROJECT", [])
            if p.get("proj_id") != proj_id
        ],
        external_links=external,
        warnings=warnings,
    )
