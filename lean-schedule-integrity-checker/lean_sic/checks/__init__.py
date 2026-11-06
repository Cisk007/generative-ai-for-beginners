"""Schedule integrity checks: DCMA 14-Point plus extended checks."""

from __future__ import annotations

from ..context import Context
from . import dcma, extended
from .base import CheckResult, group_score

__all__ = ["CheckResult", "group_score", "run_integrity"]


def run_integrity(ctx: Context) -> list[CheckResult]:
    return dcma.run(ctx) + extended.run(ctx)
