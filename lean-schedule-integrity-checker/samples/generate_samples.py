"""Generate the fictional sample project used by the docs, the demo and the tests.

    python samples/generate_samples.py

Writes (all fictional, deterministic):

* ``harbourside-health-centre.xer`` - Primavera P6 export
* ``harbourside-health-centre.xml`` - Microsoft Project XML (MSPDI)
* ``harbourside-health-centre.csv`` - CSV schedule
* ``weekly-work-plans.csv`` - Last Planner weekly commitments (PPC)
* ``constraint-log.csv`` - Last Planner make-ready constraint log

The project history is simulated: a baseline plan is calculated from the
start date, an "as-built" run with realistic overruns gives the actual
dates, and the remaining work is rescheduled from the data date. A handful
of integrity and Lean problems are planted on purpose so every check has
something to find.
"""

from __future__ import annotations

import math
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from lean_sic.calendar import WorkCalendar  # noqa: E402
from lean_sic.cpm import compute_cpm  # noqa: E402
from lean_sic.model import (  # noqa: E402
    Activity,
    ActivityType,
    ConstraintType,
    Relationship,
    RelType,
    Schedule,
    Status,
)

PROJECT, CODE = "Harbourside Health Centre", "HHC-01"
START = datetime(2025, 9, 1, 8)
DATA_DATE = datetime(2026, 3, 2, 8)
DEADLINE = datetime(2026, 8, 28, 17)
HOLIDAYS = (
    date(2025, 12, 25),
    date(2025, 12, 26),
    date(2026, 1, 1),
    date(2026, 4, 3),
    date(2026, 4, 6),
    date(2026, 5, 4),
    date(2026, 5, 25),
    date(2026, 8, 31),
)
CAL = WorkCalendar(frozenset(range(5)), HOLIDAYS, "Standard 5-day (UK)")
SEVEN_DAY = 7  # calendar days per week for curing

WBS = {
    "MS": ("1", "Milestones", None),
    "PRE": ("2", "Preconstruction & procurement", None),
    "SUB": ("3", "Substructure", None),
    "SUP": ("4", "Superstructure", None),
    "ENV": ("5", "Envelope", None),
    "FIT": ("6", "Fit-out", None),
    "FIT1": ("6.1", "Level 1", "FIT"),
    "FIT2": ("6.2", "Level 2", "FIT"),
    "FIT3": ("6.3", "Level 3", "FIT"),
    "MEP": ("7", "MEP & commissioning", None),
    "EXT": ("8", "External works & handover", None),
}
OVERRUN = {
    "MS": 1.0,
    "PRE": 1.0,
    "SUB": 1.0,
    "SUP": 1.1,
    "ENV": 1.25,
    "FIT1": 1.15,
    "FIT2": 1.15,
    "FIT3": 1.15,
    "MEP": 1.0,
    "EXT": 1.0,
}
CREWS = {
    "Groundworks": "Groundworks gang",
    "Concrete": "Concrete gang",
    "Steel": "Steel erectors",
    "Facade": "Facade fixers",
    "Roofing": "Roofing crew",
    "Masonry": "Bricklayers",
    "Scaffolding": "Scaffold crew",
    "MEP": "MEP fitters",
    "Drylining": "Dryliners",
    "Decorating": "Decorators",
    "Ceilings": "Ceiling fixers",
    "Flooring": "Floor layers",
    "Joinery": "Joiners",
    "Lift": "Lift engineers",
    "Commissioning": "Commissioning engineers",
}

ACTS: list[dict] = []
LINKS: list[tuple[str, str, str, float]] = []


def act(code, name, wbs, dur, trade=None, zone=None, kind=ActivityType.TASK, cons=None, cal=5):
    ACTS.append(
        {
            "code": code,
            "name": name,
            "wbs": wbs,
            "dur": dur,
            "trade": trade,
            "zone": zone,
            "kind": kind,
            "cons": cons,
            "cal": cal,
        }
    )


def link(pred, succ, kind="FS", lag=0.0):
    LINKS.append((pred, succ, kind, lag))


MS, MF = ActivityType.START_MILESTONE, ActivityType.FINISH_MILESTONE

