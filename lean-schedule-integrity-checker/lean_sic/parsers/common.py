"""Small helpers shared by the schedule readers."""

from __future__ import annotations

import re
from datetime import datetime


class ScheduleParseError(ValueError):
    """Raised when an uploaded file cannot be read as a schedule."""


def decode_bytes(data: bytes) -> str:
    """Decode text exported by Windows tools (P6 writes Windows-1252)."""
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def parse_float(value: str | float | int | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


_MONTHS = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"],
        start=1,
    )
}
_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?")
_DMY_TEXT = re.compile(
    r"^(\d{1,2})[- ]([A-Za-z]{3})[A-Za-z]*[- ](\d{2,4})(?:\s+(\d{1,2}):(\d{2}))?"
)
_SLASH = re.compile(r"^(\d{1,2})[/.](\d{1,2})[/.](\d{2,4})(?:\s+(\d{1,2}):(\d{2}))?")


def parse_datetime(value: str | datetime | None, dayfirst: bool = False) -> datetime | None:
    """Parse the date formats planners usually export.

    Supports ISO (``2026-03-02 08:00``), P6 style (``02-Mar-26``) and slash
    dates (``02/03/2026``). Ambiguous slash dates use ``dayfirst``.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip().rstrip("A*").strip()  # P6 marks actuals with "A"
    if not text:
        return None
    try:
        if m := _ISO.match(text):
            y, mo, d, h, mi, s = m.groups()
            return datetime(int(y), int(mo), int(d), int(h or 0), int(mi or 0), int(s or 0))
        if m := _DMY_TEXT.match(text):
            d, mon, y, h, mi = m.groups()
            month = _MONTHS.get(mon.lower()[:3])
            if month:
                year = int(y) + (2000 if len(y) == 2 else 0)
                return datetime(year, month, int(d), int(h or 0), int(mi or 0))
        if m := _SLASH.match(text):
            a, b, y, h, mi = m.groups()
            first, second = int(a), int(b)
            year = int(y) + (2000 if len(y) == 2 else 0)
            if first > 12 or (dayfirst and second <= 12):
                day, month = first, second
            else:
                month, day = first, second
            return datetime(year, month, day, int(h or 0), int(mi or 0))
    except ValueError:
        return None
    return None


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip().lower() in {
        "1",
        "y",
        "yes",
        "true",
        "t",
        "x",
        "done",
        "complete",
        "completed",
    }
