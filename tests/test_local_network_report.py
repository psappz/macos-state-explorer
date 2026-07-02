from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from macos_state_explorer.cli import app
from macos_state_explorer.core.model import Observation, Snapshot
from macos_state_explorer.launchservices.generations import analyze_generations
from macos_state_explorer.launchservices.models import LaunchServicesRecord, LaunchServicesStatus
from macos_state_explorer.launchservices.remediation_plan import plan_launchservices_remediation
from macos_state_explorer.reports.local_network import build_local_network_report, write_local_network_support_bundle

REPORT_REQUIRED_KEYS = [
    "command",
    "system_context",
    "trace",
    "diagnosis",
    "evidence",
    "matched_rules",
    "repair_candidates",
    "verification",
    "next_actions",
]


def _snapshot() -> Snapshot:
    return Snapshot(
        host="support-host",
        created_at=123.0,
        observations=[
            Observation(
                collector="tcc",
                started_at=1,
                ended_at=2,
                payload={"direct_localnetwork_query": {"stdout": ""}, "user_tcc": {"hits": []}},
            ),
            Observation(
                collector="launchservices",
                started_at=1,
                ended_at=2,
                payload={
                    "stale_entries": [
                        {"bundle_id": "com.google.Chrome", "path": "/Applications/Google Chrome.app"},
                        {"bundle_id": "com.google.Chrome.code_sign_clone", "path": "/Applications/Google Chrome.app"},
                    ],
                    "entries": [
                        {
                            "bundle_id": "com.google.Chrome",
                            "path": "/Applications/Google Chrome.app",
                            "classification": "STALE",
                        }
                    ],
                    "candidate_files": {"stdout": "/System/Library/LaunchServices/com.apple.LaunchServices.csstore\n"},
                },
            ),
        ],
    )


def _trace_analysis() -> dict[str, object]:
    return {
        "created_at": 1.0,
        "keyword_hits": {"Chrome": 2},
        "signal_counts": {"chrome_code_sign_clone": 1},
        "correlation_summary": [
            {
                "signal": "chrome_code_sign_clone",
                "count": 1,
                "sources": ["log_stream.txt"],
                "description": "Chrome code-sign clone identity observed",
            }
        ],
        "timeline_events": [
            {
                "timestamp": "2026-07-01 12:00:00",
                "source_file": "log_stream.txt",
                "signal": "chrome_code_sign_clone",
                "description": "Chrome code-sign clone identity observed",
                "process": "lsd",
                "paths": [],
                "line": "lsd com.google.Chrome.code_sign_clone",
            }
        ],
        "candidate_paths": [],
    }


def _ls_record(
    path: str,
    *,
    bundle_id: str,
    name: str,
    version: str | None,
    path_exists: bool | None = False,
    classification: LaunchServicesStatus = LaunchServicesStatus.STALE,
) -> LaunchServicesRecord:
    return LaunchServicesRecord(
        raw_block=f"path: {path}",
        bundle_id=bundle_id,
        name=name,
        display_name=name,
        version=version,
        display_version=version,
        path=path,
        path_clean=path,
        path_exists=path_exists,
        volume="/",
        volume_exists=True,
        classification=classification,
    )


def _audit_context_snapshot() -> Snapshot:
    records = [
        _ls_record(
            "/Applications/Google Chrome.app",
            bundle_id="com.google.Chrome",
            name="Google Chrome",
            version="149.0.7827.250",
            path_exists=True,
            classification=LaunchServicesStatus.ACTIVE,
        ),
        _ls_record(
            "/Applications/Google Chrome.app/Contents/Frameworks/Google Chrome Framework.framework/Versions/148.0.7778.216/Helpers/Google Chrome Helper.app",
            bundle_id="com.google.Chrome.helper",
            name="Google Chrome Helper",
            version="148.0.7778.216",
        ),
    ]
    return Snapshot(
        host="audit-context-host",
        created_at=123.0,
        observations=[Observation(collector="launchservices", started_at=1, ended_at=2, payload={"entries": [record.model_dump(mode="python") for record in records]})],
    )


def _write_audit(path: Path, *, status: str, generation_id: str, diff_key: str) -> Path:
    event = {
        "event": "launchservices_execute_plan_run",
        "command": "launchservices execute-plan",
        "confirmed": True,
        "status": status,
        "final_verdict": status,
        "generation_diff": {"removed": [], "added": [], "persisted": [], "regenerated": [], "still_present": []},
        "executed_step_count": 1,
        "skipped_step_count": 0,
        "errors": [],
    }
    event["generation_diff"][diff_key] = [generation_id]
    path.write_text(json.dumps(event) + "\n")
    return path


