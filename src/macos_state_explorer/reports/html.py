from __future__ import annotations
import html
import json
from pathlib import Path
from macos_state_explorer.core.model import Snapshot
from macos_state_explorer.core.util import write_json
from macos_state_explorer.evidence.engine import extract_evidence
from macos_state_explorer.remediation.rules import build_remediation_plan
from macos_state_explorer.reports.launchservices_html import write_launchservices_html


def write_report(out: Path, snapshot: Snapshot) -> None:
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "snapshot.json", snapshot)
    evidence = extract_evidence(snapshot)
    remediation = build_remediation_plan(evidence)

    hyp = "".join(
        f"<li><b>{html.escape(h.title)}</b> — {h.confidence:.0%}<br>"
        f"<small>{html.escape('; '.join(h.evidence))}</small></li>"
        for h in snapshot.hypotheses
    )
    evidence_html = "".join(
        f"<li><b>{html.escape(item.title)}</b> "
        f"<small>{html.escape(item.severity)} · {item.confidence:.0%} · {html.escape(item.source)}</small><br>"
        f"{html.escape(item.summary)}</li>"
        for item in evidence.items
    )
    actions_html = "".join(
        "<li>"
        f"<b>{html.escape(action.title)}</b> "
        f"<small>Risk level: {html.escape(action.risk)} · Mode: {html.escape(action.mode)}</small><br>"
        f"{html.escape(action.description)}"
        f"{_commands_html(action.commands)}"
        "</li>"
        for action in remediation.actions
    )
    sections = []
    for o in snapshot.observations:
        preview = html.escape(json.dumps(o.payload, indent=2, sort_keys=True, default=str)[:60000])
        if o.collector == "launchservices":
            write_launchservices_html(out, o.payload)
            sections.append('<p><a href="launchservices.html">Open LaunchServices Explorer</a></p>')
        sections.append(f"<h2>{html.escape(o.collector)}</h2><pre>{preview}</pre>")

    page = f'''<!doctype html>
<html><head><meta charset="utf-8"><title>macOS State Explorer</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 2rem; }}
pre {{ background: #f5f5f5; padding: 1rem; overflow: auto; max-height: 42rem; }}
code {{ background: #eee; padding: .1rem .3rem; }}
</style></head>
<body>
<h1>macOS State Explorer</h1>
<p>Host: <code>{html.escape(snapshot.host)}</code></p>
<p>Created: <code>{snapshot.created_at}</code></p>
<h2>Hypotheses</h2>
<ul>{hyp}</ul>
<h2>Evidence</h2>
<ul>{evidence_html or '<li>No evidence items found.</li>'}</ul>
<h2>Recommended Actions</h2>
<p>{html.escape(remediation.summary)}</p>
<ul>{actions_html or '<li>No recommended actions.</li>'}</ul>
{''.join(sections)}
</body></html>'''
    (out / "index.html").write_text(page)


def _commands_html(commands: list[str]) -> str:
    if not commands:
        return ""
    items = "".join(f"<li><code>{html.escape(command)}</code></li>" for command in commands)
    return f"<ul>{items}</ul>"
