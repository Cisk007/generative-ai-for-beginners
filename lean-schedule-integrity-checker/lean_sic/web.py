"""Local web app: upload a schedule, get the report, ask the assistant.

    python -m lean_sic serve        # http://127.0.0.1:5000

Uploaded files are kept in memory only (never written to disk) and are
discarded after a few hours or when newer uploads push them out. The app
binds to localhost by default; it has no authentication, so do not expose it
on a shared network.
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from datetime import datetime
from html import escape as e
from pathlib import Path

from flask import Flask, Response, abort, jsonify, redirect, request

from . import TOOL_NAME, __version__
from .ai import answer_question, generate_summary, get_client
from .analysis import analyze
from .parsers import ScheduleParseError, load_schedule
from .report import md_to_html, render_report
from .settings import Settings

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
MAX_UPLOAD = 60 * 1024 * 1024


class ReportStore:
    """A small in-memory store with a size cap and a time-to-live."""

    def __init__(self, max_items: int = 20, ttl_seconds: int = 3 * 3600) -> None:
        self.max_items, self.ttl = max_items, ttl_seconds
        self._items: dict[str, dict] = {}
        self._lock = threading.Lock()

    def put(self, entry: dict) -> str:
        key = secrets.token_urlsafe(12)
        with self._lock:
            self._expire()
            while len(self._items) >= self.max_items:
                oldest = min(self._items, key=lambda k: self._items[k]["created"])
                del self._items[oldest]
            entry["created"] = time.time()
            self._items[key] = entry
        return key

    def get(self, key: str) -> dict | None:
        with self._lock:
            self._expire()
            return self._items.get(key)

    def _expire(self) -> None:
        now = time.time()
        for key in [k for k, v in self._items.items() if now - v["created"] > self.ttl]:
            del self._items[key]


def _run(entry: dict) -> None:
    """(Re)analyse the stored inputs and keep the schedule for Q&A."""
    schedule = load_schedule(
        entry["schedule_bytes"], entry["filename"], data_date=entry.get("data_date")
    )
    settings = Settings.from_dict(entry.get("settings"))
    entry["schedule"] = schedule
    entry["result"] = analyze(
        schedule, settings, entry.get("weekly_bytes"), entry.get("constraints_bytes")
    )
    entry["ai"] = generate_summary(entry["result"]) if entry.get("use_ai") else None


def upload_page(error: str = "") -> str:
    css = (Path(__file__).resolve().parent / "report" / "report.css").read_text(encoding="utf-8")
    ai_ready = get_client() is not None
    ai_note = (
        "AI is configured. Only the summarised results are sent to the model, never the schedule file."
        if ai_ready
        else "AI is not configured. Add Azure OpenAI or OpenAI settings to .env to enable it."
    )
    err = (
        f'<p class="notice" role="alert"><strong>Could not check that file.</strong> {e(error)}</p>'
        if error
        else ""
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Lean Schedule Check</title><meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>{css}
.upload {{ display: grid; gap: 14px; max-width: 760px; }}
.upload .kv input, .upload .kv select {{ font: inherit; font-size: 14px; padding: 5px 8px; border: 1px solid var(--rule-2); border-radius: 6px; background: var(--sheet); color: var(--ink); max-width: 100%; }}
</style></head><body><div class="wrap">
<header class="titleblock"><div><span class="label">{e(TOOL_NAME)}</span><h1>Check a construction schedule</h1>
<span class="small muted">CPM integrity (DCMA 14-Point and beyond) plus Lean construction readiness</span></div>
<div><span class="label">Inputs</span><div class="value">P6 XER, MS Project XML, CSV</div></div>
<div><span class="label">Lean data</span><div class="value">Weekly plans, constraint log</div></div>
<div><span class="label">Version</span><div class="value">{e(__version__)}</div></div>
<div><span class="label">Privacy</span><div class="value">Files stay in memory on this computer</div></div>
<div><span class="label">AI assistant</span><div class="value">{"Configured" if ai_ready else "Off"}</div></div>
<div><span class="label">Sample</span><div class="value"><a href="/sample">Open the sample project</a></div></div></header>
<main><section aria-labelledby="upload-title"><div class="section-head"><span class="label">Upload</span><h2 id="upload-title">Your schedule</h2>
<p>Export from Primavera P6 (XER), Microsoft Project (File, Save As, XML) or any spreadsheet (CSV). Add Last Planner data if you have it.</p></div>
{err}
<form class="card upload" method="post" action="/analyze" enctype="multipart/form-data">
<div class="kv">
<label for="schedule">Schedule file</label><input id="schedule" name="schedule" type="file" accept=".xer,.xml,.csv,.txt" required>
<label for="weekly_plans">Weekly work plans (optional)</label><input id="weekly_plans" name="weekly_plans" type="file" accept=".csv,.txt">
<label for="constraints">Constraint log (optional)</label><input id="constraints" name="constraints" type="file" accept=".csv,.txt">
<label for="data_date">Data date (optional)</label><input id="data_date" name="data_date" type="date">
<label for="trade_field">Trade field</label><input id="trade_field" name="trade_field" placeholder="Auto-detect, e.g. Trade or resource">
<label for="location_field">Location field</label><input id="location_field" name="location_field" placeholder="Auto-detect, e.g. Zone or wbs:2">
<label for="lookahead_weeks">Lookahead weeks</label><input id="lookahead_weeks" name="lookahead_weeks" type="number" min="1" max="26" value="6">
<label for="use_ai">AI summary</label><span><input id="use_ai" name="use_ai" type="checkbox" {"" if ai_ready else "disabled"}> <span class="small muted">{e(ai_note)}</span></span>
</div>
<button class="button" type="submit">Check schedule</button>
<p class="small muted">Weekly plans CSV columns: week, activity_id, task, trade, planned, completed, reason. Constraint log CSV columns: id, activity_id, description, category, owner, identified, need_by, status, closed.</p>
</form></section></main></div></body></html>"""  # noqa: S608 - HTML, not SQL


