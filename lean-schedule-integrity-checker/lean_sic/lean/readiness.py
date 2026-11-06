"""Lean readiness checks: is this schedule ready to run with Lean methods?

A CPM schedule can pass every DCMA test and still be hard to deliver with
the Last Planner System or takt planning. These checks look at the
*lookahead* window and at workflow: is work small enough to promise weekly,
does everyone know who and where, does work flow without waiting or
crowding, are constraints being removed before work starts, and are weekly
promises kept (PPC)?
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta

from ..checks.base import (
    FAIL,
    NA,
    PASS,
    CheckResult,
    activity_row,
    fmt_date,
    fmt_days,
    fmt_pct,
    ratio_result,
    score_at_least,
    score_at_most,
)
from ..context import Context
from ..cpm import EPS
from ..model import CONSTRAINT_LABELS, ConstraintType

GROUP = "Lean readiness"


def _na(base: CheckResult, note: str) -> CheckResult:
    base.status, base.metric, base.score, base.note = NA, "n/a", None, note
    return base


def check_lookahead_granularity(ctx: Context) -> CheckResult:
    s = ctx.settings
    window = [a for a in ctx.incomplete_tasks if ctx.in_window(a, s.lookahead_weeks)]
    base = CheckResult(
        "LEAN-01",
        GROUP,
        "Lookahead granularity",
        f"Tasks in the {s.lookahead_weeks}-week lookahead with more than {fmt_days(s.lean_max_task_days)} "
        "working days remaining. Weekly work plans need assignments a crew can promise and finish "
        "within a week, so lookahead work should already be broken down.",
        severity="medium",
        weight=8,
        wastes=["Inventory", "Mura (unevenness)"],
        recommendation="In the lookahead meeting split long tasks by zone or by step (e.g. 'Board "
        "level 2 zone A') so each can be committed in a weekly plan.",
    )
    rows = [
        activity_row(
            a,
            **{
                "Remaining (d)": fmt_days(a.remaining_duration),
                "Start": fmt_date(a.start),
                "Trade": a.trade or "",
            },
        )
        for a in sorted(window, key=lambda a: -a.remaining_duration)
        if a.remaining_duration > s.lean_max_task_days + EPS
    ]
    return ratio_result(base, rows, len(window), 15.0, s.item_limit)


def check_responsibility(ctx: Context, mapping: dict) -> CheckResult:
    s = ctx.settings
    window = [a for a in ctx.incomplete_tasks if ctx.in_window(a, s.lookahead_weeks)]
    base = CheckResult(
        "LEAN-02",
        GROUP,
        "Who: responsible trade",
        "Lookahead tasks with a responsible trade, crew or company. In the Last Planner System "
        "the person who will do the work makes the promise, so every task needs an owner.",
        severity="high",
        weight=7,
        wastes=["Non-utilised talent"],
        recommendation="Add a trade / responsible-company activity code (or assign the crew "
        "resource) to every lookahead task.",
        note=f"Trade source: {mapping['trade']['label']}",
    )
    rows = [activity_row(a, Start=fmt_date(a.start)) for a in window if not a.trade]
    return ratio_result(base, rows, len(window), 95.0, s.item_limit, at_least=True)


def check_location(ctx: Context, mapping: dict) -> CheckResult:
    s = ctx.settings
    tasks = ctx.incomplete_tasks
    base = CheckResult(
        "LEAN-03",
        GROUP,
        "Where: location / zone",
        "Incomplete tasks with a location (zone, level, area). Location-based and takt planning "
        "manage the flow of trades through spaces, which is impossible without locations.",
        severity="medium",
        weight=6,
        wastes=["Motion", "Transportation"],
        recommendation="Add a location breakdown structure (activity code such as 'Zone') and code "
        "every task to it.",
        note=f"Location source: {mapping['location']['label']}",
    )
    rows = [activity_row(a, Trade=a.trade or "") for a in tasks if not a.location]
    return ratio_result(base, rows, len(tasks), 80.0, s.item_limit, at_least=True)


def check_push_constraints(ctx: Context) -> CheckResult:
    s = ctx.settings
    window = [a for a in ctx.incomplete if ctx.in_window(a, s.lookahead_weeks)]
    base = CheckResult(
        "LEAN-04",
        GROUP,
        "Push constraints in the lookahead",
        "Lookahead activities held to a date constraint. Lean planning *pulls* work from the "
        "next customer's need; date constraints push work by the calendar instead and hide "
        "whether the work is really ready.",
        severity="medium",
        weight=5,
        wastes=["Overproduction"],
        recommendation="Replace date constraints with logic from the hand-off that really "
        "releases the work (pull-plan the milestone with the trades).",
    )
    rows = []
    for a in window:
        cons = [(c, d) for c, d in a.constraints if c != ConstraintType.AS_LATE_AS_POSSIBLE]
        if cons:
            rows.append(
                activity_row(a, Constraint=CONSTRAINT_LABELS[cons[0][0]], Date=fmt_date(cons[0][1]))
            )
    return ratio_result(base, rows, len(window), 5.0, s.item_limit)


def check_stalled_wip(ctx: Context) -> CheckResult:
    s = ctx.settings
    wip = [a for a in ctx.incomplete_tasks if a.is_started]
    base = CheckResult(
        "LEAN-05",
        GROUP,
        "Slow or stalled work in progress",
        f"In-progress tasks running for at least {fmt_days(s.stalled_min_days)} working days and "
        "progressing at less than half the planned rate. Open work fronts that do not move tie "
        "up crews, space and materials (work-in-progress inventory).",
        severity="medium",
        weight=5,
        wastes=["Inventory", "Waiting"],
        recommendation="Finish what is started before opening new fronts: review stalled tasks "
        "in the daily huddle and remove what blocks them.",
    )
    rows = []
    for a in wip:
        if not a.actual_start or a.duration <= EPS:
            continue
        elapsed = ctx.schedule.calendar.count(a.actual_start.date(), ctx.data_date.date())
        if elapsed < s.stalled_min_days:
            continue
        expected = min(1.0, elapsed / a.duration)
        progress = (
            (a.percent_complete / 100.0)
            if a.percent_complete is not None
            else 1.0 - a.remaining_duration / a.duration
        )
        if progress < 0.5 * expected - EPS:
            rows.append(
                activity_row(
                    a,
                    **{
                        "Elapsed (d)": elapsed,
                        "Progress": fmt_pct(round(100 * progress, 1)),
                        "Expected": fmt_pct(round(100 * expected, 1)),
                        "Trade": a.trade or "",
                    },
                )
            )
    base.details = {
        "wip": len(wip),
        "wip_by_trade": dict(Counter(a.trade or "Unassigned" for a in wip).most_common()),
    }
    return ratio_result(base, rows, len(wip), 10.0, s.item_limit)


def check_trade_flow(ctx: Context, flow: dict) -> CheckResult:
    s = ctx.settings
    base = CheckResult(
        "LEAN-06",
        GROUP,
        "Trade flow continuity",
        f"Gaps longer than {fmt_days(s.trade_gap_days)} working days between a trade's consecutive "
        "work periods. Every gap means a crew waits, demobilises or is moved elsewhere and the "
        "learning curve is lost.",
        severity="medium",
        weight=6,
        wastes=["Waiting", "Transportation", "Non-utilised talent"],
        recommendation="Sequence each trade's work so it flows zone to zone; use takt planning to "
        "give every trade a continuous run of work.",
    )
    data = flow.get("continuity")
    if not data or not data["rows"]:
        return _na(base, "Map a trade field to measure trade flow.")
    rows = [
        {
            "Trade": r["trade"],
            "Activities": r["activities"],
            "Work periods": r["periods"],
            f"Gaps > {fmt_days(s.trade_gap_days)} d": r["long_gaps"],
            "Longest gap (d)": r["longest_gap"],
            "Work density": fmt_pct(r["density"]),
        }
        for r in data["rows"]
    ]
    if data["total_gaps"] == 0:
        base.status, base.score, base.metric, base.value = PASS, 1.0, "0%", 0.0
        base.items, base.total_items, base.threshold = rows, len(rows), "<= 20%"
        base.note = "Every trade has one continuous run of remaining work."
        return base
    result = ratio_result(
        base, rows, data["total_gaps"], 20.0, s.item_limit, flagged_count=data["long_gaps"]
    )
    result.note = f"{data['long_gaps']} of {data['total_gaps']} trade re-entries wait longer than {fmt_days(s.trade_gap_days)} days."
    return result


def check_stacking(ctx: Context, flow: dict) -> CheckResult:
    s = ctx.settings
    base = CheckResult(
        "LEAN-07",
        GROUP,
        "Trade stacking",
        "Zone-days where two or more trades are planned in the same location at the same time. "
        "Stacked trades get in each other's way, raise safety risk and erode productivity.",
        severity="medium",
        weight=6,
        wastes=["Motion", "Muri (overburden)", "Defects"],
        recommendation="Give each zone to one trade at a time (takt wagons); re-sequence or "
        "re-zone the hotspots listed below.",
        threshold="<= 15%",
    )
    data = flow.get("stacking")
    if not data or not data["occupied_zone_days"]:
        return _na(base, "Map trade and location fields to measure trade stacking.")
    rows = [
        {
            "Zone": h["zone"],
            "From": h["start"],
            "To": h["finish"],
            "Days": h["days"],
            "Max trades": h["max_trades"],
            "Trades": ", ".join(h["trades"]),
        }
        for h in data["hotspots"]
    ]
    base.count, base.population = data["stacked_zone_days"], data["occupied_zone_days"]
    base.items, base.total_items = rows[: s.item_limit], len(rows)
    pct = data["pct"]
    base.value, base.metric = pct, fmt_pct(pct)
    base.score = score_at_most(pct, 15.0)
    base.status = PASS if pct <= 15.0 + 1e-9 else FAIL
    base.note = f"Up to {data['max_trades']} trades share a zone on the same day."
    return base


def check_takt_balance(ctx: Context, flow: dict) -> CheckResult:
    base = CheckResult(
        "LEAN-08",
        GROUP,
        "Takt balance",
        "Average variation (coefficient of variation) of each trade's work content across the "
        "repeating zones. A balanced takt plan gives each trade about the same amount of work in "
        "every zone, so all trades can move at one rhythm.",
        severity="medium",
        weight=5,
        wastes=["Mura (unevenness)", "Waiting"],
        recommendation="Re-size zones or adjust crew sizes so each trade's work per zone fits one "
        "takt time; see the suggested takt plan.",
        threshold="<= 0.35",
    )
    takt = flow.get("takt") or {}
    if not takt.get("available"):
        return _na(base, takt.get("reason", "Takt analysis not available."))
    cv = takt["avg_cv"]
    base.value, base.metric = cv, f"{cv:.2f}"
    base.population, base.count = len(takt["trades"]), sum(
        1 for t in takt["trades"] if t["cv"] > 0.35
    )
    base.score = 1.0 if cv <= 0.35 else max(0.0, 1.0 - (cv - 0.35) / 0.65)
    base.status = PASS if cv <= 0.35 + 1e-9 else FAIL
    base.items = [
        {
            "Trade": t["trade"],
            "Zones": t["zones"],
            "Min (d)": fmt_days(t["min"]),
            "Median (d)": fmt_days(t["median"]),
            "Max (d)": fmt_days(t["max"]),
            "Variation (CV)": f"{t['cv']:.2f}",
        }
        for t in sorted(takt["trades"], key=lambda t: -t["cv"])
    ]
    base.total_items = len(base.items)
    return base


def make_ready_board(ctx: Context, constraints: list[dict]) -> dict:
    """Join the constraint log to lookahead activities (the make-ready board)."""
    acts = ctx.schedule.activities
    by_code = {a.code.lower(): a for a in acts.values()}
    linked: dict[str, list[dict]] = defaultdict(list)
    unlinked = []
    for c in constraints:
        hits = [by_code[x.lower()] for x in c["activity_ids"] if x.lower() in by_code]
        for a in hits:
            linked[a.uid].append(c)
        if not hits:
            unlinked.append(c)
    dd = ctx.data_date
    window = sorted(
        (a for a in ctx.incomplete if ctx.in_window(a, ctx.settings.lookahead_weeks)),
        key=lambda a: (a.start is None, a.start),
    )
    rows = []
    for a in window:
        open_c = [c for c in linked.get(a.uid, []) if c["open"]]
        overdue = [c for c in open_c if c["need_by"] and c["need_by"].date() < dd.date()]
        late = [
            c for c in open_c if c["need_by"] and a.start and c["need_by"].date() > a.start.date()
        ]
        status = "Ready" if not open_c else ("Overdue constraint" if overdue else "Constrained")
        rows.append(
            {
                "uid": a.uid,
                "id": a.code,
                "name": a.name,
                "trade": a.trade or "",
                "location": a.location or "",
                "start": fmt_date(a.start),
                "status": status,
                "open": len(open_c),
                "late_removal": len(late),
                "constraints": "; ".join(
                    f"{c['id']} {c['category']} ({c['owner']})" for c in open_c
                ),
            }
        )
    soon = dd + timedelta(weeks=ctx.settings.make_ready_weeks)
    return {
        "rows": rows,
        "ready": sum(1 for r in rows if r["status"] == "Ready"),
        "constrained": sum(1 for r in rows if r["status"] == "Constrained"),
        "overdue": sum(1 for r in rows if r["status"] == "Overdue constraint"),
        "soon_end": soon.date().isoformat(),
        "unlinked": [
            {
                "id": c["id"],
                "description": c["description"],
                "activities": ", ".join(c["activity_ids"]),
            }
            for c in unlinked
        ],
        "linked_constraints": sum(len(v) for v in linked.values()),
    }


def check_make_ready(ctx: Context, board: dict | None) -> CheckResult:
    s = ctx.settings
    base = CheckResult(
        "LEAN-09",
        GROUP,
        "Make-ready: constraint-free near-term work",
        f"Activities starting in the next {s.make_ready_weeks} weeks that still have open "
        "constraints. Work should only enter a weekly plan when it can be done (Last Planner "
        "'should - can - will - did').",
        severity="high",
        weight=7,
        wastes=["Waiting"],
        recommendation="Screen every lookahead activity for the seven flows (information, "
        "materials, labour, equipment, prior work, space, external) and remove constraints "
        "before the work is planned.",
    )
    if board is None:
        return _na(base, "Upload a constraint log to measure make-ready status.")
    soon = ctx.data_date + timedelta(weeks=s.make_ready_weeks)
    acts = ctx.schedule.activities
    near = [r for r in board["rows"] if acts[r["uid"]].start is None or acts[r["uid"]].start < soon]
    rows = [
        {
            "Activity ID": r["id"],
            "Activity name": r["name"],
            "Start": r["start"],
            "Status": r["status"],
            "Open constraints": r["constraints"],
        }
        for r in near
        if r["status"] != "Ready"
    ]
    return ratio_result(base, rows, len(near), 10.0, s.item_limit)


def check_ppc(ctx: Context, weekly: dict | None) -> CheckResult:
    s = ctx.settings
    base = CheckResult(
        "LEAN-10",
        GROUP,
        "Plan reliability (PPC)",
        f"Percent Plan Complete over the last four weeks: weekly promises kept / promises made. "
        f"Reliable promises (PPC around {fmt_pct(s.ppc_target)} or more) are what make workflow "
        "predictable for the next trade.",
        severity="high",
        weight=8,
        wastes=["Mura (unevenness)", "Waiting"],
        recommendation="Only commit to sound (constraint-free) work, review every miss in the "
        "weekly meeting and act on the top reasons for non-completion.",
        threshold=f">= {fmt_pct(s.ppc_target)}",
    )
    if weekly is None or weekly.get("ppc_last4") is None:
        return _na(base, "Upload weekly work plans to measure PPC.")
    ppc = weekly["ppc_last4"]
    base.value, base.metric = ppc, fmt_pct(ppc)
    base.population, base.count = weekly["commitments"], weekly["misses"]
    base.score = score_at_least(ppc, s.ppc_target)
    base.status = PASS if ppc >= s.ppc_target - 1e-9 else FAIL
    trend = weekly["trend_per_week"]
    base.note = f"Trend {trend:+.1f} points per week; overall PPC {fmt_pct(weekly['ppc_overall'])}."
    base.items = [
        {
            "Trade": t["trade"],
            "Promises": t["planned"],
            "Kept": t["completed"],
            "PPC": fmt_pct(t["ppc"]),
            "PPC last 4 weeks": fmt_pct(t["ppc_last4"]) if t["ppc_last4"] is not None else "",
        }
        for t in weekly["trades"]
    ]
    base.total_items = len(base.items)
    return base


def check_overdue_constraints(ctx: Context, log: dict | None) -> CheckResult:
    base = CheckResult(
        "LEAN-11",
        GROUP,
        "Overdue constraints",
        "Open constraints whose need-by date has passed. A constraint log only works if "
        "constraints are removed before the work needs them.",
        severity="medium",
        weight=5,
        wastes=["Waiting"],
        recommendation="Review overdue constraints with their owners every week and escalate the "
        "ones that block near-term work.",
    )
    if log is None:
        return _na(base, "Upload a constraint log to track constraint removal.")
    rows = [
        {
            "Constraint": r["id"],
            "Description": r["description"],
            "Category": r["category"],
            "Owner": r["owner"],
            "Need by": r["need_by"],
        }
        for r in log["overdue_rows"]
    ]
    return ratio_result(base, rows, log["open"], 10.0, ctx.settings.item_limit)


def run(
    ctx: Context,
    mapping: dict,
    flow: dict,
    board: dict | None,
    weekly: dict | None,
    log: dict | None,
) -> list[CheckResult]:
    return [
        check_lookahead_granularity(ctx),
        check_responsibility(ctx, mapping),
        check_location(ctx, mapping),
        check_push_constraints(ctx),
        check_stalled_wip(ctx),
        check_trade_flow(ctx, flow),
        check_stacking(ctx, flow),
        check_takt_balance(ctx, flow),
        check_make_ready(ctx, board),
        check_ppc(ctx, weekly),
        check_overdue_constraints(ctx, log),
    ]
