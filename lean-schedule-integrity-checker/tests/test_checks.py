from datetime import datetime

import pytest
from conftest import DATA_DATE, make_schedule, milestone, task
from lean_sic.analysis import analyze
from lean_sic.calendar import WorkCalendar
from lean_sic.checks.base import grade, score_at_least, score_at_most, score_index
from lean_sic.model import Activity, ActivityType, ConstraintType, Status

CAL = WorkCalendar()


def run(acts, rels, **kwargs) -> dict:
    result = analyze(make_schedule(acts, rels, **kwargs))
    return {c["id"]: c for c in result["checks"]}


def flagged(check: dict, column: str = "Activity ID") -> set:
    return {row[column] for row in check["items"]}


def test_missing_logic_exempts_project_start_and_finish():
    acts = [milestone("S", start=True), task("A", 5), task("B", 5), milestone("F"), task("X", 3)]
    checks = run(acts, [("S", "A"), ("A", "B"), ("B", "F")])
    c = checks["DCMA-01"]
    assert (c["status"], c["count"], c["population"]) == ("fail", 1, 5)
    assert c["items"][0]["Issue"] == "No predecessor or successor"


def test_leads_lags_and_relationship_types():
    acts = [task("A", 5), task("B", 5), task("C", 5), task("D", 5), milestone("F")]
    rels = [
        ("A", "B", "FS", -1),
        ("A", "C", "FS", 2),
        ("A", "D", "SS", 0),
        ("B", "F"),
        ("C", "F"),
        ("D", "F"),
    ]
    checks = run(acts, rels)
    assert checks["DCMA-02"]["count"] == 1 and checks["DCMA-02"]["status"] == "fail"
    assert checks["DCMA-03"]["count"] == 1 and checks["DCMA-03"]["status"] == "fail"
    assert (
        checks["DCMA-04"]["value"] == pytest.approx(83.33, abs=0.01)
        and checks["DCMA-04"]["status"] == "fail"
    )


def test_hard_soft_and_push_constraints():
    hard = task(
        "A",
        5,
        constraint=ConstraintType.MANDATORY_START,
        constraint_date=CAL.datetime_at(DATA_DATE, 1),
    )
    soft = task(
        "B",
        5,
        constraint=ConstraintType.START_ON_OR_AFTER,
        constraint_date=CAL.datetime_at(DATA_DATE, 8),
    )
    checks = run(
        [milestone("S", start=True), hard, soft, milestone("F")],
        [("S", "A"), ("A", "B"), ("B", "F")],
    )
    assert flagged(checks["DCMA-05"]) == {"A"}
    assert flagged(checks["EXT-12"]) == {"B"} and checks["EXT-12"]["status"] == "info"
    assert flagged(checks["LEAN-04"]) == {"A", "B"}


def test_negative_float_and_cpli_against_a_deadline():
    checks = run(
        [task("A", 10), milestone("F")],
        [("A", "F")],
        deadline=CAL.datetime_at(DATA_DATE, 7, finish=True),
    )
    assert checks["DCMA-07"]["count"] == 2 and checks["DCMA-07"]["status"] == "fail"
    assert checks["DCMA-13"]["value"] == pytest.approx(0.7)
    assert checks["DCMA-13"]["status"] == "fail" and checks["DCMA-13"]["score"] == 0.0


def test_high_float_and_high_duration():
    checks = run([task("A", 50), task("B", 3), milestone("F")], [("A", "F")])
    assert flagged(checks["DCMA-06"]) == {"B"}  # open end: 47 days of float
    assert flagged(checks["DCMA-08"]) == {"A"}


def test_invalid_dates():
    a = task("A", 5, status=Status.IN_PROGRESS, actual_start=datetime(2026, 3, 4, 8), remaining=3)
    checks = run([a, milestone("F")], [("A", "F")])
    assert checks["DCMA-09"]["items"][0]["Issue"] == "Actual start after data date"


def test_resources_are_informational_until_the_schedule_is_loaded():
    assert run([task("A", 5), task("B", 5)], [("A", "B")])["DCMA-10"]["status"] == "info"
    checks = run([task("A", 5, resources=["Crew"]), task("B", 5)], [("A", "B")])
    assert flagged(checks["DCMA-10"]) == {"B"}


