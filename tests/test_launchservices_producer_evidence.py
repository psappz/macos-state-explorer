from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from macos_state_explorer.cli import app
from macos_state_explorer.core.model import Observation, Snapshot
from macos_state_explorer.launchservices.models import LaunchServicesRecord, LaunchServicesStatus
from macos_state_explorer.launchservices.producer_evidence import build_launchservices_producer_evidence
from macos_state_explorer.reports.local_network import build_local_network_report, write_local_network_support_bundle


def record(
    path: str,
    *,
    bundle_id: str,
    name: str,
    version: str | None,
    path_exists: bool | None = False,
    volume: str | None = "/",
    volume_exists: bool | None = True,
    classification: LaunchServicesStatus = LaunchServicesStatus.STALE,
) -> LaunchServicesRecord:
    return LaunchServicesRecord(
        raw_block=f"path: {path}\nbundle id: {bundle_id}",
        bundle_id=bundle_id,
        identifier=bundle_id,
        canonical_id=bundle_id,
        name=name,
        display_name=name,
        version=version,
        display_version=version,
        path=path,
        path_clean=path,
        path_exists=path_exists,
        volume=volume,
        volume_exists=volume_exists,
        classification=classification,
    )


def producer_records() -> list[LaunchServicesRecord]:
    return [
        record(
            "/Applications/Google Chrome.app",
            bundle_id="com.google.Chrome",
            name="Google Chrome",
            version="149.0.7827.250",
            path_exists=True,
            classification=LaunchServicesStatus.ACTIVE,
        ),
        record(
            "/Applications/Google Chrome.app/Contents/Frameworks/Google Chrome Framework.framework/Versions/148.0.7778.216/Helpers/Google Chrome Helper.app",
            bundle_id="com.google.Chrome.helper",
            name="Google Chrome Helper",
            version="148.0.7778.216",
            path_exists=False,
        ),
        record(
            "/Volumes/Google Chrome/Google Chrome.app",
            bundle_id="com.google.Chrome",
            name="Google Chrome",
            version="149.0.7827.201",
            volume="/Volumes/Google Chrome",
            volume_exists=True,
        ),
        record(
            "/Users/patrick/.Trash/Google Chrome.app",
            bundle_id="com.google.Chrome",
            name="Google Chrome",
            version="149.0.7827.201",
            path_exists=True,
        ),
        record(
            "/Applications/GoogleUpdater.app/Contents/Helpers/GoogleUpdater Helper.app",
            bundle_id="com.google.GoogleUpdater.helper",
            name="GoogleUpdater Helper",
            version="1.0",
            path_exists=True,
        ),
    ]


def snapshot(records: list[LaunchServicesRecord] | None = None) -> Snapshot:
    records = records or producer_records()
    return Snapshot(
        host="producer-evidence-host",
        created_at=123.0,
        observations=[
            Observation(
                collector="launchservices",
                started_at=1,
                ended_at=2,
                payload={
                    "entries": [item.model_dump(mode="python") for item in records],
                    "candidate_files": {"stdout": "/System/Library/LaunchServices/com.apple.LaunchServices-3027.csstore\n"},
                },
            )
        ],
    )


def trace_analysis() -> dict[str, object]:
    return {
        "created_at": 1.0,
        "signal_counts": {
            "securityprivacyextension": 2,
            "launchservices_csstore": 3,
            "runningboard": 1,
        },
        "keyword_hits": {"System Settings": 1, "Privacy": 1, ".csstore": 3},
        "correlation_summary": [
            {"signal": "securityprivacyextension", "count": 2, "sources": ["log_stream.txt"], "description": "SecurityPrivacyExtension activity"},
            {"signal": "launchservices_csstore", "count": 3, "sources": ["fs_usage.txt"], "description": "LaunchServices cache/store access"},
            {"signal": "runningboard", "count": 1, "sources": ["log_stream.txt"], "description": "RunningBoard activity"},
        ],
        "timeline_events": [
            {"timestamp": "2026-07-02 10:00:00", "source_file": "log_stream.txt", "signal": "securityprivacyextension", "process": "SecurityPrivacyExtension", "paths": [], "line": "SecurityPrivacyExtension opened Privacy pane"},
            {"timestamp": "2026-07-02 10:00:01", "source_file": "fs_usage.txt", "signal": "launchservices_csstore", "process": "SecurityPrivacyExtension", "paths": ["/System/Library/LaunchServices/com.apple.LaunchServices-3027.csstore"], "line": "SecurityPrivacyExtension read .csstore"},
            {"timestamp": "2026-07-02 10:00:02", "source_file": "log_stream.txt", "signal": "runningboard", "process": "runningboardd", "paths": [], "line": "RunningBoard observed Chrome"},
        ],
        "candidate_paths": [
            {"path": "/System/Library/LaunchServices/com.apple.LaunchServices-3027.csstore", "count": 3, "sources": ["fs_usage.txt"], "examples": ["read csstore"], "exists": True}
        ],
    }


def write_trace(path: Path) -> Path:
    path.mkdir()
    (path / "analysis.json").write_text(json.dumps(trace_analysis()))
    return path


def evidence_by_type(payload: dict[str, object], evidence_type: str) -> list[dict[str, object]]:
    return [item for item in payload["evidence"] if item["evidence_type"] == evidence_type]


