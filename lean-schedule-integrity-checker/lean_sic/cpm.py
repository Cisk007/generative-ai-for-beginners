"""Critical Path Method (CPM) engine.

The engine recalculates the schedule from the data date so that checks do
not depend on whether the file was rescheduled before export. It supports:

* finish-to-start, start-to-start, finish-to-finish and start-to-finish links
  with lags and leads,
* progress: completed work is fixed in the past; in-progress work continues
  from the data date (P6 "retained logic"),
* date constraints, including mandatory constraints that override logic,
* loops (circular logic): they are reported and broken so the pass completes.

Times are *working-day offsets* from the start of the data date.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

from .model import CONSTRAINT_LABELS, Activity, ConstraintType, RelType, Schedule, Status

INF = math.inf
EPS = 1e-6


@dataclass
class CpmResult:
    es: dict[str, float] = field(default_factory=dict)  # early start (actual start once started)
    ef: dict[str, float] = field(default_factory=dict)  # early finish
    res: dict[str, float] = field(default_factory=dict)  # remaining early start
    ls: dict[str, float] = field(default_factory=dict)  # late start of the remaining work
    lf: dict[str, float] = field(default_factory=dict)  # late finish
    tf: dict[str, float] = field(default_factory=dict)  # total float (incomplete work only)
    ff: dict[str, float] = field(default_factory=dict)  # free float (incomplete work only)
    finish: float = 0.0  # forecast project finish
    finish_activity: str | None = None
    order: list[str] = field(default_factory=list)
    cycles: list[list[str]] = field(default_factory=list)
    back_edges: int = 0
    drivers: dict[str, tuple[str, str]] = field(default_factory=dict)
    longest_path: list[str] = field(default_factory=list)
    path_origin: str = ""  # what drives the first activity of the longest path


def _calendar_factor(schedule: Schedule, act: Activity) -> float:
    """Convert an activity's own working days into project-calendar days."""
    if act.calendar_days_per_week:
        return schedule.calendar.days_per_week / act.calendar_days_per_week
    return 1.0


def strongly_connected(nodes: list[str], succ: dict[str, list[str]]) -> list[list[str]]:
    """Tarjan's algorithm (iterative) - groups of activities that form loops."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    groups: list[list[str]] = []
    counter = 0
    for root in nodes:
        if root in index:
            continue
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        work = [(root, iter(succ.get(root, ())))]
        while work:
            node, children = work[-1]
            pushed = False
            for child in children:
                if child not in index:
                    index[child] = low[child] = counter
                    counter += 1
                    stack.append(child)
                    on_stack.add(child)
                    work.append((child, iter(succ.get(child, ()))))
                    pushed = True
                    break
                if child in on_stack:
                    low[node] = min(low[node], index[child])
            if pushed:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                group = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    group.append(member)
                    if member == node:
                        break
                groups.append(group)
    return groups


def topological_order(nodes: list[str], succ: dict[str, list[str]]) -> list[str]:
    """Kahn's algorithm; when a loop blocks progress the earliest node is forced in."""
    indegree = dict.fromkeys(nodes, 0)
    for node in nodes:
        for child in succ.get(node, ()):
            indegree[child] += 1
    queue = deque(n for n in nodes if indegree[n] == 0)
    placed: set[str] = set()
    order: list[str] = []
    pointer = 0
    while len(order) < len(nodes):
        if not queue:
            while nodes[pointer] in placed:
                pointer += 1
            queue.append(nodes[pointer])
        node = queue.popleft()
        if node in placed:
            continue
        placed.add(node)
        order.append(node)
        for child in succ.get(node, ()):
            if child not in placed:
                indegree[child] -= 1
                if indegree[child] == 0:
                    queue.append(child)
    return order


