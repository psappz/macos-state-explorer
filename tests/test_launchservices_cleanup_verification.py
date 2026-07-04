from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from macos_state_explorer.cli import app
from macos_state_explorer.core.model import Observation, Snapshot
from macos_state_explorer.launchservices.models import LaunchServicesRecord, LaunchServicesStatus
from macos_state_explorer.reports.local_network import build_local_network_report, write_local_network_support_bundle


def record(
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
        identifier=bundle_id,
        canonical_id=bundle_id,
        name=name,
        display_name=name,
        version=version,
        display_version=version,
        path=path,
        path_clean=path,
        path_exists=path_exists,
        volume="/Volumes/Google Chrome" if path.startswith("/Volumes/Google Chrome") else "/",
        volume_exists=path.startswith("/Volumes/Google Chrome") or True,
        classification=classification,
    )


def snapshot(records: list[LaunchServicesRecord]) -> Snapshot:
    return Snapshot(
        host="cleanup-verification-host",
        created_at=123.0,
        observations=[
            Observation(collector="tcc", started_at=1, ended_at=2, payload={"direct_localnetwork_query": {"stdout": ""}, "user_tcc": {"hits": []}}),
            Observation(collector="launchservices", started_at=1, ended_at=2, payload={"entries": [item.model_dump(mode="python") for item in records]}),
        ],
    )


def write_trace(path: Path) -> Path:
    path.mkdir()
    (path / "analysis.json").write_text(json.dumps({"created_at": 1.0, "signal_counts": {}, "normalized_events": []}))
    return path


def post_cleanup_records():
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
            "/Applications/GoogleUpdater.app/Contents/Helpers/GoogleUpdater Helper.app",
            bundle_id="com.google.GoogleUpdater.helper",
            name="GoogleUpdater Helper",
            version="1.3",
            path_exists=True,
        ),
        record(
            "/Applications/Google Chrome.app/Contents/Frameworks/Google Chrome Framework.framework/Versions/146.0.3/Helpers/Google Chrome Helper.app",
            bundle_id="com.google.Chrome.helper.unknown",
            name="Google Chrome Helper",
            version="146.0.3",
            path_exists=False,
        ),
        record(
            "/Volumes/Google Chrome/Google Chrome.app/Contents/Frameworks/Google Chrome Framework.framework/Versions/150.0.1/Helpers/Google Chrome Helper.app",
            bundle_id="com.google.Chrome.helper.newinstaller",
            name="Google Chrome Helper",
            version="150.0.1",
            path_exists=True,
        ),
    ]


def test_verify_cleanup_json_is_deterministic_and_buckets_findings(monkeypatch, tmp_path):
    snap = snapshot(post_cleanup_records())
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: snap)
    trace = write_trace(tmp_path / "trace")

    first = CliRunner().invoke(app, ["launchservices", "verify-cleanup", "--trace", str(trace), "--json"])
    second = CliRunner().invoke(app, ["launchservices", "verify-cleanup", "--trace", str(trace), "--json"])

    assert first.exit_code == 0
    assert json.loads(first.stdout) == json.loads(second.stdout)
    payload = json.loads(first.stdout)
    assert list(payload)[:7] == ["command", "verification_id", "timestamp", "summary", "verified", "still_present", "unexpected"]
    assert payload["command"] == "launchservices verify-cleanup"
    assert payload["read_only"] is True
    assert payload["mutation_performed"] is False
    assert payload["summary"] == {
        "verified": 2,
        "still_present": 1,
        "unexpected": 1,
        "unknown": 1,
        "active_generations_preserved": True,
        "new_stale_generations": 1,
    }
    assert payload["verified"][0]["expected_state"] == "trash registrations absent"
    assert payload["verified"][0]["actual_state"] == "absent"
    assert payload["still_present"][0]["expected_state"] == "non-automatic cleanup source absent or resolved"
    assert payload["unexpected"][0]["previous_classification"] == "new_stale_generation"
    assert payload["unknown"][0]["previous_classification"] == "updater"


