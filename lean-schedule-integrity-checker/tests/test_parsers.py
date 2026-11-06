from datetime import date, datetime

import pytest
from lean_sic.model import ActivityType, ConstraintType, RelType, Status
from lean_sic.parsers import ScheduleParseError, detect_format, load_schedule
from lean_sic.parsers.common import parse_datetime
from lean_sic.parsers.csv_schedule import parse_predecessors
from lean_sic.parsers.xer import parse_calendar_data

GOOD_FRIDAY = date(2026, 4, 3)
SERIAL = (GOOD_FRIDAY - date(1899, 12, 30)).days
WORK = "(0||0(s|07:00|f|17:00)())"
CLNDR = (
    "(0||CalendarData()((0||DaysOfWeek()((0||1()())"
    + "".join(f"(0||{d}()({WORK}))" for d in range(2, 8))
    + f"))(0||VIEW(ShowTotal|Y)())(0||Exceptions()((0||0(d|{SERIAL})()))))"
)


def xer_bytes() -> bytes:
    def table(name, fields, rows):
        lines = [f"%T\t{name}", "%F\t" + "\t".join(fields)]
        lines += ["%R\t" + "\t".join(r) for r in rows]
        return lines

    lines = ["ERMHDR\t20.12\t2026-03-02\tProject\tadmin"]
    lines += table(
        "PROJECT",
        [
            "proj_id",
            "proj_short_name",
            "clndr_id",
            "last_recalc_date",
            "plan_start_date",
            "plan_end_date",
            "sum_base_proj_id",
        ],
        [["1", "DEMO", "10", "2026-03-02 08:00", "2026-01-05 08:00", "2026-06-30 17:00", ""]],
    )
    lines += table(
        "CALENDAR",
        ["clndr_id", "default_flag", "clndr_name", "day_hr_cnt", "week_hr_cnt", "clndr_data"],
        [["10", "Y", "Six day", "10", "60", CLNDR]],
    )
    lines += table(
        "PROJWBS",
        ["wbs_id", "proj_id", "proj_node_flag", "wbs_short_name", "wbs_name", "parent_wbs_id"],
        [
            ["50", "1", "Y", "DEMO", "Demo Tower", ""],
            ["51", "1", "N", "L1", "Level 1", "50"],
            ["52", "1", "N", "ZA", "Zone A", "51"],
        ],
    )
    fields = [
        "task_id",
        "proj_id",
        "wbs_id",
        "clndr_id",
        "task_type",
        "status_code",
        "task_code",
        "task_name",
        "target_drtn_hr_cnt",
        "remain_drtn_hr_cnt",
        "total_float_hr_cnt",
        "act_start_date",
        "act_end_date",
        "early_start_date",
        "early_end_date",
        "target_start_date",
        "target_end_date",
        "cstr_type",
        "cstr_date",
        "complete_pct_type",
        "phys_complete_pct",
        "rsrc_id",
    ]
    lines += table(
        "TASK",
        fields,
        [
            [
                "100",
                "1",
                "51",
                "10",
                "TT_Mile",
                "TK_Complete",
                "M0",
                "Start",
                "0",
                "0",
                "",
                "2026-01-05 07:00",
                "2026-01-05 07:00",
                "",
                "",
                "2026-01-05 07:00",
                "2026-01-05 07:00",
                "",
                "",
                "CP_Drtn",
                "100",
                "",
            ],
            [
                "101",
                "1",
                "52",
                "10",
                "TT_Task",
                "TK_Active",
                "A10",
                "Formwork – level 1",
                "100",
                "40",
                "20",
                "2026-02-23 07:00",
                "",
                "2026-03-02 07:00",
                "2026-03-05 17:00",
                "2026-02-16 07:00",
                "2026-02-26 17:00",
                "",
                "",
                "CP_Drtn",
                "0",
                "",
            ],
            [
                "102",
                "1",
                "52",
                "10",
                "TT_Task",
                "TK_NotStart",
                "A20",
                "Pour slab",
                "30",
                "30",
                "-10",
                "",
                "",
                "2026-03-09 07:00",
                "2026-03-11 17:00",
                "2026-03-02 07:00",
                "2026-03-04 17:00",
                "CS_MEOB",
                "2026-03-20 17:00",
                "CP_Drtn",
                "0",
                "5",
            ],
        ],
    )
    lines += table(
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
        [
            ["1", "102", "101", "1", "1", "PR_FS", "20"],
            ["2", "101", "100", "1", "1", "PR_SS", "0"],
            ["3", "102", "999", "1", "2", "PR_FS", "0"],
        ],
    )
    lines += table(
        "ACTVTYPE", ["actv_code_type_id", "actv_code_type"], [["1", "Trade"], ["2", "Zone"]]
    )
    lines += table(
        "ACTVCODE",
        ["actv_code_id", "actv_code_type_id", "short_name", "actv_code_name"],
        [["11", "1", "CONC", "Concrete"], ["21", "2", "L1-A", "Level 1 zone A"]],
    )
    lines += table(
        "TASKACTV",
        ["task_id", "actv_code_type_id", "actv_code_id", "proj_id"],
        [["101", "1", "11", "1"], ["101", "2", "21", "1"], ["102", "1", "11", "1"]],
    )
    lines += table("RSRC", ["rsrc_id", "rsrc_name"], [["5", "Concrete gang"]])
    lines += table(
        "TASKRSRC", ["taskrsrc_id", "task_id", "proj_id", "rsrc_id"], [["1", "101", "1", "5"]]
    )
    lines += table(
        "UDFTYPE", ["udf_type_id", "table_name", "udf_type_label"], [["7", "TASK", "Crew size"]]
    )
    lines += table(
        "UDFVALUE", ["udf_type_id", "fk_id", "proj_id", "udf_number"], [["7", "102", "1", "6"]]
    )
    lines.append("%E")
    return ("\r\n".join(lines) + "\r\n").encode("cp1252")


