"""Thresholds and options. Defaults follow the DCMA 14-Point Assessment
and common Last Planner System practice; every value can be overridden."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class Settings:
    # -- DCMA 14-point thresholds ---------------------------------------------
    high_float_days: float = 44.0  # DCMA 06: total float above ~2 months
    high_duration_days: float = 44.0  # DCMA 08: activities longer than ~2 months
    critical_test_delay: float = 600.0  # DCMA 12: delay used by the critical path test
    critical_test_samples: int = 5
    # -- extended integrity -----------------------------------------------------
    long_lag_days: float = 10.0  # lags this long usually hide real work (cure, approvals)
    merge_hotspot_preds: int = 6  # merge points where variability accumulates
    # -- Lean construction --------------------------------------------------------
    lookahead_weeks: int = 6  # Last Planner lookahead window
    make_ready_weeks: int = 2  # work starting this soon should be constraint-free
    lean_max_task_days: float = 10.0  # lookahead tasks should fit in a weekly work plan
    stalled_min_days: float = 10.0  # in-progress work this old is checked for stalling
    trade_gap_days: float = 5.0  # idle gap that breaks a trade's continuous flow
    ppc_target: float = 80.0  # Percent Plan Complete target
    trade_field: str | None = None  # e.g. "Trade", "resource" (auto-detected when empty)
    location_field: str | None = None  # e.g. "Zone", "wbs", "wbs:2" (auto when empty)
    # -- output -------------------------------------------------------------------
    item_limit: int = 500  # flagged rows kept per check (all counts stay exact)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> Settings:
        settings = cls()
        for key, value in (data or {}).items():
            if hasattr(settings, key) and value not in (None, ""):
                current = getattr(settings, key)
                if isinstance(current, bool):
                    value = str(value).lower() in {"1", "true", "yes", "on"}
                elif isinstance(current, int) and not isinstance(current, bool):
                    value = int(float(value))
                elif isinstance(current, float):
                    value = float(value)
                setattr(settings, key, value)
        return settings
