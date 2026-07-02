from __future__ import annotations

from dataclasses import dataclass
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
        "system_settings_privacy",
        ("system settings", "privacy ui"),
        "System Settings Privacy UI activity",
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


@dataclass(frozen=True)
class TraceTimeline:
    events: list[dict[str, Any]]
    summary: dict[str, Any]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "command": "trace timeline",
            "event_count": len(self.events),
            "summary": dict(self.summary),
            "events": list(self.events),
        }


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
    normalized_events = []
    base_date = _base_date(texts.values())
    for name, text in texts.items():
        for line in text.splitlines():
            signals = _signals_for_line(line)
            if signals:
                normalized_events.extend(_normalized_events_for_line(name, line, signals, base_date))
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
    normalized_events = sorted(normalized_events, key=lambda event: (event["timestamp_sort"], event["source_file"], event["process"], event["operation"]))[:1000]

    return {
        "created_at": time.time(),
        "keyword_hits": keywords,
        "signal_counts": _signal_counts(timeline_events),
        "correlation_summary": _correlation_summary(timeline_events),
        "timeline_events": timeline_events,
        "normalized_events": normalized_events,
        "trace_timeline_summary": trace_timeline_summary(build_trace_timeline({"normalized_events": normalized_events})),
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
            "normalized_events": analysis.get("normalized_events", []),
            "trace_timeline_summary": analysis.get("trace_timeline_summary", {}),
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


def build_trace_timeline(analysis: dict[str, Any] | None) -> TraceTimeline:
    analysis = analysis if isinstance(analysis, dict) else {}
    raw_events = analysis.get("normalized_events") or analysis.get("timeline_events") or []
    events = [_normalize_timeline_event(event) for event in raw_events if isinstance(event, dict)]
    events = sorted(events, key=lambda event: (event["timestamp_sort"], event["source_file"], event["process"], event["operation"]))
    return TraceTimeline(events=events, summary=trace_timeline_summary_from_events(events))


def trace_timeline_summary(timeline: TraceTimeline) -> dict[str, Any]:
    return timeline.summary


def trace_timeline_summary_from_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    processes: dict[str, int] = {}
    operations: dict[str, int] = {}
    sources: dict[str, int] = {}
    highest_resolution = "none"
    for event in events:
        if event["process"]:
            processes[event["process"]] = processes.get(event["process"], 0) + 1
        if event["operation"]:
            operations[event["operation"]] = operations.get(event["operation"], 0) + 1
        if event["source"]:
            sources[event["source"]] = sources.get(event["source"], 0) + 1
        if "." in str(event["timestamp"]):
            highest_resolution = "subsecond"
    return {
        "event_count": len(events),
        "processes": dict(sorted(processes.items())),
        "operations": dict(sorted(operations.items())),
        "sources": dict(sorted(sources.items())),
        "highest_timestamp_resolution": highest_resolution,
    }


def render_trace_timeline(timeline: TraceTimeline) -> str:
    lines = ["High-Fidelity Trace Timeline"]
    if not timeline.events:
        return "\n".join([*lines, "- no events"])
    for index, event in enumerate(timeline.events):
        if index:
            lines.append("↓")
        detail = event["operation"] or event["signal"] or "event"
        path = f" {event['file_path']}" if event.get("file_path") else ""
        pid = f" pid={event['pid']}" if event.get("pid") is not None else ""
        lines.append(f"{event['timestamp']} {event['process']}{pid} — {detail}{path}")
    return "\n".join(lines)


def _normalize_timeline_event(event: dict[str, Any]) -> dict[str, Any]:
    timestamp = str(event.get("timestamp", ""))
    timestamp_sort = str(event.get("timestamp_sort") or _timestamp_sort(timestamp, str(event.get("raw_reference") or event.get("line", "")), "9999-12-31"))
    source_file = str(event.get("source_file") or event.get("source") or "")
    return {
        "timestamp": timestamp,
        "timestamp_sort": timestamp_sort,
        "process": str(event.get("process", "")),
        "pid": event.get("pid"),
        "parent_pid": event.get("parent_pid"),
        "thread_id": event.get("thread_id"),
        "executable_path": str(event.get("executable_path", "")),
        "subsystem": str(event.get("subsystem", "")),
        "source": str(event.get("source") or _source_kind(source_file)),
        "source_file": source_file,
        "file_path": str(event.get("file_path") or _first_path(event.get("paths", [])) or ""),
        "operation": str(event.get("operation") or _operation_for_line(str(event.get("raw_reference") or event.get("line", "")))),
        "signal": str(event.get("signal", "")),
        "confidence": float(event.get("confidence", 0.5)),
        "raw_reference": str(event.get("raw_reference") or event.get("line", ""))[:1000],
    }


def _normalized_events_for_line(source_file: str, line: str, signals: list[tuple[str, str]], base_date: str) -> list[dict[str, Any]]:
    timestamp = _timestamp_for_line(line)
    process = _process_for_line(line)
    pid, thread_id = _pid_thread_for_line(line, process)
    paths = [path.rstrip(":,);") for path in PATH_RE.findall(line)]
    file_path = _first_path(paths) or ""
    operation = _operation_for_line(line)
    source = _source_kind(source_file)
    common = {
        "timestamp": timestamp,
        "timestamp_sort": _timestamp_sort(timestamp, line, base_date),
        "process": process,
        "pid": pid,
        "parent_pid": _int_match(line, r"\bppid[=:](\d+)\b"),
        "thread_id": thread_id,
        "executable_path": _executable_for_line(line),
        "subsystem": _subsystem_for_line(line),
        "source": source,
        "source_file": source_file,
        "file_path": file_path,
        "operation": operation,
        "signal": _primary_signal(signals, process, file_path, line),
        "confidence": _confidence_for_event(source, process, pid, file_path, operation),
        "raw_reference": line[:1000],
        "observed_signals": [signal for signal, _description in signals],
    }
    return [common]


def _primary_signal(signals: list[tuple[str, str]], process: str, file_path: str, line: str) -> str:
    signal_names = [signal for signal, _description in signals]
    lowered = line.lower()
    if file_path.endswith(".csstore") or ".csstore" in lowered:
        return "launchservices_csstore"
    if process == "runningboardd":
        return "runningboard"
    if process == "System Settings":
        return "system_settings_privacy" if "system_settings_privacy" in signal_names else signal_names[0]
    if process == "SecurityPrivacyExtension":
        return "securityprivacyextension"
    return signal_names[0] if signal_names else "unknown"


def _signals_for_line(line: str) -> list[tuple[str, str]]:
    lowered = line.lower()
    matches = []
    for signal, terms, description in SIGNALS:
        if signal == "system_settings_privacy":
            if all(term in lowered for term in terms):
                matches.append((signal, description))
        elif any(term in lowered for term in terms):
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


def _source_kind(source_file: str) -> str:
    if source_file == "fs_usage.txt":
        return "fs_usage"
    if source_file == "log_stream.txt":
        return "log_stream"
    if source_file == "lsof_loop.txt":
        return "lsof"
    if source_file == "process_loop.txt":
        return "process"
    if source_file == "launchctl_loop.txt":
        return "launchctl"
    return source_file.rsplit(".", 1)[0] if source_file else "unknown"


def _first_path(paths: Any) -> str | None:
    if isinstance(paths, list):
        for path in paths:
            if isinstance(path, str) and path:
                return path
    return None


def _pid_thread_for_line(line: str, process: str) -> tuple[int | None, int | None]:
    if process:
        escaped = re.escape(process)
        bracket = re.search(rf"{escaped}\[(\d+)(?::(\d+))?\]", line)
        if bracket:
            return int(bracket.group(1)), int(bracket.group(2)) if bracket.group(2) else None
        dotted = re.search(rf"{escaped}\.(\d+)\b", line)
        if dotted:
            return int(dotted.group(1)), None
    return _int_match(line, r"\bpid[=:](\d+)\b"), _int_match(line, r"\b(?:tid|thread)[=:](\d+)\b")


def _int_match(line: str, pattern: str) -> int | None:
    match = re.search(pattern, line, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _executable_for_line(line: str) -> str:
    match = re.search(r"\bexecutable=([^\s]+(?:\sSettings\.app/Contents/MacOS/System\sSettings)?)", line)
    return match.group(1).strip('"') if match else ""


def _subsystem_for_line(line: str) -> str:
    match = re.search(r"\bsubsystem[=:]([^\s]+)", line)
    return match.group(1).strip('"') if match else ""


def _operation_for_line(line: str) -> str:
    explicit = re.search(r"\boperation[=:]([A-Za-z0-9_().-]+)", line)
    if explicit:
        return _normalize_operation(explicit.group(1))
    lowered = line.lower()
    for candidate in ["open", "read", "stat64", "stat", "access", "mmap", "close", "launch", "terminate", "registration"]:
        if re.search(rf"\b{re.escape(candidate)}(?:\(\))?\b", lowered):
            return _normalize_operation(candidate)
    if "opened" in lowered or "open" in lowered:
        return "open"
    if ".csstore" in lowered:
        return "cache access"
    return "event"


def _normalize_operation(operation: str) -> str:
    operation = operation.lower().removesuffix("()")
    if operation == "stat64":
        return "stat"
    return operation


def _confidence_for_event(source: str, process: str, pid: int | None, file_path: str, operation: str) -> float:
    score = 0.45
    if source in {"fs_usage", "log_stream"}:
        score += 0.15
    if process:
        score += 0.1
    if pid is not None:
        score += 0.1
    if file_path:
        score += 0.1
    if operation and operation != "event":
        score += 0.1
    return min(score, 0.95)


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