def create_app(store: ReportStore | None = None) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD
    reports = store or ReportStore()

    def entry_or_404(rid: str) -> dict:
        entry = reports.get(rid)
        if entry is None:
            abort(404, "This report has expired. Upload the schedule again.")
        return entry

    @app.get("/")
    def index():
        return upload_page()

    @app.post("/analyze")
    def analyze_upload():
        file = request.files.get("schedule")
        if file is None or not file.filename:
            return upload_page("Choose a schedule file to check."), 400
        entry = {
            "schedule_bytes": file.read(),
            "filename": file.filename,
            "weekly_bytes": (
                (request.files["weekly_plans"].read() or None)
                if request.files.get("weekly_plans")
                else None
            ),
            "constraints_bytes": (
                (request.files["constraints"].read() or None)
                if request.files.get("constraints")
                else None
            ),
            "settings": {
                k: request.form.get(k) for k in ("trade_field", "location_field", "lookahead_weeks")
            },
            "use_ai": request.form.get("use_ai") == "on",
        }
        if request.form.get("data_date"):
            try:
                entry["data_date"] = datetime.fromisoformat(request.form["data_date"])
            except ValueError:
                return upload_page("The data date must look like 2026-03-02."), 400
        try:
            _run(entry)
        except (ScheduleParseError, ValueError) as exc:
            return upload_page(str(exc)), 400
        return redirect(f"/report/{reports.put(entry)}", code=303)

    @app.get("/sample")
    def sample():
        entry = {
            "schedule_bytes": (SAMPLES / "harbourside-health-centre.xer").read_bytes(),
            "filename": "harbourside-health-centre.xer",
            "weekly_bytes": (SAMPLES / "weekly-work-plans.csv").read_bytes(),
            "constraints_bytes": (SAMPLES / "constraint-log.csv").read_bytes(),
            "settings": {},
            "use_ai": False,
        }
        _run(entry)
        return redirect(f"/report/{reports.put(entry)}", code=303)

    @app.get("/report/<rid>")
    def report(rid: str):
        entry = entry_or_404(rid)
        return render_report(entry["result"], entry["ai"], mode="web", report_id=rid)

    @app.post("/report/<rid>/rerun")
    def rerun(rid: str):
        entry = entry_or_404(rid)
        entry["settings"] = {
            k: request.form.get(k) for k in ("trade_field", "location_field", "lookahead_weeks")
        }
        try:
            _run(entry)
        except (ScheduleParseError, ValueError) as exc:
            abort(400, str(exc))
        return redirect(f"/report/{rid}", code=303)

    @app.get("/report/<rid>/json")
    def report_json(rid: str):
        entry = entry_or_404(rid)
        body = json.dumps(entry["result"] | {"ai": entry["ai"]}, indent=2, default=str)
        name = Path(entry["filename"]).stem
        return Response(
            body,
            mimetype="application/json",
            headers={"Content-Disposition": f'attachment; filename="{name}-results.json"'},
        )

    @app.get("/report/<rid>/download")
    def report_download(rid: str):
        entry = entry_or_404(rid)
        name = Path(entry["filename"]).stem
        return Response(
            render_report(entry["result"], entry["ai"]),
            mimetype="text/html",
            headers={"Content-Disposition": f'attachment; filename="{name}-report.html"'},
        )

    @app.post("/api/report/<rid>/ask")
    def ask(rid: str):
        entry = entry_or_404(rid)
        payload = request.get_json(silent=True) or {}
        question = str(payload.get("question", "")).strip()
        if not question:
            return jsonify({"error": "Type a question first."}), 400
        answer = answer_question(entry["result"], question, entry["schedule"])
        return jsonify(
            {
                "html": md_to_html(answer["text"]),
                "source": answer["source"],
                "model": answer.get("model"),
            }
        )

    @app.errorhandler(413)
    def too_large(_exc):
        return upload_page(f"The upload is larger than {MAX_UPLOAD // (1024 * 1024)} MB."), 413

    return app
