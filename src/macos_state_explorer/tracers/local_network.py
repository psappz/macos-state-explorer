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
FILTER = (
    "System Settings|SecurityPrivacyExtension|tccd|TCC|lsd|LaunchServices|csstore|runningboardd|"
    "dprivacyd|webprivacyd|transparencyd|REG|Privacy|privacy|LocalNetwork|Chrome|Google|"
    "code_sign_clone|\\.db|\\.sqlite|\\.plist|\\.sql|\\.csstore"
)
PATH_RE = re.compile(
    r"(/[^ \t\n]+(?:TCC|REG|LaunchServices|Privacy|privacy|LocalNetwork|Chrome|Google|"
    r"SecurityPrivacyExtension|code_sign_clone|\.db|\.sqlite|\.plist|\.sql|\.csstore)[^ \t\n]*)"
)
TIMESTAMP_RE = re.compile(
    r"(?P<stamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{4})?|"
    r"\d{2}:\d{2}:\d{2}(?:\.\d+)?)"
)

SIGNALS = [
    (
        "securityprivacyextension",
        ("securityprivacyextension",),
        "SecurityPrivacyExtension activity while Local Network UI is open",
    ),
    (
        "launchservices_csstore",
        (".csstore", "launchservices"),
        "LaunchServices cache/store access",
    ),
    (
        "tcc_localnetwork",
        ("tcc", "ktccservicelocalnetwork"),
        "TCC Local Network authorization activity",
    ),
    (
        "chrome_code_sign_clone",
        ("com.google.chrome.code_sign_clone", "code_sign_clone"),
        "Chrome code-sign clone identity observed",
    ),
    (
        "runningboard",
        ("runningboardd", "runningboard"),
        "RunningBoard process/app lifecycle activity",
    ),
]


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


def trace_local_network(out: Path, seconds: int | None = None) -> dict[str, Any]:
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
    return analysis


def analyze_trace(out: Path) -> dict[str, Any]:
    texts = {p.name: p.read_text(errors="replace") for p in out.glob("*.txt")}
    keywords = {}
    for kw in [
        "System Settings",
        "SecurityPrivacyExtension",
        "tccd",
        "lsd",
        "runningboardd",
        "dprivacyd",
        "webprivacyd",
        "transparencyd",
        "LocalNetwork",
        "Chrome",
        "Google",
        "TCC",
        "LaunchServices",
        ".csstore",
        "code_sign_clone",
        "Privacy",
    ]:
        count = sum(text.lower().count(kw.lower()) for text in texts.values())
        if count:
            keywords[kw] = count

    paths: dict[str, dict[str, Any]] = {}
    timeline_events = []
    base_date = _base_date(texts.values())
    for name, text in texts.items():
        for line in text.splitlines():
            signals = _signals_for_line(line)
            if signals:
                timeline_events.extend(_timeline_events_for_line(name, line, signals, base_date))
            for match in PATH_RE.findall(line):
                path = match.rstrip(":,);")
                rec = paths.setdefault(path, {"count": 0, "sources": set(), "examples": []})
                rec["count"] += 1
                rec["sources"].add(name)
                if len(rec["examples"]) < 5:
                    rec["examples"].append(line[:1000])

    path_list = []
    for path, rec in sorted(paths.items(), key=lambda kv: kv[1]["count"], reverse=True):
        path_list.append(
            {
                "path": path,
                "count": rec["count"],
                "sources": sorted(rec["sources"]),
                "examples": rec["examples"],
                "exists": Path(path).exists() if path.startswith("/") else None,
            }
        )

    timeline_events = sorted(timeline_events, key=lambda event: (event["timestamp_sort"], event["source_file"]))[:500]
    for event in timeline_events:
        event.pop("timestamp_sort", None)

    return {
        "created_at": time.time(),
        "keyword_hits": keywords,
        "signal_counts": _signal_counts(timeline_events),
        "correlation_summary": _correlation_summary(timeline_events),
        "timeline_events": timeline_events,
        "candidate_paths": path_list[:300],
    }


def trace_json_payload(out: Path, analysis: dict[str, Any]) -> dict[str, Any]:
    return {
        "command": "trace local-network",
        "out": str(out),
        "analysis": {
            "created_at": analysis.get("created_at"),
            "keyword_hits": analysis.get("keyword_hits", {}),
            "signal_counts": analysis.get("signal_counts", {}),
            "correlation_summary": analysis.get("correlation_summary", []),
            "timeline_events": analysis.get("timeline_events", []),
        },
        "signals": analysis.get("correlation_summary", []),
        "candidate_paths": analysis.get("candidate_paths", []),
        "next_action": {
            "type": "inspect-solve",
            "command": f"mse solve local-network --trace {out}",
        },
    }


