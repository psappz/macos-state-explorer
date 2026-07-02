from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from macos_state_explorer.cli import app
from macos_state_explorer.core.model import Observation, Snapshot
from macos_state_explorer.launchservices.generations import analyze_generations
from macos_state_explorer.launchservices.models import LaunchServicesRecord, LaunchServicesStatus
from macos_state_explorer.launchservices.outcome import GenerationOutcomeState, build_launchservices_outcome
from macos_state_explorer.reports.local_network import build_local_network_report, write_local_network_support_bundle


def record(path: str, *, bundle_id: str, name: str, version: str | None, path_exists: bool | None = False, volume: str | None = "/", volume_exists: bool | None = True, classification: LaunchServicesStatus = LaunchServicesStatus.STALE) -> LaunchServicesRecord:
    return LaunchServicesRecord(raw_block=f"path: {path}", bundle_id=bundle_id, name=name, display_name=name, version=version, display_version=version, path=path, path_clean=path, path_exists=path_exists, volume=volume, volume_exists=volume_exists, classification=classification)


def outcome_records(*, include_safe: bool = False) -> list[LaunchServicesRecord]:
    records = [
        record("/Applications/Google Chrome.app", bundle_id="com.google.Chrome", name="Google Chrome", version="149.0.7827.250", path_exists=True, classification=LaunchServicesStatus.ACTIVE),
        record("/Users/patrick/.Trash/Google Chrome.app", bundle_id="com.google.Chrome", name="Google Chrome", version="149.0.7827.201", path_exists=True),
        record("/Volumes/Google Chrome/Google Chrome.app", bundle_id="com.google.Chrome", name="Google Chrome", version="149.0.7827.201", volume="/Volumes/Google Chrome", volume_exists=True),
        record("/Applications/GoogleUpdater.app", bundle_id="com.google.GoogleUpdater", name="GoogleUpdater", version="2.0", path_exists=True, classification=LaunchServicesStatus.ACTIVE),
        record("/Applications/GoogleUpdater.app/Contents/Helpers/GoogleUpdater Helper.app", bundle_id="com.google.GoogleUpdater.helper", name="GoogleUpdater Helper", version="1.0"),
        record("/Applications/Microsoft Edge.app", bundle_id="com.microsoft.edgemac", name="Microsoft Edge", version="130.0", path_exists=True, classification=LaunchServicesStatus.ACTIVE),
        record("/Applications/EdgeUpdater.app/Contents/Helpers/EdgeUpdater Helper.app", bundle_id="com.microsoft.EdgeUpdater.helper", name="EdgeUpdater Helper", version="1.0"),
        record("/Applications/Google Chrome Mystery.app", bundle_id="com.google.Chrome.mystery", name="Mystery", version="1.0", path_exists=None, classification=LaunchServicesStatus.UNKNOWN),
    ]
    if include_safe:
        records.append(record("/Applications/Google Chrome.app/Contents/Frameworks/Google Chrome Framework.framework/Versions/148.0.7778.216/Helpers/Google Chrome Helper.app", bundle_id="com.google.Chrome.helper", name="Google Chrome Helper", version="148.0.7778.216"))
    return records


def snapshot(records: list[LaunchServicesRecord]) -> Snapshot:
    return Snapshot(host="outcome-host", created_at=123.0, observations=[Observation(collector="launchservices", started_at=1, ended_at=2, payload={"entries": [item.model_dump(mode="python") for item in records]})])


def test_outcome_engine_classifies_completed_remaining_manual_and_blocked_generations():
    analysis = analyze_generations(outcome_records(include_safe=True))
    outcome = build_launchservices_outcome(analysis, completed_generation_ids=["Google Chrome|148.0.7778.179|/Applications/Google Chrome.app"])

    payload = outcome.to_json_dict()
    assert payload["command"] == "launchservices outcome"
    assert payload["completed_generations"][0]["state"] == GenerationOutcomeState.COMPLETED.value
    assert any(item["state"] == GenerationOutcomeState.REMAINING_PLAN_SAFE.value for item in payload["remaining_generations"])
    assert any(item["state"] == GenerationOutcomeState.MANUAL_REVIEW_REQUIRED.value and item["product_family"] == "Google Chrome" for item in payload["remaining_generations"])
    assert any(item["state"] == GenerationOutcomeState.MANUAL_REVIEW_REQUIRED.value and item["product_family"] == "GoogleUpdater" for item in payload["skipped_generations"])
    assert any(item["state"] == GenerationOutcomeState.BLOCKED_ACTIVE.value and item["product_family"] == "Google Chrome" for item in payload["active_generations"])
    assert any(item["state"] == GenerationOutcomeState.BLOCKED_UNKNOWN.value for item in payload["blocked_generations"])
    assert payload["automatic_remediation_complete"] is False


