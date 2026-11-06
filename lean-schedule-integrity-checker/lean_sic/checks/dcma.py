"""The DCMA 14-Point Schedule Assessment.

Published by the US Defense Contract Management Agency, it is the de facto
baseline for schedule quality reviews (and the starting point that nPlan's
Schedule Integrity Checker extends). Populations follow common practice:
incomplete tasks and milestones; level-of-effort and summary activities are
excluded.
"""

from __future__ import annotations

from ..context import Context
from ..cpm import EPS, critical_path_test
from ..model import CONSTRAINT_LABELS, HARD_CONSTRAINTS, TYPE_LABELS, Relationship, RelType
from .base import (
    FAIL,
    INFO,
    NA,
    PASS,
    CheckResult,
    activity_row,
    fmt_date,
    fmt_days,
    ratio_result,
    score_index,
)

GROUP = "DCMA 14-Point"


def open_links(ctx: Context) -> list[Relationship]:
    """Relationships between network activities whose successor is not finished."""
    acts = ctx.schedule.activities
    return [
        r
        for r in ctx.schedule.relationships
        if r.pred in acts
        and r.succ in acts
        and acts[r.pred].in_network
        and acts[r.succ].in_network
        and not acts[r.succ].is_complete
    ]


def link_row(ctx: Context, rel: Relationship, **extra) -> dict:
    acts = ctx.schedule.activities
    row = {
        "Predecessor": acts[rel.pred].code,
        "Successor": acts[rel.succ].code,
        "Type": rel.type.value,
        "Lag (d)": fmt_days(rel.lag),
    }
    row.update(extra)
    row["Successor name"] = acts[rel.succ].name
    return row


def check_logic(ctx: Context) -> CheckResult:
    base = CheckResult(
        "DCMA-01",
        GROUP,
        "Missing logic",
        "Incomplete activities without a predecessor and/or a successor. Open ends let work "
        "float freely, so delays do not ripple through the network and float is overstated.",
        severity="high",
        weight=10,
        wastes=["Defects"],
        recommendation="Give every activity a driving predecessor and a successor. Only the project "
        "start and finish milestones should have an open end.",
    )
    rows = []
    for a in ctx.incomplete:
        no_pred = not ctx.network_preds(a.uid) and a.uid != ctx.exempt_open_start
        no_succ = not ctx.network_succs(a.uid) and a.uid != ctx.exempt_open_finish
        if no_pred or no_succ:
            issue = (
                "No predecessor or successor"
                if no_pred and no_succ
                else "No predecessor" if no_pred else "No successor"
            )
            rows.append(activity_row(a, Issue=issue, Type=TYPE_LABELS[a.type]))
    return ratio_result(base, rows, len(ctx.incomplete), 5.0, ctx.settings.item_limit)


def check_leads(ctx: Context) -> CheckResult:
    links = open_links(ctx)
    base = CheckResult(
        "DCMA-02",
        GROUP,
        "Leads (negative lag)",
        "Relationships with a negative lag let a successor start before its predecessor is done. "
        "Leads are hard to see, distort the critical path and usually mean overlapping work.",
        severity="high",
        weight=5,
        wastes=["Defects", "Muri (overburden)"],
        recommendation="Replace leads with start-to-start links or split the predecessor so the "
        "overlap is explicit.",
    )
    rows = [link_row(ctx, r) for r in links if r.lag < -EPS]
    return ratio_result(base, rows, len(links), 0.0, ctx.settings.item_limit)


def check_lags(ctx: Context) -> CheckResult:
    links = open_links(ctx)
    base = CheckResult(
        "DCMA-03",
        GROUP,
        "Lags",
        "Relationships with a positive lag. Lags are waiting time nobody owns; they often hide "
        "work such as curing, approvals or deliveries that should be visible activities.",
        severity="medium",
        weight=4,
        wastes=["Waiting"],
        recommendation="Model the waiting time as an activity with an owner (e.g. 'Cure slab', "
        "'Client approval') instead of a lag.",
    )
    rows = sorted(
        (link_row(ctx, r) for r in links if r.lag > EPS), key=lambda x: -float(x["Lag (d)"])
    )
    return ratio_result(base, rows, len(links), 5.0, ctx.settings.item_limit)


