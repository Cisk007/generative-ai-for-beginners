"""Integrity checks that go beyond the DCMA 14 points."""

from __future__ import annotations

from collections import Counter

from ..context import Context
from ..cpm import EPS
from ..model import CONSTRAINT_LABELS, HARD_CONSTRAINTS, TYPE_LABELS, ActivityType, RelType
from .base import (
    FAIL,
    INFO,
    NA,
    PASS,
    CheckResult,
    activity_row,
    fmt_date,
    fmt_days,
    fmt_pct,
    ratio_result,
)
from .dcma import link_row, open_links

GROUP = "Extended integrity"
REDUNDANCY_LIMIT = 20000  # bitset reachability is skipped above this many activities


def _count_result(
    base: CheckResult, rows: list[dict], item_limit: int, scale: float = 10.0
) -> CheckResult:
    base.count = base.total_items = len(rows)
    base.items = rows[:item_limit]
    base.value = float(len(rows))
    base.metric = str(len(rows))
    base.threshold = base.threshold or "0"
    base.status = PASS if not rows else FAIL
    base.score = max(0.0, 1.0 - len(rows) / scale)
    return base


def check_dangling(ctx: Context) -> CheckResult:
    base = CheckResult(
        "EXT-01",
        GROUP,
        "Dangling activities",
        "Tasks whose start is not driven (only finish-to-finish or start-to-finish predecessors) "
        "or whose finish drives nothing (only start-to-start successors). The open side can "
        "slip without affecting anything else.",
        severity="high",
        weight=6,
        wastes=["Defects"],
        recommendation="Add a finish-to-start or start-to-start predecessor to every start, and a "
        "finish-to-start or finish-to-finish successor to every finish.",
    )
    rows = []
    for a in ctx.incomplete_tasks:
        preds, succs = ctx.network_preds(a.uid), ctx.network_succs(a.uid)
        issues = []
        if preds and not any(r.type in (RelType.FS, RelType.SS) for r in preds):
            issues.append("Start not driven")
        if succs and not any(r.type in (RelType.FS, RelType.FF) for r in succs):
            issues.append("Finish drives nothing")
        if issues:
            rows.append(activity_row(a, Issue="; ".join(issues)))
    return ratio_result(base, rows, len(ctx.incomplete_tasks), 0.0, ctx.settings.item_limit)


def check_out_of_sequence(ctx: Context) -> CheckResult:
    acts = ctx.schedule.activities
    started = [a for a in ctx.network if a.is_started]
    base = CheckResult(
        "EXT-02",
        GROUP,
        "Out-of-sequence progress",
        "Work that started before its finish-to-start predecessor finished (or before its "
        "start-to-start predecessor started). The logic no longer matches what happened on site.",
        severity="medium",
        weight=4,
        wastes=["Defects", "Motion"],
        recommendation="Correct the logic to reflect the real sequence (or split the activities) "
        "at each update so the remaining logic stays valid.",
    )
    rows = []
    for a in started:
        for r in ctx.network_preds(a.uid):
            p = acts[r.pred]
            issue = ""
            if r.type == RelType.FS:
                if not p.is_complete:
                    issue = f"Started before {p.code} finished"
                elif (
                    p.actual_finish
                    and a.actual_start
                    and p.actual_finish.date() > a.actual_start.date()
                ):
                    issue = f"Started before {p.code} finished"
            elif r.type == RelType.SS and not p.is_started:
                issue = f"Started before {p.code} started"
            if issue:
                rows.append(
                    activity_row(a, Issue=issue, **{"Actual start": fmt_date(a.actual_start)})
                )
                break
    return ratio_result(base, rows, len(started), 5.0, ctx.settings.item_limit)


def check_loops(ctx: Context) -> CheckResult:
    acts = ctx.schedule.activities
    base = CheckResult(
        "EXT-03",
        GROUP,
        "Circular logic",
        "Loops in the network (A drives B drives A). A loop has no valid start or finish, so "
        "dates and float in it cannot be trusted.",
        severity="high",
        weight=8,
        wastes=["Defects"],
        recommendation="Remove the relationship that closes each loop.",
    )
    rows = [
        {
            "Loop": " > ".join(acts[u].code for u in loop[:12])
            + (" > ..." if len(loop) > 12 else ""),
            "Activities": len(loop),
        }
        for loop in ctx.cpm.cycles
    ]
    base.population = len(ctx.network)
    return _count_result(base, rows, ctx.settings.item_limit, scale=1.0)


