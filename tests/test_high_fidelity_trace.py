from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from macos_state_explorer.cli import app
from macos_state_explorer.core.model import Observation, Snapshot
from macos_state_explorer.reports.local_network import build_local_network_report, write_local_network_support_bundle
from macos_state_explorer.tracers.local_network import analyze_trace, build_trace_timeline


CSSTORE = "/System/Library/LaunchServices/com.apple.LaunchServices-3027.csstore"


def write_raw_trace(path: Path) -> Path:
    path.mkdir()
    (path / "log_stream.txt").write_text(
        "2026-07-02 10:15:01.221123+0200 System Settings[431:77] subsystem=com.apple.preference.security eventMessage=\"Privacy UI opened Local Network\" executable=/System/Applications/System Settings.app/Contents/MacOS/System Settings\n"
        "2026-07-02 10:15:01.226456+0200 runningboardd[99:12] subsystem=com.apple.runningboard operation=launch eventMessage=\"launch System Settings pid=431 ppid=1\"\n"
        "2026-07-02 10:15:01.245999+0200 SecurityPrivacyExtension[876:55] subsystem=com.apple.preference.security operation=access eventMessage=\"LocalNetwork view\" executable=/System/Library/ExtensionKit/Extensions/SecurityPrivacyExtension.appex/Contents/MacOS/SecurityPrivacyExtension\n"
    )
    (path / "fs_usage.txt").write_text(
        f"10:15:01.229789  read      SecurityPrivacyExtension.876  {CSSTORE}\n"
        f"10:15:01.231001  stat64    lsd.321  {CSSTORE}\n"
    )
    return path


def timeline_analysis() -> dict[str, object]:
    return analyze_trace(write_raw_trace(Path.cwd() / "__mse_tmp_trace_fixture__"))


def write_analysis_trace(path: Path) -> Path:
    raw = write_raw_trace(path)
    analysis = analyze_trace(raw)
    (path / "analysis.json").write_text(json.dumps(analysis))
    return path


def snapshot() -> Snapshot:
    return Snapshot(
        host="high-fidelity-host",
        created_at=123.0,
        observations=[
            Observation(collector="tcc", started_at=1, ended_at=2, payload={"direct_localnetwork_query": {"stdout": ""}, "user_tcc": {"hits": []}}),
            Observation(
                collector="launchservices",
                started_at=1,
                ended_at=2,
                payload={
                    "entries": [{"bundle_id": "com.google.Chrome", "path": "/Applications/Google Chrome.app", "classification": "STALE", "path_exists": True}],
                    "candidate_files": {"stdout": f"{CSSTORE}\n"},
                },
            ),
        ],
    )


def test_analyze_trace_emits_high_fidelity_normalized_events(tmp_path):
    trace_dir = write_raw_trace(tmp_path / "trace")

    analysis = analyze_trace(trace_dir)

    events = analysis["normalized_events"]
    assert [event["operation"] for event in events[:3]] == ["open", "launch", "read"]
    read_event = next(event for event in events if event["operation"] == "read")
    assert list(read_event)[:15] == [
        "timestamp",
        "timestamp_sort",
        "process",
        "pid",
        "parent_pid",
        "thread_id",
        "executable_path",
        "subsystem",
        "source",
        "source_file",
        "file_path",
        "operation",
        "signal",
        "confidence",
        "raw_reference",
    ]
    assert read_event["timestamp"] == "10:15:01.229789"
    assert read_event["process"] == "SecurityPrivacyExtension"
    assert read_event["pid"] == 876
    assert read_event["file_path"] == CSSTORE
    assert read_event["source"] == "fs_usage"
    assert read_event["confidence"] >= 0.8


def test_trace_timeline_cli_json_and_human_output(tmp_path):
    trace_dir = write_analysis_trace(tmp_path / "trace")

    json_result = CliRunner().invoke(app, ["trace", "timeline", str(trace_dir), "--json"])
    human_result = CliRunner().invoke(app, ["trace", "timeline", str(trace_dir)])

    assert json_result.exit_code == 0
    payload = json.loads(json_result.stdout)
    assert payload["command"] == "trace timeline"
    assert payload["event_count"] == 5
    assert payload["events"][0]["process"] == "System Settings"
    assert payload["events"][2]["operation"] == "read"
    assert human_result.exit_code == 0
    assert "High-Fidelity Trace Timeline" in human_result.stdout
    assert "System Settings" in human_result.stdout
    assert "↓" in human_result.stdout


def test_local_network_solution_and_report_include_trace_timeline_summary(monkeypatch, tmp_path):
    trace_dir = write_analysis_trace(tmp_path / "trace")
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: snapshot())

    solution_result = CliRunner().invoke(app, ["solve", "local-network", "--trace", str(trace_dir), "--json"])
    report_result = CliRunner().invoke(app, ["report", "local-network", "--trace", str(trace_dir), "--json"])

    assert solution_result.exit_code == 0
    solution = json.loads(solution_result.stdout)
    assert solution["trace_timeline_summary"]["event_count"] == 5
    assert solution["trace_timeline_summary"]["operations"]["read"] == 1
    assert report_result.exit_code == 0
    report = json.loads(report_result.stdout)
    assert report["trace_timeline_summary"]["processes"]["SecurityPrivacyExtension"] == 2


def test_support_bundle_includes_trace_timeline_artifacts(tmp_path):
    trace_dir = write_analysis_trace(tmp_path / "trace")
    analysis = json.loads((trace_dir / "analysis.json").read_text())
    report = build_local_network_report(snapshot(), trace_analysis=analysis)

    bundle = write_local_network_support_bundle(report, tmp_path / "bundle", branch_id="manual-empty-trash-reboot", trace_path=trace_dir)

    assert (bundle / "trace-timeline.json").exists()
    assert (bundle / "trace-timeline.txt").exists()
    payload = json.loads((bundle / "trace-timeline.json").read_text())
    assert payload["events"][2]["operation"] == "read"


def test_bundle_diff_includes_trace_timeline_diff(tmp_path):
    before_trace = write_raw_trace(tmp_path / "before-trace")
    before_analysis = analyze_trace(before_trace)
    before_analysis["normalized_events"] = before_analysis["normalized_events"][:2]
    before = write_local_network_support_bundle(build_local_network_report(snapshot(), trace_analysis=before_analysis), tmp_path / "before", branch_id="manual-empty-trash-reboot")

    after_trace = write_raw_trace(tmp_path / "after-trace")
    after_analysis = analyze_trace(after_trace)
    after = write_local_network_support_bundle(build_local_network_report(snapshot(), trace_analysis=after_analysis), tmp_path / "after", branch_id="manual-empty-trash-reboot")

    result = CliRunner().invoke(app, ["diff", "bundles", str(before), str(after), "--json"])

    assert result.exit_code == 0
    diff = json.loads(result.stdout)["trace_timeline_diff"]
    assert diff["added_events"] >= 3
    assert "trace_timeline_summary" in json.loads(result.stdout)["changed_fields"]


def test_trace_timeline_json_is_deterministic(tmp_path):
    trace_dir = write_analysis_trace(tmp_path / "trace")

    first = json.dumps(build_trace_timeline(json.loads((trace_dir / "analysis.json").read_text())).to_json_dict(), sort_keys=True)
    second = json.dumps(build_trace_timeline(json.loads((trace_dir / "analysis.json").read_text())).to_json_dict(), sort_keys=True)

    assert first == second
    assert "repair" not in first.lower()
    assert "planner" not in first.lower()
