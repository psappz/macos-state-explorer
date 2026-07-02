from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from macos_state_explorer.cli import app
from macos_state_explorer.core.model import Observation, Snapshot
from macos_state_explorer.reports.local_network import build_local_network_report, write_local_network_support_bundle
from macos_state_explorer.trace_correlation import build_trace_correlation_evidence


def correlated_trace() -> dict[str, object]:
    return {
        "created_at": 1.0,
        "signal_counts": {"securityprivacyextension": 2, "launchservices_csstore": 2, "runningboard": 1},
        "correlation_summary": [
            {"signal": "securityprivacyextension", "count": 2, "sources": ["log_stream.txt"], "description": "SecurityPrivacyExtension activity"},
            {"signal": "launchservices_csstore", "count": 2, "sources": ["fs_usage.txt"], "description": "LaunchServices cache/store access"},
            {"signal": "runningboard", "count": 1, "sources": ["log_stream.txt"], "description": "RunningBoard lifecycle"},
        ],
        "timeline_events": [
            {"timestamp": "2026-07-02 10:00:00.000", "source_file": "log_stream.txt", "signal": "securityprivacyextension", "process": "SecurityPrivacyExtension", "paths": [], "line": "SecurityPrivacyExtension opened Privacy pane"},
            {"timestamp": "2026-07-02 10:00:01.000", "source_file": "fs_usage.txt", "signal": "launchservices_csstore", "process": "SecurityPrivacyExtension", "paths": ["/System/Library/LaunchServices/com.apple.LaunchServices-3027.csstore"], "line": "SecurityPrivacyExtension read .csstore"},
            {"timestamp": "2026-07-02 10:00:02.000", "source_file": "log_stream.txt", "signal": "runningboard", "process": "runningboardd", "paths": [], "line": "runningboardd observed System Settings"},
            {"timestamp": "2026-07-02 10:00:03.000", "source_file": "log_stream.txt", "signal": "system_settings_privacy", "process": "System Settings", "paths": [], "line": "System Settings Privacy UI visible"},
        ],
        "candidate_paths": [],
    }


def uncorrelated_trace() -> dict[str, object]:
    data = correlated_trace()
    data["timeline_events"] = [
        {"timestamp": "2026-07-02 10:00:00.000", "source_file": "log_stream.txt", "signal": "securityprivacyextension", "process": "SecurityPrivacyExtension", "paths": [], "line": "SecurityPrivacyExtension opened Privacy pane"},
        {"timestamp": "2026-07-02 10:05:30.000", "source_file": "fs_usage.txt", "signal": "launchservices_csstore", "process": "lsd", "paths": ["/System/Library/LaunchServices/com.apple.LaunchServices-3027.csstore"], "line": "lsd read .csstore"},
        {"timestamp": "2026-07-02 10:08:00.000", "source_file": "log_stream.txt", "signal": "runningboard", "process": "runningboardd", "paths": [], "line": "runningboardd observed System Settings"},
    ]
    return data


def write_trace(path: Path, analysis: dict[str, object]) -> Path:
    path.mkdir()
    (path / "analysis.json").write_text(json.dumps(analysis))
    return path


def snapshot() -> Snapshot:
    return Snapshot(
        host="trace-correlation-host",
        created_at=123.0,
        observations=[
            Observation(collector="tcc", started_at=1, ended_at=2, payload={"direct_localnetwork_query": {"stdout": ""}, "user_tcc": {"hits": []}}),
            Observation(
                collector="launchservices",
                started_at=1,
                ended_at=2,
                payload={
                    "entries": [
                        {"bundle_id": "com.google.Chrome", "path": "/Applications/Google Chrome.app", "classification": "STALE", "path_exists": True},
                    ],
                    "candidate_files": {"stdout": "/System/Library/LaunchServices/com.apple.LaunchServices-3027.csstore\n"},
                },
            ),
        ],
    )