def check_redundant(ctx: Context) -> CheckResult:
    base = CheckResult(
        "EXT-04",
        GROUP,
        "Redundant relationships",
        "Finish-to-start links already implied by another chain of finish-to-start links "
        "(A>B>C plus A>C). They add clutter and make the schedule harder to maintain.",
        severity="low",
        weight=2,
        wastes=["Extra-processing"],
        recommendation="Delete links that duplicate a longer chain.",
    )
    nodes = [a.uid for a in ctx.network]
    if len(nodes) > REDUNDANCY_LIMIT:
        base.status, base.metric = NA, "Skipped"
        base.note = f"Skipped for schedules with more than {REDUNDANCY_LIMIT} activities."
        return base
    pos = {u: i for i, u in enumerate(ctx.cpm.order)}
    bit = {u: i for i, u in enumerate(nodes)}
    chain: dict[str, list[str]] = {u: [] for u in nodes}
    for r in ctx.schedule.relationships:
        if r.type == RelType.FS and r.lag >= -EPS and r.pred in chain and r.succ in chain:
            if pos.get(r.pred, 0) < pos.get(r.succ, 0):
                chain[r.pred].append(r.succ)
    reach: dict[str, int] = {}
    for u in reversed(ctx.cpm.order):
        bits = 0
        for s in chain.get(u, ()):
            bits |= (1 << bit[s]) | reach.get(s, 0)
        reach[u] = bits
    links = [r for r in open_links(ctx) if r.type == RelType.FS]
    rows = []
    for r in links:
        if r.lag > EPS:
            continue
        target = 1 << bit[r.succ]
        if any(w != r.succ and reach.get(w, 0) & target for w in chain.get(r.pred, ())):
            rows.append(link_row(ctx, r))
    return ratio_result(base, rows, len(links), 5.0, ctx.settings.item_limit)


def check_long_lags(ctx: Context) -> CheckResult:
    limit = ctx.settings.long_lag_days
    links = open_links(ctx)
    base = CheckResult(
        "EXT-05",
        GROUP,
        "Long lags",
        f"Lags longer than {fmt_days(limit)} working days. Long lags almost always stand in for "
        "real work or waiting (curing, approvals, procurement) that deserves its own activity.",
        severity="medium",
        weight=3,
        wastes=["Waiting"],
        recommendation="Replace each long lag with an activity that has an owner and a duration.",
    )
    rows = sorted(
        (link_row(ctx, r) for r in links if r.lag > limit + EPS), key=lambda x: -float(x["Lag (d)"])
    )
    return ratio_result(base, rows, len(links), 1.0, ctx.settings.item_limit)


def check_start_to_finish(ctx: Context) -> CheckResult:
    links = open_links(ctx)
    base = CheckResult(
        "EXT-06",
        GROUP,
        "Start-to-finish relationships",
        "Start-to-finish links (the successor cannot finish until the predecessor starts) are "
        "counter-intuitive and almost always a modelling error.",
        severity="low",
        weight=2,
        wastes=["Defects"],
        recommendation="Rewrite start-to-finish links as finish-to-start logic.",
    )
    rows = [link_row(ctx, r) for r in links if r.type == RelType.SF]
    return ratio_result(base, rows, len(links), 0.0, ctx.settings.item_limit)


def check_loe_logic(ctx: Context) -> CheckResult:
    acts = ctx.schedule.activities
    base = CheckResult(
        "EXT-07",
        GROUP,
        "Level-of-effort or summary driving work",
        "Relationships where a level-of-effort or summary activity drives a real activity. "
        "Hammocks should span work, never drive it.",
        severity="low",
        weight=2,
        wastes=["Defects"],
        recommendation="Re-link the successor to the real activity that drives it.",
    )
    rows = [
        link_row(ctx, r, **{"Predecessor type": TYPE_LABELS[acts[r.pred].type]})
        for r in ctx.schedule.relationships
        if r.pred in acts
        and r.succ in acts
        and acts[r.pred].type in (ActivityType.LOE, ActivityType.SUMMARY)
        and acts[r.succ].in_network
        and not acts[r.succ].is_complete
    ]
    return _count_result(base, rows, ctx.settings.item_limit)


