from datetime import date, datetime

import pytest
from lean_sic.calendar import WorkCalendar

MON = date(2026, 3, 2)


def test_count_skips_weekends_and_holidays():
    cal = WorkCalendar()
    assert cal.count(MON, date(2026, 3, 9)) == 5
    assert cal.count(date(2026, 3, 9), MON) == -5
    with_holiday = WorkCalendar(holidays=(date(2026, 3, 4), date(2026, 3, 7)))  # Saturday ignored
    assert with_holiday.holidays == (date(2026, 3, 4),)
    assert with_holiday.count(MON, date(2026, 3, 9)) == 4


@pytest.mark.parametrize("days", [5, 6, 7])
def test_nth_workday_round_trips_count(days):
    cal = WorkCalendar.from_days_per_week(days, holidays=(date(2026, 4, 3), date(2026, 12, 25)))
    for n in range(-40, 420, 7):
        assert cal.count(MON, cal.nth_workday(MON, n)) == n


def test_nth_workday_starts_on_next_working_day():
    cal = WorkCalendar()
    saturday = date(2026, 3, 7)
    assert cal.nth_workday(saturday, 0) == date(2026, 3, 9)
    assert cal.nth_workday(saturday, -1) == date(2026, 3, 6)


def test_offsets_treat_afternoon_as_end_of_day():
    cal = WorkCalendar()
    dd = datetime(2026, 3, 2, 8)
    assert cal.offset(dd, datetime(2026, 3, 2, 8)) == 0
    assert cal.offset(dd, datetime(2026, 3, 2, 17)) == 1
    assert cal.offset(dd, datetime(2026, 2, 27, 17)) == 0  # finished last Friday evening
    assert cal.datetime_at(dd, 9, finish=True) == datetime(2026, 3, 12, 17)
    assert cal.datetime_at(dd, 9) == datetime(2026, 3, 13, 8)


def test_six_and_seven_day_weeks():
    assert WorkCalendar.from_days_per_week(6).count(MON, date(2026, 3, 9)) == 6
    assert WorkCalendar.from_days_per_week(7).count(MON, date(2026, 3, 9)) == 7
    assert "Sat" in WorkCalendar.from_days_per_week(6).describe()