def by_code(schedule):
    return {a.code: a for a in schedule.activities.values()}


def test_xer_reads_project_calendar_tasks_codes_and_links():
    s = load_schedule(xer_bytes(), "demo.xer")
    assert (s.name, s.project_code, s.source_format) == ("Demo Tower", "DEMO", "xer")
    assert s.data_date == datetime(2026, 3, 2, 8)
    assert s.deadline == datetime(2026, 6, 30, 17)
    assert s.calendar.days_per_week == 6 and GOOD_FRIDAY in s.calendar.holidays
    acts = by_code(s)
    a10, a20 = acts["A10"], acts["A20"]
    assert a10.name == "Formwork – level 1"  # decoded from Windows-1252
    assert (a10.duration, a10.remaining, a10.total_float, a10.percent_complete) == (10, 4, 2, 60)
    assert a10.status == Status.IN_PROGRESS and a10.actual_start == datetime(2026, 2, 23, 7)
    assert a10.codes == {"Trade": "CONC", "Zone": "L1-A"}
    assert a10.resources == ["Concrete gang"]
    assert a10.wbs == "Level 1 > Zone A"
    assert a20.constraint == ConstraintType.FINISH_ON_OR_BEFORE and a20.total_float == -1
    assert a20.codes["UDF: Crew size"] == "6"
    assert acts["M0"].type == ActivityType.START_MILESTONE and acts["M0"].is_complete
    rels = {
        (s.activities[r.pred].code, s.activities[r.succ].code): (r.type, r.lag)
        for r in s.relationships
    }
    assert rels == {("A10", "A20"): (RelType.FS, 2.0), ("M0", "A10"): (RelType.SS, 0.0)}
    assert s.external_links == 1 and any("other projects" in w for w in s.warnings)
    assert "planned dates" in (s.baseline_source or "")


def test_calendar_data_parser():
    workdays, holidays = parse_calendar_data(CLNDR)
    assert workdays == frozenset(range(6))  # Monday to Saturday
    assert holidays == (GOOD_FRIDAY,)
    assert parse_calendar_data("") == (None, ())


