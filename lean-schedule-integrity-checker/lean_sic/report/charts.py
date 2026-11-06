"""Small, dependency-free chart builders (inline SVG and HTML bars).

Conventions: thin marks (columns <= 24px with a 4px rounded data-end, 2px
lines, 8px dots with a surface ring), hairline solid gridlines, text in text
colours (never the series colour), a tooltip on every mark via ``data-tip``,
and a table view next to every chart.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from html import escape as e

SERIES = [f"var(--s{i})" for i in range(1, 9)]


def nice_ticks(maximum: float, count: int = 4) -> list[float]:
    if maximum <= 0:
        return [0, 1]
    raw = maximum / count
    magnitude = 10 ** math.floor(math.log10(raw))
    step = next(m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw)
    top = step * math.ceil(maximum / step)
    ticks, value = [], 0.0
    while value <= top + 1e-9:
        ticks.append(round(value, 6))
        value += step
    return ticks


def _fmt_tick(v: float) -> str:
    return f"{v:,.0f}" if abs(v - round(v)) < 1e-9 else f"{v:,.1f}"


def column_path(x: float, y: float, w: float, base: float, r: float = 4.0) -> str:
    """A column with a rounded top (data end) and a square baseline."""
    h = base - y
    if h <= 0:
        return ""
    r = min(r, h, w / 2)
    return (
        f"M{x:.1f},{base:.1f}V{y + r:.1f}Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f}"
        f"H{x + w - r:.1f}Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f}V{base:.1f}Z"
    )


def float_histogram(bins: list[dict]) -> str:
    """Total float distribution; problem bins use status colours (with labels)."""
    W, H, left, right, top, bottom = 560, 242, 40, 12, 34, 44
    pw, ph = W - left - right, H - top - bottom
    total = sum(b["count"] for b in bins) or 1
    ticks = nice_ticks(max((b["count"] for b in bins), default=1))
    ymax = ticks[-1] or 1
    band = pw / max(1, len(bins))
    width = min(24.0, band * 0.6)
    base = top + ph
    parts = [
        f'<svg class="chart-svg" viewBox="0 0 {W} {H}" width="100%" style="max-width:{W}px" role="img" aria-label="Total float distribution of incomplete activities">'
    ]
    for t in ticks:
        y = base - t / ymax * ph
        cls = "axis" if t == 0 else "grid"
        parts.append(
            f'<line class="{cls}" x1="{left}" x2="{W - right}" y1="{y:.1f}" y2="{y:.1f}"/>'
        )
        parts.append(
            f'<text class="tick" x="{left - 6}" y="{y + 4:.1f}" text-anchor="end">{_fmt_tick(t)}</text>'
        )
    for i, b in enumerate(bins):
        cx = left + band * i + band / 2
        y = base - b["count"] / ymax * ph
        color = (
            "var(--bad)"
            if b["label"] == "Negative"
            else "var(--warn)" if b["label"].startswith(">") else SERIES[0]
        )
        tip = f'{b["label"]} float\n{b["count"]} activities ({100 * b["count"] / total:.0f}%)'
        parts.append(f'<g class="mark" tabindex="0" data-tip="{e(tip)}">')
        parts.append(
            f'<rect class="hit" x="{left + band * i:.1f}" y="{top}" width="{band:.1f}" height="{ph}"/>'
        )
        if b["count"]:
            parts.append(
                f'<path d="{column_path(cx - width / 2, y, width, base)}" fill="{color}"/>'
            )
        parts.append(
            f'<text class="value" x="{cx:.1f}" y="{y - 6:.1f}" text-anchor="middle">{b["count"]}</text>'
        )
        parts.append(
            f'<text class="tick" x="{cx:.1f}" y="{base + 18:.1f}" text-anchor="middle">{e(b["label"])}</text>'
        )
        parts.append("</g>")
    parts.append(f'<text class="tick" x="{left}" y="12">Activities</text>')
    parts.append("</svg>")
    return "".join(parts)


def _short_week(iso: str) -> str:
    d = date.fromisoformat(iso)
    return d.strftime("%d %b")


def ppc_chart(weeks: list[dict], target: float) -> str:
    """Weekly PPC (dots + line) and the 4-week rolling PPC against the target."""
    W, H, left, right, top, bottom = 660, 250, 40, 58, 18, 38
    pw, ph = W - left - right, H - top - bottom
    n = len(weeks)
    base = top + ph

    def x(i: int) -> float:
        return left + (pw * i / (n - 1) if n > 1 else pw / 2)

    def y(v: float) -> float:
        return base - v / 100.0 * ph

    parts = [
        f'<svg class="chart-svg" viewBox="0 0 {W} {H}" width="100%" style="max-width:{W}px" role="img" aria-label="Percent Plan Complete by week">'
    ]
    for t in (0, 25, 50, 75, 100):
        parts.append(
            f'<line class="{"axis" if t == 0 else "grid"}" x1="{left}" x2="{W - right}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>'
        )
        parts.append(
            f'<text class="tick" x="{left - 6}" y="{y(t) + 4:.1f}" text-anchor="end">{t}%</text>'
        )
    parts.append(
        f'<line class="target" x1="{left}" x2="{W - right}" y1="{y(target):.1f}" y2="{y(target):.1f}"/>'
    )
    parts.append(
        f'<text class="tick" x="{left + 6}" y="{y(target) - 5:.1f}">Target {target:g}%</text>'
    )
    step = max(1, math.ceil(n / 8))
    for i, w in enumerate(weeks):
        if i % step == 0 or i == n - 1:
            parts.append(
                f'<text class="tick" x="{x(i):.1f}" y="{base + 18:.1f}" text-anchor="middle">{e(_short_week(w["week"]))}</text>'
            )
    for key, color, dots in (("rolling4", SERIES[1], False), ("ppc", SERIES[0], True)):
        pts = " ".join(f"{x(i):.1f},{y(w[key]):.1f}" for i, w in enumerate(weeks))
        parts.append(f'<polyline class="series" points="{pts}" stroke="{color}"/>')
        if dots:
            parts += [
                f'<circle class="dot" cx="{x(i):.1f}" cy="{y(w[key]):.1f}" r="4" fill="{color}"/>'
                for i, w in enumerate(weeks)
            ]
    if weeks:
        last = weeks[-1]
        ly1, ly2 = y(last["ppc"]), y(last["rolling4"])
        parts.append(
            f'<text class="value" x="{x(n - 1) + 8:.1f}" y="{ly1 + 4:.1f}">{last["ppc"]:g}%</text>'
        )
        if abs(ly1 - ly2) >= 13:
            parts.append(
                f'<text class="tick" x="{x(n - 1) + 8:.1f}" y="{ly2 + 4:.1f}">{last["rolling4"]:g}%</text>'
            )
    band = pw / max(1, n - 1) if n > 1 else pw
    for i, w in enumerate(weeks):
        tip = f'Week of {w["week"]}\nPPC {w["ppc"]:g}% ({w["completed"]} of {w["planned"]} promises kept)\n4-week rolling {w["rolling4"]:g}%'
        x0 = max(left, x(i) - band / 2)
        x1 = min(W - right, x(i) + band / 2)
        parts.append(
            f'<g class="mark" tabindex="0" data-tip="{e(tip)}"><rect class="hit" x="{x0:.1f}" y="{top}" width="{x1 - x0:.1f}" height="{ph}"/>'
            f'<line class="xhair" x1="{x(i):.1f}" x2="{x(i):.1f}" y1="{top}" y2="{base}"/></g>'
        )
    parts.append("</svg>")
    return "".join(parts)


def hbar_rows(rows: list[tuple[str, float, str]], color: str = SERIES[0], css: str = "") -> str:
    """Ranked horizontal bars in HTML: (label, value, value text)."""
    peak = max((v for _, v, _ in rows), default=0) or 1
    out = [f'<ol class="hbars {css}">']
    for label, value, text in rows:
        pct = 100.0 * value / peak
        out.append(
            f'<li><span class="hbar-label">{e(label)}</span><span class="hbar-track">'
            f'<span class="hbar-fill" style="width:{pct:.1f}%;background:{color}"></span></span>'
            f'<span class="hbar-value">{e(text)}</span></li>'
        )
    out.append("</ol>")
    return "".join(out)


def segmented_bar(parts: list[tuple[str, float, str]], label: str) -> str:
    """Thin segmented bar (no text): (name, value, colour)."""
    total = sum(v for _, v, _ in parts) or 1
    out = [f'<div class="segbar" role="img" aria-label="{e(label)}">']
    for name, value, color in parts:
        if value <= 0:
            continue
        tip = f"{name}: {value:g} ({100 * value / total:.0f}%)"
        out.append(
            f'<span class="seg" tabindex="0" style="flex-grow:{value:g};background:{color}" data-tip="{e(tip)}"></span>'
        )
    out.append("</div>")
    return "".join(out)


def _month_ticks(start: datetime, end: datetime) -> list[datetime]:
    ticks = []
    current = datetime(start.year, start.month, 1)
    while current <= end:
        if current >= start:
            ticks.append(current)
        current = datetime(current.year + (current.month == 12), current.month % 12 + 1, 1)
    return ticks


def flowline_chart(flow: dict, colors: dict[str, str]) -> str:
    """Line-of-balance (flowline) chart: zones up the y axis, time across."""
    zones, trades, segments = flow["zones"], flow["trades"], flow["segments"]
    if not zones or not segments:
        return ""
    starts = [datetime.fromisoformat(s["start"]) for s in segments]
    finishes = [datetime.fromisoformat(s["finish"]) for s in segments]
    lo, hi = min(starts), max(finishes)
    span = max(1.0, (hi - lo).total_seconds())
    row = 30
    W, left, right, top, bottom = 920, 70, 24, 24, 34
    H = top + row * len(zones) + bottom
    pw = W - left - right

    def x(d: datetime) -> float:
        return left + (d - lo).total_seconds() / span * pw

    def y(zone: str) -> float:
        return top + (len(zones) - 1 - zones.index(zone)) * row + row / 2

    offsets = {
        t: (i - (len(trades) - 1) / 2) * min(3.2, 18 / max(1, len(trades)))
        for i, t in enumerate(trades)
    }
    parts = [
        f'<svg class="chart-svg flowline" viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="Flowline of trades through zones">'
    ]
    for z in zones:
        parts.append(
            f'<line class="grid" x1="{left}" x2="{W - right}" y1="{y(z) + row / 2:.1f}" y2="{y(z) + row / 2:.1f}"/>'
        )
        parts.append(
            f'<text class="tick" x="{left - 8}" y="{y(z) + 4:.1f}" text-anchor="end">{e(z)}</text>'
        )
    for t in _month_ticks(lo, hi):
        tx = x(t)
        parts.append(
            f'<line class="grid" x1="{tx:.1f}" x2="{tx:.1f}" y1="{top}" y2="{H - bottom}"/>'
        )
        label = (
            t.strftime("%b %Y")
            if t.month == 1 or t == _month_ticks(lo, hi)[0]
            else t.strftime("%b")
        )
        parts.append(f'<text class="tick" x="{tx + 3:.1f}" y="{H - bottom + 16}">{label}</text>')
    dd = datetime.fromisoformat(flow["data_date"])
    if lo <= dd <= hi:
        parts.append(
            f'<line class="datadate" x1="{x(dd):.1f}" x2="{x(dd):.1f}" y1="{top - 6}" y2="{H - bottom}"/>'
        )
        parts.append(f'<text class="tick" x="{x(dd) + 4:.1f}" y="{top - 10}">Data date</text>')
    by_trade: dict[str, list[dict]] = {}
    for s in segments:
        by_trade.setdefault(s["trade"], []).append(s)
    for trade in trades:
        segs = sorted(by_trade.get(trade, []), key=lambda s: (zones.index(s["zone"]), s["start"]))
        color = colors.get(trade, "var(--ink-3)")
        off = offsets[trade]
        # zone-to-zone connectors form the trade's flowline
        per_zone: dict[str, tuple[datetime, datetime]] = {}
        for s in segs:
            a, b = datetime.fromisoformat(s["start"]), datetime.fromisoformat(s["finish"])
            prev = per_zone.get(s["zone"])
            per_zone[s["zone"]] = (min(a, prev[0]), max(b, prev[1])) if prev else (a, b)
        ordered = [z for z in zones if z in per_zone]
        for z1, z2 in zip(ordered, ordered[1:], strict=False):
            parts.append(
                f'<line class="connector" x1="{x(per_zone[z1][1]):.1f}" y1="{y(z1) + off:.1f}" '
                f'x2="{x(per_zone[z2][0]):.1f}" y2="{y(z2) + off:.1f}" stroke="{color}"/>'
            )
        for s in segs:
            a, b = datetime.fromisoformat(s["start"]), datetime.fromisoformat(s["finish"])
            x1, x2 = x(a), max(x(b), x(a) + 3)
            tip = f'{trade} - {s["zone"]}\n{s["id"]}: {a:%d %b %Y} to {b:%d %b %Y}' + (
                " (complete)" if s["complete"] else ""
            )
            cls = "work done" if s["complete"] else "work"
            parts.append(
                f'<g class="mark" tabindex="0" data-tip="{e(tip)}"><rect class="hit" x="{x1 - 4:.1f}" y="{y(s["zone"]) + off - 9:.1f}" width="{x2 - x1 + 8:.1f}" height="18"/>'
                f'<line class="{cls}" x1="{x1:.1f}" x2="{x2:.1f}" y1="{y(s["zone"]) + off:.1f}" y2="{y(s["zone"]) + off:.1f}" stroke="{color}"/></g>'
            )
    parts.append("</svg>")
    return "".join(parts)


def legend(items: list[tuple[str, str]], kind: str = "line") -> str:
    keys = "".join(
        f'<li><span class="key key-{kind}" style="background:{c}"></span>{e(name)}</li>'
        for name, c in items
    )
    return f'<ul class="legend">{keys}</ul>'