def test_verify_cleanup_items_include_required_fields_and_no_mutation(monkeypatch, tmp_path):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: snapshot(post_cleanup_records()))
    trace = write_trace(tmp_path / "trace")

    result = CliRunner().invoke(app, ["launchservices", "verify-cleanup", "--trace", str(trace), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    rendered = json.dumps(payload).lower()
    assert not any(token in rendered for token in ["sudo rm", "rm -", "rm -rf", "diskutil erase", "lsregister -kill", "tccutil reset"])
    for bucket in ["verified", "still_present", "unexpected", "unknown"]:
        for item in payload[bucket]:
            assert list(item) == [
                "item_id",
                "generation_id",
                "producer",
                "previous_classification",
                "current_classification",
                "expected_state",
                "actual_state",
                "explanation",
            ]
            assert item["generation_id"]
            assert item["producer"]
            assert item["expected_state"]
            assert item["actual_state"]
            assert item["explanation"]


def test_verify_cleanup_human_output(monkeypatch, tmp_path):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: snapshot(post_cleanup_records()))
    trace = write_trace(tmp_path / "trace")

    result = CliRunner().invoke(app, ["launchservices", "verify-cleanup", "--trace", str(trace)])

    assert result.exit_code == 0
    assert "LaunchServices cleanup verification" in result.stdout
    assert "Verified" in result.stdout
    assert "Still Present" in result.stdout
    assert "Unexpected" in result.stdout
    assert "Unknown" in result.stdout
    assert "No mutation is performed" in result.stdout


def test_local_network_report_and_bundle_include_cleanup_verification(monkeypatch, tmp_path):
    snap = snapshot(post_cleanup_records())
    trace_dir = write_trace(tmp_path / "trace")
    report = build_local_network_report(snap, trace_analysis=json.loads((trace_dir / "analysis.json").read_text()))

    payload = report.to_json_dict()
    bundle = write_local_network_support_bundle(report, tmp_path / "bundle", branch_id="manual-empty-trash-reboot", trace_path=trace_dir)

    assert "launchservices_cleanup_verification_summary" in payload
    assert payload["launchservices_cleanup_verification_summary"]["verified"] == 2
    assert payload["launchservices_cleanup_verification_summary"]["still_present"] == 1
    assert "LaunchServices cleanup verification" in report.render_text()
    assert (bundle / "cleanup-verification.json").exists()
    assert (bundle / "cleanup-verification.txt").exists()
    assert json.loads((bundle / "cleanup-verification.json").read_text())["command"] == "launchservices verify-cleanup"


def test_bundle_diff_includes_cleanup_verification_changes(tmp_path):
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    (before / "report.json").write_text(
        json.dumps(
            {
                "command": "report local-network",
                "evidence": [],
                "launchservices_cleanup_verification_summary": {
                    "verified_item_ids": ["trash:old"],
                    "failed_item_ids": ["unknown:old"],
                    "newly_appeared_generation_ids": [],
                    "disappeared_generation_ids": ["trash-old"],
                    "unchanged_generation_ids": ["chrome-old"],
                },
            }
        )
    )
    (after / "report.json").write_text(
        json.dumps(
            {
                "command": "report local-network",
                "evidence": [],
                "launchservices_cleanup_verification_summary": {
                    "verified_item_ids": ["trash:old", "active:current"],
                    "failed_item_ids": ["unknown:old", "mounted:new"],
                    "newly_appeared_generation_ids": ["mounted-new"],
                    "disappeared_generation_ids": ["trash-old"],
                    "unchanged_generation_ids": ["chrome-old", "updater-current"],
                },
            }
        )
    )

    result = CliRunner().invoke(app, ["diff", "bundles", str(before), str(after), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["cleanup_verification_diff"] == {
        "verified_items": ["active:current"],
        "failed_verification": ["mounted:new"],
        "newly_appeared_generations": ["mounted-new"],
        "disappeared_generations": [],
        "unchanged_generations": ["updater-current"],
    }


def test_verify_cleanup_command_does_not_call_mutation_paths(monkeypatch, tmp_path):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: snapshot(post_cleanup_records()))
    monkeypatch.setattr("macos_state_explorer.cli._launchservices_execute_plan_confirm", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("mutation called")))
    trace = write_trace(tmp_path / "trace")

    result = CliRunner().invoke(app, ["launchservices", "verify-cleanup", "--trace", str(trace), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["read_only"] is True
    assert payload["mutation_performed"] is False