MSPDI = """<?xml version="1.0" encoding="UTF-8"?>
<Project xmlns="http://schemas.microsoft.com/project">
<Title>Demo MSP</Title><StatusDate>2026-03-02T08:00:00</StatusDate><MinutesPerDay>480</MinutesPerDay><CalendarUID>1</CalendarUID>
<ExtendedAttributes>
<ExtendedAttribute><FieldID>188743731</FieldID><FieldName>Text1</FieldName><Alias>Trade</Alias></ExtendedAttribute>
<ExtendedAttribute><FieldID>188743734</FieldID><FieldName>Text2</FieldName><Alias>Activity ID</Alias></ExtendedAttribute>
</ExtendedAttributes>
<Calendars><Calendar><UID>1</UID><Name>Standard</Name><WeekDays>
<WeekDay><DayType>1</DayType><DayWorking>0</DayWorking></WeekDay><WeekDay><DayType>2</DayType><DayWorking>1</DayWorking></WeekDay>
<WeekDay><DayType>3</DayType><DayWorking>1</DayWorking></WeekDay><WeekDay><DayType>4</DayType><DayWorking>1</DayWorking></WeekDay>
<WeekDay><DayType>5</DayType><DayWorking>1</DayWorking></WeekDay><WeekDay><DayType>6</DayType><DayWorking>1</DayWorking></WeekDay>
<WeekDay><DayType>7</DayType><DayWorking>0</DayWorking></WeekDay></WeekDays>
<Exceptions><Exception><TimePeriod><FromDate>2026-04-03T00:00:00</FromDate><ToDate>2026-04-06T23:59:00</ToDate></TimePeriod><DayWorking>0</DayWorking></Exception></Exceptions>
</Calendar></Calendars>
<Tasks>
<Task><UID>0</UID><ID>0</ID><Name>Demo</Name><Summary>1</Summary></Task>
<Task><UID>1</UID><ID>1</ID><Name>Phase 1</Name><Summary>1</Summary><OutlineNumber>1</OutlineNumber></Task>
<Task><UID>2</UID><ID>2</ID><Name>Dig</Name><OutlineNumber>1.1</OutlineNumber><Duration>PT40H0M0S</Duration><RemainingDuration>PT16H0M0S</RemainingDuration>
<ActualStart>2026-02-25T08:00:00</ActualStart><PercentComplete>60</PercentComplete><TotalSlack>9600</TotalSlack>
<ExtendedAttribute><FieldID>188743731</FieldID><Value>Groundworks</Value></ExtendedAttribute>
<ExtendedAttribute><FieldID>188743734</FieldID><Value>G-100</Value></ExtendedAttribute>
<Baseline><Number>0</Number><Start>2026-02-23T08:00:00</Start><Finish>2026-02-27T17:00:00</Finish><Duration>PT40H0M0S</Duration></Baseline></Task>
<Task><UID>3</UID><ID>3</ID><Name>Pour</Name><OutlineNumber>1.2</OutlineNumber><Duration>PT24H0M0S</Duration>
<ConstraintType>4</ConstraintType><ConstraintDate>2026-03-09T08:00:00</ConstraintDate><Deadline>2026-03-20T17:00:00</Deadline>
<PredecessorLink><PredecessorUID>2</PredecessorUID><Type>1</Type><LinkLag>4800</LinkLag><LagFormat>7</LagFormat></PredecessorLink></Task>
<Task><UID>4</UID><ID>4</ID><Name>Done</Name><OutlineNumber>1.3</OutlineNumber><Milestone>1</Milestone><Duration>PT0H0M0S</Duration>
<PredecessorLink><PredecessorUID>3</PredecessorUID><Type>3</Type><LinkLag>0</LinkLag></PredecessorLink></Task>
</Tasks>
<Resources><Resource><UID>1</UID><Name>Digger crew</Name></Resource></Resources>
<Assignments><Assignment><UID>1</UID><TaskUID>2</TaskUID><ResourceUID>1</ResourceUID></Assignment></Assignments>
</Project>"""


def test_mspdi_reads_tasks_links_calendar_and_custom_fields():
    s = load_schedule(MSPDI.encode(), "demo.xml")
    assert (s.name, s.source_format, s.data_date) == ("Demo MSP", "mspdi", datetime(2026, 3, 2, 8))
    assert s.calendar.holidays == (date(2026, 4, 3), date(2026, 4, 6))
    acts = by_code(s)
    dig = acts["G-100"]  # the "Activity ID" custom field becomes the activity code
    assert (dig.duration, dig.remaining, dig.total_float, dig.percent_complete) == (5, 2, 2, 60)
    assert dig.status == Status.IN_PROGRESS and dig.codes == {"Trade": "Groundworks"}
    assert dig.resources == ["Digger crew"] and dig.wbs == "Phase 1"
    assert dig.baseline_finish == datetime(2026, 2, 27, 17)
    pour = acts["3"]
    assert pour.constraint == ConstraintType.START_ON_OR_AFTER and pour.deadline == datetime(
        2026, 3, 20, 17
    )
    assert acts["4"].type == ActivityType.FINISH_MILESTONE
    assert acts["1"].type == ActivityType.SUMMARY and "0" not in acts
    rels = {
        (s.activities[r.pred].code, s.activities[r.succ].code): (r.type, r.lag)
        for r in s.relationships
    }
    assert rels == {("G-100", "3"): (RelType.FS, 1.0), ("3", "4"): (RelType.SS, 0.0)}


