"""The shipped sample project: every format gives the same answers."""

import json

import pytest
from conftest import SAMPLES
from lean_sic.analysis import analyze
from lean_sic.parsers import load_schedule

# Differences planted on purpose: stale P6 dates (XER only), the level-of-effort
# activity (absent from MS Project) and MS Project's own slack values.
EXPECTED_DIFFERENCES = {
    "csv": {"DCMA-09", "EXT-13", "LEAN-09"},
    "xml": {"DCMA-09", "EXT-07", "EXT-13", "LEAN-09"},
}


@pytest.fixture(scope="module")
def results():
    out = {}
    for fmt in ("xer", "xml", "csv"):
        schedule = load_schedule(SAMPLES / f"harbourside-health-centre.{fmt}")
        out[fmt] = analyze(
            schedule,
            weekly_plans=SAMPLES / "weekly-work-plans.csv",
            constraints=SAMPLES / "constraint-log.csv",
        )
    return out


@pytest.mark.parametrize("fmt", ["csv", "xml"])
def test_formats_agree(results, fmt):
    base = {c["id"]: c for c in results["xer"]["checks"]}
    other = {c["id"]: c for c in results[fmt]["checks"]}
    differing = {
        k
        for k in base
        if (base[k]["status"], base[k]["count"]) != (other[k]["status"], other[k]["count"])
    }
    assert differing == EXPECTED_DIFFERENCES[fmt]
    assert results[fmt]["dates"]["forecast_finish"] == results["xer"]["dates"]["forecast_finish"]


def test_planted_problems_are_found(results):
    r = results["xer"]
    checks = {c["id"]: c for c in r["checks"]}
    open_ends = {row["Activity ID"] for row in checks["DCMA-01"]["items"]}
    assert {"H8010", "H8020", "P2080"} <= open_ends
    assert {(row["Predecessor"], row["Successor"]) for row in checks["DCMA-02"]["items"]} == {
        ("FO-L2A-20", "FO-L2A-30"),
        ("FO-L3A-20", "FO-L3A-30"),
    }
    assert {row["Activity ID"] for row in checks["EXT-01"]["items"]} >= {"K7010"}
    assert checks["EXT-06"]["count"] == 1
    assert checks["EXT-07"]["count"] == 1
    assert {row["Activity ID"] for row in checks["LEAN-05"]["items"]} == {"K7000"}
    assert checks["DCMA-07"]["status"] == "fail"
    takt = r["flow"]["takt"]
    assert takt["zones"] == ["L1-A", "L1-B", "L2-A", "L2-B", "L3-A", "L3-B"]
    assert [t["trade"] for t in takt["trades"]] == [
        "MEP",
        "Drylining",
        "Decorating",
        "Ceilings",
        "Flooring",
        "Joinery",
    ]
    assert r["lps"]["weekly"]["ppc_last4"] < 80 < 100
    assert r["project"]["name"] == "Harbourside Health Centre"


def test_result_is_json_serialisable(results):
    text = json.dumps(results["xer"])
    assert json.loads(text)["tool"]["name"] == "Lean Schedule Integrity Checker"