def check_critical_density(ctx: Context) -> CheckResult:
    pop = [a for a in ctx.incomplete if ctx.float_days.get(a.uid) is not None]
    base = CheckResult(
        "EXT-08",
        GROUP,
        "Critical path density",
        "Share of incomplete activities that are critical. When too much work is critical there "
        "is no slack to absorb variability and every hiccup delays the finish.",
        severity="medium",
        weight=3,
        wastes=["Muri (overburden)"],
        recommendation="Look for artificial criticality (constraints, over-linked logic) and add "
        "explicit buffers before key milestones.",
    )
    rows = [
        activity_row(
            a, **{"Total float (d)": fmt_days(ctx.float_days[a.uid]), "Start": fmt_date(a.start)}
        )
        for a in sorted(pop, key=lambda a: (a.start is None, a.start))
        if ctx.is_critical(a.uid)
    ]
    return ratio_result(base, rows, len(pop), 25.0, ctx.settings.item_limit)


def check_path_continuity(ctx: Context) -> CheckResult:
    cpm, acts = ctx.cpm, ctx.schedule.activities
    base = CheckResult(
        "EXT-09",
        GROUP,
        "Driving path continuity",
        "Traces the driving (longest) path back from the project finish. A sound path runs "
        "continuously from the data date or from work in progress; a path that starts at a "
        "date constraint means the critical path is being set by a date, not by logic.",
        severity="high",
        weight=5,
        wastes=["Defects"],
        recommendation="Replace the constraint at the start of the driving path with the logic "
        "it stands for (e.g. a procurement or approval activity).",
        threshold="Starts at the data date",
    )
    path = cpm.longest_path
    if not path:
        base.status, base.metric, base.note = NA, "n/a", "No remaining work."
        return base
    rows = [
        activity_row(
            acts[u],
            Start=fmt_date(acts[u].start),
            Finish=fmt_date(acts[u].finish),
            **{"Total float (d)": fmt_days(ctx.float_days.get(u))},
        )
        for u in path
    ]
    broken = cpm.path_origin.startswith("a '")
    base.items, base.total_items = rows[: ctx.settings.item_limit], len(rows)
    base.population = len(path)
    base.count = 1 if broken else 0
    base.status = FAIL if broken else PASS
    base.score = 0.0 if broken else 1.0
    base.metric = "Broken" if broken else "Continuous"
    base.note = f"The driving path ({len(path)} activities) starts from {cpm.path_origin}."
    base.details = {"origin": cpm.path_origin, "length": len(path)}
    return base


def check_logic_density(ctx: Context) -> CheckResult:
    acts = ctx.schedule.activities
    network = ctx.network
    links = [
        r
        for r in ctx.schedule.relationships
        if r.pred in acts and r.succ in acts and acts[r.pred].in_network and acts[r.succ].in_network
    ]
    base = CheckResult(
        "EXT-10",
        GROUP,
        "Logic density",
        "Average number of relationships per activity (predecessors + successors). Below 2 the "
        "network is under-linked; above 6 it is usually over-linked with redundant logic.",
        severity="medium",
        weight=3,
        wastes=["Defects", "Extra-processing"],
        recommendation="Aim for 2 to 4 links per activity: enough to model the real sequence, "
        "no more.",
        threshold="2.0 to 6.0",
    )
    if not network:
        base.status, base.metric = NA, "n/a"
        return base
    density = 2.0 * len(links) / len(network)
    base.value, base.metric = round(density, 2), f"{density:.2f}"
    base.population, base.count = len(network), len(links)
    if density < 2.0:
        base.status, base.score = FAIL, max(0.0, density / 2.0)
    elif density > 6.0:
        base.status, base.score = FAIL, max(0.0, 1.0 - (density - 6.0) / 6.0)
    else:
        base.status, base.score = PASS, 1.0
    return base


def check_data_integrity(ctx: Context) -> CheckResult:
    acts = list(ctx.schedule.activities.values())
    base = CheckResult(
        "EXT-11",
        GROUP,
        "Status and data integrity",
        "Inconsistent progress or definitions: completed work without an actual finish, started "
        "work without an actual start, finish before start, zero-duration tasks that should be "
        "milestones, milestones with a duration, duplicate activity IDs.",
        severity="medium",
        weight=4,
        wastes=["Defects"],
        recommendation="Fix the statusing errors before the next update; they corrupt float and "
        "performance metrics.",
    )
    duplicates = {code for code, n in Counter(a.code for a in acts).items() if n > 1}
    rows = []
    for a in acts:
        issues = []
        if a.is_complete and not a.actual_finish:
            issues.append("Complete without actual finish")
        if a.is_started and not a.actual_start:
            issues.append("Started without actual start")
        if a.actual_start and a.actual_finish and a.actual_finish < a.actual_start:
            issues.append("Actual finish before actual start")
        if a.type == ActivityType.TASK and a.duration <= EPS and not a.is_complete:
            issues.append("Zero-duration task (make it a milestone)")
        if a.is_milestone and a.duration > EPS:
            issues.append("Milestone with a duration")
        if a.code in duplicates:
            issues.append("Duplicate activity ID")
        if issues:
            rows.append(activity_row(a, Issue="; ".join(issues)))
    return ratio_result(base, rows, len(acts), 0.0, ctx.settings.item_limit)