# -- milestones -----------------------------------------------------------------
act("M1000", "Notice to proceed", "MS", 0, kind=MS)
act("M1010", "Superstructure topped out", "MS", 0, kind=MF)
act("M1020", "Building watertight", "MS", 0, kind=MF)
act(
    "M1030",
    "Level 3 handover to tenant",
    "MS",
    0,
    kind=MF,
    cons=(ConstraintType.FINISH_ON_OR_BEFORE, datetime(2026, 8, 14, 17)),
)
act("M1040", "Substantial completion", "MS", 0, kind=MF)
act("M1050", "Project completion", "MS", 0, kind=MF)
# -- preconstruction & procurement ----------------------------------------------------
act("P2000", "Mobilise site", "PRE", 5, "GC", "Site")
act("P2010", "Temporary works design", "PRE", 10, "GC")
act("P2020", "Site set-up and hoarding", "PRE", 8, "GC", "Site")
act("P2030", "Facade design and submittals", "PRE", 30, "Facade")
act("P2040", "Facade panel approval", "PRE", 10, "Facade")
act("P2050", "Facade panels delivered - batch 1", "PRE", 0, kind=MF)
act(
    "P2055",
    "Facade panels delivered - batch 2",
    "PRE",
    0,
    kind=MF,
    cons=(ConstraintType.MANDATORY_START, datetime(2026, 3, 30, 8)),
)
act("P2060", "MEP plant procurement (long lead)", "PRE", 60, "MEP")
act("P2070", "Lift procurement", "PRE", 70, "Lift")
act(
    "P2080",
    "Utility connection - gas",
    "PRE",
    10,
    "Utilities",
    "Site",
    cons=(ConstraintType.START_ON_OR_AFTER, datetime(2026, 5, 4, 8)),
)
act("P2090", "Utility connection - electrical", "PRE", 10, "Utilities", "Site")
# -- substructure -------------------------------------------------------------------------
act("S3000", "Bulk excavation", "SUB", 15, "Groundworks", "Ground")
act("S3010", "Piling", "SUB", 20, "Groundworks", "Ground")
act("S3020", "Pile caps and ground beams", "SUB", 12, "Concrete", "Ground")
act("S3030", "Below-ground drainage", "SUB", 10, "Groundworks", "Ground")
act("S3040", "Ground floor slab", "SUB", 8, "Concrete", "Ground")
# -- superstructure ---------------------------------------------------------------------
act("F4000", "Columns and core - level 1", "SUP", 6, "Concrete", "L1")
act("F4010", "Slab - level 2", "SUP", 8, "Concrete", "L2")
act("F4020", "Columns and core - level 2", "SUP", 6, "Concrete", "L2")
act("F4030", "Slab - level 3", "SUP", 8, "Concrete", "L3")
act("F4040", "Columns and core - level 3", "SUP", 6, "Concrete", "L3")
act("F4050", "Roof slab", "SUP", 8, "Concrete", "Roof")
act("F4055", "Cure roof slab", "SUP", 10, "Concrete", "Roof", cal=SEVEN_DAY)
act("F4060", "Roof steel and plant deck", "SUP", 10, "Steel", "Roof")
# -- envelope ---------------------------------------------------------------------------------
act("E5000", "Scaffold erection", "ENV", 10, "Scaffolding", "Envelope")
act("E5010", "Roof insulation", "ENV", 5, "Roofing", "Roof")
act("E5020", "Roof membrane", "ENV", 6, "Roofing", "Roof")
act("E5030", "Curtain wall - north and east elevations", "ENV", 48, "Facade", "Envelope")
act("E5035", "Curtain wall - south and west elevations", "ENV", 30, "Facade", "Envelope")
act("E5040", "Brickwork - plant enclosure", "ENV", 25, "Masonry", "Roof")
act("E5050", "Windows and louvres", "ENV", 15, None, "Envelope")
act("E5060", "Scaffold strike - east elevation", "ENV", 5, "Scaffolding", "Envelope")
# -- MEP & commissioning --------------------------------------------------------------------
act("K7000", "MEP risers and primary distribution", "MEP", 60, "MEP", "Risers")
act("K7010", "Lift installation", "MEP", 25, "Lift", "Core")
act("K7020", "Commissioning and testing", "MEP", 50, "Commissioning", "Building")
act("K7030", "Fire alarm and life safety tests", "MEP", 10, "Commissioning", "Building")
act("K7040", "Permanent power on", "MEP", 1, "MEP", "Building")
act("K7050", "Temporary power off", "MEP", 1, "MEP", "Building")
# -- external works & handover -----------------------------------------------------------------
act("H8000", "External works and paving", "EXT", 25, "Groundworks", "Site")
act(
    "H8010",
    "Landscaping",
    "EXT",
    15,
    "Landscaping",
    "Site",
    cons=(ConstraintType.START_ON_OR_AFTER, datetime(2026, 6, 1, 8)),
)
act("H8020", "Install signage", "EXT", 5, "Signage", "Building")
act("H8030", "Final clean", "EXT", 10, "GC", "Building")
act("H8040", "Snagging and defects", "EXT", 15, "GC", "Building")
act("H8050", "Issue handover documents", "EXT", 0, "GC")
act("H8060", "Demobilise site", "EXT", 5, "GC", "Site")
act("L9000", "Site management and preliminaries", "PRE", 0, "GC", kind=ActivityType.LOE)

# -- fit-out: six zones x six trades (the takt candidates) -----------------------------------------
ZONES = [("L1-A", 1.0), ("L1-B", 1.2), ("L2-A", 1.0), ("L2-B", 1.8), ("L3-A", 0.7), ("L3-B", 0.7)]
STEPS = [
    ("10", "MEP first fix", "MEP", 4),
    ("20", "Partition framing and boarding", "Drylining", 6),
    ("30", "Tape, joint and paint", "Decorating", 4),
    ("40", "Ceilings", "Ceilings", 3),
    ("50", "Floor finishes", "Flooring", 3),
    ("60", "Doors and ironmongery", "Joinery", 2),
]
CREW_FLOW = {"10", "20", "40", "50"}  # trades with crew logic zone to zone


def fo(zone: str, step: str) -> str:
    return f"FO-{zone.replace('-', '')}-{step}"


for zone, factor in ZONES:
    level = zone[1]
    for num, name, trade, d in STEPS:
        act(
            fo(zone, num), f"{name} - {zone}", f"FIT{level}", max(1, round(d * factor)), trade, zone
        )
act("QA-L1-FS", "Fire stopping inspection - level 1", "FIT1", 1, None, "L1-B")

# -- logic -------------------------------------------------------------------------------------------
for a, b in [
    ("M1000", "P2000"),
    ("P2000", "P2020"),
    ("P2000", "S3000"),
    ("S3000", "S3010"),
    ("S3010", "S3020"),
    ("S3020", "S3030"),
    ("S3030", "S3040"),
    ("S3040", "F4000"),
    ("F4000", "F4010"),
    ("F4010", "F4020"),
    ("F4020", "F4030"),
    ("F4030", "F4040"),
    ("F4040", "F4050"),
    ("F4050", "F4055"),
    ("F4055", "F4060"),
    ("F4060", "M1010"),
    ("M1000", "P2030"),
    ("P2030", "P2040"),
    ("P2050", "E5030"),
    ("P2055", "E5035"),
    ("F4030", "E5000"),
    ("E5000", "E5030"),
    ("E5030", "E5035"),
    ("F4060", "E5010"),
    ("E5010", "E5020"),
    ("E5020", "M1020"),
    ("E5010", "M1020"),
    ("E5035", "M1020"),
    ("E5030", "E5050"),
    ("E5050", "M1020"),
    ("F4060", "E5040"),
    ("E5040", "M1020"),
    ("E5030", "E5060"),
    ("E5060", "H8000"),
    ("H8000", "M1040"),
    ("M1000", "P2060"),
    ("P2060", "K7000"),
    ("F4020", "K7000"),
    ("K7000", "K7020"),
    ("M1000", "P2070"),
    ("K7010", "K7020"),
    ("P2090", "K7040"),
    ("K7040", "K7020"),
    ("P2080", "K7020"),
    ("K7020", "M1040"),
    ("K7030", "M1040"),
    ("M1030", "M1040"),
    ("M1040", "H8050"),
    ("H8050", "M1050"),
    ("M1020", "P2090"),
    ("M1040", "H8060"),
    ("H8060", "M1050"),
    ("H8030", "H8040"),
    ("H8040", "M1040"),
    ("F4020", fo("L1-A", "10")),
    ("F4040", fo("L2-A", "10")),
    ("E5020", fo("L3-A", "10")),
    (fo("L1-B", "20"), "QA-L1-FS"),
    ("QA-L1-FS", fo("L1-A", "40")),
    ("QA-L1-FS", fo("L1-B", "40")),
    (fo("L3-B", "10"), "K7020"),
    (fo("L3-A", "60"), "M1030"),
    (fo("L3-B", "60"), "M1030"),
    (fo("L3-B", "60"), "H8030"),
    (fo("L1-A", "60"), "H8020"),
]:
    link(a, b)
