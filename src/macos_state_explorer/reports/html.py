from __future__ import annotations
import html
import json
from pathlib import Path
from macos_state_explorer.core.model import Snapshot
from macos_state_explorer.core.util import write_json
from macos_state_explorer.reports.launchservices_html import write_launchservices_html


def write_report(out: Path, snapshot: Snapshot) -> None:
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "snapshot.json", snapshot)

    hyp = "".join(
        f"<li><b>{html.escape(h.title)}</b> — {h.confidence:.0%}<br>"
        f"<small>{html.escape('; '.join(h.evidence))}</small></li>"
        for h in snapshot.hypotheses
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
{''.join(sections)}
</body></html>'''
    (out / "index.html").write_text(page)