def _safe_generation_id(snapshot: Snapshot) -> str:
    payload = next(observation.payload for observation in snapshot.observations if observation.collector == "launchservices")
    analysis = analyze_generations([LaunchServicesRecord.model_validate(item) for item in payload["entries"]])
    return next(step.generation_id for step in plan_launchservices_remediation(analysis).steps if step.safety.value == "PLAN_ONLY_SAFE")


def test_report_model_json_contract_and_deterministic_ordering():
    report = build_local_network_report(
        _snapshot(),
        trace_analysis=_trace_analysis(),
        branch_id="manual-empty-trash-reboot",
    )

    payload = report.to_json_dict()

    _assert_required_key_prefix(payload, REPORT_REQUIRED_KEYS)
    assert payload["command"] == "report local-network"
    assert list(payload["system_context"]) == [
        "host",
        "snapshot_schema_version",
        "snapshot_created_at",
        "observation_collectors",
        "observation_count",
    ]
    assert payload["system_context"]["observation_collectors"] == ["launchservices", "tcc"]
    assert [item["id"] for item in payload["evidence"]] == [
        "LN-E001",
        "LN-E002",
        "LN-E003",
        "LN-E004",
        "LN-E005",
        "LN-E006",
        "LN-E007",
        "LN-E008",
        "LN-E009",
    ]
    assert payload["matched_rules"][0]["id"] == "ln-rule-chrome-identity-reinstall"
    assert [candidate["id"] for candidate in payload["repair_candidates"]] == ["manual-reinstall-chrome", "trace-local-network"]
    assert list(payload["verification"]) == [
        "status",
        "branch_id",
        "transition",
        "expected_change",
        "observed_result",
        "current_diagnosis",
        "evidence_ids",
        "continues_workflow",
        "next_repair_candidate",
        "next_action",
        "retry_guidance",
        "fallback_guidance",
    ]
    assert payload["verification"]["transition"] == "fallback-to-current-plan"
    assert [action["type"] for action in payload["next_actions"]] == ["repair", "verify", "trace"]


def test_report_json_contract_allows_backwards_compatible_additions_after_required_keys():
    payload = build_local_network_report(_snapshot(), branch_id="manual-empty-trash-reboot").to_json_dict()
    payload["future_optional_field"] = {"safe": True}

    _assert_required_key_prefix(payload, REPORT_REQUIRED_KEYS)


def test_report_human_output_contains_support_ready_sections(monkeypatch):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: _snapshot())
    monkeypatch.setattr("macos_state_explorer.cli.load_trace_analysis", lambda trace: _trace_analysis())
    runner = CliRunner()

    result = runner.invoke(app, ["report", "local-network", "--branch", "manual-empty-trash-reboot"])

    assert result.exit_code == 0
    assert result.stdout.startswith("Local Network diagnostic report")
    for heading in (
        "System context",
        "Trace summary",
        "Diagnosis",
        "Evidence",
        "Matched rules",
        "Repair ranking",
        "Verification state",
        "Next actions",
    ):
        assert heading in result.stdout
    assert "support-host" in result.stdout
    assert "LN-E006" in result.stdout
    assert "ln-rule-chrome-identity-reinstall" in result.stdout
    assert "manual-reinstall-chrome" in result.stdout
    assert "Verification: FAILED" in result.stdout
    assert "Audit context: unavailable" in result.stdout