link("P2040", "P2050", lag=25)  # fabrication hidden in a long lag
link("P2050", "P2055")
link("P2010", "P2020", "SS", 5)  # dangling finish: only a start-to-start successor
link("P2000", "P2010")
link("P2070", "K7010", "FF", 0)  # dangling start: only a finish-to-finish predecessor
link("E5020", "K7010", "FF", 0)
link("K7020", "K7030", "SS", 20)
link("K7040", "K7050", "SF", 0)  # start-to-finish: temporary power stays on until permanent is live
link("K7050", "K7020")
link("M1000", "L9000", "SS")
link("L9000", "H8060")  # a level-of-effort driving real work
link("F4050", "E5010", "FS", 0)
link("K7000", fo("L1-A", "10"), "SS", 10)
link("M1020", fo("L1-A", "30"))
for zone, _ in ZONES:
    link(fo(zone, "10"), fo(zone, "20"))
    if zone in ("L2-A", "L3-A"):
        link(fo(zone, "20"), fo(zone, "30"), "FS", -2)  # leads
    else:
        link(fo(zone, "20"), fo(zone, "30"), "SS", 2)
        link(fo(zone, "20"), fo(zone, "30"), "FF", 1)
    link(fo(zone, "30"), fo(zone, "40"))
    link(fo(zone, "40"), fo(zone, "50"))
    link(fo(zone, "50"), fo(zone, "60"))
    link("M1020", fo(zone, "40"))
for i in range(1, len(ZONES)):
    prev, cur = ZONES[i - 1][0], ZONES[i][0]
    for num in CREW_FLOW:
        link(fo(prev, num), fo(cur, num))


# -- simulation helpers ---------------------------------------------------------------------------------
def build(
    data_date: datetime, durations: dict[str, float], progress: dict | None = None
) -> Schedule:
    acts = {}
    for i, a in enumerate(ACTS):
        uid = str(1000 + i)
        act_obj = Activity(
            uid=uid,
            code=a["code"],
            name=a["name"],
            type=a["kind"],
            duration=float(durations[a["code"]]),
        )
        act_obj.calendar_days_per_week = a["cal"] if a["cal"] != 5 else None
        if a["cons"]:
            act_obj.constraint, act_obj.constraint_date = a["cons"]
        if progress and a["code"] in progress:
            p = progress[a["code"]]
            act_obj.status, act_obj.actual_start, act_obj.actual_finish = (
                p["status"],
                p.get("start"),
                p.get("finish"),
            )
            act_obj.remaining = p.get("remaining")
        acts[uid] = act_obj
    by_code = {a.code: a.uid for a in acts.values()}
    rels = [Relationship(by_code[p], by_code[s], RelType(k), float(lag)) for p, s, k, lag in LINKS]
    return Schedule(PROJECT, data_date, acts, rels, "sim", calendar=CAL)


def offsets_to_dates(sched: Schedule, cpm, code: str):
    uid = next(a.uid for a in sched.activities.values() if a.code == code)
    a = sched.activities[uid]
    if uid not in cpm.es:  # level of effort: spans the whole project
        return START, DEADLINE
    start = CAL.datetime_at(sched.data_date, cpm.es[uid])
    finish = CAL.datetime_at(sched.data_date, cpm.ef[uid], finish=True)
    if a.type == ActivityType.START_MILESTONE or (a.duration == 0 and finish < start):
        finish = start if a.type == ActivityType.START_MILESTONE else finish
    return start, finish


def simulate():
    planned = {a["code"]: a["dur"] for a in ACTS}
    base = build(START, planned)
    base_cpm = compute_cpm(base)
    baseline = {a["code"]: offsets_to_dates(base, base_cpm, a["code"]) for a in ACTS}

    rng = random.Random(7)  # noqa: S311 - deterministic sample data
    actual = {
        a["code"]: (
            math.ceil(a["dur"] * OVERRUN[a["wbs"]] + rng.choice([0, 0, 0, 1, 2])) if a["dur"] else 0
        )
        for a in ACTS
    }
    built = build(START, actual)
    built_cpm = compute_cpm(built)
    as_built = {a["code"]: offsets_to_dates(built, built_cpm, a["code"]) for a in ACTS}

    progress: dict[str, dict] = {}
    for a in ACTS:
        start, finish = as_built[a["code"]]
        if a["kind"] == ActivityType.LOE:
            progress[a["code"]] = {"status": Status.IN_PROGRESS, "start": START}
            continue
        if finish < DATA_DATE and (a["dur"] == 0 and start < DATA_DATE or a["dur"] > 0):
            progress[a["code"]] = {
                "status": Status.COMPLETE,
                "start": start,
                "finish": finish,
                "remaining": 0.0,
            }
        elif start < DATA_DATE:
            left = max(1, CAL.count(DATA_DATE.date(), finish.date()) + 1)
            progress[a["code"]] = {
                "status": Status.IN_PROGRESS,
                "start": start,
                "remaining": float(min(left, actual[a["code"]])),
            }
    # planted: stalled MEP risers, out-of-sequence drylining, invalid actual start
    progress["K7000"] = {
        "status": Status.IN_PROGRESS,
        "start": datetime(2026, 1, 12, 8),
        "remaining": 51.0,
    }
    progress[fo("L1-A", "10")] = {
        "status": Status.IN_PROGRESS,
        "start": datetime(2026, 2, 2, 8),
        "remaining": 2.0,
    }
    progress[fo("L1-A", "20")] = {
        "status": Status.IN_PROGRESS,
        "start": datetime(2026, 2, 26, 8),
        "remaining": 5.0,
    }
    progress["E5060"] = {
        "status": Status.IN_PROGRESS,
        "start": datetime(2026, 3, 4, 8),
        "remaining": 3.0,
    }
    return baseline, as_built, progress, actual


