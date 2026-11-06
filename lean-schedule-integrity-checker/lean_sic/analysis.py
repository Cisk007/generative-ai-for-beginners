"""Run every analysis on a schedule and return one JSON-serialisable result."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from . import TOOL_NAME, __version__
from .checks import group_score, run_integrity
from .checks.base import FAIL, fmt_date
from .context import Context
from .cpm import EPS, compute_cpm
from .lean import readiness
from .lean.flow import analyze_flow
from .lean.lps import (
    analyze_constraints,
    analyze_weekly_plans,
    parse_constraints,
    parse_weekly_plans,
)
from .lean.mapping import resolve_mapping
from .lean.waste import waste_lens
from .model import STATUS_LABELS, TYPE_LABELS, ActivityType, RelType, Schedule, Status
from .settings import Settings

FLOAT_BINS = [
    ("Negative", lambda f, c: f < -EPS),
    ("Critical", lambda f, c: f <= c + EPS),
    ("1-5 d", lambda f, c: f <= 5 + EPS),
    ("6-10 d", lambda f, c: f <= 10 + EPS),
    ("11-20 d", lambda f, c: f <= 20 + EPS),
    ("21-44 d", lambda f, c: f <= 44 + EPS),
    ("> 44 d", lambda f, c: True),
]


def _read(source: bytes | str | Path | None) -> bytes | str | None:
    """Accept raw CSV bytes/text or a path to a CSV file."""
    if source is None or isinstance(source, bytes):
        return source
    if isinstance(source, Path):
        return source.read_bytes()
    if "\n" not in source and len(source) < 4096:
        try:
            path = Path(source)
            if path.is_file():
                return path.read_bytes()
        except OSError:
            pass
    return source


def _fill_dates(schedule: Schedule, cpm) -> int:
    """Use CPM dates where the file has none (typical for CSV input)."""
    cal, dd = schedule.calendar, schedule.data_date
    filled = 0
    for uid, act in schedule.activities.items():
        if not act.in_network or act.is_complete or uid not in cpm.ef:
            continue
        instant = act.remaining_duration <= EPS  # milestones happen at one moment
        start_of = act.type == ActivityType.START_MILESTONE
        if act.early_start is None:
            if instant and not start_of:  # a finish milestone: end of the previous day
                act.early_start = cal.datetime_at(dd, cpm.ef[uid], finish=True)
            else:
                act.early_start = cal.datetime_at(dd, cpm.res[uid])
            filled += 1
        if act.early_finish is None:
            if instant:
                act.early_finish = act.early_start
            else:
                act.early_finish = cal.datetime_at(dd, cpm.ef[uid], finish=True)
        if act.late_finish is None and uid in cpm.lf:
            if instant and not start_of:
                act.late_start = act.late_finish = cal.datetime_at(dd, cpm.lf[uid], finish=True)
            elif instant:
                act.late_start = act.late_finish = cal.datetime_at(dd, cpm.ls[uid])
            else:
                act.late_start = cal.datetime_at(dd, cpm.ls[uid])
                act.late_finish = cal.datetime_at(dd, cpm.lf[uid], finish=True)
    return filled


def _choose_float(schedule: Schedule, cpm) -> tuple[dict[str, float], str]:
    open_acts = [a for a in schedule.activities.values() if a.in_network and not a.is_complete]
    stored = [a for a in open_acts if a.total_float is not None]
    use_stored = bool(open_acts) and len(stored) >= 0.9 * len(open_acts)
    floats: dict[str, float] = {}
    for a in open_acts:
        computed = cpm.tf.get(a.uid)
        if computed is not None and a.calendar_days_per_week:
            computed = computed * a.calendar_days_per_week / schedule.calendar.days_per_week
        if use_stored and a.total_float is not None:
            floats[a.uid] = a.total_float
        elif computed is not None:
            floats[a.uid] = computed
    label = (
        "Exported by the scheduling tool"
        if use_stored
        else "Recalculated by the built-in CPM engine"
    )
    return floats, label


def _exemptions(ctx: Context) -> None:
    dated = [a for a in ctx.network if a.start]
    if dated:
        first = min(dated, key=lambda a: (a.start, a.type != ActivityType.START_MILESTONE))
        if not ctx.network_preds(first.uid):
            ctx.exempt_open_start = first.uid
    finished = [a for a in ctx.network if a.finish]
    if finished:
        last = max(finished, key=lambda a: (a.finish, a.is_milestone))
        if not ctx.network_succs(last.uid):
            ctx.exempt_open_finish = last.uid


def _stats(ctx: Context) -> dict:
    sched = ctx.schedule
    acts = list(sched.activities.values())
    by_type = {TYPE_LABELS[t]: sum(1 for a in acts if a.type == t) for t in ActivityType}
    by_status = {
        STATUS_LABELS[s]: sum(1 for a in acts if a.status == s and a.in_network) for s in Status
    }
    histogram = []
    floats = [ctx.float_days[a.uid] for a in ctx.incomplete if a.uid in ctx.float_days]
    for label, _ in FLOAT_BINS:
        histogram.append({"label": label, "count": 0})
    for f in floats:
        for i, (_, test) in enumerate(FLOAT_BINS):
            if test(f, sched.critical_float):
                histogram[i]["count"] += 1
                break
    network_links = [
        r
        for r in sched.relationships
        if sched.activities[r.pred].in_network and sched.activities[r.succ].in_network
    ]
    total = sum(a.duration for a in ctx.network if a.is_task)
    done = sum(a.duration - a.remaining_duration for a in ctx.network if a.is_task)
    return {
        "activities": len(acts),
        "by_type": by_type,
        "by_status": by_status,
        "relationships": len(network_links),
        "relationship_types": {
            t.value: sum(1 for r in network_links if r.type == t) for t in RelType
        },
        "incomplete": len(ctx.incomplete),
        "critical": sum(1 for a in ctx.incomplete if ctx.is_critical(a.uid)),
        "near_critical": sum(1 for f in floats if sched.critical_float + EPS < f <= 10 + EPS),
        "float_histogram": histogram,
        "duration_complete_pct": round(100.0 * done / total, 1) if total else 0.0,
    }


def _dates(ctx: Context) -> dict:
    sched, cpm = ctx.schedule, ctx.cpm
    finishes = [a.finish for a in ctx.network if a.finish]
    forecast = sched.scheduled_finish or (max(finishes) if finishes else None)
    if forecast is None and cpm.finish_activity:
        forecast = sched.calendar.datetime_at(sched.data_date, cpm.finish, finish=True)
    baselines = [a.baseline_finish for a in ctx.network if a.baseline_finish]
    baseline = max(baselines) if baselines else None
    starts = [a.start for a in ctx.network if a.start]
    variance = None
    if forecast and baseline:
        variance = sched.calendar.count(baseline.date(), forecast.date())
    return {
        "data_date": fmt_date(sched.data_date),
        "start": fmt_date(sched.planned_start or (min(starts) if starts else None)),
        "forecast_finish": fmt_date(forecast),
        "baseline_finish": fmt_date(baseline),
        "deadline": fmt_date(
            sched.deadline or max((a.deadline for a in ctx.network if a.deadline), default=None)
        ),
        "finish_variance_days": variance,
    }


def _lookahead(ctx: Context, board: dict | None) -> dict:
    s = ctx.settings
    window = [a for a in ctx.incomplete if ctx.in_window(a, s.lookahead_weeks)]
    trades: dict[str, int] = {}
    for a in window:
        trades[a.trade or "Unassigned"] = trades.get(a.trade or "Unassigned", 0) + 1
    return {
        "weeks": s.lookahead_weeks,
        "end": fmt_date(ctx.lookahead_end),
        "activities": len(window),
        "in_progress": sum(1 for a in window if a.is_started),
        "critical": sum(1 for a in window if ctx.is_critical(a.uid)),
        "by_trade": sorted(
            ({"trade": t, "count": n} for t, n in trades.items()), key=lambda x: -x["count"]
        ),
        "board": board,
    }


def analyze(
    schedule: Schedule,
    settings: Settings | None = None,
    weekly_plans: bytes | str | Path | None = None,
    constraints: bytes | str | Path | None = None,
    dayfirst: bool = False,
) -> dict:
    """Analyse a schedule. Optional Last Planner inputs are CSV bytes or paths."""
    settings = settings or Settings()
    cpm = compute_cpm(schedule)
    filled = _fill_dates(schedule, cpm)
    floats, float_source = _choose_float(schedule, cpm)
    mapping = resolve_mapping(schedule, settings.trade_field, settings.location_field)
    ctx = Context(schedule, cpm, settings, floats, float_source)
    _exemptions(ctx)

    integrity = run_integrity(ctx)
    flow = analyze_flow(ctx)

    weekly = log = board = None
    lps_errors: list[str] = []
    codes = {a.code.lower() for a in schedule.activities.values()}
    raw_weekly, raw_constraints = _read(weekly_plans), _read(constraints)
    if raw_weekly is not None:
        try:
            weekly = analyze_weekly_plans(
                parse_weekly_plans(raw_weekly, dayfirst), settings.ppc_target, codes
            )
        except ValueError as exc:
            lps_errors.append(f"Weekly work plans: {exc}")
    if raw_constraints is not None:
        try:
            rows = parse_constraints(raw_constraints, dayfirst)
            log = analyze_constraints(rows, schedule.data_date, settings.make_ready_weeks)
            board = readiness.make_ready_board(ctx, rows)
        except ValueError as exc:
            lps_errors.append(f"Constraint log: {exc}")

    lean_checks = readiness.run(ctx, mapping, flow, board, weekly, log)
    all_checks = integrity + lean_checks
    top = sorted(
        (c for c in all_checks if c.status == FAIL),
        key=lambda c: -(c.weight * (1.0 - (c.score or 0.0))),
    )[:8]
    acts = schedule.activities
    cpt = next((c.details.get("test") for c in integrity if c.id == "DCMA-12"), None)
    result = {
        "tool": {"name": TOOL_NAME, "version": __version__},
        "generated_at": datetime.now().replace(microsecond=0).isoformat(),
        "project": {
            "name": schedule.name,
            "code": schedule.project_code,
            "source_name": schedule.source_name,
            "source_format": {
                "xer": "Primavera P6 XER",
                "mspdi": "Microsoft Project XML",
                "csv": "CSV",
            }.get(schedule.source_format, schedule.source_format),
            "calendar": schedule.calendar.describe(),
            "float_source": float_source,
            "baseline_source": schedule.baseline_source or "None",
            "critical_float": schedule.critical_float,
            "other_projects": schedule.other_projects,
            "warnings": schedule.warnings + mapping.get("warnings", []) + lps_errors,
            "dates_computed": filled,
        },
        "dates": _dates(ctx),
        "stats": _stats(ctx),
        "mapping": mapping,
        "settings": settings.to_dict(),
        "scores": {"integrity": group_score(integrity), "lean": group_score(lean_checks)},
        "checks": [c.to_dict() for c in all_checks],
        "top_issues": [
            {
                "id": c.id,
                "group": c.group,
                "name": c.name,
                "metric": c.metric,
                "threshold": c.threshold,
                "count": c.count,
                "recommendation": c.recommendation,
            }
            for c in top
        ],
        "critical_path": {
            "origin": cpm.path_origin,
            "length": len(cpm.longest_path),
            "remaining_days": round(cpm.finish, 1),
            "activities": [
                {
                    "id": acts[u].code,
                    "name": acts[u].name,
                    "start": fmt_date(acts[u].start),
                    "finish": fmt_date(acts[u].finish),
                    "float": round(floats.get(u, 0.0), 1),
                }
                for u in cpm.longest_path
            ],
            "test": cpt,
            "loops": len(cpm.cycles),
        },
        "lookahead": _lookahead(ctx, board),
        "flow": flow,
        "lps": {"weekly": weekly, "constraints": log},
        "wastes": waste_lens(all_checks),
    }
    from .ai import offline_summary  # local import: ai imports nothing from here

    result["narrative"] = offline_summary(result)
    return result