def compute_cpm(
    schedule: Schedule,
    extra_duration: dict[str, float] | None = None,
    backward: bool = True,
) -> CpmResult:
    """Run the forward (and optionally backward) pass from the data date."""
    acts = schedule.activities
    cal, dd = schedule.calendar, schedule.data_date
    extra_duration = extra_duration or {}

    nodes = [uid for uid, a in acts.items() if a.in_network]
    node_set = set(nodes)
    links = [
        r
        for r in schedule.relationships
        if r.pred in node_set and r.succ in node_set and r.pred != r.succ
    ]
    succ_ids: dict[str, list[str]] = {n: [] for n in nodes}
    for r in links:
        succ_ids[r.pred].append(r.succ)

    result = CpmResult()
    result.cycles = [g for g in strongly_connected(nodes, succ_ids) if len(g) > 1]
    self_loops = [
        [r.pred] for r in schedule.relationships if r.pred == r.succ and r.pred in node_set
    ]
    result.cycles += self_loops
    order = topological_order(nodes, succ_ids)
    pos = {uid: i for i, uid in enumerate(order)}
    result.order = order

    preds_of: dict[str, list] = {n: [] for n in nodes}
    succs_of: dict[str, list] = {n: [] for n in nodes}
    for r in links:
        if pos[r.pred] < pos[r.succ]:
            preds_of[r.succ].append(r)
            succs_of[r.pred].append(r)
        else:
            result.back_edges += 1

    factor = {uid: _calendar_factor(schedule, acts[uid]) for uid in nodes}
    dur = {
        uid: acts[uid].remaining_duration * factor[uid] + extra_duration.get(uid, 0.0)
        for uid in nodes
    }
    cons = {
        uid: [(c, cal.offset(dd, d)) for c, d in acts[uid].constraints if d is not None]
        for uid in nodes
    }
    deadlines = {uid: cal.offset(dd, acts[uid].deadline) for uid in nodes if acts[uid].deadline}

    es, ef, res, drivers = result.es, result.ef, result.res, result.drivers
    # -- forward pass ---------------------------------------------------------
    for uid in order:
        act = acts[uid]
        d = dur[uid]
        if act.status == Status.COMPLETE:
            start = cal.offset(dd, act.actual_start) if act.actual_start else None
            end = cal.offset(dd, act.actual_finish) if act.actual_finish else None
            end = end if end is not None else (start if start is not None else 0.0)
            start = start if start is not None else end - act.duration * factor[uid]
            es[uid], ef[uid], res[uid] = start, end, end
            continue
        started = act.status == Status.IN_PROGRESS
        low = 0.0
        driver: tuple[str, str] = (
            ("in_progress", "")
            if started
            else (("data_date", "") if preds_of[uid] else ("open_start", ""))
        )
        for r in preds_of[uid]:
            lag = r.lag * factor[r.pred]
            if r.type == RelType.FS:
                bound = ef[r.pred] + lag
            elif r.type == RelType.SS:
                if started:
                    continue  # the start has already happened
                bound = es[r.pred] + lag
            elif r.type == RelType.FF:
                bound = ef[r.pred] + lag - d
            else:  # SF
                bound = es[r.pred] + lag - d
            if bound > low + EPS:
                low, driver = bound, ("rel", r.pred)
        for ctype, offset in cons[uid]:
            label = CONSTRAINT_LABELS[ctype]
            if ctype in (ConstraintType.START_ON_OR_AFTER, ConstraintType.START_ON) and not started:
                if offset > low + EPS:
                    low, driver = offset, ("constraint", label)
            elif ctype in (ConstraintType.FINISH_ON_OR_AFTER, ConstraintType.FINISH_ON):
                if offset - d > low + EPS:
                    low, driver = offset - d, ("constraint", label)
            elif ctype == ConstraintType.MANDATORY_START and not started:
                low, driver = max(0.0, offset), ("constraint", label)
            elif ctype == ConstraintType.MANDATORY_FINISH:
                low, driver = max(0.0, offset - d), ("constraint", label)
        res[uid] = low
        es[uid] = cal.offset(dd, act.actual_start) if started and act.actual_start else low
        ef[uid] = low + d
        drivers[uid] = driver

    open_work = [uid for uid in order if acts[uid].status != Status.COMPLETE]
    if open_work:
        result.finish = max(ef[uid] for uid in open_work)
        ends = [uid for uid in open_work if abs(ef[uid] - result.finish) < EPS]
        ends.sort(key=lambda u: (len(succs_of[u]) > 0, -pos[u]))
        result.finish_activity = ends[0]
    result.longest_path, result.path_origin = _trace_path(result, acts)
    if not backward:
        return result

    # -- backward pass --------------------------------------------------------
    ls, lf, tf, ff = result.ls, result.lf, result.tf, result.ff
    target = result.finish
    if schedule.deadline is not None:
        target = cal.offset(dd, schedule.deadline)  # "must finish by" drives late dates
    for uid in reversed(order):
        act = acts[uid]
        if act.status == Status.COMPLETE:
            ls[uid], lf[uid] = es[uid], ef[uid]
            continue
        d = dur[uid]
        started = act.status == Status.IN_PROGRESS
        high = INF
        free = INF
        for r in succs_of[uid]:
            nxt = acts[r.succ]
            if nxt.status == Status.COMPLETE:
                continue
            lag = r.lag * factor[uid]
            next_started = nxt.status == Status.IN_PROGRESS
            if r.type == RelType.FS:
                bound, slack = ls[r.succ] - lag, res[r.succ] - lag - ef[uid]
            elif r.type == RelType.SS:
                if started or next_started:
                    continue
                bound, slack = ls[r.succ] - lag + d, es[r.succ] - lag - es[uid]
            elif r.type == RelType.FF:
                bound, slack = lf[r.succ] - lag, ef[r.succ] - lag - ef[uid]
            else:  # SF
                if started:
                    continue
                bound, slack = lf[r.succ] - lag + d, ef[r.succ] - lag - es[uid]
            high, free = min(high, bound), min(free, slack)
        if high == INF:  # open end: tied to the project finish
            high = target
            free = target - ef[uid]
        for ctype, offset in cons[uid]:
            if (
                ctype in (ConstraintType.START_ON_OR_BEFORE, ConstraintType.START_ON)
                and not started
            ):
                high = min(high, offset + d)
            elif ctype in (ConstraintType.FINISH_ON_OR_BEFORE, ConstraintType.FINISH_ON):
                high = min(high, offset)
            elif ctype == ConstraintType.MANDATORY_START and not started:
                high = offset + d
            elif ctype == ConstraintType.MANDATORY_FINISH:
                high = offset
        if uid in deadlines:  # a deadline pulls the late finish in, like FNLT
            high = min(high, deadlines[uid])
        lf[uid], ls[uid] = high, high - d
        tf[uid] = high - ef[uid]
        ff[uid] = min(free, tf[uid])
    return result


