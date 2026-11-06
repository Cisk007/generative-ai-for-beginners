"""Check results and the scoring rules shared by every check."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime

from ..model import Activity

PASS, FAIL, INFO, NA = "pass", "fail", "info", "na"


@dataclass
class CheckResult:
    id: str  # e.g. "DCMA-07"
    group: str  # "DCMA 14-Point", "Extended integrity", "Lean readiness"
    name: str
    description: str  # what is measured and why it matters
    status: str = PASS  # pass | fail | info | na
    metric: str = ""  # formatted value shown in the report, e.g. "3.2%"
    value: float | None = None
    threshold: str = ""  # e.g. "<= 5%"
    count: int = 0  # flagged items
    population: int = 0  # items tested
    severity: str = "medium"  # high | medium | low | info
    weight: float = 1.0  # contribution to the group score
    score: float | None = None  # 0..1, None when not scored
    recommendation: str = ""
    wastes: list[str] = field(default_factory=list)  # Lean waste categories
    items: list[dict] = field(default_factory=list)  # flagged rows (capped)
    total_items: int = 0
    details: dict = field(default_factory=dict)
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# -- scoring ---------------------------------------------------------------
# A check scores 1.0 when it meets its threshold. Misses lose credit in
# proportion to how far they are from the threshold: the credit reaches zero
# once the miss is twice the threshold (at least 10 points) beyond it, so one
# stray open end costs a little while widespread problems cost the full weight.
def score_at_most(pct: float, limit: float) -> float:
    if pct <= limit + 1e-9:
        return 1.0
    band = max(2.0 * limit, 10.0)
    return max(0.0, 1.0 - (pct - limit) / band)


def score_at_least(pct: float, minimum: float) -> float:
    if pct >= minimum - 1e-9:
        return 1.0
    band = max(2.0 * (100.0 - minimum), 10.0)
    return max(0.0, 1.0 - (minimum - pct) / band)


def score_index(value: float, minimum: float = 0.95, floor: float = 0.75) -> float:
    if value >= minimum:
        return 1.0
    return max(0.0, (value - floor) / (minimum - floor))


def grade(score: float) -> tuple[str, str]:
    if score >= 90:
        return "A", "Robust"
    if score >= 80:
        return "B", "Sound"
    if score >= 70:
        return "C", "Fair"
    if score >= 60:
        return "D", "Weak"
    return "F", "Unreliable"


def group_score(checks: list[CheckResult]) -> dict:
    scored = [c for c in checks if c.score is not None and c.weight > 0]
    total = sum(c.weight for c in scored)
    value = 100.0 * sum(c.weight * (c.score or 0.0) for c in scored) / total if total else None
    letter, label = grade(value) if value is not None else ("-", "Not enough data")
    return {
        "score": round(value, 1) if value is not None else None,
        "grade": letter,
        "label": label,
        "passed": sum(1 for c in checks if c.status == PASS),
        "failed": sum(1 for c in checks if c.status == FAIL),
        "info": sum(1 for c in checks if c.status in (INFO, NA)),
        "scored": len(scored),
    }


# -- helpers for building results ----------------------------------------------
def fmt_pct(value: float) -> str:
    return f"{value:.1f}%" if value % 1 else f"{value:.0f}%"


def fmt_days(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.1f}" if abs(value - round(value)) > 0.05 else f"{round(value):.0f}"


def fmt_date(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d") if value else ""


def activity_row(act: Activity, **extra) -> dict:
    row = {"Activity ID": act.code, "Activity name": act.name}
    row.update(extra)
    row["WBS"] = act.wbs
    return row


def ratio_result(
    base: CheckResult,
    flagged: list[dict],
    population: int,
    limit: float,
    item_limit: int,
    at_least: bool = False,
    flagged_count: int | None = None,
) -> CheckResult:
    """Fill a percentage-style check (e.g. "<= 5% of incomplete tasks")."""
    count = len(flagged) if flagged_count is None else flagged_count
    base.count, base.population = count, population
    base.items, base.total_items = flagged[:item_limit], len(flagged)
    if population == 0:
        base.status, base.metric, base.score = NA, "n/a", None
        base.note = base.note or "Nothing to test in this schedule."
        return base
    pct = 100.0 * (population - count if at_least else count) / population
    base.value = round(pct, 2)
    base.metric = fmt_pct(round(pct, 1))
    if at_least:
        base.score = score_at_least(pct, limit)
        base.status = PASS if pct >= limit - 1e-9 else FAIL
        base.threshold = base.threshold or f">= {fmt_pct(limit)}"
    else:
        base.score = score_at_most(pct, limit)
        base.status = PASS if pct <= limit + 1e-9 else FAIL
        base.threshold = base.threshold or f"<= {fmt_pct(limit)}"
    return base
