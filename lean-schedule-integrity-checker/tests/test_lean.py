from datetime import datetime, timedelta

import pytest
from conftest import DATA_DATE, make_schedule, task
from lean_sic.analysis import analyze
from lean_sic.calendar import WorkCalendar
from lean_sic.checks.base import CheckResult
from lean_sic.lean.lps import analyze_weekly_plans, categorize, parse_weekly_plans
from lean_sic.lean.mapping import resolve_mapping
from lean_sic.lean.waste import points_lost
from lean_sic.model import ConstraintType, Status

CAL = WorkCalendar()


def coded(uid, duration, trade, zone, **kwargs):
    return task(uid, duration, codes={"Trade": trade, "Zone": zone}, **kwargs)


def test_mapping_detects_codes_wbs_and_resources():
    s = make_schedule([coded("A", 2, "Drylining", "L1")], [], code_fields=["Trade", "Zone"])
    m = resolve_mapping(s)
    assert m["trade"]["spec"] == "Trade" and m["location"]["spec"] == "Zone"
    assert s.activities["A"].trade == "Drylining" and s.activities["A"].location == "L1"

    wbs = task("B", 2, wbs="Tower A > Level 2 > Kitchen", resources=["Crew B"])
    s = make_schedule([wbs], [])
    m = resolve_mapping(s)
    assert s.activities["B"].location == "Tower A / Level 2"
    assert s.activities["B"].trade == "Crew B" and m["trade"]["spec"] == "resource"


def takt_schedule():
    """Three trades flow through three zones; trade T2 takes twice as long."""
    acts, rels = [], []
    for z in ("Z1", "Z2", "Z3"):
        for t, d in (("T1", 2), ("T2", 4), ("T3", 2)):
            acts.append(coded(f"{t}-{z}", d, t, z))
    for z in ("Z1", "Z2", "Z3"):
        rels += [(f"T1-{z}", f"T2-{z}"), (f"T2-{z}", f"T3-{z}")]
    for t in ("T1", "T2", "T3"):
        rels += [(f"{t}-Z1", f"{t}-Z2"), (f"{t}-Z2", f"{t}-Z3")]
    return make_schedule(acts, rels, code_fields=["Trade", "Zone"])


def test_takt_analysis_and_flow():
    result = analyze(takt_schedule())
    takt = result["flow"]["takt"]
    assert takt["zones"] == ["Z1", "Z2", "Z3"]
    assert [t["trade"] for t in takt["trades"]] == ["T1", "T2", "T3"]
    assert (takt["takt_balanced"], takt["takt_fit"], takt["periods"], takt["train_balanced"]) == (
        2,
        4,
        5,
        10,
    )
    assert {(o["trade"], o["factor"]) for o in takt["overloaded"]} == {("T2", 2.0)}
    assert takt["avg_cv"] == 0
    assert takt["grid"][0] == [0, 1, 2, None, None]  # zone Z1 gets T1, T2, T3 in takt periods 1-3
    assert result["flow"]["stacking"]["stacked_zone_days"] == 0
    checks = {c["id"]: c for c in result["checks"]}
    assert checks["LEAN-08"]["status"] == "pass" and checks["LEAN-07"]["status"] == "pass"


def test_trade_stacking_and_continuity():
    later = CAL.datetime_at(DATA_DATE, 10)
    acts = [
        coded("A", 3, "Drylining", "L1"),
        coded("B", 3, "MEP", "L1"),
        coded(
            "C",
            3,
            "Drylining",
            "L2",
            constraint=ConstraintType.START_ON_OR_AFTER,
            constraint_date=later,
        ),
    ]
    result = analyze(make_schedule(acts, [("A", "C")], code_fields=["Trade", "Zone"]))
    stacking = result["flow"]["stacking"]
    assert (stacking["stacked_zone_days"], stacking["occupied_zone_days"]) == (
        3,
        6,
    )  # L1 days 0-2 (stacked), L2 days 10-12
    dry = next(r for r in result["flow"]["continuity"]["rows"] if r["trade"] == "Drylining")
    assert (dry["periods"], dry["longest_gap"], dry["long_gaps"]) == (2, 7, 1)


