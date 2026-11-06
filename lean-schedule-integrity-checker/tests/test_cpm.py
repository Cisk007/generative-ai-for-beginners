from datetime import datetime

import pytest
from conftest import DATA_DATE, make_schedule, milestone, task
from lean_sic.calendar import WorkCalendar
from lean_sic.cpm import compute_cpm, critical_path_test
from lean_sic.model import ConstraintType, Status

CAL = WorkCalendar()


def _network():
    acts = [
        milestone("S", start=True),
        task("A", 5),
        task("B", 3),
        task("C", 4),
        task("D", 2),
        milestone("F"),
    ]
    rels = [
        ("S", "A"),
        ("S", "B"),
        ("A", "C"),
        ("B", "C", "SS", 1),
        ("C", "F"),
        ("B", "D"),
        ("D", "F", "FF", 0),
    ]
    return make_schedule(acts, rels)


def test_forward_and_backward_pass_match_hand_calculation():
    r = compute_cpm(_network())
    expected = {  # ES, EF, LS, LF, TF, FF
        "A": (0, 5, 0, 5, 0, 0),
        "B": (0, 3, 4, 7, 4, 0),
        "C": (5, 9, 5, 9, 0, 0),
        "D": (3, 5, 7, 9, 4, 4),
        "F": (9, 9, 9, 9, 0, 0),
    }
    for uid, (es, ef, ls, lf, tf, ff) in expected.items():
        assert (r.es[uid], r.ef[uid], r.ls[uid], r.lf[uid], r.tf[uid], r.ff[uid]) == (
            es,
            ef,
            ls,
            lf,
            tf,
            ff,
        ), uid
    assert r.finish == 9
    assert r.longest_path == ["A", "C", "F"]
    assert r.path_origin == "the data date"


@pytest.mark.parametrize("lag,start", [(2, 7), (-2, 3), (0, 5)])
def test_lags_and_leads(lag, start):
    r = compute_cpm(make_schedule([task("A", 5), task("B", 3)], [("A", "B", "FS", lag)]))
    assert r.es["B"] == start


def test_start_on_or_after_pushes_and_mandatory_start_overrides_logic():
    snet = task(
        "B",
        3,
        constraint=ConstraintType.START_ON_OR_AFTER,
        constraint_date=CAL.datetime_at(DATA_DATE, 10),
    )
    r = compute_cpm(make_schedule([task("A", 5), snet], [("A", "B")]))
    assert r.es["B"] == 10
    mandatory = task(
        "B",
        3,
        constraint=ConstraintType.MANDATORY_START,
        constraint_date=CAL.datetime_at(DATA_DATE, 2),
    )
    r = compute_cpm(make_schedule([task("A", 5), mandatory], [("A", "B")]))
    assert r.es["B"] == 2  # logic says 5, the mandatory date wins


def test_finish_on_or_before_creates_negative_float():
    fnlt = task(
        "B",
        5,
        constraint=ConstraintType.FINISH_ON_OR_BEFORE,
        constraint_date=CAL.datetime_at(DATA_DATE, 8, finish=True),
    )
    r = compute_cpm(make_schedule([task("A", 5), fnlt], [("A", "B")]))
    assert r.tf["B"] == -2
    assert r.tf["A"] == -2


def test_project_deadline_applies_to_open_ends():
    sched = make_schedule([task("A", 10)], [], deadline=CAL.datetime_at(DATA_DATE, 7, finish=True))
    assert compute_cpm(sched).tf["A"] == -3


def test_progress_and_retained_logic():
    a = task("A", 5, status=Status.IN_PROGRESS, actual_start=datetime(2026, 2, 25, 8), remaining=2)
    done = task(
        "P",
        3,
        status=Status.COMPLETE,
        actual_start=datetime(2026, 2, 20, 8),
        actual_finish=datetime(2026, 2, 24, 17),
    )
    r = compute_cpm(
        make_schedule([done, a, task("B", 3), task("C", 1)], [("P", "B"), ("A", "C", "FS", 1)])
    )
    assert r.es["A"] == -3  # actual start three working days ago
    assert r.ef["A"] == 2
    assert r.es["B"] == 0  # completed predecessor: free to start at the data date
    assert r.es["C"] == 3


def test_loops_are_reported_and_broken():
    sched = make_schedule(
        [task("A", 1), task("B", 1), task("C", 1)], [("A", "B"), ("B", "C"), ("C", "A")]
    )
    r = compute_cpm(sched)
    assert len(r.cycles) == 1 and sorted(r.cycles[0]) == ["A", "B", "C"]
    assert r.back_edges == 1
    assert set(r.tf) == {"A", "B", "C"}


def test_critical_path_test_passes_on_sound_logic():
    sched = _network()
    base = compute_cpm(sched)
    test = critical_path_test(sched, base, ["A", "C"])
    assert test["passed"] and all(t["finish_moved_days"] == 600 for t in test["tested"])


def test_critical_path_test_fails_when_a_constraint_fakes_criticality():
    # M is critical only because of its mandatory start; B after it has 5 days of float.
    m = milestone(
        "M",
        constraint=ConstraintType.MANDATORY_START,
        constraint_date=CAL.datetime_at(DATA_DATE, 3),
    )
    sched = make_schedule(
        [task("A", 10), m, task("B", 2), milestone("F")], [("A", "F"), ("M", "B"), ("B", "F")]
    )
    base = compute_cpm(sched)
    assert base.tf["M"] == 0
    test = critical_path_test(sched, base, ["A", "M"])
    moved = {t["uid"]: t["finish_moved_days"] for t in test["tested"]}
    assert moved == {"A": 600, "M": 595}
    assert not test["passed"]