def test_missed_tasks_and_bei():
    on_time = task(
        "A",
        5,
        status=Status.COMPLETE,
        actual_start=datetime(2026, 2, 16, 8),
        actual_finish=datetime(2026, 2, 20, 17),
        baseline_finish=datetime(2026, 2, 20, 17),
    )
    late = task(
        "B",
        5,
        status=Status.COMPLETE,
        actual_start=datetime(2026, 2, 16, 8),
        actual_finish=datetime(2026, 2, 25, 17),
        baseline_finish=datetime(2026, 2, 20, 17),
    )
    open_ = task(
        "C",
        5,
        status=Status.IN_PROGRESS,
        actual_start=datetime(2026, 2, 23, 8),
        remaining=3,
        baseline_finish=datetime(2026, 2, 27, 17),
    )
    later = task("D", 5, baseline_finish=datetime(2026, 3, 20, 17))
    checks = run([on_time, late, open_, later], [])
    assert flagged(checks["DCMA-11"]) == {"B", "C"} and checks["DCMA-11"]["population"] == 3
    assert checks["DCMA-14"]["value"] == pytest.approx(0.667, abs=0.001)


def test_no_baseline_means_not_applicable():
    checks = run([task("A", 5)], [])
    assert checks["DCMA-11"]["status"] == checks["DCMA-14"]["status"] == "na"


def test_dangling_activities():
    acts = [
        milestone("S", start=True),
        task("A", 5),
        task("B", 5),
        task("C", 5),
        task("D", 5),
        milestone("F"),
    ]
    rels = [
        ("S", "A"),
        ("A", "B", "FF", 0),
        ("S", "C"),
        ("C", "D", "SS", 0),
        ("B", "F"),
        ("D", "F"),
    ]
    issues = {r["Activity ID"]: r["Issue"] for r in run(acts, rels)["EXT-01"]["items"]}
    assert issues == {"B": "Start not driven", "C": "Finish drives nothing"}


def test_out_of_sequence_progress():
    a = task("A", 5, status=Status.IN_PROGRESS, actual_start=datetime(2026, 2, 23, 8), remaining=2)
    b = task("B", 5, status=Status.IN_PROGRESS, actual_start=datetime(2026, 2, 26, 8), remaining=4)
    c = run([a, b], [("A", "B")])["EXT-02"]
    assert flagged(c) == {"B"} and c["population"] == 2


def test_loops_redundant_long_lags_sf_and_loe():
    checks = run([task("A", 1), task("B", 1), task("C", 1)], [("A", "B"), ("B", "C"), ("C", "A")])
    assert checks["EXT-03"]["count"] == 1 and checks["EXT-03"]["status"] == "fail"

    acts = [task("A", 2), task("B", 2), task("C", 2), task("D", 2), task("E", 2)]
    loe = Activity(uid="L", code="L", name="Site management", type=ActivityType.LOE, duration=10)
    rels = [
        ("A", "B"),
        ("B", "C"),
        ("A", "C"),
        ("C", "D", "FS", 15),
        ("D", "E", "SF", 0),
        ("L", "E"),
    ]
    checks = run(acts + [loe], rels)
    assert {(r["Predecessor"], r["Successor"]) for r in checks["EXT-04"]["items"]} == {("A", "C")}
    assert {(r["Predecessor"], r["Successor"]) for r in checks["EXT-05"]["items"]} == {("C", "D")}
    assert checks["EXT-06"]["count"] == 1
    assert checks["EXT-07"]["count"] == 1


def test_data_integrity():
    dup1 = Activity(uid="1", code="DUP", name="First", duration=2)
    dup2 = Activity(uid="2", code="DUP", name="Second", duration=2)
    zero = Activity(uid="3", code="Z", name="Zero", duration=0)
    issues = [
        r["Issue"] for r in run([dup1, dup2, zero], [("1", "2"), ("2", "3")])["EXT-11"]["items"]
    ]
    assert issues.count("Duplicate activity ID") == 2
    assert "Zero-duration task (make it a milestone)" in issues


def test_scoring_rules():
    assert score_at_most(5, 5) == 1.0
    assert score_at_most(10, 5) == pytest.approx(0.5)
    assert score_at_most(15, 5) == 0.0
    assert score_at_least(90, 95) == pytest.approx(0.5)
    assert score_at_least(80, 80) == 1.0
    assert score_index(0.85) == pytest.approx(0.5)
    assert grade(91) == ("A", "Robust") and grade(59.9) == ("F", "Unreliable")