def test_producer_evidence_separates_observed_inferred_and_unknown_without_trace():
    evidence = build_launchservices_producer_evidence(snapshot())
    payload = evidence.to_json_dict()

    assert list(payload)[:7] == ["command", "evidence_id", "timestamp", "target_registration_count", "evidence_count", "trace_context", "summary"]
    assert payload["command"] == "launchservices producer-evidence"
    assert payload["trace_context"] == {"available": False, "source": None}
    assert evidence_by_type(payload, "lsregister_dump_contains_path")
    assert evidence_by_type(payload, "lsregister_dump_contains_bundle_id")
    assert evidence_by_type(payload, "registration_path_missing")
    assert evidence_by_type(payload, "registration_path_exists")
    assert evidence_by_type(payload, "mounted_volume_path")
    assert evidence_by_type(payload, "trash_path")
    assert evidence_by_type(payload, "updater_path")
    assert evidence_by_type(payload, "active_application_bundle_path")
    no_trace = evidence_by_type(payload, "security_privacy_trace_reads_csstore")
    assert no_trace and no_trace[0]["observed"] is False
    assert no_trace[0]["source"] == "trace unavailable"
    assert "no trace was provided" in no_trace[0]["reasoning"]
    assert payload["summary"]["observed_evidence_count"] > 0
    assert payload["summary"]["inferred_evidence_count"] > 0
    assert payload["summary"]["unknown_evidence_count"] > 0


def test_producer_evidence_trace_marks_securityprivacy_csstore_system_settings_and_runningboard_observed():
    evidence = build_launchservices_producer_evidence(snapshot(), trace_analysis=trace_analysis(), trace_source=Path("trace-dir"))
    payload = evidence.to_json_dict()

    assert payload["trace_context"] == {"available": True, "source": "trace-dir"}
    for evidence_type in [
        "security_privacy_trace_reads_csstore",
        "system_settings_trace_observed",
        "runningboard_trace_observed",
    ]:
        matches = evidence_by_type(payload, evidence_type)
        assert matches
        assert all(item["observed"] is True for item in matches)
        assert all(item["source"] == "trace" for item in matches)
        assert all(item["raw_reference"] for item in matches)


def test_producer_evidence_cli_json_and_human_output(monkeypatch, tmp_path):
    trace_dir = write_trace(tmp_path / "trace")
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: snapshot())

    json_result = CliRunner().invoke(app, ["launchservices", "producer-evidence", "--trace", str(trace_dir), "--json"])
    human_result = CliRunner().invoke(app, ["launchservices", "producer-evidence", "--trace", str(trace_dir)])

    assert json_result.exit_code == 0
    payload = json.loads(json_result.stdout)
    assert payload["command"] == "launchservices producer-evidence"
    assert payload["trace_context"]["available"] is True
    assert human_result.exit_code == 0
    assert "LaunchServices producer evidence" in human_result.stdout
    assert "Observed evidence" in human_result.stdout
    assert "Trace observed" in human_result.stdout
    assert "Inferred evidence" in human_result.stdout
    assert "Unknown" in human_result.stdout


def test_local_network_solution_includes_compact_producer_evidence_summary(monkeypatch, tmp_path):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: snapshot())
    trace_dir = write_trace(tmp_path / "trace")

    result = CliRunner().invoke(app, ["solve", "local-network", "--trace", str(trace_dir), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    summary = payload["launchservices_producer_evidence_summary"]
    assert summary["trace_observed"] == ["RunningBoard observed", "SecurityPrivacyExtension observed", "System Settings Privacy UI observed", ".csstore reads observed"]
    assert "lsregister dump contains Chrome helper paths" in summary["observed"]
    assert "persistence likely derived from LaunchServices cache" in summary["inferred"]
    assert "LaunchServices producer evidence" in CliRunner().invoke(app, ["solve", "local-network"]).stdout


def test_support_bundle_includes_producer_evidence_artifacts(tmp_path):
    report = build_local_network_report(snapshot(), trace_analysis=trace_analysis())
    bundle = write_local_network_support_bundle(report, tmp_path / "bundle", branch_id="manual-empty-trash-reboot")

    assert (bundle / "producer-evidence.json").exists()
    assert (bundle / "producer-evidence.txt").exists()
    payload = json.loads((bundle / "producer-evidence.json").read_text())
    assert payload["command"] == "launchservices producer-evidence"
    report_payload = json.loads((bundle / "report.json").read_text())
    assert "launchservices_producer_evidence_summary" in report_payload
    assert "LaunchServices producer evidence" in (bundle / "producer-evidence.txt").read_text()


def test_bundle_diff_includes_producer_evidence_diff(tmp_path):
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    before_report = {"command": "report local-network", "evidence": [], "launchservices_producer_evidence_summary": {"observed_evidence_ids": ["ls-prod-old"], "evidence_confidence": {"ls-prod-shared": 0.4}, "observed_status": {"ls-prod-shared": False}}}
    after_report = {"command": "report local-network", "evidence": [], "launchservices_producer_evidence_summary": {"observed_evidence_ids": ["ls-prod-new"], "evidence_confidence": {"ls-prod-shared": 0.9}, "observed_status": {"ls-prod-shared": True}}}
    (before / "report.json").write_text(json.dumps(before_report))
    (after / "report.json").write_text(json.dumps(after_report))

    result = CliRunner().invoke(app, ["diff", "bundles", str(before), str(after), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["producer_evidence_diff"] == {
        "added_evidence": ["ls-prod-new"],
        "removed_evidence": ["ls-prod-old"],
        "changed_confidence": ["ls-prod-shared"],
        "changed_observed_status": ["ls-prod-shared"],
    }


def test_producer_evidence_docs_keep_phase2_investigation_scope_public_project_only():
    docs = "\n".join(Path(path).read_text() for path in ["README.md", "ARCHITECTURE.md", "docs/LAUNCHSERVICES_OUTCOME_ENGINE.md"])

    assert "Phase 2 is investigation-driven" in docs
    assert "modeled provenance" in docs
    assert "observed producer evidence" in docs
    assert "Chrome Local Network reference case" in docs
    assert "WASP Prism" in docs
    assert "project" in docs
    assert "WASP Lens" not in docs