def current_schedule(progress) -> tuple[Schedule, object]:
    durations = {a["code"]: a["dur"] for a in ACTS}
    sched = build(DATA_DATE, durations, progress)
    sched.deadline = DEADLINE
    for a in sched.activities.values():
        p = progress.get(a.code)
        if p and p["status"] == Status.IN_PROGRESS and a.type == ActivityType.LOE:
            a.remaining = float(CAL.count(DATA_DATE.date(), DEADLINE.date()))
    return sched, compute_cpm(sched)


# -- writers ----------------------------------------------------------------------------------------------
def fmt(d: datetime | None) -> str:
    return d.strftime("%Y-%m-%d %H:%M") if d else ""


def hours(days: float | None) -> str:
    if days is None:
        return ""
    value = days * 8
    return str(int(round(value))) if abs(value - round(value)) < 1e-6 else f"{value:.1f}"


def clndr_data(workdays: set[int], holidays: tuple[date, ...]) -> str:
    days = []
    for p6_day in range(1, 8):
        weekday = (p6_day - 2) % 7
        if weekday in workdays:
            days.append(f"(0||{p6_day}()((0||0(s|08:00|f|12:00)())(0||1(s|13:00|f|17:00)())))")
        else:
            days.append(f"(0||{p6_day}()())")
    exceptions = "".join(
        f"(0||{i}(d|{(h - date(1899, 12, 30)).days})())" for i, h in enumerate(holidays)
    )
    return f"(0||CalendarData()((0||DaysOfWeek()({''.join(days)}))(0||VIEW(ShowTotal|Y)())(0||Exceptions()({exceptions}))))"


