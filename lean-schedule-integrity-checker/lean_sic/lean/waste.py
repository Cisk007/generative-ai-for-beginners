"""The Lean waste lens: translate schedule findings into the wastes of Lean.

The eight wastes (DOWNTIME: Defects, Overproduction, Waiting, Non-utilised
talent, Transportation, Inventory, Motion, Extra-processing) plus Mura
(unevenness) and Muri (overburden) give site teams a shared language for
*why* a schedule problem matters and *what* to do about it.
"""

from __future__ import annotations

from ..checks.base import FAIL, CheckResult

WASTES = {
    "Defects": (
        "Errors in the plan itself (broken logic, invalid dates, out-of-sequence work) that cause rework of the plan and unreliable hand-offs.",
        "Fix logic at source; review the network with the trades in a pull-planning session.",
    ),
    "Overproduction": (
        "Work pushed by dates rather than pulled by the next trade's need, so it starts before it is needed or before it is ready.",
        "Pull-plan from milestones backwards; replace date constraints with real hand-offs.",
    ),
    "Waiting": (
        "Crews and work faces idle: lags, broken trade flow, missed hand-offs and constraints not removed in time.",
        "Make work ready in the lookahead; keep trades flowing zone to zone; own every wait as an activity.",
    ),
    "Non-utilised talent": (
        "The people doing the work are not planning it: no responsible trade, no promises, no learning from misses.",
        "Give every task a Last Planner; run weekly planning and learning with the trade foremen.",
    ),
    "Transportation": (
        "Crews and materials moved between disconnected work areas, demobilised and remobilised.",
        "Plan by location so each trade moves to the next zone, not across the site.",
    ),
    "Inventory": (
        "Work-in-progress and large batches: long activities, stalled work fronts, unmanaged float.",
        "Break work into small batches; finish started work before opening new fronts.",
    ),
    "Motion": (
        "Crowded work faces and trades stacked in one area, forcing extra movement and re-handling.",
        "One trade per zone at a time (takt wagons); plan laydown and access.",
    ),
    "Extra-processing": (
        "Planning effort that adds no value: redundant links and needless complexity.",
        "Simplify the network: model the real sequence, no more.",
    ),
    "Mura (unevenness)": (
        "Uneven workflow: unbalanced takt, unreliable weekly plans, missed baseline tasks.",
        "Level work content per zone; stabilise weekly commitments (PPC).",
    ),
    "Muri (overburden)": (
        "An overburdened plan: negative float, no slack, too much critical work, unknown crew capacity.",
        "Re-plan to a feasible date; add explicit buffers; check crew capacity.",
    ),
}


def points_lost(checks: list[CheckResult]) -> dict[str, float]:
    """Score points (0-100 scale of each check's group) that each check costs."""
    totals: dict[str, float] = {}
    for c in checks:
        if c.score is not None and c.weight > 0:
            totals[c.group] = totals.get(c.group, 0.0) + c.weight
    return {
        c.id: 100.0 * c.weight * (1.0 - c.score) / totals[c.group]
        for c in checks
        if c.score is not None and c.weight > 0 and totals.get(c.group)
    }


def waste_lens(checks: list[CheckResult]) -> list[dict]:
    """One row per waste: the failed checks behind it and the points they cost."""
    lost = points_lost(checks)
    rows = []
    for waste, (meaning, countermeasure) in WASTES.items():
        hits = [c for c in checks if waste in c.wastes and c.status == FAIL]
        rows.append(
            {
                "waste": waste,
                "meaning": meaning,
                "countermeasure": countermeasure,
                "checks": [
                    {
                        "id": c.id,
                        "name": c.name,
                        "count": c.count,
                        "points": round(lost.get(c.id, 0.0), 1),
                    }
                    for c in hits
                ],
                "points": round(sum(lost.get(c.id, 0.0) for c in hits), 1),
                "findings": sum(c.count for c in hits),  # mixed units; for reference only
            }
        )
    rows.sort(key=lambda r: (-r["points"], -len(r["checks"])))
    return rows
