import json

import pytest
from conftest import make_schedule, task
from lean_sic.analysis import analyze
from lean_sic.cli import main
from lean_sic.parsers import load_schedule
from lean_sic.report import md_to_html, render_report


def test_report_renders_every_section(samples):
    schedule = load_schedule(samples / "harbourside-health-centre.xer")
    result = analyze(
        schedule,
        weekly_plans=samples / "weekly-work-plans.csv",
        constraints=samples / "constraint-log.csv",
    )
    html = render_report(result)
    for anchor in (
        "overview",
        "integrity",
        "lean",
        "flow",
        "lps",
        "waste",
        "assistant",
        "assumptions",
    ):
        assert f'id="{anchor}"' in html
    assert html.count('class="check"') == len(result["checks"])
    assert "<title>Harbourside Health Centre schedule check</title>" in html
    assert "fonts.googleapis.com" not in render_report(result, web_fonts=False)


def test_report_escapes_schedule_text():
    evil = task("X1", 3)
    evil.name = '<script>alert("x")</script>'
    html = render_report(analyze(make_schedule([evil], [])))
    assert '<script>alert("x")</script>' not in html
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in html


def test_markdown_subset_is_safe():
    out = md_to_html("## Plan\n- **Fix** `DCMA-01` <b>now</b>\n1. second")
    assert (
        out
        == "<h3>Plan</h3><ul><li><strong>Fix</strong> <code>DCMA-01</code> &lt;b&gt;now&lt;/b&gt;</li></ul><ol><li>second</li></ol>"
    )


def test_cli_analyze_writes_report_and_json(samples, tmp_path, capsys):
    out, js = tmp_path / "r.html", tmp_path / "r.json"
    code = main(
        [
            "analyze",
            str(samples / "harbourside-health-centre.csv"),
            "-o",
            str(out),
            "--json",
            str(js),
            "--quiet",
        ]
    )
    assert code == 0 and out.read_text(encoding="utf-8").startswith("<!doctype html>")
    assert json.loads(js.read_text(encoding="utf-8"))["project"]["source_format"] == "CSV"
    assert (
        main(
            [
                "analyze",
                str(samples / "harbourside-health-centre.csv"),
                "-o",
                str(out),
                "--quiet",
                "--fail-under",
                "99",
            ]
        )
        == 1
    )


def test_cli_settings_and_fields(samples, tmp_path, capsys):
    out = tmp_path / "r.html"
    main(
        [
            "analyze",
            str(samples / "harbourside-health-centre.xer"),
            "-o",
            str(out),
            "--set",
            "lookahead_weeks=3",
            "--trade-field",
            "resource",
        ]
    )
    printed = capsys.readouterr().out
    assert "Schedule integrity" in printed and "LEAN-01" in printed
    assert main(["fields", str(samples / "harbourside-health-centre.xer")]) == 0
    assert "Trade" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(
            [
                "analyze",
                str(samples / "harbourside-health-centre.xer"),
                "--set",
                "no_such_setting=1",
            ]
        )


def test_web_app_flow(samples, monkeypatch):
    pytest.importorskip("flask")
    from lean_sic.web import create_app

    for var in ("OPENAI_API_KEY", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("lean_sic.ai.get_client", lambda: None)
    monkeypatch.setattr("lean_sic.web.get_client", lambda: None)
    client = create_app().test_client()
    assert b"Check a construction schedule" in client.get("/").data
    with (samples / "harbourside-health-centre.xer").open("rb") as fh:
        resp = client.post(
            "/analyze", data={"schedule": (fh, "plan.xer")}, content_type="multipart/form-data"
        )
    assert resp.status_code == 303
    report_url = resp.headers["Location"]
    page = client.get(report_url)
    assert page.status_code == 200 and b'id="ask-form"' in page.data
    rid = report_url.rsplit("/", 1)[-1]
    answer = client.post(
        f"/api/report/{rid}/ask", json={"question": "What drives handover?"}
    ).get_json()
    assert answer["source"] == "offline" and "not configured" in answer["html"]
    assert client.get(f"/report/{rid}/json").status_code == 200
    assert client.post("/analyze", data={}, content_type="multipart/form-data").status_code == 400
    assert client.get("/report/unknown").status_code == 404