def write_xer(sched: Schedule, cpm, baseline: dict, path: Path) -> None:
    acts = list(sched.activities.values())
    meta = {a["code"]: a for a in ACTS}
    wbs_ids = {key: str(500 + i) for i, key in enumerate(WBS)}
    trades = sorted({a["trade"] for a in ACTS if a["trade"]})
    zones = sorted({a["zone"] for a in ACTS if a["zone"]})
    rsrc = {crew: str(300 + i) for i, crew in enumerate(sorted(set(CREWS.values())))}
    out: list[str] = [
        "ERMHDR\t20.12\t2026-03-02\tProject\tADMIN\tadmin\tdbxDatabaseNoName\tProject Management\tGBP"
    ]

    def table(name: str, fields: list[str], rows: list[list[str]]) -> None:
        out.append(f"%T\t{name}")
        out.append("%F\t" + "\t".join(fields))
        out.extend("%R\t" + "\t".join(r) for r in rows)

    finish = max(
        (
            CAL.datetime_at(DATA_DATE, cpm.ef[u], finish=True)
            for u in cpm.ef
            if not sched.activities[u].is_complete
        ),
        default=DEADLINE,
    )
    table(
        "PROJECT",
        [
            "proj_id",
            "proj_short_name",
            "clndr_id",
            "last_recalc_date",
            "plan_start_date",
            "plan_end_date",
            "scd_end_date",
            "critical_drtn_hr_cnt",
            "sum_base_proj_id",
        ],
        [["100", CODE, "1", fmt(DATA_DATE), fmt(START), fmt(DEADLINE), fmt(finish), "0", ""]],
    )
    table(
        "CALENDAR",
        [
            "clndr_id",
            "default_flag",
            "clndr_name",
            "proj_id",
            "day_hr_cnt",
            "week_hr_cnt",
            "clndr_type",
            "clndr_data",
        ],
        [
            ["1", "Y", CAL.name, "", "8", "40", "CA_Base", clndr_data(set(range(5)), HOLIDAYS)],
            ["2", "N", "7-day curing", "", "8", "56", "CA_Base", clndr_data(set(range(7)), ())],
        ],
    )
    wbs_rows = [["499", "100", "Y", "0", CODE, PROJECT, ""]]
    for i, (key, (num, name, parent)) in enumerate(WBS.items()):
        wbs_rows.append(
            [wbs_ids[key], "100", "N", str(i + 1), num, name, wbs_ids[parent] if parent else "499"]
        )
    table(
        "PROJWBS",
        [
            "wbs_id",
            "proj_id",
            "proj_node_flag",
            "seq_num",
            "wbs_short_name",
            "wbs_name",
            "parent_wbs_id",
        ],
        wbs_rows,
    )
    table(
        "RSRC",
        ["rsrc_id", "rsrc_name", "rsrc_short_name", "rsrc_type"],
        [[rid, name, name.upper()[:10], "RT_Labor"] for name, rid in rsrc.items()],
    )
    table(
        "ACTVTYPE",
        ["actv_code_type_id", "actv_code_type", "proj_id", "actv_code_type_scope"],
        [["10", "Trade", "100", "AS_Project"], ["11", "Zone", "100", "AS_Project"]],
    )
    codes = [[str(1000 + i), "10", t, f"{t} trade", str(i)] for i, t in enumerate(trades)]
    codes += [[str(2000 + i), "11", z, f"Zone {z}", str(i)] for i, z in enumerate(zones)]
    table(
        "ACTVCODE",
        ["actv_code_id", "actv_code_type_id", "short_name", "actv_code_name", "seq_num"],
        codes,
    )
    trade_id = {t: str(1000 + i) for i, t in enumerate(trades)}
    zone_id = {z: str(2000 + i) for i, z in enumerate(zones)}
    kinds = {
        ActivityType.TASK: "TT_Task",
        MS: "TT_Mile",
        MF: "TT_FinMile",
        ActivityType.LOE: "TT_LOE",
    }
    status = {
        Status.NOT_STARTED: "TK_NotStart",
        Status.IN_PROGRESS: "TK_Active",
        Status.COMPLETE: "TK_Complete",
    }
    cstr = {
        ConstraintType.FINISH_ON_OR_BEFORE: "CS_MEOB",
        ConstraintType.MANDATORY_START: "CS_MANDSTART",
        ConstraintType.START_ON_OR_AFTER: "CS_MSOA",
    }
    task_rows, rsrc_rows, actv_rows = [], [], []
    for a in acts:
        m = meta[a.code]
        uid = a.uid
        done = a.is_complete
        es = ef = ls = lf = None
        tf = ff = None
        if not done and uid in cpm.ef:
            es = CAL.datetime_at(DATA_DATE, cpm.res[uid])
            ef = CAL.datetime_at(DATA_DATE, cpm.ef[uid], finish=True)
            ls = CAL.datetime_at(DATA_DATE, cpm.ls[uid])
            lf = CAL.datetime_at(DATA_DATE, cpm.lf[uid], finish=True)
            tf, ff = cpm.tf[uid], cpm.ff[uid]
            if a.is_milestone:
                ef = es if a.type == MS else ef
        if a.type == ActivityType.LOE:
            es, ef = DATA_DATE, DEADLINE
        if a.code == "QA-L1-FS":  # planted: stale forecast dates (not rescheduled)
            es, ef = datetime(2026, 2, 24, 8), datetime(2026, 2, 24, 17)
        b_start, b_finish = baseline[a.code]
        cal_id = "2" if m["cal"] == SEVEN_DAY else "1"
        crew = CREWS.get(m["trade"] or "")
        has_crew = bool(crew) and m["wbs"] not in ("PRE", "EXT") and not a.is_milestone
        remaining = 0.0 if done else a.remaining_duration
        pct = (
            100.0
            if done
            else (round(100.0 * (1 - remaining / a.duration), 1) if a.duration else 0.0)
        )
        con = cstr.get(a.constraint, "")
        task_rows.append(
            [
                uid,
                "100",
                wbs_ids[m["wbs"]],
                cal_id,
                f"{pct:g}",
                "CP_Drtn",
                kinds[a.type],
                status[a.status],
                a.code,
                a.name,
                rsrc[crew] if has_crew else "",
                hours(tf),
                hours(ff),
                hours(remaining),
                hours(a.duration),
                fmt(a.constraint_date) if con else "",
                fmt(a.actual_start),
                fmt(a.actual_finish),
                fmt(ls),
                fmt(lf),
                fmt(es),
                fmt(ef),
                fmt(b_start),
                fmt(b_finish),
                con,
                "",
            ]
        )
        if has_crew:
            rsrc_rows.append(
                [
                    str(len(rsrc_rows) + 1),
                    uid,
                    "100",
                    rsrc[crew],
                    hours(a.duration),
                    hours(remaining),
                ]
            )
        if m["trade"] and m["trade"] in trade_id:
            actv_rows.append([uid, "10", trade_id[m["trade"]], "100"])
        if m["zone"]:
            actv_rows.append([uid, "11", zone_id[m["zone"]], "100"])
    table(
        "TASK",
        [
            "task_id",
            "proj_id",
            "wbs_id",
            "clndr_id",
            "phys_complete_pct",
            "complete_pct_type",
            "task_type",
            "status_code",
            "task_code",
            "task_name",
            "rsrc_id",
            "total_float_hr_cnt",
            "free_float_hr_cnt",
            "remain_drtn_hr_cnt",
            "target_drtn_hr_cnt",
            "cstr_date",
            "act_start_date",
            "act_end_date",
            "late_start_date",
            "late_end_date",
            "early_start_date",
            "early_end_date",
            "target_start_date",
            "target_end_date",
            "cstr_type",
            "driving_path_flag",
        ],
        task_rows,
    )
    by_code = {a.code: a.uid for a in acts}
    pred_rows = [
        [str(i + 1), by_code[s], by_code[p], "100", "100", f"PR_{k}", hours(lag)]
        for i, (p, s, k, lag) in enumerate(LINKS)
    ]
    table(
        "TASKPRED",
        [
            "task_pred_id",
            "task_id",
            "pred_task_id",
            "proj_id",
            "pred_proj_id",
            "pred_type",
            "lag_hr_cnt",
        ],
        pred_rows,
    )
    table(
        "TASKRSRC",
        ["taskrsrc_id", "task_id", "proj_id", "rsrc_id", "target_qty", "remain_qty"],
        rsrc_rows,
    )
    table("TASKACTV", ["task_id", "actv_code_type_id", "actv_code_id", "proj_id"], actv_rows)
    out.append("%E")
    path.write_bytes(("\r\n".join(out) + "\r\n").encode("cp1252"))


def iso_duration(days: float) -> str:
    total_minutes = int(round(days * 480))
    return f"PT{total_minutes // 60}H{total_minutes % 60}M0S"