def test_mspdi_rejects_entity_declarations():
    evil = b'<?xml version="1.0"?><!DOCTYPE p [<!ENTITY x "boom">]><Project xmlns="http://schemas.microsoft.com/project"/>'
    with pytest.raises(ScheduleParseError, match="DOCTYPE"):
        load_schedule(evil, "evil.xml")


CSV = """# project: CSV demo
# data_date: 2026-03-02
# holidays: 2026-04-03
id,name,duration,predecessors,trade,zone,actual_start,percent_complete,constraint,constraint_date
L1-010,Set out,2,,GC,L1,2026-02-26,50,,
L1-020,Frame walls,5,L1-010,Drylining,L1,,,,
L1-030,Board walls,4,"L1-020SS+2; L1-010",Drylining,L1,,,SNET,2026-03-09
M-100,Level 1 done,0,L1-030FF-1d,,,,,,
"""


def test_csv_reads_meta_predecessors_status_and_codes():
    s = load_schedule(CSV.encode(), "plan.csv")
    assert (s.name, s.data_date) == ("CSV demo", datetime(2026, 3, 2))
    assert s.calendar.holidays == (date(2026, 4, 3),)
    acts = s.activities
    assert acts["L1-010"].status == Status.IN_PROGRESS and acts["L1-010"].remaining == 1
    assert acts["L1-030"].constraint == ConstraintType.START_ON_OR_AFTER
    assert acts["M-100"].type == ActivityType.FINISH_MILESTONE
    assert acts["L1-020"].codes == {"trade": "Drylining", "zone": "L1"}
    rels = {(r.pred, r.succ): (r.type, r.lag) for r in s.relationships}
    assert rels == {
        ("L1-010", "L1-020"): (RelType.FS, 0.0),
        ("L1-020", "L1-030"): (RelType.SS, 2.0),
        ("L1-010", "L1-030"): (RelType.FS, 0.0),
        ("L1-030", "M-100"): (RelType.FF, -1.0),
    }


def test_predecessor_strings_prefer_known_ids():
    known = {"A10", "A-20", "L1-020"}
    assert parse_predecessors("A10SS+2; A-20FF-1d, L1-020", known) == [
        ("A10", RelType.SS, 2.0),
        ("A-20", RelType.FF, -1.0),
        ("L1-020", RelType.FS, 0.0),
    ]
    assert parse_predecessors("A10 FS +3 days", known) == [("A10", RelType.FS, 3.0)]


@pytest.mark.parametrize(
    "text,dayfirst,expected",
    [
        ("2026-03-02 08:00", False, datetime(2026, 3, 2, 8)),
        ("02-Mar-26", False, datetime(2026, 3, 2)),
        ("02-Mar-26 A", False, datetime(2026, 3, 2)),
        ("02/03/2026", False, datetime(2026, 2, 3)),
        ("02/03/2026", True, datetime(2026, 3, 2)),
        ("13/03/2026", False, datetime(2026, 3, 13)),
        ("not a date", False, None),
    ],
)
def test_parse_datetime(text, dayfirst, expected):
    assert parse_datetime(text, dayfirst=dayfirst) == expected


def test_detect_format():
    assert detect_format(b"ERMHDR\t20.12", "export.txt") == "xer"
    assert detect_format(b"<?xml version='1.0'?><Project/>", "plan.dat") == "mspdi"
    assert detect_format(b"id,name\n1,a", "plan.csv") == "csv"
    for name in ("plan.mpp", "plan.pp"):
        with pytest.raises(ScheduleParseError):
            detect_format(b"binary", name)
