"""Command line interface.

Examples::

    python -m lean_sic analyze samples/harbourside-health-centre.xer \\
        --weekly-plans samples/weekly-work-plans.csv --constraints samples/constraint-log.csv
    python -m lean_sic fields my-schedule.xer
    python -m lean_sic serve
    python -m lean_sic ask my-schedule.xer "What drives the level 3 handover?"
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from . import TOOL_NAME, __version__
from .analysis import analyze
from .parsers import ScheduleParseError, load_schedule
from .settings import Settings

STATUS_TEXT = {"pass": "PASS", "fail": "FAIL", "info": "INFO", "na": "N/A "}


def _settings(args: argparse.Namespace) -> Settings:
    overrides: dict = {}
    for item in args.set or []:
        key, sep, value = item.partition("=")
        if not sep or not hasattr(Settings(), key.strip()):
            raise SystemExit(
                f"Unknown setting '{item}'. Valid keys: {', '.join(Settings().to_dict())}"
            )
        overrides[key.strip()] = value.strip()
    for key in ("trade_field", "location_field", "lookahead_weeks"):
        value = getattr(args, key, None)
        if value not in (None, ""):
            overrides[key] = value
    return Settings.from_dict(overrides)


def _load(args: argparse.Namespace):
    data_date = None
    if getattr(args, "data_date", None):
        data_date = datetime.fromisoformat(args.data_date)
    try:
        return load_schedule(
            args.schedule, project=args.project, data_date=data_date, dayfirst=args.dayfirst
        )
    except (ScheduleParseError, OSError) as exc:
        raise SystemExit(f"Could not read {args.schedule}: {exc}") from exc


def print_summary(result: dict) -> None:
    p, s = result["project"], result["scores"]
    print(f"{TOOL_NAME} {__version__}")
    print(f"Project: {p['name']} ({p['source_format']}), data date {result['dates']['data_date']}")
    for name in ("integrity", "lean"):
        sc = s[name]
        value = "n/a" if sc["score"] is None else f"{sc['score']:.1f}"
        print(
            f"{'Schedule integrity' if name == 'integrity' else 'Lean readiness':<20} {value:>6} / 100  grade {sc['grade']} ({sc['label']})"
        )
    print()
    group = None
    for c in result["checks"]:
        if c["group"] != group:
            group = c["group"]
            print(f"-- {group} --")
        counts = (
            f"{c['count']}/{c['population']}"
            if c["population"]
            else (str(c["count"]) if c["count"] else "")
        )
        print(
            f"  {STATUS_TEXT.get(c['status'], c['status']):4}  {c['id']:<8} {c['name'][:44]:<44} {c['metric']:>14}  {c['threshold']:<16} {counts}"
        )
    for w in p["warnings"]:
        print(f"Warning: {w}")


def cmd_analyze(args: argparse.Namespace) -> int:
    schedule = _load(args)
    result = analyze(
        schedule, _settings(args), args.weekly_plans, args.constraints, dayfirst=args.dayfirst
    )
    ai = None
    if args.ai:
        from .ai import generate_summary

        ai = generate_summary(result)
        result["ai"] = ai
        if ai["source"] == "offline" and not args.quiet:
            print(
                "AI is not configured (or the request failed); the report uses the offline summary.",
                file=sys.stderr,
            )
    from .report import render_report

    out = (
        Path(args.output)
        if args.output
        else Path(args.schedule).with_name(Path(args.schedule).stem + "-report.html")
    )
    out.write_text(render_report(result, ai, web_fonts=not args.no_web_fonts), encoding="utf-8")
    if args.json_path:
        Path(args.json_path).write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    if not args.quiet:
        print_summary(result)
        print(f"\nReport written to {out}")
        if args.json_path:
            print(f"Results written to {args.json_path}")
    score = result["scores"]["integrity"]["score"]
    if args.fail_under is not None and (score is None or score < args.fail_under):
        print(f"Integrity score {score} is below --fail-under {args.fail_under}.", file=sys.stderr)
        return 1
    return 0


def cmd_fields(args: argparse.Namespace) -> int:
    schedule = _load(args)
    from .lean.mapping import resolve_mapping

    mapping = resolve_mapping(schedule)
    print(f"{schedule.name}: {len(schedule.activities)} activities")
    print("Fields available for --trade-field / --location-field:")
    for name in schedule.code_fields or ["(none)"]:
        values = {a.codes.get(name) for a in schedule.activities.values() if a.codes.get(name)}
        print(f"  {name:<30} {len(values)} distinct values")
    print("  resource                       first assigned resource")
    print("  wbs / wbs:N                    a WBS level (auto-detected or level N)")
    print(
        f"Auto-detected trade: {mapping['trade']['label']} ({mapping['trade']['coverage']}% of tasks)"
    )
    print(
        f"Auto-detected location: {mapping['location']['label']} ({mapping['location']['coverage']}% of tasks)"
    )
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    from .ai import answer_question

    schedule = _load(args)
    result = analyze(
        schedule, _settings(args), args.weekly_plans, args.constraints, dayfirst=args.dayfirst
    )
    answer = answer_question(result, args.question, schedule)
    print(answer["text"])
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    try:
        from .web import create_app
    except ImportError as exc:  # Flask is optional
        raise SystemExit("The web app needs Flask: pip install -r requirements.txt") from exc
    app = create_app()
    print(f"{TOOL_NAME} running on http://{args.host}:{args.port} (press Ctrl+C to stop)")
    app.run(host=args.host, port=args.port, debug=False)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lean_sic", description=f"{TOOL_NAME}: CPM integrity and Lean construction readiness."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def schedule_args(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "schedule", help="Primavera P6 .xer, Microsoft Project .xml or .csv schedule"
        )
        p.add_argument(
            "--project", help="P6 project short name when the XER contains several projects"
        )
        p.add_argument("--data-date", help="override the data date, e.g. 2026-03-02")
        p.add_argument(
            "--dayfirst", action="store_true", help="read ambiguous dates as day/month/year"
        )
        p.add_argument(
            "--trade-field", help="activity code or column holding the trade, or 'resource'"
        )
        p.add_argument(
            "--location-field", help="activity code or column holding the zone, or 'wbs' / 'wbs:N'"
        )
        p.add_argument(
            "--lookahead-weeks", type=int, help="Last Planner lookahead window (default 6)"
        )
        p.add_argument(
            "--weekly-plans", help="weekly work plan CSV (PPC and reasons for non-completion)"
        )
        p.add_argument("--constraints", help="constraint log CSV (make-ready)")
        p.add_argument(
            "--set",
            action="append",
            metavar="KEY=VALUE",
            help="override a threshold, e.g. --set high_float_days=30",
        )

    a = sub.add_parser("analyze", help="check a schedule and write an HTML report")
    schedule_args(a)
    a.add_argument("-o", "--output", help="HTML report path (default: <schedule>-report.html)")
    a.add_argument("--json", dest="json_path", help="also write the full results as JSON")
    a.add_argument(
        "--ai",
        action="store_true",
        help="add an AI-written summary (Azure OpenAI or OpenAI settings in .env)",
    )
    a.add_argument(
        "--no-web-fonts", action="store_true", help="do not load Google Fonts in the report"
    )
    a.add_argument(
        "--fail-under",
        type=float,
        help="exit with code 1 when the integrity score is below this value",
    )
    a.add_argument("--quiet", action="store_true", help="do not print the summary")
    a.set_defaults(func=cmd_analyze)

    f = sub.add_parser("fields", help="list fields available for trade and location mapping")
    f.add_argument("schedule")
    f.add_argument("--project")
    f.add_argument("--dayfirst", action="store_true")
    f.set_defaults(func=cmd_fields, data_date=None)

    q = sub.add_parser("ask", help="ask the AI planning assistant about a schedule")
    schedule_args(q)
    q.add_argument("question")
    q.set_defaults(func=cmd_ask)

    s = sub.add_parser("serve", help="start the local web app")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=5000)
    s.set_defaults(func=cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