def write_mspdi(sched: Schedule, cpm, baseline: dict, path: Path) -> None:
    meta = {a["code"]: a for a in ACTS}
    acts = [a for a in sched.activities.values() if a.type != ActivityType.LOE]
    uid_of = {a.code: str(i + 1) for i, a in enumerate(acts)}
    crews = sorted(set(CREWS.values()))
    res_uid = {c: str(i + 1) for i, c in enumerate(crews)}
    x = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<Project xmlns="http://schemas.microsoft.com/project">',
    ]
    x += [
        f"<Name>{CODE}.xml</Name>",
        f"<Title>{escape(PROJECT)}</Title>",
        "<ScheduleFromStart>1</ScheduleFromStart>",
        f"<StartDate>{START.isoformat()}</StartDate>",
        f"<StatusDate>{DATA_DATE.isoformat()}</StatusDate>",
        "<CalendarUID>1</CalendarUID>",
        "<MinutesPerDay>480</MinutesPerDay>",
        "<MinutesPerWeek>2400</MinutesPerWeek>",
    ]
    x += [
        "<ExtendedAttributes>",
        "<ExtendedAttribute><FieldID>188743731</FieldID><FieldName>Text1</FieldName><Alias>Trade</Alias></ExtendedAttribute>",
        "<ExtendedAttribute><FieldID>188743734</FieldID><FieldName>Text2</FieldName><Alias>Zone</Alias></ExtendedAttribute>",
        "<ExtendedAttribute><FieldID>188743737</FieldID><FieldName>Text3</FieldName><Alias>Activity ID</Alias></ExtendedAttribute>",
        "</ExtendedAttributes>",
    ]
    x.append(
        "<Calendars><Calendar><UID>1</UID><Name>Standard 5-day (UK)</Name><IsBaseCalendar>1</IsBaseCalendar><WeekDays>"
    )
    for day_type in range(1, 8):
        working = 1 if (day_type - 2) % 7 < 5 else 0
        x.append(
            f"<WeekDay><DayType>{day_type}</DayType><DayWorking>{working}</DayWorking></WeekDay>"
        )
    x.append("</WeekDays><Exceptions>")
    for h in HOLIDAYS:
        x.append(
            f"<Exception><TimePeriod><FromDate>{h.isoformat()}T00:00:00</FromDate><ToDate>{h.isoformat()}T23:59:00</ToDate></TimePeriod><DayWorking>0</DayWorking></Exception>"
        )
    x.append("</Exceptions></Calendar>")
    x.append(
        "<Calendar><UID>2</UID><Name>7-day curing</Name><IsBaseCalendar>1</IsBaseCalendar><WeekDays>"
    )
    x += [
        f"<WeekDay><DayType>{d}</DayType><DayWorking>1</DayWorking></WeekDay>" for d in range(1, 8)
    ]
    x.append("</WeekDays></Calendar></Calendars><Tasks>")
    x.append(
        "<Task><UID>0</UID><ID>0</ID><Name>Harbourside Health Centre</Name><Summary>1</Summary><OutlineNumber>0</OutlineNumber><OutlineLevel>0</OutlineLevel></Task>"
    )
    next_uid = len(acts) + 1
    summary_uid = {}
    for key, (num, name, _parent) in WBS.items():
        summary_uid[key] = str(next_uid)
        x.append(
            f"<Task><UID>{next_uid}</UID><ID>{next_uid}</ID><Name>{escape(name)}</Name><Summary>1</Summary><OutlineNumber>{num}</OutlineNumber></Task>"
        )
        next_uid += 1
    counters: dict[str, int] = {}
    mtypes = {
        ConstraintType.FINISH_ON_OR_BEFORE: 7,
        ConstraintType.MANDATORY_START: 2,
        ConstraintType.START_ON_OR_AFTER: 4,
    }
    link_types = {"FF": 0, "FS": 1, "SF": 2, "SS": 3}
    by_uid = {a.uid: a for a in acts}
    for a in acts:
        m = meta[a.code]
        num = WBS[m["wbs"]][0]
        counters[num] = counters.get(num, 0) + 1
        outline = f"{num}.{counters[num]}"
        uid = a.uid
        es = CAL.datetime_at(DATA_DATE, cpm.res[uid]) if not a.is_complete else a.actual_start
        ef = (
            CAL.datetime_at(DATA_DATE, cpm.ef[uid], finish=True)
            if not a.is_complete
            else a.actual_finish
        )
        if a.is_milestone and not a.is_complete:
            ef = es if a.type == MS else ef
        b_start, b_finish = baseline[a.code]
        parts = [
            f"<UID>{uid_of[a.code]}</UID>",
            f"<ID>{uid_of[a.code]}</ID>",
            f"<Name>{escape(a.name)}</Name>",
            f"<OutlineNumber>{outline}</OutlineNumber>",
            f"<Milestone>{1 if a.is_milestone else 0}</Milestone>",
            f"<Duration>{iso_duration(a.duration)}</Duration>",
            f"<RemainingDuration>{iso_duration(a.remaining_duration)}</RemainingDuration>",
        ]
        if es:
            parts.append(f"<Start>{es.isoformat()}</Start>")
        if ef:
            parts.append(f"<Finish>{ef.isoformat()}</Finish>")
        if a.actual_start:
            parts.append(f"<ActualStart>{a.actual_start.isoformat()}</ActualStart>")
        if a.actual_finish:
            parts.append(f"<ActualFinish>{a.actual_finish.isoformat()}</ActualFinish>")
        pct = (
            100
            if a.is_complete
            else (int(round(100 * (1 - a.remaining_duration / a.duration))) if a.duration else 0)
        )
        parts.append(f"<PercentComplete>{pct}</PercentComplete>")
        if a.constraint in mtypes:
            parts.append(
                f"<ConstraintType>{mtypes[a.constraint]}</ConstraintType><ConstraintDate>{a.constraint_date.isoformat()}</ConstraintDate>"
            )
        if not a.is_complete and uid in cpm.tf:
            parts.append(f"<TotalSlack>{int(round(cpm.tf[uid] * 4800))}</TotalSlack>")
        if m["cal"] == SEVEN_DAY:
            parts.append("<CalendarUID>2</CalendarUID>")
        if a.code == "M1050":
            parts.append(f"<Deadline>{DEADLINE.isoformat()}</Deadline>")
        parts.append(
            f"<ExtendedAttribute><FieldID>188743737</FieldID><Value>{escape(a.code)}</Value></ExtendedAttribute>"
        )
        if m["trade"]:
            parts.append(
                f"<ExtendedAttribute><FieldID>188743731</FieldID><Value>{escape(m['trade'])}</Value></ExtendedAttribute>"
            )
        if m["zone"]:
            parts.append(
                f"<ExtendedAttribute><FieldID>188743734</FieldID><Value>{escape(m['zone'])}</Value></ExtendedAttribute>"
            )
        parts.append(
            f"<Baseline><Number>0</Number><Start>{b_start.isoformat()}</Start><Finish>{b_finish.isoformat()}</Finish><Duration>{iso_duration(a.duration)}</Duration></Baseline>"
        )
        for r in sched.predecessors(uid):
            if r.pred in by_uid:
                parts.append(
                    f"<PredecessorLink><PredecessorUID>{uid_of[by_uid[r.pred].code]}</PredecessorUID><Type>{link_types[r.type.value]}</Type><LinkLag>{int(round(r.lag * 4800))}</LinkLag><LagFormat>7</LagFormat></PredecessorLink>"
                )
        x.append("<Task>" + "".join(parts) + "</Task>")
    x.append("</Tasks><Resources>")
    x += [
        f"<Resource><UID>{res_uid[c]}</UID><ID>{res_uid[c]}</ID><Name>{escape(c)}</Name></Resource>"
        for c in crews
    ]
    x.append("</Resources><Assignments>")
    n = 1
    for a in acts:
        m = meta[a.code]
        crew = CREWS.get(m["trade"] or "")
        if crew and m["wbs"] not in ("PRE", "EXT") and not a.is_milestone:
            x.append(
                f"<Assignment><UID>{n}</UID><TaskUID>{uid_of[a.code]}</TaskUID><ResourceUID>{res_uid[crew]}</ResourceUID></Assignment>"
            )
            n += 1
    x.append("</Assignments></Project>")
    path.write_text("\n".join(x), encoding="utf-8")