def test_report_cli_json_output_is_parseable_and_uses_contract(monkeypatch):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: _snapshot())
    monkeypatch.setattr("macos_state_explorer.cli.load_trace_analysis", lambda trace: _trace_analysis())
    runner = CliRunner()

    result = runner.invoke(app, ["report", "local-network", "--branch", "manual-empty-trash-reboot", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    _assert_required_key_prefix(payload, REPORT_REQUIRED_KEYS)
    assert payload["trace"]["signals"][0]["signal"] == "chrome_code_sign_clone"
    assert payload["verification"]["status"] == "FAILED"


def test_report_bundle_writes_deterministic_support_directory(monkeypatch, tmp_path):
    trace_dir = _write_trace_fixture(tmp_path / "trace")
    bundle_dir = tmp_path / "support-bundle"
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: _snapshot())
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "report",
            "local-network",
            "--branch",
            "manual-empty-trash-reboot",
            "--trace",
            str(trace_dir),
            "--bundle",
            str(bundle_dir),
        ],
    )

    assert result.exit_code == 0
    assert result.stdout.startswith("Local Network diagnostic report")
    assert _relative_files(bundle_dir) == [
        "cleanup-checklist.json",
        "cleanup-checklist.txt",
        "cleanup-verification.json",
        "cleanup-verification.txt",
        "command.json",
        "environment.json",
        "launchservices-analysis.json",
        "networkextension-correlation.json",
        "networkextension-correlation.txt",
        "networkextension-raw-references.json",
        "networkextension-raw-references.txt",
        "networkextension-state.json",
        "networkextension-state.txt",
        "outcome.json",
        "outcome.txt",
        "producer-evidence.json",
        "producer-evidence.txt",
        "provenance.json",
        "provenance.txt",
        "regeneration.json",
        "regeneration.txt",
        "report.json",
        "report.txt",
        "trace-correlation.json",
        "trace-correlation.txt",
        "trace-timeline.json",
        "trace-timeline.txt",
        "trace/analysis.json",
        "trace/log_stream.txt",
    ]
    report_json = json.loads((bundle_dir / "report.json").read_text())
    assert report_json["command"] == "report local-network"
    assert report_json["trace"]["available"] is True
    assert (bundle_dir / "report.txt").read_text().startswith("Local Network diagnostic report")
    command_json = json.loads((bundle_dir / "command.json").read_text())
    assert list(command_json) == ["command", "branch", "trace", "launchservices_audit_log", "bundle_schema_version"]
    assert command_json["branch"] == "manual-empty-trash-reboot"
    environment_json = json.loads((bundle_dir / "environment.json").read_text())
    assert list(environment_json) == ["python_version", "platform", "system", "machine"]


def test_report_local_network_accepts_multiple_audit_logs_and_marks_audit_context(monkeypatch, tmp_path):
    snap = _audit_context_snapshot()
    safe_id = _safe_generation_id(snap)
    first = _write_audit(tmp_path / "ls-selective-exec.jsonl", status="MUTATED_AND_REMOVED", generation_id=safe_id, diff_key="removed")
    second = _write_audit(tmp_path / "ls-persistent-validation.jsonl", status="UNKNOWN", generation_id=safe_id, diff_key="still_present")
    bundle_dir = tmp_path / "audit-bundle"
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: snap)
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "report",
            "local-network",
            "--audit-log",
            str(first),
            "--audit-log",
            str(second),
            "--bundle",
            str(bundle_dir),
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    _assert_required_key_prefix(payload, REPORT_REQUIRED_KEYS)
    assert payload["audit_context"] == {"available": True, "source_count": 2}
    assert payload["launchservices_outcome_summary"]["automatic_remediation_status"] == "UNKNOWN"
    assert payload["launchservices_outcome_summary"]["audit_informed"] is True
    assert "Audit context: available" in (bundle_dir / "report.txt").read_text()
    command_json = json.loads((bundle_dir / "command.json").read_text())
    assert command_json["launchservices_audit_log"] == {"provided": True, "count": 2, "paths": [str(first), str(second)], "kinds": ["file", "file"]}


def test_report_bundle_outcome_json_is_audit_informed_for_attempted_but_present_again(monkeypatch, tmp_path):
    snap = _audit_context_snapshot()
    safe_id = _safe_generation_id(snap)
    audit = _write_audit(tmp_path / "removed-but-present-again.jsonl", status="MUTATED_AND_REMOVED", generation_id=safe_id, diff_key="removed")
    bundle_dir = tmp_path / "audit-bundle"
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: snap)

    result = CliRunner().invoke(app, ["report", "local-network", "--audit-log", str(audit), "--bundle", str(bundle_dir), "--json"])

    assert result.exit_code == 0
    report_payload = json.loads((bundle_dir / "report.json").read_text())
    outcome_payload = json.loads((bundle_dir / "outcome.json").read_text())
    plan_safe = [item for item in outcome_payload["remaining_generations"] if item["generation_id"] == safe_id][0]
    assert report_payload["audit_context"] == {"available": True, "source_count": 1}
    assert report_payload["launchservices_outcome_summary"]["automatic_remediation_status"] == "UNKNOWN"
    assert outcome_payload["automatic_remediation_status"] == "UNKNOWN"
    assert outcome_payload["audit_history"]["source_count"] == 1
    assert plan_safe["history_state"] == "attempted_but_present_again"
    assert "UNKNOWN" in (bundle_dir / "outcome.txt").read_text()


