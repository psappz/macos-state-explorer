from __future__ import annotations

import html
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

PREDICATE = (
    'process CONTAINS[c] "System Settings" OR '
    'process == "tccd" OR process == "lsd" OR process == "runningboardd" OR '
    'process == "dprivacyd" OR process == "webprivacyd" OR process == "transparencyd" OR '
    'eventMessage CONTAINS[c] "LocalNetwork" OR eventMessage CONTAINS[c] "Local Network" OR '
    'eventMessage CONTAINS[c] "Chrome" OR eventMessage CONTAINS[c] "Google" OR '
    'eventMessage CONTAINS[c] "Privacy"'
)
FILTER = "System Settings|tccd|lsd|runningboardd|dprivacyd|webprivacyd|transparencyd|TCC|REG|LaunchServices|Privacy|privacy|LocalNetwork|Chrome|Google|\\.db|\\.sqlite|\\.plist|\\.sql"
PATH_RE = re.compile(r"(/[^ \t\n]+(?:TCC|REG|LaunchServices|Privacy|privacy|LocalNetwork|Chrome|Google|\.db|\.sqlite|\.plist|\.sql)[^ \t\n]*)")


def _start(cmd: list[str], path: Path) -> subprocess.Popen:
    f = path.open("w")
    p = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT, text=True)
    p._mse_file = f
    return p


def _stop(p: subprocess.Popen) -> None:
    try:
        p.terminate()
        p.wait(timeout=3)
    except Exception:
        try:
            p.kill()
        except Exception:
            pass
    f = getattr(p, "_mse_file", None)
    if f:
        f.close()


def trace_local_network(out: Path, seconds: int | None = None) -> None:
    out.mkdir(parents=True, exist_ok=True)
    commands = {
        "log_stream.txt": ["log", "stream", "--style", "compact", "--predicate", PREDICATE],
        "fs_usage.txt": ["/bin/bash", "-lc", f"sudo fs_usage -w -f filesystem 2>/dev/null | grep -Ei '{FILTER}'"],
        "lsof_loop.txt": ["/bin/bash", "-lc", f"while true; do date; sudo lsof -nP 2>/dev/null | grep -Ei '{FILTER}' || true; sleep 2; done"],
        "process_loop.txt": ["/bin/bash", "-lc", f"while true; do date; ps auxww | grep -Ei '{FILTER}' | grep -v grep || true; sleep 2; done"],
        "launchctl_loop.txt": ["/bin/bash", "-lc", "while true; do date; launchctl print gui/$(id -u) 2>/dev/null | grep -Ei -A2 -B2 'tccd|privacy|webprivacy|dprivacy|transparency|lsd|runningboard|System Settings' || true; sleep 5; done"],
    }
    procs = [_start(cmd, out / name) for name, cmd in commands.items()]
    print("Trace läuft.")
    print("Öffne jetzt: Systemeinstellungen -> Datenschutz & Sicherheit -> Lokales Netzwerk.")
    print("Warte 20–30 Sekunden.")
    if seconds:
        time.sleep(seconds)
    else:
        input("Enter drücken, wenn fertig...")
    for p in procs:
        _stop(p)

    analysis = analyze_trace(out)
    (out / "analysis.json").write_text(json.dumps(analysis, indent=2, sort_keys=True, default=str))
    (out / "index.html").write_text(render_trace_html(analysis))
    print(f"Report: {out / 'index.html'}")


def analyze_trace(out: Path) -> dict[str, Any]:
    texts = {p.name: p.read_text(errors="replace") for p in out.glob("*.txt")}
    keywords = {}
    for kw in ["System Settings", "tccd", "lsd", "dprivacyd", "webprivacyd", "transparencyd", "LocalNetwork", "Chrome", "Google", "TCC", "LaunchServices", "Privacy"]:
        c = sum(t.lower().count(kw.lower()) for t in texts.values())
        if c:
            keywords[kw] = c

    paths: dict[str, dict[str, Any]] = {}
    for name, text in texts.items():
        for line in text.splitlines():
            for m in PATH_RE.findall(line):
                path = m.rstrip(":,);")
                rec = paths.setdefault(path, {"count": 0, "sources": set(), "examples": []})
                rec["count"] += 1
                rec["sources"].add(name)
                if len(rec["examples"]) < 5:
                    rec["examples"].append(line[:1000])

    path_list = []
    for path, rec in sorted(paths.items(), key=lambda kv: kv[1]["count"], reverse=True):
        path_list.append({
            "path": path,
            "count": rec["count"],
            "sources": sorted(rec["sources"]),
            "examples": rec["examples"],
            "exists": Path(path).exists() if path.startswith("/") else None,
        })
    return {"created_at": time.time(), "keyword_hits": keywords, "candidate_paths": path_list[:300]}


def render_trace_html(analysis: dict[str, Any]) -> str:
    kw = "".join(f"<li><b>{html.escape(k)}</b>: {v}</li>" for k, v in analysis.get("keyword_hits", {}).items())
    rows = []
    for p in analysis.get("candidate_paths", []):
        rows.append("<tr><td>{}</td><td>{}</td><td><code>{}</code></td><td>{}</td></tr>".format(
            p["count"], html.escape(str(p["exists"])), html.escape(p["path"]), html.escape(", ".join(p["sources"]))
        ))
    return """<!doctype html><html><head><meta charset="utf-8"><title>Local Network Trace</title>
<style>body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;margin:2rem}td,th{border:1px solid #ddd;padding:.4rem}table{border-collapse:collapse;width:100%}code{font-family:ui-monospace,Menlo,monospace}</style>
</head><body><h1>Local Network Trace</h1><h2>Keyword Hits</h2><ul>""" + kw + """</ul>
<h2>Candidate Paths</h2><table><tr><th>Count</th><th>Exists</th><th>Path</th><th>Sources</th></tr>""" + "".join(rows) + """</table></body></html>"""
