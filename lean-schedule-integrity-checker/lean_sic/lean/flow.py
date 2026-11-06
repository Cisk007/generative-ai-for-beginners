"""Flow analysis: how trades move through locations.

Lean and location-based planning aim for *continuous flow*: each trade moves
from zone to zone without waiting, one trade per zone at a time, all at a
common rhythm (the *takt time*). This module measures, from the schedule:

* trade continuity - idle gaps between a trade's work periods,
* trade stacking - zones with several trades working at once,
* takt balance - how evenly each trade's work is spread across zones,
* a suggested takt plan ("train" of trade wagons) and flowline data.
"""

from __future__ import annotations

import math
import re
import statistics
from collections import Counter, defaultdict
from datetime import date, time

from ..context import Context
from ..cpm import EPS
from ..model import Activity

MAX_SPAN = 260  # ignore occupancy beyond ~1 year for a single activity


def _natural_key(text: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", text)]


def day_span(ctx: Context, act: Activity, remaining_only: bool) -> tuple[int, int] | None:
    """Working-day index range (inclusive) occupied by an activity."""
    start, finish = act.start, act.finish
    if start is None or finish is None:
        return None
    if remaining_only:
        if act.is_complete:
            return None
        if act.is_started:
            start = max(start, ctx.data_date)
    first = ctx.day_index(start)
    last = ctx.day_index(finish)
    if finish.time() < time(12):  # finished at the start of that day
        last -= 1
    return first, max(first, last)


def _day_to_date(ctx: Context, index: int) -> date:
    return ctx.schedule.calendar.nth_workday(ctx.data_date.date(), index)


def _iso(ctx: Context, index: int) -> str:
    return _day_to_date(ctx, index).isoformat()


def trade_continuity(ctx: Context, tasks: list[Activity]) -> dict:
    spans: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for a in tasks:
        if a.trade:
            span = day_span(ctx, a, remaining_only=True)
            if span:
                spans[a.trade].append(span)
    rows, total_gaps, long_gaps = [], 0, 0
    for trade, items in spans.items():
        items.sort()
        periods: list[list[int]] = []
        for first, last in items:
            if periods and first <= periods[-1][1] + 1:
                periods[-1][1] = max(periods[-1][1], last)
            else:
                periods.append([first, last])
        gaps = [periods[i + 1][0] - periods[i][1] - 1 for i in range(len(periods) - 1)]
        long = [g for g in gaps if g > ctx.settings.trade_gap_days]
        busy = sum(last - first + 1 for first, last in periods)
        span = periods[-1][1] - periods[0][0] + 1
        total_gaps += len(gaps)
        long_gaps += len(long)
        rows.append(
            {
                "trade": trade,
                "activities": len(items),
                "periods": len(periods),
                "gaps": len(gaps),
                "long_gaps": len(long),
                "longest_gap": max(gaps, default=0),
                "idle_days": sum(gaps),
                "density": round(100.0 * busy / span, 1) if span else 100.0,
                "first_start": _iso(ctx, periods[0][0]),
                "last_finish": _iso(ctx, periods[-1][1]),
            }
        )
    rows.sort(key=lambda r: (-r["long_gaps"], r["density"]))
    return {
        "rows": rows,
        "total_gaps": total_gaps,
        "long_gaps": long_gaps,
        "pct_long": round(100.0 * long_gaps / total_gaps, 1) if total_gaps else 0.0,
    }


def trade_stacking(ctx: Context, tasks: list[Activity]) -> dict:
    occupancy: dict[tuple[str, int], set[str]] = defaultdict(set)
    for a in tasks:
        if a.trade and a.location:
            span = day_span(ctx, a, remaining_only=True)
            if span:
                for day in range(span[0], min(span[1], span[0] + MAX_SPAN) + 1):
                    occupancy[(a.location, day)].add(a.trade)
    stacked = {k: v for k, v in occupancy.items() if len(v) > 1}
    by_zone: dict[str, list[int]] = defaultdict(list)
    for zone, day in stacked:
        by_zone[zone].append(day)
    hotspots = []
    for zone, days in by_zone.items():
        days.sort()
        run = [days[0]]
        for day in days[1:] + [None]:  # type: ignore[list-item]
            if day is not None and day == run[-1] + 1:
                run.append(day)
                continue
            trades = sorted(set().union(*(stacked[(zone, d)] for d in run)))
            hotspots.append(
                {
                    "zone": zone,
                    "start": _iso(ctx, run[0]),
                    "finish": _iso(ctx, run[-1]),
                    "days": len(run),
                    "max_trades": max(len(stacked[(zone, d)]) for d in run),
                    "trades": trades,
                }
            )
            if day is not None:
                run = [day]
    hotspots.sort(key=lambda h: (-h["days"] * h["max_trades"], h["start"]))
    return {
        "occupied_zone_days": len(occupancy),
        "stacked_zone_days": len(stacked),
        "pct": round(100.0 * len(stacked) / len(occupancy), 1) if occupancy else 0.0,
        "max_trades": max((len(v) for v in occupancy.values()), default=0),
        "hotspots": hotspots,
    }


def takt_analysis(ctx: Context, tasks: list[Activity]) -> dict:
    cells: dict[tuple[str, str], dict] = {}
    for a in tasks:
        if not (a.trade and a.location):
            continue
        cell = cells.setdefault(
            (a.trade, a.location), {"work": 0.0, "start": None, "finish": None, "count": 0}
        )
        cell["work"] += a.duration
        cell["count"] += 1
        if a.start and (cell["start"] is None or a.start < cell["start"]):
            cell["start"] = a.start
        if a.finish and (cell["finish"] is None or a.finish > cell["finish"]):
            cell["finish"] = a.finish
    trades_per_zone = Counter(zone for (_, zone) in cells)
    zones = [z for z, n in trades_per_zone.items() if n >= 3]
    if len(zones) < 2:
        return {
            "available": False,
            "reason": "Takt analysis needs at least two zones that each have work from three or more trades.",
        }
    # Keep the trades that repeat across most zones, then the zones that hold
    # most of those trades; two rounds settle on the repetitive "takt area".
    trades: list[str] = []
    for _ in range(3):
        needed = max(2, math.ceil(0.5 * len(zones)))
        zone_count = Counter(t for (t, z) in cells if z in zones)
        trades = [t for t, n in zone_count.items() if n >= needed]
        if len(trades) < 2:
            return {
                "available": False,
                "reason": "Fewer than two trades repeat across the takt zones.",
            }
        min_trades = max(2, math.ceil(0.5 * len(trades)))
        kept = [z for z in zones if sum(1 for t in trades if (t, z) in cells) >= min_trades]
        if len(kept) < 2:
            return {
                "available": False,
                "reason": "Fewer than two zones share the repeating trades.",
            }
        if kept == zones:
            break
        zones = kept

    # Order zones by where they sit in each trade's own sequence, and trades by
    # their position within each zone. Median ranks shrug off one late trade.
    def rank_key(ranks: list[int], name: str):
        if not ranks:
            return (math.inf, math.inf, _natural_key(name))
        return (statistics.median(ranks), statistics.fmean(ranks), _natural_key(name))

    zone_ranks: dict[str, list[int]] = defaultdict(list)
    for t in trades:
        seq = sorted(
            (z for z in zones if (t, z) in cells and cells[(t, z)]["start"]),
            key=lambda z, t=t: cells[(t, z)]["start"],
        )
        for rank, z in enumerate(seq):
            zone_ranks[z].append(rank)
    zones.sort(key=lambda z: rank_key(zone_ranks[z], z))
    trade_ranks: dict[str, list[int]] = defaultdict(list)
    for z in zones:
        seq = sorted(
            (t for t in trades if (t, z) in cells and cells[(t, z)]["start"]),
            key=lambda t, z=z: cells[(t, z)]["start"],
        )
        for rank, t in enumerate(seq):
            trade_ranks[t].append(rank)
    trades.sort(key=lambda t: rank_key(trade_ranks[t], t))
    stats = []
    for t in trades:
        work = [cells[(t, z)]["work"] for z in zones if (t, z) in cells]
        mean = statistics.fmean(work)
        cv = statistics.pstdev(work) / mean if len(work) > 1 and mean > EPS else 0.0
        stats.append(
            {
                "trade": t,
                "zones": len(work),
                "min": round(min(work), 1),
                "median": round(statistics.median(work), 1),
                "max": round(max(work), 1),
                "mean": round(mean, 1),
                "cv": round(cv, 2),
                "by_zone": {z: round(cells[(t, z)]["work"], 1) for z in zones if (t, z) in cells},
            }
        )
    takt_fit = max(1, math.ceil(max(s["max"] for s in stats) - EPS))
    takt_bal = max(1, math.ceil(statistics.median(s["median"] for s in stats) - EPS))
    overloaded = sorted(
        (
            {
                "trade": t,
                "zone": z,
                "work": round(cells[(t, z)]["work"], 1),
                "factor": round(cells[(t, z)]["work"] / takt_bal, 2),
            }
            for t in trades
            for z in zones
            if (t, z) in cells and cells[(t, z)]["work"] > takt_bal + EPS
        ),
        key=lambda o: -o["factor"],
    )
    starts = [
        c["start"] for (t, z), c in cells.items() if t in trades and z in zones and c["start"]
    ]
    finishes = [
        c["finish"] for (t, z), c in cells.items() if t in trades and z in zones and c["finish"]
    ]
    current = (
        ctx.schedule.calendar.count(min(starts).date(), max(finishes).date()) + 1
        if starts and finishes
        else None
    )
    periods = len(trades) + len(zones) - 1
    grid = [
        [(p - zi) if 0 <= p - zi < len(trades) else None for p in range(periods)]
        for zi in range(len(zones))
    ]
    return {
        "available": True,
        "zones": zones,
        "trades": stats,
        "avg_cv": round(statistics.fmean(s["cv"] for s in stats), 2),
        "takt_fit": takt_fit,
        "takt_balanced": takt_bal,
        "train_fit": periods * takt_fit,
        "train_balanced": periods * takt_bal,
        "current_span": current,
        "overloaded": overloaded,
        "grid": grid,
        "periods": periods,
    }


def flowline(ctx: Context, tasks: list[Activity], takt: dict) -> dict:
    if takt.get("available"):
        zones = list(takt["zones"])
        trades = [s["trade"] for s in takt["trades"]]
    else:
        zone_trades: dict[str, set[str]] = defaultdict(set)
        for a in tasks:
            if a.trade and a.location:
                zone_trades[a.location].add(a.trade)
        zones = sorted(zone_trades, key=_natural_key)[:30]
        counts = Counter(t for z in zones for t in zone_trades[z])
        trades = [t for t, n in counts.most_common(12) if n >= 2]
    segments = []
    for a in tasks:
        if a.trade in trades and a.location in zones and a.start and a.finish:
            segments.append(
                {
                    "trade": a.trade,
                    "zone": a.location,
                    "start": a.start.isoformat(),
                    "finish": a.finish.isoformat(),
                    "complete": a.is_complete,
                    "id": a.code,
                }
            )
    return {
        "zones": zones,
        "trades": trades,
        "segments": segments,
        "data_date": ctx.data_date.isoformat(),
    }


def analyze_flow(ctx: Context) -> dict:
    tasks = [a for a in ctx.network if a.is_task and a.duration > EPS]
    has_trade = any(a.trade for a in tasks)
    has_location = any(a.location for a in tasks)
    result: dict = {"has_trade": has_trade, "has_location": has_location}
    result["continuity"] = trade_continuity(ctx, tasks) if has_trade else None
    result["stacking"] = trade_stacking(ctx, tasks) if has_trade and has_location else None
    takt = (
        takt_analysis(ctx, tasks)
        if has_trade and has_location
        else {
            "available": False,
            "reason": "Map a trade field and a location field to enable takt analysis.",
        }
    )
    result["takt"] = takt
    result["flowline"] = flowline(ctx, tasks, takt) if has_trade and has_location else None
    return result
