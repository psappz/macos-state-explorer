from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from macos_state_explorer.cli import app
from macos_state_explorer.core.model import Observation, Snapshot
from macos_state_explorer.reports.local_network import build_local_network_report

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
        "command.json",
        "environment.json",
        "launchservices-analysis.json",
        "report.json",
        "report.txt",
        "trace/analysis.json",
        "trace/log_stream.txt",
    ]
    report_json = json.loads((bundle_dir / "report.json").read_text())
    assert report_json["command"] == "report local-network"
    assert report_json["trace"]["available"] is True
    assert (bundle_dir / "report.txt").read_text().startswith("Local Network diagnostic report")
    command_json = json.loads((bundle_dir / "command.json").read_text())
    assert list(command_json) == ["command", "branch", "trace", "bundle_schema_version"]
    assert command_json["branch"] == "manual-empty-trash-reboot"
    environment_json = json.loads((bundle_dir / "environment.json").read_text())
    assert list(environment_json) == ["python_version", "platform", "system", "machine"]


def test_report_bundle_without_trace_records_no_trace_artifacts(monkeypatch, tmp_path):
    bundle_dir = tmp_path / "support-bundle"
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: _snapshot())
    runner = CliRunner()

    result = runner.invoke(app, ["report", "local-network", "--bundle", str(bundle_dir)])

    assert result.exit_code == 0
    assert _relative_files(bundle_dir) == [
        "command.json",
        "environment.json",
        "launchservices-analysis.json",
        "report.json",
        "report.txt",
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