def write_csv(sched: Schedule, baseline: dict, path: Path) -> None:
    import csv

    meta = {a["code"]: a for a in ACTS}
    with path.open("w", newline="", encoding="utf-8") as fh:
        fh.write(
            f"# project: {PROJECT}\n# data_date: {DATA_DATE:%Y-%m-%d}\n# deadline: {DEADLINE:%Y-%m-%d}\n"
        )
        fh.write("# holidays: " + ", ".join(h.isoformat() for h in HOLIDAYS) + "\n")
        w = csv.writer(fh)
        w.writerow(
            [
                "id",
                "name",
                "type",
                "wbs",
                "duration",
                "remaining_duration",
                "actual_start",
                "actual_finish",
                "baseline_start",
                "baseline_finish",
                "predecessors",
                "constraint",
                "constraint_date",
                "trade",
                "zone",
                "resources",
            ]
        )
        types = {
            ActivityType.TASK: "task",
            MS: "start milestone",
            MF: "finish milestone",
            ActivityType.LOE: "loe",
        }
        cons = {
            ConstraintType.FINISH_ON_OR_BEFORE: "FNLT",
            ConstraintType.MANDATORY_START: "Mandatory start",
            ConstraintType.START_ON_OR_AFTER: "SNET",
        }
        for a in sched.activities.values():
            m = meta[a.code]
            preds = []
            for r in sched.predecessors(a.uid):
                p = sched.activities[r.pred].code
                lag = f"{r.lag:+g}" if r.lag else ""
                preds.append(p if r.type == RelType.FS and not lag else f"{p}{r.type.value}{lag}")
            wbs = WBS[m["wbs"]]
            wbs_path = f"{WBS[wbs[2]][1]} > {wbs[1]}" if wbs[2] else wbs[1]
            b_start, b_finish = baseline[a.code]
            crew = CREWS.get(m["trade"] or "")
            factor = 5 / 7 if m["cal"] == SEVEN_DAY else 1.0  # CSV uses one (5-day) calendar
            duration = round(a.duration * factor, 4)
            remaining = round(a.remaining_duration * factor, 4)
            w.writerow(
                [
                    a.code,
                    a.name,
                    types[a.type],
                    wbs_path,
                    f"{duration:g}",
                    f"{remaining:g}" if a.status == Status.IN_PROGRESS else "",
                    a.actual_start.strftime("%Y-%m-%d") if a.actual_start else "",
                    a.actual_finish.strftime("%Y-%m-%d") if a.actual_finish else "",
                    b_start.strftime("%Y-%m-%d"),
                    b_finish.strftime("%Y-%m-%d"),
                    "; ".join(preds),
                    cons.get(a.constraint, ""),
                    a.constraint_date.strftime("%Y-%m-%d") if a.constraint_date else "",
                    m["trade"] or "",
                    m["zone"] or "",
                    crew if crew and m["wbs"] not in ("PRE", "EXT") and not a.is_milestone else "",
                ]
            )


def write_weekly_plans(as_built: dict, path: Path) -> None:
    import csv

    rng = random.Random(2026)  # noqa: S311 - deterministic sample data
    meta = {a["code"]: a for a in ACTS}
    targets = [0.55, 0.6, 0.57, 0.65, 0.68, 0.72, 0.76, 0.79]
    reasons = [
        (
            "Prerequisite work",
            [
                "Previous trade not finished",
                "Slab edge not handed over",
                "Scaffold lift not adapted",
            ],
            30,
        ),
        (
            "Materials",
            ["Brackets not delivered", "Wrong panel size delivered", "Membrane short-shipped"],
            18,
        ),
        (
            "Information / design",
            ["RFI 108 unanswered", "Drawing revision late", "Submittal not approved"],
            15,
        ),
        ("Labour / crew", ["Crew short - two operatives off", "Gang moved to another site"], 12),
        (
            "External / permits",
            ["High wind - crane stood down", "Heavy rain - roof works stopped"],
            9,
        ),
        ("Equipment", ["Hoist breakdown", "MEWP not available"], 6),
        ("Planning / commitment", ["Over-committed", "Task sequence changed on the day"], 10),
    ]
    weights = [r[2] for r in reasons]
    fillers = [
        ("Housekeeping and waste removal", "GC"),
        ("Edge protection checks", "Scaffolding"),
        ("Set out next zone", "GC"),
        ("Survey and as-built records", "GC"),
        ("Material call-off for next week", "MEP"),
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["week", "activity_id", "task", "trade", "planned", "completed", "reason"])
        for i, target in enumerate(targets):
            week = DATA_DATE - timedelta(weeks=8 - i)
            week_end = week + timedelta(days=5)
            active = [
                code
                for code, (s, f) in as_built.items()
                if meta[code]["dur"] > 0
                and meta[code]["kind"] == ActivityType.TASK
                and s < week_end
                and f >= week
                and code != "L9000"
            ]
            rows = [(code, meta[code]["name"], meta[code]["trade"] or "GC") for code in active]
            while len(rows) < 16:
                name, trade = fillers[len(rows) % len(fillers)]
                rows.append(("", f"{name} (week {i + 1})", trade))
            kept = set(rng.sample(range(len(rows)), round(target * len(rows))))
            for n, (code, name, trade) in enumerate(rows):
                done = n in kept
                reason = ""
                if not done:
                    category, texts, _ = rng.choices(reasons, weights=weights)[0]
                    reason = f"{category}: {rng.choice(texts)}"
                w.writerow(
                    [
                        week.strftime("%Y-%m-%d"),
                        code,
                        name,
                        trade,
                        "yes",
                        "yes" if done else "no",
                        reason,
                    ]
                )


