"""Render an analysis result as one self-contained HTML page.

All text that comes from the schedule is escaped with ``html.escape``; the
page has no external scripts. Web fonts load from Google Fonts with system
fallbacks (pass ``web_fonts=False`` for a fully offline page).
"""

from __future__ import annotations

import re
from html import escape as e
from pathlib import Path

from . import charts

HERE = Path(__file__).resolve().parent
FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600'
    '&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap">'
)
ICONS = {
    "pass": '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M2.5 6.2l2.3 2.3 4.7-4.9" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    "fail": '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M3 3l6 6M9 3l-6 6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
    "warn": '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M6 2.5v4.2M6 9.1v.1" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
    "info": '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M6 5.3v3.6M6 3.1v.1" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
    "na": '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M3 6h6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
}
LABELS = {"pass": "Pass", "fail": "Fail", "warn": "Watch", "info": "Info", "na": "N/A"}
CHEVRON = '<svg class="chev" viewBox="0 0 14 14" aria-hidden="true"><path d="M5 3l4 4-4 4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>'
ID_COLUMNS = {"Activity ID", "Predecessor", "Successor", "Constraint", "Loop"}
NUMERIC = re.compile(r"^-?[\d,]+(\.\d+)?%?$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def pill(status: str, label: str | None = None) -> str:
    return f'<span class="pill {status}">{ICONS[status]}{e(label or LABELS[status])}</span>'


def nice(text: str) -> str:
    """Display form of thresholds (ASCII in JSON, symbols on the page)."""
    return text.replace("<=", "≤").replace(">=", "≥")


def md_to_html(text: str) -> str:
    """Tiny, safe Markdown subset: headings, lists, bold, code, paragraphs."""
    out: list[str] = []
    list_tag: str | None = None
    para: list[str] = []

    def inline(s: str) -> str:
        s = e(s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        return s

    def flush_para() -> None:
        if para:
            out.append(f"<p>{inline(' '.join(para))}</p>")
            para.clear()

    def close_list() -> None:
        nonlocal list_tag
        if list_tag:
            out.append(f"</{list_tag}>")
            list_tag = None

    for raw in (text or "").splitlines():
        line = raw.strip()
        bullet = re.match(r"^[-*]\s+(.*)", line)
        number = re.match(r"^\d+[.)]\s+(.*)", line)
        heading = re.match(r"^#{1,6}\s+(.*)", line)
        if not line:
            flush_para()
            close_list()
        elif heading:
            flush_para()
            close_list()
            out.append(f"<h3>{inline(heading.group(1))}</h3>")
        elif bullet or number:
            flush_para()
            tag = "ul" if bullet else "ol"
            if list_tag != tag:
                close_list()
                out.append(f"<{tag}>")
                list_tag = tag
            out.append(f"<li>{inline((bullet or number).group(1))}</li>")  # type: ignore[union-attr]
        else:
            close_list()
            para.append(line)
    flush_para()
    close_list()
    return "".join(out)


def data_table(rows: list[dict], table_id: str, visible: int = 15, caption: str = "") -> str:
    if not rows:
        return ""
    cols = list(rows[0].keys())
    numeric = {
        c
        for c in cols
        if all(
            isinstance(r.get(c), (int, float)) or NUMERIC.match(str(r.get(c, "")).strip() or "x")
            for r in rows
            if r.get(c) not in (None, "")
        )
        and any(r.get(c) not in (None, "") for r in rows)
    }
    head = "".join(
        f'<th class="{"n" if c in numeric else ""}" scope="col">{e(c)}</th>' for c in cols
    )
    body = []
    for i, r in enumerate(rows):
        cells = []
        for c in cols:
            value = r.get(c, "")
            cls = (
                "id"
                if c in ID_COLUMNS
                else ("n" if c in numeric else ("date" if DATE.match(str(value)) else ""))
            )
            cells.append(f'<td class="{cls}">{e(str(value))}</td>')
        body.append(f'<tr class="{"more" if i >= visible else ""}">{"".join(cells)}</tr>')
    cap = f'<caption class="sr-only">{e(caption)}</caption>' if caption else ""
    html = f'<div class="table-wrap"><table id="{e(table_id)}">{cap}<thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'
    if len(rows) > visible:
        html += f'<button class="show-more" type="button" data-show-rows="{e(table_id)}">Show all {len(rows)} rows</button>'
    return html


def _grade_status(grade: str) -> str:
    return "pass" if grade in ("A", "B") else "warn" if grade == "C" else "fail"


def score_tile(title: str, score: dict, anchor: str) -> str:
    value = score.get("score")
    if value is None:
        return f'<div class="tile score"><span class="label">{e(title)}</span><span class="value">n/a</span><span class="context">Not enough data</span></div>'
    status = _grade_status(score["grade"])
    token = {"pass": "good", "warn": "warn", "fail": "bad"}[status]
    grade_label = f"Grade {score['grade']} \u00b7 {score['label']}"
    return (
        f'<a class="tile score" href="#{anchor}" style="text-decoration:none;color:inherit">'
        f'<span class="label">{e(title)}</span>'
        f'<span class="value">{value:.0f}<small> / 100</small></span>'
        f'<span class="meter" style="background:var(--{token}-soft)" role="img" aria-label="{value:.0f} out of 100">'
        f'<span style="width:{max(2.0, value):.1f}%;background:var(--{token})"></span></span>'
        f'<span class="grade">{pill(status, grade_label)}</span>'
        f'<span class="context">{score["passed"]} passed, {score["failed"]} failed of {score["scored"]} scored checks</span></a>'
    )


def tile(label: str, value: str, context: str = "", value_class: str = "") -> str:
    ctx = f'<span class="context">{context}</span>' if context else ""
    return f'<div class="tile"><span class="label">{e(label)}</span><span class="value {value_class}">{value}</span>{ctx}</div>'


def check_row(c: dict) -> str:
    status = c["status"]
    counts = ""
    if c["population"]:
        counts = f'{c["count"]:,} of {c["population"]:,} flagged'
    elif c["count"]:
        counts = f'{c["count"]:,} flagged'
    threshold = " \u00b7 ".join(
        x for x in (f"target {nice(c['threshold'])}" if c["threshold"] else "", counts) if x
    )
    wastes = "".join(f'<span class="chip">{e(w)}</span>' for w in c["wastes"])
    meta = (
        f'<span class="label">Severity</span><span class="chip">{e(c["severity"].title())}</span>'
    )
    if wastes:
        meta += f'<span class="label">Lean waste</span>{wastes}'
    note = f'<p class="small muted">{e(c["note"])}</p>' if c["note"] else ""
    items = ""
    if c["items"]:
        items = data_table(c["items"], f'items-{c["id"]}', caption=c["name"])
        if c["total_items"] > len(c["items"]):
            items += f'<p class="small muted">Showing the first {len(c["items"])} of {c["total_items"]} rows (raise item_limit for more).</p>'
    search = f'{c["id"]} {c["name"]} {" ".join(c["wastes"])}'.lower()
    fix = (
        f'<p class="fix"><strong>Fix:</strong> {e(c["recommendation"])}</p>'
        if c["recommendation"] and status == "fail"
        else (f'<p class="fix">{e(c["recommendation"])}</p>' if c["recommendation"] else "")
    )
    return (
        f'<details class="check" id="check-{e(c["id"])}" data-status="{status}" data-search="{e(search)}">'
        f'<summary><span class="cstatus">{pill(status)}</span><span class="cid">{e(c["id"])}</span>'
        f'<span class="cname">{e(c["name"])}</span><span class="cmetric">{e(c["metric"])}</span>'
        f'<span class="cthreshold">{e(threshold)}</span>{CHEVRON}</summary>'
        f'<div class="check-body"><p class="desc">{e(c["description"])}</p>{fix}'
        f'<div class="check-meta">{meta}</div>{note}{items}</div></details>'
    )


def check_list(list_id: str, groups: list[tuple[str, list[dict]]]) -> str:
    total = sum(len(g) for _, g in groups)
    failed = sum(1 for _, g in groups for c in g if c["status"] == "fail")
    bar = (
        f'<div class="filterbar" data-check-filter="{list_id}">'
        '<div class="segmented" role="group" aria-label="Filter checks by result">'
        '<button type="button" data-status="all" aria-pressed="true">All</button>'
        f'<button type="button" data-status="fail" aria-pressed="false">Failed ({failed})</button>'
        '<button type="button" data-status="pass" aria-pressed="false">Passed</button>'
        '<button type="button" data-status="info" aria-pressed="false">Info</button></div>'
        f'<input type="search" id="{list_id}-search" placeholder="Search checks" aria-label="Search checks">'
        f'<span class="count">{total} checks</span></div>'
    )
    body = []
    for title, checks in groups:
        body.append(f'<div class="checks-group"><span class="label">{e(title)}</span></div>')
        body += [check_row(c) for c in checks]
    body.append('<p class="empty" hidden>No checks match this filter.</p>')
    return bar + f'<div class="checks" id="{list_id}">{"".join(body)}</div>'


def section_head(anchor: str, eyebrow: str, title: str, intro: str) -> str:
    return (
        f'<div class="section-head"><span class="label">{e(eyebrow)}</span><h2 id="{anchor}-title">{e(title)}</h2>'
        f"<p>{intro}</p></div>"
    )


# -- sections ----------------------------------------------------------------------
def render_titleblock(r: dict) -> str:
    p, d = r["project"], r["dates"]
    cells = [
        ("Data date", d["data_date"]),
        ("Source", f'{p["source_format"]}'),
        ("Forecast finish", d["forecast_finish"] or "n/a"),
        ("File", p["source_name"] or "uploaded file"),
        ("Calendar", p["calendar"]),
        ("Generated", r["generated_at"].replace("T", " ")),
    ]
    cell_html = "".join(
        f'<div><span class="label">{e(k)}</span><div class="value">{e(str(v))}</div></div>'
        for k, v in cells
    )
    code = (
        f' <span class="muted mono" style="font-size:14px">{e(p["code"])}</span>'
        if p["code"] and p["code"] != p["name"]
        else ""
    )
    return (
        f'<header class="titleblock"><div><span class="label">{e(r["tool"]["name"])}</span>'
        f'<h1>{e(p["name"])}</h1><span class="small muted">Schedule integrity and Lean readiness review{code}</span></div>{cell_html}</header>'
    )


def render_nav(has_flow: bool) -> str:
    links = [
        ("overview", "Overview"),
        ("integrity", "Schedule integrity"),
        ("lean", "Lean readiness"),
    ]
    if has_flow:
        links.append(("flow", "Flow and takt"))
    links += [
        ("lps", "Last Planner"),
        ("waste", "Waste lens"),
        ("assistant", "Assistant"),
        ("assumptions", "Assumptions"),
    ]
    items = "".join(f'<li><a href="#{a}">{e(t)}</a></li>' for a, t in links)
    return f'<nav class="sections" aria-label="Report sections"><ul>{items}</ul></nav>'


def render_overview(r: dict) -> str:
    s, d, cp = r["stats"], r["dates"], r["critical_path"]
    weekly = r["lps"].get("weekly")
    board = r["lookahead"].get("board")
    finish_ctx = []
    if d.get("finish_variance_days") is not None and d.get("baseline_finish"):
        v = d["finish_variance_days"]
        finish_ctx.append(
            f'{abs(v)} working days {"after" if v > 0 else "before"} baseline ({e(d["baseline_finish"])})'
            if v
            else "On the baseline finish"
        )
    if d.get("deadline"):
        finish_ctx.append(f'Deadline {e(d["deadline"])}')
    tiles = [
        score_tile("Schedule integrity", r["scores"]["integrity"], "integrity"),
        score_tile("Lean readiness", r["scores"]["lean"], "lean"),
        tile("Forecast finish", e(d["forecast_finish"] or "n/a"), "; ".join(finish_ctx), "date"),
        tile(
            "Critical activities",
            f'{s["critical"]}<small> of {s["incomplete"]}</small>',
            f'Driving path: {cp["length"]} activities from {e(cp["origin"] or "n/a")}',
        ),
    ]
    if weekly and weekly.get("ppc_last4") is not None:
        tiles.append(
            tile(
                "PPC, last 4 weeks",
                f'{weekly["ppc_last4"]:g}%',
                f'Target {weekly["target"]:g}%; trend {weekly["trend_per_week"]:+.1f} points a week',
            )
        )
    else:
        tiles.append(
            tile("PPC, last 4 weeks", "n/a", "Add weekly work plans to track plan reliability")
        )
    if board:
        n = len(board["rows"])
        tiles.append(
            tile(
                "Lookahead ready",
                f'{board["ready"]}<small> of {n}</small>',
                f'{board["overdue"]} with overdue constraints; {board["constrained"]} constrained',
            )
        )
    else:
        tiles.append(
            tile(
                "Lookahead activities",
                str(r["lookahead"]["activities"]),
                f'Next {r["lookahead"]["weeks"]} weeks, to {e(r["lookahead"]["end"])}',
            )
        )
    issues = (
        "".join(
            f'<li><div><a class="what" href="#check-{e(i["id"])}">{e(i["id"])} {e(i["name"])}</a>'
            f' <span class="muted">{e(i["metric"])} against {e(nice(i["threshold"]))}</span>'
            f'<p class="how">{e(i["recommendation"])}</p></div></li>'
            for i in r["top_issues"]
        )
        or '<li><div class="what">No failed checks.</div></li>'
    )
    bins = s["float_histogram"]
    hist_rows = [{"Total float": b["label"], "Activities": b["count"]} for b in bins]
    rel = s["relationship_types"]
    rel_parts = [(k, v, charts.SERIES[i]) for i, (k, v) in enumerate(rel.items())]
    rel_legend = charts.legend(
        [(f"{k} {v:,}", charts.SERIES[i]) for i, (k, v) in enumerate(rel.items())], "box"
    )
    by_status = ", ".join(f"{v:,} {k.lower()}" for k, v in s["by_status"].items())
    return (
        '<section id="overview" aria-labelledby="overview-title">'
        + section_head(
            "overview",
            "Summary",
            "Overview",
            "Headline scores, then the fixes that would raise them the most.",
        )
        + f'<div class="tiles">{"".join(tiles)}</div>'
        + '<div class="grid-2">'
        + f'<div class="card"><header><h3>Top priorities</h3><span class="small muted">Failed checks ranked by their effect on the scores</span></header><ol class="issues">{issues}</ol></div>'
        + '<div class="card"><header><h3>Total float of incomplete activities</h3>'
        + f'<span class="small muted">Float source: {e(r["project"]["float_source"].lower())}. Red is negative float, amber is above 44 days.</span></header>'
        + charts.float_histogram(bins)
        + f'<details class="tableview"><summary>Show as table</summary>{data_table(hist_rows, "float-table", visible=99)}</details>'
        + f'<div class="small muted">{s["activities"]:,} activities ({by_status}); {s["relationships"]:,} relationships</div>'
        + charts.segmented_bar(rel_parts, "Relationship types")
        + rel_legend
        + "</div></div></section>"
    )


def render_integrity(r: dict) -> str:
    dcma = [c for c in r["checks"] if c["group"] == "DCMA 14-Point"]
    ext = [c for c in r["checks"] if c["group"] == "Extended integrity"]
    intro = (
        "Critical path method (CPM) health. The DCMA 14-Point Assessment is the common baseline for schedule "
        "reviews; the extended checks look for the logic problems it misses. Open a check to see the flagged "
        "activities and how to fix them."
    )
    return (
        '<section id="integrity" aria-labelledby="integrity-title">'
        + section_head("integrity", "CPM network", "Schedule integrity", intro)
        + check_list("integrity-list", [("DCMA 14-Point Assessment", dcma), ("Beyond DCMA", ext)])
        + "</section>"
    )


def render_lean(r: dict) -> str:
    lean = [c for c in r["checks"] if c["group"] == "Lean readiness"]
    la = r["lookahead"]
    m = r["mapping"]
    intro = (
        f'Can this schedule be run with the Last Planner System? These checks look at the {la["weeks"]}-week lookahead '
        "(work sized for weekly promises, a responsible trade and a location for every task, no date-driven push), "
        "at workflow between trades and at plan reliability."
    )
    chips = (
        f'<span class="label">Trade from</span><span class="chip">{e(m["trade"]["label"])} ({m["trade"]["coverage"]:g}% of tasks)</span>'
        f'<span class="label">Location from</span><span class="chip">{e(m["location"]["label"])} ({m["location"]["coverage"]:g}% of tasks)</span>'
    )
    trade_rows = [(t["trade"], t["count"], str(t["count"])) for t in la["by_trade"][:12]]
    board = la.get("board")
    if board:
        status_map = {"Ready": "pass", "Constrained": "warn", "Overdue constraint": "fail"}
        late_chip = ' <span class="chip">removal due after start</span>'
        rows = "".join(
            f'<tr class="{"more" if i >= 15 else ""}"><td class="id">{e(b["id"])}</td><td>{e(b["name"])}</td><td>{e(b["trade"])}</td>'
            f'<td>{e(b["location"])}</td><td class="date">{e(b["start"])}</td><td>{pill(status_map[b["status"]], b["status"])}</td>'
            f'<td>{e(b["constraints"])}{late_chip if b["late_removal"] else ""}</td></tr>'
            for i, b in enumerate(board["rows"])
        )
        more = (
            f'<button class="show-more" type="button" data-show-rows="board-table">Show all {len(board["rows"])} rows</button>'
            if len(board["rows"]) > 15
            else ""
        )
        unlinked = ""
        if board["unlinked"]:
            unlinked = (
                f'<p class="small muted">{len(board["unlinked"])} constraint(s) do not match a schedule activity ID: '
                + ", ".join(e(u["id"]) for u in board["unlinked"])
                + ".</p>"
            )
        board_html = (
            '<div class="card"><header><h3>Make-ready board</h3>'
            f'<span class="small muted">Lookahead activities and their open constraints from the constraint log. {board["ready"]} ready, {board["constrained"]} constrained, {board["overdue"]} with overdue constraints.</span></header>'
            '<div class="table-wrap"><table id="board-table"><thead><tr><th>Activity ID</th><th>Activity</th><th>Trade</th><th>Zone</th><th>Start</th><th>Status</th><th>Open constraints</th></tr></thead>'
            f"<tbody>{rows}</tbody></table></div>{more}{unlinked}</div>"
        )
    else:
        board_html = (
            '<div class="card"><header><h3>Make-ready board</h3></header><p class="notice">Add a constraint log (CSV with id, activity_id, '
            "description, category, owner, need_by, status) to see which lookahead activities are ready to be committed.</p></div>"
        )
    return (
        '<section id="lean" aria-labelledby="lean-title">'
        + section_head("lean", "Last Planner System", "Lean readiness", intro)
        + f'<div class="check-meta">{chips}</div>'
        + check_list("lean-list", [("Lean readiness checks", lean)])
        + f'<div class="card"><header><h3>Lookahead by trade</h3><span class="small muted">{la["activities"]} activities under way or starting before {e(la["end"])}; {la["in_progress"]} in progress, {la["critical"]} critical</span></header>'
        + (
            charts.hbar_rows(trade_rows, css="wide")
            if trade_rows
            else '<p class="muted">No lookahead work.</p>'
        )
        + "</div>"
        + board_html
        + "</section>"
    )


def trade_colors(flow: dict | None) -> dict[str, str]:
    trades = (flow or {}).get("flowline", {}) or {}
    names = trades.get("trades", []) if trades else []
    return {t: charts.SERIES[i] for i, t in enumerate(names[:8])}


def render_flow(r: dict) -> str:
    flow = r["flow"]
    colors = trade_colors(flow)
    fl = flow.get("flowline")
    takt = flow.get("takt") or {}
    parts = [
        '<section id="flow" aria-labelledby="flow-title">',
        section_head(
            "flow",
            "Takt and location-based planning",
            "Flow and takt",
            "How trades move through locations. Each line on the flowline is one trade working zone by zone; parallel, "
            "evenly spaced lines mean continuous flow, while lines that bunch or cross mean trades waiting or stacked in the same zone.",
        ),
    ]
    if fl and fl["segments"]:
        shown = fl["trades"][:8]
        fl_view = dict(
            fl, trades=shown, segments=[s for s in fl["segments"] if s["trade"] in shown]
        )
        seg_rows = [
            {
                "Trade": s["trade"],
                "Zone": s["zone"],
                "Activity ID": s["id"],
                "Start": s["start"][:10],
                "Finish": s["finish"][:10],
                "Status": "Complete" if s["complete"] else "Planned",
            }
            for s in sorted(fl_view["segments"], key=lambda s: (s["trade"], s["start"]))
        ]
        extra = f' Showing 8 of {len(fl["trades"])} trades.' if len(fl["trades"]) > 8 else ""
        parts.append(
            '<div class="card"><header><h3>Flowline (line of balance)</h3>'
            f'<span class="small muted">Zones from first to last, bottom to top. Faded segments are complete.{extra}</span></header>'
            + charts.legend([(t, colors[t]) for t in shown])
            + f'<div class="chart-scroll">{charts.flowline_chart(fl_view, colors)}</div>'
            + f'<details class="tableview"><summary>Show as table</summary>{data_table(seg_rows, "flowline-table", visible=20)}</details></div>'
        )
    if takt.get("available"):
        trades = [t["trade"] for t in takt["trades"]]
        head = "".join(f'<th scope="col">T{p + 1}</th>' for p in range(takt["periods"]))
        rows = []
        for zi, zone in enumerate(takt["zones"]):
            cells = []
            for p in range(takt["periods"]):
                k = takt["grid"][zi][p]
                if k is None:
                    cells.append('<td class="cell empty"></td>')
                else:
                    t = trades[k]
                    slot = list(colors).index(t) if t in colors else -1
                    on = "on-s4" if slot == 3 else "on-s"
                    color = colors.get(t, "var(--ink-3)")
                    cells.append(
                        f'<td class="cell {on}" style="background:{color}" title="{e(t)} in {e(zone)}, takt {p + 1}">{e(t[:3])}</td>'
                    )
            rows.append(f'<tr><th scope="row">{e(zone)}</th>{"".join(cells)}</tr>')
        stats_rows = [
            {
                "Trade": t["trade"],
                "Zones": t["zones"],
                "Min (d)": t["min"],
                "Median (d)": t["median"],
                "Max (d)": t["max"],
                "Variation (CV)": f'{t["cv"]:.2f}',
            }
            for t in takt["trades"]
        ]
        over_rows = [
            {
                "Trade": o["trade"],
                "Zone": o["zone"],
                "Work (d)": o["work"],
                "Crew factor": f'x{o["factor"]:.2f}',
            }
            for o in takt["overloaded"]
        ]
        current = takt["current_span"]
        saving = (
            f'{current - takt["train_balanced"]} working days shorter than the current plan ({current} days)'
            if current and current > takt["train_balanced"]
            else (f"Current plan: {current} working days" if current else "")
        )
        parts.append(
            '<div class="tiles">'
            + tile(
                "Takt time, balanced",
                f'{takt["takt_balanced"]}<small> days</small>',
                f'Trades above it need more crew or smaller zones ({len(takt["overloaded"])} trade-zone cells)',
            )
            + tile(
                "Takt train, balanced", f'{takt["train_balanced"]}<small> days</small>', e(saving)
            )
            + tile(
                "Takt time, no rebalancing",
                f'{takt["takt_fit"]}<small> days</small>',
                f'Train of {takt["train_fit"]} working days',
            )
            + tile(
                "Takt balance (CV)",
                f'{takt["avg_cv"]:.2f}',
                "Average variation of work per zone; 0.35 or less is balanced",
            )
            + "</div>"
        )
        parts.append(
            '<div class="card"><header><h3>Suggested takt plan</h3>'
            f'<span class="small muted">{len(takt["zones"])} zones and {len(trades)} trades at a {takt["takt_balanced"]}-day takt. Each trade is a wagon that moves one zone per takt period.</span></header>'
            + charts.legend([(t, colors.get(t, "var(--ink-3)")) for t in trades], "box")
            + f'<div class="table-wrap takt"><table><thead><tr><th scope="col">Zone</th>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div></div>'
        )
        parts.append(
            '<div class="grid-2">'
            + f'<div class="card"><header><h3>Work content per zone</h3><span class="small muted">Working days of work for each trade in each takt zone</span></header>{data_table(stats_rows, "takt-stats", visible=20)}</div>'
            + '<div class="card"><header><h3>Cells above the balanced takt</h3><span class="small muted">Crew factor = work / takt time: the crew increase (or zone split) needed to keep the rhythm</span></header>'
            + (
                data_table(over_rows, "takt-over", visible=12)
                or '<p class="muted">Every cell fits the takt.</p>'
            )
            + "</div></div>"
        )
    elif fl is not None or flow.get("has_trade"):
        parts.append(
            f'<p class="notice">{e(takt.get("reason", "Takt analysis is not available."))}</p>'
        )
    stacking = flow.get("stacking")
    continuity = flow.get("continuity")
    cards = []
    if stacking:
        rows = [
            {
                "Zone": h["zone"],
                "From": h["start"],
                "To": h["finish"],
                "Days": h["days"],
                "Max trades": h["max_trades"],
                "Trades": ", ".join(h["trades"]),
            }
            for h in stacking["hotspots"]
        ]
        cards.append(
            f'<div class="card"><header><h3>Trade stacking hotspots</h3><span class="small muted">{stacking["stacked_zone_days"]} of {stacking["occupied_zone_days"]} occupied zone-days have more than one trade ({stacking["pct"]:g}%)</span></header>'
            + (
                data_table(rows, "stacking-table", visible=10)
                or '<p class="muted">No zone has two trades at once.</p>'
            )
            + "</div>"
        )
    if continuity and continuity["rows"]:
        body = "".join(
            f'<tr class="{"more" if i >= 12 else ""}"><td>{e(c["trade"])}</td><td class="n">{c["periods"]}</td>'
            f'<td class="n">{c["long_gaps"]}</td><td class="n">{c["longest_gap"]}</td>'
            f'<td><span class="density"><span class="track"><span class="fill" style="width:{c["density"]:.0f}%"></span></span>{c["density"]:.0f}%</span></td></tr>'
            for i, c in enumerate(continuity["rows"])
        )
        more = (
            f'<button class="show-more" type="button" data-show-rows="continuity-table">Show all {len(continuity["rows"])} trades</button>'
            if len(continuity["rows"]) > 12
            else ""
        )
        cards.append(
            '<div class="card"><header><h3>Trade continuity</h3><span class="small muted">Remaining work per trade. Density is the share of a trade\'s span with work in hand.</span></header>'
            '<div class="table-wrap"><table id="continuity-table"><thead><tr><th>Trade</th><th class="n">Work periods</th>'
            f'<th class="n">Gaps &gt; {r["settings"]["trade_gap_days"]:g} d</th><th class="n">Longest gap (d)</th><th>Density</th></tr></thead><tbody>{body}</tbody></table></div>{more}</div>'
        )
    if cards:
        parts.append(f'<div class="grid-2">{"".join(cards)}</div>')
    parts.append("</section>")
    return "".join(parts)


def render_lps(r: dict) -> str:
    weekly, log = r["lps"].get("weekly"), r["lps"].get("constraints")
    parts = [
        '<section id="lps" aria-labelledby="lps-title">',
        section_head(
            "lps",
            "Last Planner System",
            "Last Planner",
            "Plan reliability and constraint removal. PPC (Percent Plan Complete) is the share of weekly promises kept; "
            "the reasons for misses show where the system needs fixing.",
        ),
    ]
    if not weekly and not log:
        parts.append(
            '<p class="notice">No Last Planner data in this report. Add a weekly work plan CSV (week, activity_id, task, trade, '
            "planned, completed, reason) and a constraint log CSV to track PPC, reasons for non-completion and make-ready.</p></section>"
        )
        return "".join(parts)
    cards = []
    if weekly:
        week_rows = [
            {
                "Week": w["week"],
                "Promises": w["planned"],
                "Kept": w["completed"],
                "PPC": f'{w["ppc"]:g}%',
                "4-week PPC": f'{w["rolling4"]:g}%',
            }
            for w in weekly["weeks"]
        ]
        cards.append(
            '<div class="card"><header><h3>Percent Plan Complete</h3>'
            f'<span class="small muted">{weekly["commitments"]} promises over {len(weekly["weeks"])} weeks; {weekly["linked"]} linked to schedule activities</span></header>'
            + charts.legend(
                [("Weekly PPC", charts.SERIES[0]), ("4-week rolling PPC", charts.SERIES[1])]
            )
            + charts.ppc_chart(weekly["weeks"], weekly["target"])
            + f'<details class="tableview"><summary>Show as table</summary>{data_table(week_rows, "ppc-table", visible=99)}</details>'
            + '<h3 style="margin-top:6px">PPC by trade</h3>'
            + data_table(
                [
                    {
                        "Trade": t["trade"],
                        "Promises": t["planned"],
                        "Kept": t["completed"],
                        "PPC": f'{t["ppc"]:g}%',
                        "Last 4 weeks": (
                            f'{t["ppc_last4"]:g}%' if t["ppc_last4"] is not None else ""
                        ),
                    }
                    for t in weekly["trades"]
                ],
                "ppc-trade",
                visible=10,
            )
            + "</div>"
        )
        reasons = weekly["reasons"]
        reason_rows = [(x["reason"], x["count"], f'{x["count"]} ({x["pct"]:g}%)') for x in reasons]
        reason_table = [
            {
                "Reason": x["reason"],
                "Misses": x["count"],
                "Share": f'{x["pct"]:g}%',
                "Cumulative": f'{x["cum_pct"]:g}%',
            }
            for x in reasons
        ]
        cards.append(
            '<div class="card"><header><h3>Reasons for non-completion</h3>'
            f'<span class="small muted">{weekly["misses"]} missed promises, largest cause first</span></header>'
            + (
                charts.hbar_rows(reason_rows)
                if reason_rows
                else '<p class="muted">No misses recorded.</p>'
            )
            + f'<details class="tableview"><summary>Show as table</summary>{data_table(reason_table, "rnc-table", visible=99)}</details>'
            + "</div>"
        )
    if cards:
        parts.append(f'<div class="grid-2">{"".join(cards)}</div>')
    if log:
        avg = f'{log["avg_days_to_remove"]:g}' if log["avg_days_to_remove"] is not None else "n/a"
        on_time = (
            f'{log["removed_on_time_pct"]:g}%' if log["removed_on_time_pct"] is not None else "n/a"
        )
        parts.append(
            '<div class="tiles">'
            + tile(
                "Open constraints",
                str(log["open"]),
                f'{log["total"]} logged, {log["closed"]} removed',
            )
            + tile("Overdue", str(log["overdue"]), "Open and past their need-by date")
            + tile("Due in 2 weeks", str(log["due_soon"]), "Open, need-by date coming up")
            + tile("Days to remove", avg, f"Average; {on_time} removed by the need-by date")
            + "</div>"
        )
        cat_rows = "".join(
            f'<tr><td>{e(c["category"])}</td><td class="n">{c["open"] - c["overdue"]}</td><td class="n">{c["overdue"]}</td><td class="n">{c["closed"]}</td>'
            f'<td style="width:34%">{charts.segmented_bar([("Open", c["open"] - c["overdue"], charts.SERIES[0]), ("Overdue", c["overdue"], "var(--bad)"), ("Removed", c["closed"], "var(--rule-2)")], c["category"])}</td></tr>'
            for c in log["by_category"]
        )
        overdue = [
            {
                "Constraint": o["id"],
                "Description": o["description"],
                "Category": o["category"],
                "Owner": o["owner"],
                "Need by": o["need_by"],
            }
            for o in log["overdue_rows"]
        ]
        parts.append(
            '<div class="grid-2">'
            + '<div class="card"><header><h3>Constraints by flow</h3><span class="small muted">The seven preconditions of sound work, plus other causes</span></header>'
            + charts.legend(
                [
                    ("Open", charts.SERIES[0]),
                    ("Overdue", "var(--bad)"),
                    ("Removed", "var(--rule-2)"),
                ],
                "box",
            )
            + f'<div class="table-wrap"><table><thead><tr><th>Category</th><th class="n">Open</th><th class="n">Overdue</th><th class="n">Removed</th><th>Split</th></tr></thead><tbody>{cat_rows}</tbody></table></div></div>'
            + '<div class="card"><header><h3>Overdue constraints</h3><span class="small muted">Escalate these in the next lookahead meeting</span></header>'
            + (
                data_table(overdue, "overdue-table", visible=10)
                or '<p class="muted">None overdue.</p>'
            )
            + "</div></div>"
        )
    parts.append("</section>")
    return "".join(parts)


def render_waste(r: dict) -> str:
    rows = []
    for w in r["wastes"]:
        checks = (
            " ".join(
                f'<a class="chip" href="#check-{e(c["id"])}" title="{e(c["name"])}: {c["points"]:g} points">{e(c["id"])}</a>'
                for c in w["checks"]
            )
            or '<span class="muted">No failed checks</span>'
        )
        rows.append(
            f'<tr><td><strong>{e(w["waste"])}</strong><div class="small muted">{e(w["meaning"])}</div></td>'
            f'<td class="n">{w["points"]:g}</td><td>{checks}</td><td>{e(w["countermeasure"])}</td></tr>'
        )
    return (
        '<section id="waste" aria-labelledby="waste-title">'
        + section_head(
            "waste",
            "Toyota Production System",
            "Waste lens",
            "Every failed check, translated into the eight wastes of Lean (plus Mura, unevenness, and Muri, overburden), "
            "ranked by the score points those checks cost. A check can point to more than one waste. Use it to explain "
            "to the site team why a schedule problem matters.",
        )
        + f'<div class="table-wrap"><table><thead><tr><th>Waste</th><th class="n">Points lost</th><th>Failed checks</th><th>Countermeasure</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
        + "</section>"
    )


def render_assistant(r: dict, ai: dict | None, mode: str, report_id: str | None) -> str:
    ai = ai or {"text": r.get("narrative", ""), "source": "offline", "model": None}
    if ai["source"] == "offline":
        badge = '<span class="chip">Offline summary: rule-based, no AI service used</span>'
    else:
        badge = f'<span class="chip">AI summary: {e(ai.get("model") or "")} via {e(ai["source"])}</span>'
    error = (
        f'<p class="small muted">The AI request failed ({e(ai["error"])}); showing the offline summary.</p>'
        if ai.get("error")
        else ""
    )
    if mode == "web" and report_id:
        ask = (
            f'<form class="ask" id="ask-form" data-endpoint="/api/report/{e(report_id)}/ask">'
            '<label for="ask-question"><strong>Ask about this schedule</strong></label>'
            '<textarea id="ask-question" name="question" placeholder="Which activities drive the level 3 handover? What should we pull-plan first?"></textarea>'
            '<button class="button" type="submit">Ask</button></form><div class="prose" id="ask-answer" hidden></div>'
        )
    else:
        ask = (
            '<p class="notice">To ask questions about this schedule, run the web app (<code>python -m lean_sic serve</code>) '
            "and configure Azure OpenAI or OpenAI in <code>.env</code>.</p>"
        )
    return (
        '<section id="assistant" aria-labelledby="assistant-title">'
        + section_head(
            "assistant",
            "Generative AI",
            "Planning assistant",
            "An executive summary and Lean action plan for the project team.",
        )
        + f'<div class="card"><div class="check-meta">{badge}</div>{error}<div class="prose">{md_to_html(ai["text"])}</div></div>'
        + f'<div class="card">{ask}</div></section>'
    )


def render_assumptions(r: dict, mode: str, report_id: str | None) -> str:
    p, m, st = r["project"], r["mapping"], r["settings"]
    rows = [
        ("Source file", p["source_name"] or "uploaded file"),
        ("Format", p["source_format"]),
        ("Data date", r["dates"]["data_date"]),
        ("Calendar", p["calendar"]),
        ("Float source", p["float_source"]),
        ("Baseline source", p["baseline_source"]),
        ("Critical when float is at or below", f'{p["critical_float"]:g} days'),
        ("Trade", f'{m["trade"]["label"]} ({m["trade"]["values"]} trades)'),
        ("Location", f'{m["location"]["label"]} ({m["location"]["values"]} locations)'),
        (
            "Lookahead",
            f'{st["lookahead_weeks"]} weeks; make-ready window {st["make_ready_weeks"]} weeks',
        ),
        (
            "Thresholds",
            f'high float {st["high_float_days"]:g} d, high duration {st["high_duration_days"]:g} d, long lag {st["long_lag_days"]:g} d, lookahead task {st["lean_max_task_days"]:g} d, trade gap {st["trade_gap_days"]:g} d, PPC target {st["ppc_target"]:g}%',
        ),
        (
            "Scoring",
            "Each check scores 1 when it meets its threshold and loses credit in proportion to the miss; group scores are weighted averages (0-100). Info checks are not scored.",
        ),
    ]
    if p["other_projects"]:
        rows.append(("Other projects in the file", ", ".join(p["other_projects"])))
    if p.get("dates_computed"):
        rows.append(
            ("Dates", f'{p["dates_computed"]} forecast dates were calculated by the CPM engine')
        )
    kv = "".join(f"<dt>{e(k)}</dt><dd>{e(str(v))}</dd>" for k, v in rows)
    warnings = "".join(f"<li>{e(w)}</li>" for w in p["warnings"])
    warn_html = (
        f'<div class="card"><h3>Warnings</h3><ul class="small">{warnings}</ul></div>'
        if warnings
        else ""
    )
    rerun = ""
    if mode == "web" and report_id:
        options = ["", "resource", "wbs", "wbs:1", "wbs:2", "wbs:3", "none"] + m["available_fields"]

        def select(name: str, current: str) -> str:
            opts = "".join(
                f'<option value="{e(o)}"{" selected" if o == current else ""}>{e(o or "Auto-detect")}</option>'
                for o in dict.fromkeys(options)
            )
            return f'<select id="{name}" name="{name}">{opts}</select>'

        rerun = (
            f'<form class="card" method="post" action="/report/{e(report_id)}/rerun"><h3>Re-run with different settings</h3>'
            f'<div class="kv"><label for="trade_field">Trade field</label>{select("trade_field", st["trade_field"] or "")}'
            f'<label for="location_field">Location field</label>{select("location_field", st["location_field"] or "")}'
            f'<label for="lookahead_weeks">Lookahead weeks</label><input id="lookahead_weeks" name="lookahead_weeks" type="number" min="1" max="26" value="{st["lookahead_weeks"]}"></div>'
            '<button class="button" type="submit">Re-run analysis</button>'
            f'<p class="small"><a href="/report/{e(report_id)}/json">Download JSON</a> - <a href="/report/{e(report_id)}/download">Download this report</a> - <a href="/">Check another schedule</a></p></form>'
        )
    return (
        '<section id="assumptions" aria-labelledby="assumptions-title">'
        + section_head(
            "assumptions",
            "Method",
            "Assumptions and settings",
            "How the numbers in this report were produced.",
        )
        + f'<div class="grid-2"><div class="card"><dl class="kv">{kv}</dl></div><div style="display:grid;gap:16px;align-content:start">{warn_html}{rerun}</div></div>'
        + "</section>"
    )


def render_report(
    result: dict,
    ai: dict | None = None,
    mode: str = "static",
    report_id: str | None = None,
    web_fonts: bool = True,
) -> str:
    """Return the full HTML page for an analysis result."""
    css = (HERE / "report.css").read_text(encoding="utf-8")
    js = (HERE / "report.js").read_text(encoding="utf-8")
    flow = result.get("flow") or {}
    has_flow = bool(
        flow.get("flowline") or (flow.get("takt") or {}).get("available") or flow.get("continuity")
    )
    body = "".join(
        [
            '<div class="wrap">',
            render_titleblock(result),
            render_nav(has_flow),
            "<main>",
            render_overview(result),
            render_integrity(result),
            render_lean(result),
            render_flow(result) if has_flow else "",
            render_lps(result),
            render_waste(result),
            render_assistant(result, ai, mode, report_id),
            render_assumptions(result, mode, report_id),
            "</main>",
            f'<footer class="colophon"><span>{e(result["tool"]["name"])} {e(result["tool"]["version"])}</span>'
            "<span>DCMA 14-Point Assessment, extended CPM checks, Last Planner System and takt readiness</span>"
            f'<span>Generated {e(result["generated_at"].replace("T", " "))}</span></footer>',
            "</div>",
        ]
    )
    title = f'{result["project"]["name"]} schedule check'
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
        f"<title>{e(title)}</title>"
        '<meta name="claude:viewport-fit-sides" content="cover">'
        + (FONTS if web_fonts else "")
        + f"<style>{css}.sr-only{{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}}</style></head>"
        + f"<body>{body}<script>{js}</script></body></html>"
    )
