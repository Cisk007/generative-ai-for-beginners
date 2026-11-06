"""Schedule readers: Primavera P6 XER, Microsoft Project XML and CSV."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ..model import Schedule
from .common import ScheduleParseError
from .csv_schedule import parse_csv_schedule
from .mspdi import parse_mspdi
from .xer import parse_xer

__all__ = ["ScheduleParseError", "detect_format", "load_schedule"]

MAX_BYTES = 200 * 1024 * 1024  # refuse anything larger than 200 MB


def detect_format(data: bytes, filename: str = "") -> str:
    """Return ``"xer"``, ``"mspdi"`` or ``"csv"`` from the name and content."""
    name = filename.lower()
    head = data[:4096].lstrip(b"\xef\xbb\xbf \r\n\t")
    if name.endswith(".mpp"):
        raise ScheduleParseError(
            "Binary .mpp files cannot be read. In Microsoft Project use File > Save As > XML Format."
        )
    if name.endswith(".pp"):
        raise ScheduleParseError(
            "Asta Powerproject .pp files are binary. Export the programme to XER or Microsoft Project XML."
        )
    if name.endswith(".xer") or head.startswith(b"ERMHDR") or b"\n%T\t" in data[:65536]:
        return "xer"
    if name.endswith(".xml") or head.startswith(b"<?xml") or head.startswith(b"<Project"):
        return "mspdi"
    return "csv"


def load_schedule(
    source: str | Path | bytes,
    filename: str = "",
    project: str | None = None,
    data_date: datetime | None = None,
    dayfirst: bool = False,
) -> Schedule:
    """Read a schedule from a path or from raw bytes (e.g. an upload)."""
    if isinstance(source, (str, Path)):
        path = Path(source)
        filename = filename or path.name
        data = path.read_bytes()
    else:
        data = source
    if len(data) > MAX_BYTES:
        raise ScheduleParseError("The schedule file is larger than 200 MB.")
    if not data.strip():
        raise ScheduleParseError("The schedule file is empty.")
    kind = detect_format(data, filename)
    if kind == "xer":
        schedule = parse_xer(data, filename, project=project)
    elif kind == "mspdi":
        schedule = parse_mspdi(data, filename)
    else:
        schedule = parse_csv_schedule(data, filename, data_date=data_date, dayfirst=dayfirst)
    if data_date is not None and kind != "csv":
        schedule.warnings.append(
            f"Data date overridden to {data_date:%Y-%m-%d} (file says {schedule.data_date:%Y-%m-%d})."
        )
        schedule.data_date = data_date
    return schedule
