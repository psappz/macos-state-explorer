from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from macos_state_explorer.cli import app
from macos_state_explorer.core.model import Observation, Snapshot
from macos_state_explorer.launchservices.generations import analyze_generations
from macos_state_explorer.launchservices.models import LaunchServicesRecord, LaunchServicesStatus
from macos_state_explorer.launchservices.provenance import build_launchservices_provenance
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
        volume=volume,
        volume_exists=volume_exists,
        classification=classification,
    )


def provenance_records() -> list[LaunchServicesRecord]:
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


def snapshot(records: list[LaunchServicesRecord]) -> Snapshot:
    return Snapshot(
        host="provenance-host",
        created_at=123.0,
        observations=[
            Observation(
                collector="launchservices",
                started_at=1,
                ended_at=2,
                payload={"entries": [item.model_dump(mode="python") for item in records]},
            )
        ],
    )


def test_provenance_classifies_producers_consumers_and_persistence_reasoning():
    provenance = build_launchservices_provenance(analyze_generations(provenance_records()))
    payload = provenance.to_json_dict()

    helper = next(item for item in payload["registrations"] if item["path"].endswith("Google Chrome Helper.app"))
    mounted = next(item for item in payload["registrations"] if item["path"].startswith("/Volumes/Google Chrome"))
    trash = next(item for item in payload["registrations"] if "/.Trash/" in item["path"])
    updater = next(item for item in payload["registrations"] if item["product_family"] == "GoogleUpdater")

    assert helper["producer"] == "LaunchServices application enumeration"
    assert helper["producer_confidence"] >= 0.8
    assert helper["persistence_source"] == "derived LaunchServices cache"
    assert helper["regeneration_source"] == "rebuilt from application enumeration"
    assert "LaunchServices" in helper["consumer_set"]
    assert "SecurityPrivacyExtension" in helper["consumer_set"]
    assert "System Settings Privacy UI" in helper["consumer_set"]
    assert any(evidence["kind"] == "path" for evidence in helper["evidence"])

    assert mounted["producer"] == "Mounted installer"
    assert mounted["persistence_source"] == "mounted volume"
    assert mounted["regeneration_source"] == "mounted volume enumeration"
    assert trash["producer"] == "Finder Trash"
    assert trash["persistence_source"] == "trash item"
    assert updater["producer"] == "GoogleUpdater"
    assert updater["persistence_source"] == "updater registration"


def test_provenance_json_and_human_cli(monkeypatch):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: snapshot(provenance_records()))

    json_result = CliRunner().invoke(app, ["launchservices", "provenance", "--json"])
    human_result = CliRunner().invoke(app, ["launchservices", "provenance"])

    assert json_result.exit_code == 0
    payload = json.loads(json_result.stdout)
    assert list(payload)[:5] == ["command", "provenance_id", "timestamp", "registration_count", "product_families"]
    assert payload["command"] == "launchservices provenance"
    assert payload["registration_count"] >= 5
    assert payload["summary"]["producers"]["LaunchServices application enumeration"] >= 1
    assert human_result.exit_code == 0
    assert "LaunchServices registration provenance" in human_result.stdout
    assert "Producer" in human_result.stdout
    assert "Consumers" in human_result.stdout
    assert "Persistence" in human_result.stdout


def test_local_network_solution_and_report_include_provenance_summary(monkeypatch):
    snap = snapshot(provenance_records())
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: snap)

    solve_result = CliRunner().invoke(app, ["solve", "local-network", "--json"])
    report = build_local_network_report(snap)
    report_payload = report.to_json_dict()

    assert solve_result.exit_code == 0
    solve_payload = json.loads(solve_result.stdout)
    assert "launchservices_provenance_summary" in solve_payload
    assert solve_payload["launchservices_provenance_summary"]["primary_producer"] == "LaunchServices application enumeration"
    assert "SecurityPrivacyExtension" in solve_payload["launchservices_provenance_summary"]["consumers"]
    assert "launchservices_provenance_summary" in report_payload
    assert "LaunchServices provenance" in report.render_text()


def test_support_bundle_includes_provenance_artifacts(tmp_path):
    report = build_local_network_report(snapshot(provenance_records()))
    bundle = write_local_network_support_bundle(report, tmp_path / "bundle", branch_id="manual-empty-trash-reboot")

    assert (bundle / "provenance.json").exists()
    assert (bundle / "provenance.txt").exists()
    payload = json.loads((bundle / "provenance.json").read_text())
    assert payload["command"] == "launchservices provenance"
    assert "LaunchServices registration provenance" in (bundle / "provenance.txt").read_text()


def test_bundle_diff_includes_provenance_diff(tmp_path):
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    (before / "report.json").write_text(json.dumps({"command": "report local-network", "evidence": [], "launchservices_provenance_summary": {"primary_producer": "Unknown", "persistence_source": "unknown", "consumers": ["LaunchServices"]}}))
    (after / "report.json").write_text(json.dumps({"command": "report local-network", "evidence": [], "launchservices_provenance_summary": {"primary_producer": "LaunchServices application enumeration", "persistence_source": "derived LaunchServices cache", "consumers": ["LaunchServices", "SecurityPrivacyExtension"]}}))

    result = CliRunner().invoke(app, ["diff", "bundles", str(before), str(after), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["provenance_diff"] == {
        "producer_before": "Unknown",
        "producer_after": "LaunchServices application enumeration",
        "persistence_before": "unknown",
        "persistence_after": "derived LaunchServices cache",
        "added_consumers": ["SecurityPrivacyExtension"],
        "removed_consumers": [],
    }


def test_provenance_documentation_defines_public_project_identity_only():
    docs = "\n".join(Path(path).read_text() for path in ["README.md", "CONTRIBUTING.md", "ARCHITECTURE.md", "ROADMAP.md", "docs/LAUNCHSERVICES_OUTCOME_ENGINE.md"])

    assert "Open State Diagnostics & Repair Framework" in docs
    assert "Open State Diagnostics & Repair Framework" in docs
    assert "Chrome Local Network reference case" in docs
    assert "Core must not contain domain-specific logic" in docs
    assert "Every architecture-affecting PR must update docs" in docs
    assert "Registration Provenance Engine" in docs
    assert "OSDRF" not in docs