def check_relationship_types(ctx: Context) -> CheckResult:
    links = open_links(ctx)
    counts = {t.value: sum(1 for r in links if r.type == t) for t in RelType}
    base = CheckResult(
        "DCMA-04",
        GROUP,
        "Finish-to-start relationships",
        "Share of relationships that are finish-to-start. Heavy use of start-to-start and "
        "finish-to-finish links makes the critical path hard to follow.",
        severity="low",
        weight=3,
        wastes=[],
        recommendation="Prefer finish-to-start logic; break overlapping work into smaller "
        "activities that hand over cleanly.",
        details={"relationship_types": counts},
    )
    rows = [link_row(ctx, r) for r in links if r.type != RelType.FS]
    return ratio_result(base, rows, len(links), 90.0, ctx.settings.item_limit, at_least=True)


def check_hard_constraints(ctx: Context) -> CheckResult:
    base = CheckResult(
        "DCMA-05",
        GROUP,
        "Hard constraints",
        "Constraints that stop dates moving with the logic (start/finish on, on or before, "
        "mandatory). They mask delays and create artificial float or negative float.",
        severity="high",
        weight=7,
        wastes=["Overproduction", "Mura (unevenness)"],
        recommendation="Replace hard constraints with logic; keep contractual dates as deadlines "
        "or soft constraints and track the float against them.",
    )
    rows = []
    for a in ctx.incomplete:
        for c, d in a.constraints:
            if c in HARD_CONSTRAINTS:
                rows.append(activity_row(a, Constraint=CONSTRAINT_LABELS[c], Date=fmt_date(d)))
                break
    return ratio_result(base, rows, len(ctx.incomplete), 5.0, ctx.settings.item_limit)


def _float_population(ctx: Context):
    return [a for a in ctx.incomplete if ctx.float_days.get(a.uid) is not None]


def check_high_float(ctx: Context) -> CheckResult:
    limit = ctx.settings.high_float_days
    pop = _float_population(ctx)
    base = CheckResult(
        "DCMA-06",
        GROUP,
        "High float",
        f"Incomplete activities with more than {fmt_days(limit)} working days of total float. "
        "High float usually means missing successors or logic that does not reflect reality.",
        severity="medium",
        weight=5,
        wastes=["Inventory", "Overproduction"],
        recommendation="Check the successors of high-float work; tie it to the activity that "
        "really needs it so float is honest.",
        threshold="<= 5%",
    )
    rows = [
        activity_row(a, **{"Total float (d)": fmt_days(ctx.float_days[a.uid])})
        for a in sorted(pop, key=lambda a: -ctx.float_days[a.uid])
        if ctx.float_days[a.uid] > limit + EPS
    ]
    return ratio_result(base, rows, len(pop), 5.0, ctx.settings.item_limit)


def check_negative_float(ctx: Context) -> CheckResult:
    pop = _float_population(ctx)
    base = CheckResult(
        "DCMA-07",
        GROUP,
        "Negative float",
        "Incomplete activities with less than zero total float: the plan cannot meet a constraint "
        "or deadline as it stands.",
        severity="high",
        weight=8,
        wastes=["Muri (overburden)", "Waiting"],
        recommendation="Agree a recovery plan (re-sequence, add crews, pull-plan the milestone) or "
        "formally re-baseline the date that cannot be met.",
    )
    rows = [
        activity_row(a, **{"Total float (d)": fmt_days(ctx.float_days[a.uid])})
        for a in sorted(pop, key=lambda a: ctx.float_days[a.uid])
        if ctx.float_days[a.uid] < -EPS
    ]
    return ratio_result(base, rows, len(pop), 0.0, ctx.settings.item_limit)


def check_high_duration(ctx: Context) -> CheckResult:
    limit = ctx.settings.high_duration_days
    pop = ctx.incomplete_tasks
    base = CheckResult(
        "DCMA-08",
        GROUP,
        "High duration",
        f"Incomplete tasks with an original duration above {fmt_days(limit)} working days. Long "
        "activities are hard to status and hide the real sequence of work.",
        severity="medium",
        weight=5,
        wastes=["Inventory", "Mura (unevenness)"],
        recommendation="Break long activities down by location or work package so progress and "
        "hand-offs can be measured.",
    )
    rows = [
        activity_row(a, **{"Duration (d)": fmt_days(a.duration)})
        for a in sorted(pop, key=lambda a: -a.duration)
        if a.duration > limit + EPS
    ]
    return ratio_result(base, rows, len(pop), 5.0, ctx.settings.item_limit)