def check_soft_constraints(ctx: Context) -> CheckResult:
    base = CheckResult(
        "EXT-12",
        GROUP,
        "Soft constraints",
        "Start/finish on-or-after and as-late-as-possible constraints. They do not break logic "
        "but push work to dates; review that each one is genuine (access dates, deliveries).",
        severity="info",
        weight=0,
        wastes=["Overproduction"],
        recommendation="Keep only constraints that reflect real external dates.",
    )
    rows = []
    for a in ctx.incomplete:
        for c, d in a.constraints:
            if c not in HARD_CONSTRAINTS:
                rows.append(activity_row(a, Constraint=CONSTRAINT_LABELS[c], Date=fmt_date(d)))
                break
    ratio_result(base, rows, len(ctx.incomplete), 100.0, ctx.settings.item_limit)
    base.status, base.score, base.threshold = (INFO if base.population else NA), None, "Review"
    return base


def check_float_agreement(ctx: Context) -> CheckResult:
    base = CheckResult(
        "EXT-13",
        GROUP,
        "Float recalculation agreement",
        "Compares the total float stored in the file with float recalculated by this tool. Large "
        "differences suggest the schedule was not rescheduled before export, or uses settings "
        "this tool approximates (multiple calendars, progress override, leveling).",
        severity="info",
        weight=0,
        wastes=[],
        recommendation="Reschedule (F9 in P6) before exporting so stored dates and float are current.",
        threshold="Review",
    )
    if not ctx.float_source.startswith("Exported"):
        base.status, base.metric, base.note = NA, "n/a", "The file has no stored float to compare."
        return base
    acts = ctx.schedule.activities
    rows = []
    compared = 0
    for a in ctx.incomplete:
        stored = a.total_float
        computed = ctx.cpm.tf.get(a.uid)
        if stored is None or computed is None:
            continue
        compared += 1
        factor = (
            (ctx.schedule.calendar.days_per_week / a.calendar_days_per_week)
            if a.calendar_days_per_week
            else 1.0
        )
        computed_own = computed / factor
        if abs(stored - computed_own) > 1.0 + EPS:
            rows.append(
                activity_row(
                    acts[a.uid],
                    **{
                        "Stored float (d)": fmt_days(stored),
                        "Recalculated (d)": fmt_days(computed_own),
                    },
                )
            )
    ratio_result(base, rows, compared, 100.0, ctx.settings.item_limit)
    if base.population:
        base.metric = f"{fmt_pct(100.0 - (base.value or 0.0))} agree"
    base.status, base.score = (INFO if base.population else NA), None
    return base


def check_merge_hotspots(ctx: Context) -> CheckResult:
    limit = ctx.settings.merge_hotspot_preds
    base = CheckResult(
        "EXT-14",
        GROUP,
        "Merge hotspots",
        f"Activities with {limit} or more predecessors. Variability accumulates where many paths "
        "merge (merge bias), so these points are the most likely to slip.",
        severity="info",
        weight=0,
        wastes=["Waiting"],
        recommendation="Protect merge points with an explicit buffer and check their "
        "predecessors in every lookahead meeting.",
        threshold="Review",
    )
    rows = [
        activity_row(a, Predecessors=len(ctx.network_preds(a.uid)), Start=fmt_date(a.start))
        for a in sorted(ctx.incomplete, key=lambda a: -len(ctx.network_preds(a.uid)))
        if len(ctx.network_preds(a.uid)) >= limit
    ]
    ratio_result(base, rows, len(ctx.incomplete), 100.0, ctx.settings.item_limit)
    base.status, base.score = (INFO if base.population else NA), None
    base.metric = str(len(rows))
    return base


def run(ctx: Context) -> list[CheckResult]:
    return [
        check_dangling(ctx),
        check_out_of_sequence(ctx),
        check_loops(ctx),
        check_redundant(ctx),
        check_long_lags(ctx),
        check_start_to_finish(ctx),
        check_loe_logic(ctx),
        check_critical_density(ctx),
        check_path_continuity(ctx),
        check_logic_density(ctx),
        check_data_integrity(ctx),
        check_soft_constraints(ctx),
        check_float_agreement(ctx),
        check_merge_hotspots(ctx),
    ]