def test_trace_correlation_creates_same_window_correlation():
    evidence = build_trace_correlation_evidence(correlated_trace(), trace_source=Path("trace"))
    payload = evidence.to_json_dict()

    assert list(payload)[:6] == ["command", "evidence_id", "trace_context", "correlation_count", "summary", "correlations"]
    assert payload["command"] == "trace correlate"
    assert payload["summary"]["observed_signals"] == ["launchservices_csstore", "runningboard", "securityprivacyextension", "system_settings_privacy"]
    security = next(item for item in payload["correlations"] if item["producer_process"] == "SecurityPrivacyExtension" and item["consumer_process"] == "SecurityPrivacyExtension")
    assert security["observed_signals"] == ["securityprivacyextension", "launchservices_csstore"]
    assert security["correlation_strength"] == "strong"
    assert security["confidence"] == 0.91
    assert "same process" in security["reasoning"]


def test_trace_correlation_does_not_correlate_separate_observations_without_support():
    evidence = build_trace_correlation_evidence(uncorrelated_trace(), trace_source=Path("trace"))
    payload = evidence.to_json_dict()

    assert payload["summary"]["not_correlated"]
    assert all(item["correlation_strength"] != "strong" for item in payload["correlations"])
    assert "not in same time window/process" in payload["summary"]["not_correlated"][0]


def test_trace_correlate_cli_json_and_human_output(tmp_path):
    trace_dir = write_trace(tmp_path / "trace", correlated_trace())

    json_result = CliRunner().invoke(app, ["trace", "correlate", str(trace_dir), "--json"])
    human_result = CliRunner().invoke(app, ["trace", "correlate", str(trace_dir)])

    assert json_result.exit_code == 0
    payload = json.loads(json_result.stdout)
    assert payload["command"] == "trace correlate"
    assert payload["correlations"][0]["trace_window"]["start"] == "2026-07-02 10:00:00.000"
    assert human_result.exit_code == 0
    assert "Trace Correlation Evidence" in human_result.stdout
    assert "Observed" in human_result.stdout
    assert "Correlated" in human_result.stdout
    assert "Not correlated" in human_result.stdout


def test_local_network_solution_includes_trace_correlation_summary(monkeypatch, tmp_path):
    trace_dir = write_trace(tmp_path / "trace", correlated_trace())
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: snapshot())

    result = CliRunner().invoke(app, ["solve", "local-network", "--trace", str(trace_dir), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    summary = payload["trace_correlation_summary"]
    assert "SecurityPrivacyExtension" in summary["observed"]
    assert summary["correlated"][0]["confidence"] == 0.91
    assert "Correlation summary" in CliRunner().invoke(app, ["solve", "local-network", "--trace", str(trace_dir)]).stdout


def test_support_bundle_includes_trace_correlation_artifacts(tmp_path):
    report = build_local_network_report(snapshot(), trace_analysis=correlated_trace())
    bundle = write_local_network_support_bundle(report, tmp_path / "bundle", branch_id="manual-empty-trash-reboot")

    assert (bundle / "trace-correlation.json").exists()
    assert (bundle / "trace-correlation.txt").exists()
    payload = json.loads((bundle / "trace-correlation.json").read_text())
    assert payload["summary"]["correlated"]


def test_bundle_diff_includes_trace_correlation_diff(tmp_path):
    before = write_local_network_support_bundle(build_local_network_report(snapshot(), trace_analysis=uncorrelated_trace()), tmp_path / "before", branch_id="manual-empty-trash-reboot")
    after = write_local_network_support_bundle(build_local_network_report(snapshot(), trace_analysis=correlated_trace()), tmp_path / "after", branch_id="manual-empty-trash-reboot")

    result = CliRunner().invoke(app, ["diff", "bundles", str(before), str(after), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    diff = payload["trace_correlation_diff"]
    assert diff["added_correlations"]
    assert "SecurityPrivacyExtension->SecurityPrivacyExtension" in diff["added_correlations"]


def test_trace_correlation_json_is_deterministic():
    first = json.dumps(build_trace_correlation_evidence(correlated_trace()).to_json_dict(), sort_keys=True)
    second = json.dumps(build_trace_correlation_evidence(correlated_trace()).to_json_dict(), sort_keys=True)

    assert first == second
    assert "repair" not in first.lower()
    assert "planner" not in first.lower()