def check_invalid_dates(ctx: Context) -> CheckResult:
    dd = ctx.data_date.date()
    base = CheckResult(
        "DCMA-09",
        GROUP,
        "Invalid dates",
        "Actual dates after the data date, or forecast dates before it. Either means progress "
        "was recorded incorrectly or the schedule was not recalculated.",
        severity="high",
        weight=8,
        wastes=["Defects"],
        recommendation="Re-status the activities (actuals must be in the past, forecasts in the "
        "future) and reschedule from the data date.",
    )
    rows = []
    for a in ctx.network:
        issues = []
        if a.actual_start and a.actual_start.date() > dd:
            issues.append("Actual start after data date")
        if a.actual_finish and a.actual_finish.date() > dd:
            issues.append("Actual finish after data date")
        if not a.is_complete:
            if not a.is_started and a.early_start and a.early_start.date() < dd:
                issues.append("Forecast start before data date")
            if a.early_finish and a.early_finish.date() < dd:
                issues.append("Forecast finish before data date")
        if issues:
            rows.append(activity_row(a, Issue="; ".join(issues)))
    return ratio_result(base, rows, len(ctx.network), 0.0, ctx.settings.item_limit)


def check_resources(ctx: Context) -> CheckResult:
    pop = [a for a in ctx.incomplete_tasks if a.duration > EPS]
    base = CheckResult(
        "DCMA-10",
        GROUP,
        "Resources",
        "Incomplete tasks without resources. Without crews or cost on each task the plan "
        "cannot be checked for capacity.",
        severity="low",
        weight=2,
        wastes=["Muri (overburden)"],
        recommendation="Assign the crew or trade that will do each task (Lean check LEAN-02 "
        "covers responsibility for the lookahead).",
    )
    if not ctx.schedule.has_resources:
        base.status, base.metric, base.score = INFO, "Not loaded", None
        base.population = len(pop)
        base.note = "The schedule has no resource assignments, so this check is informational."
        return base
    rows = [
        activity_row(a, **{"Duration (d)": fmt_days(a.duration)}) for a in pop if not a.resources
    ]
    return ratio_result(base, rows, len(pop), 0.0, ctx.settings.item_limit)


def _baselined_tasks(ctx: Context):
    dd = ctx.data_date.date()
    return [
        a
        for a in ctx.network
        if a.is_task and a.baseline_finish is not None and a.baseline_finish.date() <= dd
    ]


def check_missed_tasks(ctx: Context) -> CheckResult:
    base = CheckResult(
        "DCMA-11",
        GROUP,
        "Missed tasks",
        "Tasks planned (baseline) to finish by the data date that finished late or are not "
        "finished. A high share means the plan is not being delivered as promised.",
        severity="medium",
        weight=6,
        wastes=["Waiting", "Mura (unevenness)"],
        recommendation="Run a root-cause review of missed work (the Last Planner 'reasons for "
        "non-completion') and fix the most common causes.",
        note=f"Baseline: {ctx.schedule.baseline_source}" if ctx.schedule.baseline_source else "",
    )
    if not ctx.schedule.has_baseline:
        base.status, base.metric = NA, "No baseline"
        base.note = "No baseline dates found. Export the baseline with the schedule."
        return base
    pop = _baselined_tasks(ctx)
    rows = []
    for a in pop:
        assert a.baseline_finish is not None
        if not a.is_complete:
            rows.append(
                activity_row(
                    a,
                    **{
                        "Baseline finish": fmt_date(a.baseline_finish),
                        "Actual finish": "Not finished",
                    },
                )
            )
        elif a.actual_finish and a.actual_finish.date() > a.baseline_finish.date():
            rows.append(
                activity_row(
                    a,
                    **{
                        "Baseline finish": fmt_date(a.baseline_finish),
                        "Actual finish": fmt_date(a.actual_finish),
                    },
                )
            )
    return ratio_result(base, rows, len(pop), 5.0, ctx.settings.item_limit)


def check_critical_path_test(ctx: Context) -> CheckResult:
    s = ctx.settings
    base = CheckResult(
        "DCMA-12",
        GROUP,
        "Critical path test",
        f"Adds {fmt_days(s.critical_test_delay)} working days to critical activities and checks "
        "that the project finish moves by the same amount. If it does not, the critical path is "
        "broken by constraints or missing logic.",
        severity="high",
        weight=8,
        wastes=["Defects"],
        recommendation="Trace the critical path from the data date to the finish and remove the "
        "constraint or open end that absorbs the delay.",
        threshold="Finish moves by the full delay",
    )
    cpm = ctx.cpm
    if not cpm.tf:
        base.status, base.metric, base.note = NA, "n/a", "No incomplete critical activities."
        return base
    # The critical path is the lowest-float path: with negative float, "float <= 0"
    # would also catch less-critical branches; with a generous "must finish by"
    # date nothing would have zero float at all.
    lowest = min(cpm.tf.values())
    critical = sorted(
        (u for u, tf in cpm.tf.items() if tf <= lowest + 0.5),
        key=lambda u: (cpm.res[u], cpm.ef[u]),
    )
    base.note = f"Tested the lowest-float path (total float {fmt_days(lowest)} days)."
    test = critical_path_test(
        ctx.schedule, cpm, critical, s.critical_test_delay, s.critical_test_samples
    )
    acts = ctx.schedule.activities
    rows = [
        activity_row(
            acts[t["uid"]],
            **{
                "Finish moved (d)": fmt_days(t["finish_moved_days"]),
                "Result": "Pass" if t["passed"] else "Fail",
            },
        )
        for t in test["tested"]
    ]
    passed = sum(1 for t in test["tested"] if t["passed"])
    base.items, base.total_items = rows, len(rows)
    base.population, base.count = len(rows), len(rows) - passed
    base.status = PASS if test["passed"] else FAIL
    base.score = 1.0 if test["passed"] else 0.0
    base.metric = f"{passed} of {len(rows)} passed"
    base.details = {"test": test}
    return base