def test_outcome_engine_reports_no_safe_automatic_remediation_complete():
    outcome = build_launchservices_outcome(analyze_generations(outcome_records()), completed_generation_ids=["Google Chrome|148.0.7778.216|/Applications/Google Chrome.app"])

    payload = outcome.to_json_dict()
    assert payload["automatic_remediation_complete"] is True
    assert payload["local_network_status"]["status"] == "UNCHANGED"
    assert "Only manual-review generations remain" in payload["explanation"]
    assert "No automatic execution recommended." in payload["next_manual_actions"]


def test_outcome_human_and_json_cli(monkeypatch):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: snapshot(outcome_records()))

    json_result = CliRunner().invoke(app, ["launchservices", "outcome", "--json"])
    human_result = CliRunner().invoke(app, ["launchservices", "outcome"])

    assert json_result.exit_code == 0
    payload = json.loads(json_result.stdout)
    assert list(payload)[:5] == ["command", "outcome_id", "timestamp", "product_families", "completed_generations"]
    assert payload["automatic_remediation_complete"] is True
    assert human_result.exit_code == 0
    assert "LaunchServices remediation outcome" in human_result.stdout
    assert "Automatic remediation" in human_result.stdout
    assert "COMPLETE" in human_result.stdout
    assert "No automatic execution recommended." in human_result.stdout


def test_local_network_solution_and_report_include_outcome_summary(monkeypatch):
    snap = snapshot(outcome_records())
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: snap)

    solve_result = CliRunner().invoke(app, ["solve", "local-network", "--json"])
    report = build_local_network_report(snap)
    report_payload = report.to_json_dict()

    assert solve_result.exit_code == 0
    solve_payload = json.loads(solve_result.stdout)
    assert "launchservices_outcome_summary" in solve_payload
    assert solve_payload["launchservices_outcome_summary"]["automatic_remediation_complete"] is True
    assert "launchservices_outcome_summary" in report_payload
    assert report_payload["launchservices_outcome_summary"]["automatic_remediation_complete"] is True
    assert "Automatic LaunchServices remediation" in report.render_text()


def test_support_bundle_includes_outcome_artifacts(tmp_path):
    report = build_local_network_report(snapshot(outcome_records()))
    bundle = write_local_network_support_bundle(report, tmp_path / "bundle", branch_id="manual-empty-trash-reboot")

    assert (bundle / "outcome.json").exists()
    assert (bundle / "outcome.txt").exists()
    payload = json.loads((bundle / "outcome.json").read_text())
    assert payload["automatic_remediation_complete"] is True
    assert "LaunchServices remediation outcome" in (bundle / "outcome.txt").read_text()


def test_bundle_diff_includes_outcome_comparison(tmp_path):
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    (before / "report.json").write_text(json.dumps({"command": "report local-network", "evidence": [], "launchservices_outcome_summary": {"completed": 0, "remaining": 1, "blocked": 1, "automatic_remediation_complete": False}}))
    (after / "report.json").write_text(json.dumps({"command": "report local-network", "evidence": [], "launchservices_outcome_summary": {"completed": 1, "remaining": 0, "blocked": 2, "automatic_remediation_complete": True}}))

    result = CliRunner().invoke(app, ["diff", "bundles", str(before), str(after), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["outcome_diff"] == {"completed": 1, "remaining": -1, "newly_blocked": 1, "resolved": 1}


def test_phase1_lifecycle_outcome_documentation_exists():
    note = Path("docs/LAUNCHSERVICES_OUTCOME_ENGINE.md").read_text()

    assert "diagnosis" in note
    assert "planning" in note
    assert "execution" in note
    assert "validation" in note
    assert "outcome" in note
    assert "manual-review generations intentionally terminate automatic execution" in note