def write_constraints(path: Path) -> None:
    import csv

    rows = [
        (
            "C001",
            fo("L1-A", "20"),
            "Partition layout drawings rev C for level 1",
            "Information / design",
            "Architect",
            "2026-02-02",
            "2026-02-27",
            "open",
            "",
        ),
        (
            "C002",
            fo("L2-A", "10"),
            "MEP first fix materials for level 2 on site",
            "Materials",
            "MEP subcontractor",
            "2026-02-09",
            "2026-03-13",
            "open",
            "",
        ),
        (
            "C003",
            "E5035",
            "Batch 2 panel delivery slot confirmed",
            "Materials",
            "Facade subcontractor",
            "2026-02-02",
            "2026-04-03",
            "open",
            "",
        ),
        (
            "C004",
            "K7010",
            "Lift shaft verticality survey",
            "Prerequisite work",
            "Lift contractor",
            "2026-01-26",
            "2026-02-20",
            "open",
            "",
        ),
        (
            "C005",
            fo("L1-B", "10"),
            "Access to L1-B blocked by scaffold stair",
            "Space / access",
            "Site manager",
            "2026-02-09",
            "2026-02-27",
            "closed",
            "2026-02-25",
        ),
        (
            "C006",
            "H8000",
            "Highway permit for paving works",
            "External / permits",
            "Site manager",
            "2026-02-16",
            "2026-05-15",
            "open",
            "",
        ),
        (
            "C007",
            fo("L1-A", "30"),
            "Paint specification approval",
            "Information / design",
            "Client",
            "2026-02-16",
            "2026-03-09",
            "open",
            "",
        ),
        (
            "C008",
            "E5050",
            "Louvre RFI 112 answered",
            "Information / design",
            "Architect",
            "2026-01-12",
            "2026-02-06",
            "closed",
            "2026-02-13",
        ),
        (
            "C009",
            fo("L2-B", "20"),
            "Second drylining crew for the larger L2-B zone",
            "Labour / crew",
            "Drylining subcontractor",
            "2026-02-23",
            "2026-03-27",
            "open",
            "",
        ),
        (
            "C010",
            fo("L1-A", "10"),
            "Crane time for MEP plant lift",
            "Equipment",
            "Site manager",
            "2026-01-26",
            "2026-02-13",
            "closed",
            "2026-02-12",
        ),
        (
            "C011",
            "TC-01",
            "Tower crane dismantle date agreed",
            "Equipment",
            "Crane hire",
            "2026-02-02",
            "2026-03-20",
            "open",
            "",
        ),
        (
            "C012",
            "QA-L1-FS",
            "Fire stopping inspector booked",
            "External / permits",
            "QA manager",
            "2026-02-16",
            "2026-02-24",
            "open",
            "",
        ),
        (
            "C013",
            fo("L1-B", "20"),
            "Board delivery for level 1",
            "Materials",
            "Drylining subcontractor",
            "2026-02-09",
            "2026-03-04",
            "open",
            "",
        ),
        (
            "C014",
            "E5030",
            "Facade bracket redesign at grid C",
            "Information / design",
            "Facade designer",
            "2025-12-15",
            "2026-01-16",
            "closed",
            "2026-01-28",
        ),
        (
            "C015",
            "K7000",
            "Riser access through level 2 slab openings",
            "Space / access",
            "Site manager",
            "2026-01-12",
            "2026-01-30",
            "closed",
            "2026-01-29",
        ),
        (
            "C016",
            "E5020",
            "Roof membrane weather window",
            "External / permits",
            "Roofing subcontractor",
            "2026-01-19",
            "2026-02-27",
            "closed",
            "2026-02-20",
        ),
        (
            "C017",
            fo("L2-A", "20"),
            "Level 2 setting out complete",
            "Prerequisite work",
            "Site engineer",
            "2026-02-23",
            "2026-03-20",
            "open",
            "",
        ),
        (
            "C018",
            "K7020",
            "Commissioning management plan approved",
            "Information / design",
            "MEP consultant",
            "2026-02-16",
            "2026-06-30",
            "open",
            "",
        ),
        (
            "C019",
            fo("L1-A", "40"),
            "Ceiling grid colour sample sign-off",
            "Information / design",
            "Client",
            "2026-02-23",
            "2026-03-11",
            "open",
            "",
        ),
        (
            "C020",
            "E5000",
            "Scaffold design check",
            "Prerequisite work",
            "Temporary works coordinator",
            "2025-11-03",
            "2025-11-21",
            "closed",
            "2025-11-20",
        ),
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "id",
                "activity_id",
                "description",
                "category",
                "owner",
                "identified",
                "need_by",
                "status",
                "closed",
            ]
        )
        w.writerows(rows)


def main() -> None:
    baseline, as_built, progress, _ = simulate()
    sched, cpm = current_schedule(progress)
    write_xer(sched, cpm, baseline, HERE / "harbourside-health-centre.xer")
    write_mspdi(sched, cpm, baseline, HERE / "harbourside-health-centre.xml")
    write_csv(sched, baseline, HERE / "harbourside-health-centre.csv")
    write_weekly_plans(as_built, HERE / "weekly-work-plans.csv")
    write_constraints(HERE / "constraint-log.csv")
    done = sum(1 for a in sched.activities.values() if a.is_complete)
    started = sum(1 for a in sched.activities.values() if a.status == Status.IN_PROGRESS)
    print(
        f"{len(sched.activities)} activities ({done} complete, {started} in progress), {len(sched.relationships)} relationships"
    )
    print(
        f"Forecast finish offset {cpm.finish:.0f} working days from {DATA_DATE:%Y-%m-%d}: {CAL.datetime_at(DATA_DATE, cpm.finish, True):%Y-%m-%d}"
    )


if __name__ == "__main__":
    main()