def render_trace_html(analysis: dict[str, Any]) -> str:
    kw = "".join(f"<li><b>{html.escape(k)}</b>: {v}</li>" for k, v in analysis.get("keyword_hits", {}).items())
    signal_rows = []
    for item in analysis.get("correlation_summary", []):
        signal_rows.append(
            "<tr><td><code>{}</code></td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                html.escape(str(item["signal"])),
                html.escape(str(item["count"])),
                html.escape(", ".join(item["sources"])),
                html.escape(str(item["description"])),
            )
        )
    timeline_rows = []
    for event in analysis.get("timeline_events", []):
        timeline_rows.append(
            "<tr><td>{}</td><td>{}</td><td><code>{}</code></td><td>{}</td><td>{}</td></tr>".format(
                html.escape(str(event["timestamp"])),
                html.escape(str(event["source_file"])),
                html.escape(str(event["signal"])),
                html.escape(str(event["process"])),
                html.escape(str(event["line"])),
            )
        )
    rows = []
    for path in analysis.get("candidate_paths", []):
        rows.append(
            "<tr><td>{}</td><td>{}</td><td><code>{}</code></td><td>{}</td></tr>".format(
                path["count"],
                html.escape(str(path["exists"])),
                html.escape(path["path"]),
                html.escape(", ".join(path["sources"])),
            )
        )
    return (
        """<!doctype html><html><head><meta charset="utf-8"><title>Local Network Trace</title>
<style>body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;margin:2rem}td,th{border:1px solid #ddd;padding:.4rem;vertical-align:top}table{border-collapse:collapse;width:100%}code{font-family:ui-monospace,Menlo,monospace}</style>
</head><body><h1>Local Network Trace</h1><h2>Keyword Hits</h2><ul>"""
        + kw
        + """</ul>
<h2>Root-cause Signals</h2><table><tr><th>Signal</th><th>Count</th><th>Sources</th><th>Meaning</th></tr>"""
        + "".join(signal_rows)
        + """</table>
<h2>Correlated Timeline</h2><table><tr><th>Time</th><th>Source</th><th>Signal</th><th>Process</th><th>Line</th></tr>"""
        + "".join(timeline_rows)
        + """</table>
<h2>Candidate Paths</h2><table><tr><th>Count</th><th>Exists</th><th>Path</th><th>Sources</th></tr>"""
        + "".join(rows)
        + """</table></body></html>"""
    )


def _signals_for_line(line: str) -> list[tuple[str, str]]:
    lowered = line.lower()
    matches = []
    for signal, terms, description in SIGNALS:
        if any(term in lowered for term in terms):
            matches.append((signal, description))
    return matches


def _timeline_events_for_line(
    source_file: str,
    line: str,
    signals: list[tuple[str, str]],
    base_date: str,
) -> list[dict[str, Any]]:
    timestamp = _timestamp_for_line(line)
    process = _process_for_line(line)
    paths = [path.rstrip(":,);") for path in PATH_RE.findall(line)]
    return [
        {
            "timestamp": timestamp,
            "timestamp_sort": _timestamp_sort(timestamp, line, base_date),
            "source_file": source_file,
            "signal": signal,
            "description": description,
            "process": process,
            "paths": paths,
            "line": line[:1000],
        }
        for signal, description in signals
    ]


def _timestamp_for_line(line: str) -> str:
    match = TIMESTAMP_RE.search(line)
    return match.group("stamp") if match else ""


def _base_date(texts: Any) -> str:
    for text in texts:
        match = re.search(r"\d{4}-\d{2}-\d{2}", text)
        if match:
            return match.group(0)
    return "9999-12-31"


def _timestamp_sort(timestamp: str, line: str, base_date: str) -> str:
    if not timestamp:
        return f"9999-12-31 {line}"
    if re.match(r"\d{4}-\d{2}-\d{2}", timestamp):
        return timestamp
    return f"{base_date} {timestamp}"


def _process_for_line(line: str) -> str:
    lowered = line.lower()
    for process in [
        "System Settings",
        "SecurityPrivacyExtension",
        "runningboardd",
        "tccd",
        "lsd",
        "dprivacyd",
        "webprivacyd",
        "transparencyd",
        "Google Chrome",
        "Chrome",
    ]:
        if process.lower() in lowered:
            return process
    return ""


def _signal_counts(events: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in events:
        signal = event["signal"]
        counts[signal] = counts.get(signal, 0) + 1
    return counts


def _correlation_summary(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for event in events:
        item = summary.setdefault(
            event["signal"],
            {
                "signal": event["signal"],
                "description": event["description"],
                "count": 0,
                "sources": set(),
                "first_seen": event["timestamp"],
            },
        )
        item["count"] += 1
        item["sources"].add(event["source_file"])
    return [
        {
            "signal": item["signal"],
            "description": item["description"],
            "count": item["count"],
            "sources": sorted(item["sources"]),
            "first_seen": item["first_seen"],
        }
        for item in summary.values()
    ]