def _trace_path(result: CpmResult, acts: dict[str, Activity]) -> tuple[list[str], str]:
    """Follow driving predecessors back from the project finish."""
    path: list[str] = []
    seen: set[str] = set()
    current = result.finish_activity
    origin = ""
    while current and current not in seen:
        seen.add(current)
        path.append(current)
        kind, detail = result.drivers.get(current, ("data_date", ""))
        if kind == "rel" and acts[detail].status != Status.COMPLETE:
            current = detail
            continue
        origin = {
            "rel": "completed work",
            "in_progress": "work in progress at the data date",
            "data_date": "the data date",
            "open_start": "an activity with no predecessor",
            "constraint": f"a '{detail}' constraint",
        }[kind]
        break
    path.reverse()
    return path, origin


def critical_path_test(
    schedule: Schedule, base: CpmResult, critical: list[str], delay: float = 600.0, samples: int = 5
) -> dict:
    """DCMA check 12: delay critical activities and confirm the finish moves.

    ``critical`` must be ordered by start. Each sampled activity gets
    ``delay`` extra working days; in a sound network the project finish moves
    by the same amount.
    """
    # Tasks first (as DCMA describes), then milestones while samples remain:
    # a milestone made critical by a constraint is exactly what the test exposes.
    ordered = [u for u in critical if schedule.activities[u].is_task]
    ordered += [u for u in critical if not schedule.activities[u].is_task]
    tested = []
    for uid in ordered[:samples]:
        trial = compute_cpm(schedule, extra_duration={uid: delay}, backward=False)
        moved = trial.finish - base.finish
        tested.append(
            {"uid": uid, "finish_moved_days": round(moved, 1), "passed": moved >= delay - 0.5}
        )
    return {
        "delay_days": delay,
        "tested": tested,
        "passed": bool(tested) and all(t["passed"] for t in tested),
    }