def test_bundle_diff_shows_stable_unknown_when_both_bundles_use_same_audit_context(monkeypatch, tmp_path):
    snap = _audit_context_snapshot()
    safe_id = _safe_generation_id(snap)
    audit = _write_audit(tmp_path / "removed-but-present-again.jsonl", status="MUTATED_AND_REMOVED", generation_id=safe_id, diff_key="removed")
    before = tmp_path / "before"
    after = tmp_path / "after"
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: snap)
    runner = CliRunner()

    before_result = runner.invoke(app, ["report", "local-network", "--audit-log", str(audit), "--bundle", str(before), "--json"])
    after_result = runner.invoke(app, ["report", "local-network", "--audit-log", str(audit), "--bundle", str(after), "--json"])
    diff_result = runner.invoke(app, ["diff", "bundles", str(before), str(after), "--json"])

    assert before_result.exit_code == 0
    assert after_result.exit_code == 0
    assert diff_result.exit_code == 0
    diff_payload = json.loads(diff_result.stdout)
    assert diff_payload["outcome_diff"]["status_before"] == "UNKNOWN"
    assert diff_payload["outcome_diff"]["status_after"] == "UNKNOWN"
    assert diff_payload["outcome_diff"]["audit_informed_before"] is True
    assert diff_payload["outcome_diff"]["audit_informed_after"] is True


def test_support_bundle_uses_supplied_audit_log_even_when_report_was_built_without_it(tmp_path):
    snap = _audit_context_snapshot()
    safe_id = _safe_generation_id(snap)
    audit = _write_audit(tmp_path / "removed-but-present-again.jsonl", status="MUTATED_AND_REMOVED", generation_id=safe_id, diff_key="removed")
    report = build_local_network_report(snap)

    bundle = write_local_network_support_bundle(
        report,
        tmp_path / "bundle",
        branch_id="manual-empty-trash-reboot",
        launchservices_audit_log=audit,
    )

    report_payload = json.loads((bundle / "report.json").read_text())
    outcome_payload = json.loads((bundle / "outcome.json").read_text())
    assert report_payload["audit_context"] == {"available": True, "source_count": 1}
    assert report_payload["launchservices_outcome_summary"]["automatic_remediation_status"] == "UNKNOWN"
    assert outcome_payload["automatic_remediation_status"] == "UNKNOWN"


def test_report_bundle_without_trace_records_no_trace_artifacts(monkeypatch, tmp_path):
    bundle_dir = tmp_path / "support-bundle"
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: _snapshot())
    runner = CliRunner()

    result = runner.invoke(app, ["report", "local-network", "--bundle", str(bundle_dir)])

    assert result.exit_code == 0
    assert _relative_files(bundle_dir) == [
        "cleanup-checklist.json",
        "cleanup-checklist.txt",
        "cleanup-verification.json",
        "cleanup-verification.txt",
        "command.json",
        "environment.json",
        "launchservices-analysis.json",
        "networkextension-correlation.json",
        "networkextension-correlation.txt",
        "networkextension-raw-references.json",
        "networkextension-raw-references.txt",
        "networkextension-state.json",
        "networkextension-state.txt",
        "outcome.json",
        "outcome.txt",
        "producer-evidence.json",
        "producer-evidence.txt",
        "provenance.json",
        "provenance.txt",
        "regeneration.json",
        "regeneration.txt",
        "report.json",
        "report.txt",
        "trace-correlation.json",
        "trace-correlation.txt",
        "trace-timeline.json",
        "trace-timeline.txt",
    ]
    report_json = json.loads((bundle_dir / "report.json").read_text())
    assert report_json["trace"]["available"] is False


def test_report_bundle_rejects_file_path_without_writing(monkeypatch, tmp_path):
    bundle_path = tmp_path / "bundle-file"
    bundle_path.write_text("not a directory")
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: _snapshot())
    runner = CliRunner()

    result = runner.invoke(app, ["report", "local-network", "--bundle", str(bundle_path)])

    assert result.exit_code != 0
    assert "Bundle path exists and is not a directory" in result.stdout
    assert bundle_path.read_text() == "not a directory"


def _assert_required_key_prefix(payload: dict[str, object], required_keys: list[str]) -> None:
    assert list(payload)[: len(required_keys)] == required_keys


def _write_trace_fixture(trace_dir: Path) -> Path:
    trace_dir.mkdir()
    (trace_dir / "analysis.json").write_text(json.dumps(_trace_analysis()))
    (trace_dir / "log_stream.txt").write_text("lsd com.google.Chrome.code_sign_clone\n")
    return trace_dir


def _relative_files(root: Path) -> list[str]:
    return sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file())