def check_cpli(ctx: Context) -> CheckResult:
    cpm = ctx.cpm
    base = CheckResult(
        "DCMA-13",
        GROUP,
        "Critical path length index (CPLI)",
        "(Critical path length + project float) / critical path length. Below 0.95 the remaining "
        "work cannot be finished by the required date without acceleration.",
        severity="medium",
        weight=6,
        wastes=["Muri (overburden)"],
        recommendation="Recover negative float on the critical path or agree a realistic "
        "completion date.",
        threshold=">= 0.95",
    )
    length = cpm.finish
    if length <= EPS or cpm.finish_activity is None:
        base.status, base.metric, base.note = NA, "n/a", "No remaining critical path."
        return base
    project_float = cpm.tf.get(cpm.finish_activity, 0.0)
    cpli = (length + project_float) / length
    base.value = round(cpli, 3)
    base.metric = f"{cpli:.2f}"
    base.score = score_index(cpli)
    base.status = PASS if cpli >= 0.95 - 1e-9 else FAIL
    base.details = {
        "critical_path_length_days": round(length, 1),
        "project_float_days": round(project_float, 1),
    }
    if ctx.schedule.deadline is None and abs(project_float) < EPS:
        base.note = "No 'must finish by' date and no constraint on the finish, so CPLI is 1.00 by definition."
    return base


def check_bei(ctx: Context) -> CheckResult:
    base = CheckResult(
        "DCMA-14",
        GROUP,
        "Baseline execution index (BEI)",
        "Tasks completed / tasks that the baseline planned to finish by the data date. Below "
        "0.95 the team is completing less work than it planned.",
        severity="medium",
        weight=6,
        wastes=["Mura (unevenness)", "Waiting"],
        recommendation="Protect weekly commitments: make work ready before it is planned and "
        "track Percent Plan Complete (PPC) every week.",
        threshold=">= 0.95",
        note=f"Baseline: {ctx.schedule.baseline_source}" if ctx.schedule.baseline_source else "",
    )
    if not ctx.schedule.has_baseline:
        base.status, base.metric = NA, "No baseline"
        base.note = "No baseline dates found. Export the baseline with the schedule."
        return base
    planned = _baselined_tasks(ctx)
    if not planned:
        base.status, base.metric, base.note = (
            NA,
            "n/a",
            "No tasks were planned to finish by the data date.",
        )
        return base
    done = sum(1 for a in ctx.network if a.is_task and a.is_complete)
    bei = done / len(planned)
    base.value, base.metric = round(bei, 3), f"{bei:.2f}"
    base.population, base.count = len(planned), sum(1 for a in planned if not a.is_complete)
    base.score = score_index(bei)
    base.status = PASS if bei >= 0.95 - 1e-9 else FAIL
    rows = [
        activity_row(
            a, **{"Baseline finish": fmt_date(a.baseline_finish), "Status": "Not finished"}
        )
        for a in planned
        if not a.is_complete
    ]
    base.items, base.total_items = rows[: ctx.settings.item_limit], len(rows)
    base.details = {"completed_tasks": done, "planned_tasks": len(planned)}
    return base


def run(ctx: Context) -> list[CheckResult]:
    return [
        check_logic(ctx),
        check_leads(ctx),
        check_lags(ctx),
        check_relationship_types(ctx),
        check_hard_constraints(ctx),
        check_high_float(ctx),
        check_negative_float(ctx),
        check_high_duration(ctx),
        check_invalid_dates(ctx),
        check_resources(ctx),
        check_missed_tasks(ctx),
        check_critical_path_test(ctx),
        check_cpli(ctx),
        check_bei(ctx),
    ]