WEEKLY = """week,activity_id,task,trade,planned,completed,reason
2026-02-16,A,Frame L1,Drylining,yes,yes,
2026-02-16,B,Board L1,Drylining,yes,no,Materials: boards not delivered
2026-02-16,,Clean L1,GC,yes,yes,
2026-02-16,,Set out L2,GC,yes,no,RFI 12 unanswered
2026-02-23,C,Frame L2,Drylining,yes,yes,
2026-02-23,,Clean L2,GC,yes,yes,
2026-02-23,,Set out L3,GC,yes,yes,
2026-02-23,D,Board L2,Drylining,yes,no,Previous trade not finished
"""


def test_weekly_plans_ppc_and_reasons():
    rows = parse_weekly_plans(WEEKLY)
    w = analyze_weekly_plans(rows, 80, {"a", "b", "c"})
    assert [x["ppc"] for x in w["weeks"]] == [50.0, 75.0]
    assert w["weeks"][1]["rolling4"] == 62.5 and w["ppc_last4"] == 62.5
    assert {r["reason"] for r in w["reasons"]} == {
        "Materials",
        "Information / design",
        "Prerequisite work",
    }
    assert w["linked"] == 3 and w["trend_per_week"] == 25.0


@pytest.mark.parametrize(
    "text,category",
    [
        ("External / permits: High wind - crane stood down", "External / permits"),
        ("crane broke down", "Equipment"),
        ("RFI 108 unanswered", "Information / design"),
        ("Over-committed", "Planning / commitment"),
        ("Something odd", "Other"),
    ],
)
def test_categorize(text, category):
    assert categorize(text) == category


def test_make_ready_board_and_overdue_constraints():
    soon, later = DATA_DATE, CAL.datetime_at(DATA_DATE, 15)
    acts = [
        task("A", 3),
        task("B", 3, constraint=ConstraintType.START_ON_OR_AFTER, constraint_date=later),
    ]
    log = "\n".join(
        [
            "id,activity_id,description,category,owner,need_by,status",
            f"C1,A,Drawings,Information / design,Architect,{(soon - timedelta(days=3)):%Y-%m-%d},open",
            f"C2,B,Materials on site,Materials,Supplier,{(soon + timedelta(days=5)):%Y-%m-%d},open",
            "C3,X9,Crane slot,Equipment,Site,2026-03-20,open",
            "C4,A,Access,Space / access,Site,2026-02-20,closed",
        ]
    )
    result = analyze(make_schedule(acts, []), constraints=log)
    board = {r["id"]: r["status"] for r in result["lookahead"]["board"]["rows"]}
    assert board == {"A": "Overdue constraint", "B": "Constrained"}
    assert [u["id"] for u in result["lookahead"]["board"]["unlinked"]] == ["C3"]
    checks = {c["id"]: c for c in result["checks"]}
    assert (checks["LEAN-09"]["count"], checks["LEAN-09"]["population"]) == (1, 1)
    assert (checks["LEAN-11"]["count"], checks["LEAN-11"]["population"]) == (1, 3)
    assert result["lps"]["constraints"]["closed"] == 1


def test_points_lost_uses_group_weights():
    a = CheckResult("X-1", "G", "a", "", weight=1, score=0.5)
    b = CheckResult("X-2", "G", "b", "", weight=1, score=1.0)
    assert points_lost([a, b]) == {"X-1": 25.0, "X-2": 0.0}


def test_lookahead_granularity_and_stalled_work():
    long_task = task("L", 30)
    stalled = task(
        "S",
        20,
        status=Status.IN_PROGRESS,
        actual_start=DATA_DATE - timedelta(days=28),
        remaining=19,
    )
    checks = {c["id"]: c for c in analyze(make_schedule([long_task, stalled], []))["checks"]}
    assert {r["Activity ID"] for r in checks["LEAN-01"]["items"]} == {"L", "S"}
    assert {r["Activity ID"] for r in checks["LEAN-05"]["items"]} == {"S"}
    assert checks["LEAN-02"]["value"] == 0.0  # nobody is responsible yet


def test_data_date_is_used_for_lookahead_window():
    far = task(
        "F", 2, constraint=ConstraintType.START_ON_OR_AFTER, constraint_date=datetime(2026, 9, 1, 8)
    )
    result = analyze(make_schedule([task("N", 2), far], []))
    assert result["lookahead"]["activities"] == 1
