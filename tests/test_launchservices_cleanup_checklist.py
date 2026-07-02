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


def checklist_records() -> list[LaunchServicesRecord]:
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
            "/Users/psi/.Trash/Google Chrome.app/Contents/Frameworks/Google Chrome Framework.framework/Versions/147.0.1/Helpers/Google Chrome Helper.app",
            bundle_id="com.google.Chrome.helper.trash",
            name="Google Chrome Helper",
            version="147.0.1",
        ),
        record(
            "/Volumes/Google Chrome/Google Chrome.app/Contents/Frameworks/Google Chrome Framework.framework/Versions/148.0.2/Helpers/Google Chrome Helper.app",
            bundle_id="com.google.Chrome.helper.installer",
            name="Google Chrome Helper",
            version="148.0.2",
            path_exists=True,
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
    ]


def snapshot(records: list[LaunchServicesRecord] | None = None) -> Snapshot:
    records = records or checklist_records()
    return Snapshot(
        host="cleanup-host",
        created_at=123.0,
        observations=[
            Observation(collector="tcc", started_at=1, ended_at=2, payload={"direct_localnetwork_query": {"stdout": ""}, "user_tcc": {"hits": []}}),
            Observation(collector="launchservices", started_at=1, ended_at=2, payload={"entries": [item.model_dump(mode="python") for item in records]}),
        ],
    )


def trace_analysis() -> dict[str, object]:
    csstore = "/private/var/folders/zz/com.apple.LaunchServices/com.apple.LaunchServices-3027.csstore"
    return {
        "created_at": 1.0,
        "signal_counts": {"launchservices_csstore": 1},
        "normalized_events": [
            {
                "timestamp": "2026-07-02 15:08:22.100000",
                "process": "launchctl",
                "pid": 88,
                "operation": "read",
                "file_path": "/Library/LaunchAgents/com.google.GoogleUpdater.plist",
                "source": "launchctl",
                "source_file": "launchctl_loop.txt",
                "signal": "googleupdater_launchagent",
                "confidence": 0.9,
                "raw_reference": "launchctl com.google.GoogleUpdater",
            },
            {
                "timestamp": "2026-07-02 15:08:23.000000",
                "process": "lsd",
                "pid": 222,
                "operation": "cache rebuild",
                "file_path": csstore,
                "source": "fs_usage",
                "source_file": "fs_usage.txt",
                "signal": "launchservices_csstore",
                "confidence": 0.9,
                "raw_reference": f"lsd rebuild {csstore}",
            },
        ],
    }


def write_trace(path: Path) -> Path:
    path.mkdir()
    (path / "analysis.json").write_text(json.dumps(trace_analysis()))
    return path


def test_cleanup_checklist_json_is_deterministic_and_separates_categories(monkeypatch, tmp_path):
    snap = snapshot()
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: snap)
    trace = write_trace(tmp_path / "trace")

    first = CliRunner().invoke(app, ["launchservices", "cleanup-checklist", "--trace", str(trace), "--json"])
    second = CliRunner().invoke(app, ["launchservices", "cleanup-checklist", "--trace", str(trace), "--json"])

    assert first.exit_code == 0
    assert json.loads(first.stdout) == json.loads(second.stdout)
    payload = json.loads(first.stdout)
    assert list(payload)[:6] == ["command", "checklist_id", "timestamp", "item_count", "summary", "items"]
    assert payload["command"] == "launchservices cleanup-checklist"
    categories = {item["category"] for item in payload["items"]}
    assert categories == {"trash", "mounted_installer", "updater", "unknown_chrome_application"}
    assert payload["summary"]["counts_by_category"] == {
        "mounted_installer": 1,
        "trash": 1,
        "unknown_chrome_application": 1,
        "updater": 1,
    }


def test_cleanup_checklist_items_have_manual_actions_and_no_mutation(monkeypatch, tmp_path):
    snap = snapshot()
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: snap)
    trace = write_trace(tmp_path / "trace")

    result = CliRunner().invoke(app, ["launchservices", "cleanup-checklist", "--trace", str(trace), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["read_only"] is True
    assert payload["mutation_performed"] is False
    forbidden = ["sudo rm", "rm -", "rm -rf", "diskutil erase", "lsregister -kill", "tccutil reset"]
    rendered = json.dumps(payload).lower()
    assert not any(token in rendered for token in forbidden)
    by_category = {item["category"]: item for item in payload["items"]}
    trash = by_category["trash"]
    assert "Inspect Finder Trash" in trash["exact_manual_action"]
    assert "empty only if contents are disposable" in trash["exact_manual_action"]
    assert trash["verification_command"] == "mse launchservices cleanup-checklist --json"
    assert "Trash generation absent" in trash["expected_post_condition"]
    mounted = by_category["mounted_installer"]
    assert "Eject /Volumes/Google Chrome" in mounted["exact_manual_action"]
    updater = by_category["updater"]
    assert "do not delete blindly" in updater["why_automatic_cleanup_not_recommended"]
    unknown = by_category["unknown_chrome_application"]
    assert "After Trash and mounted installer" in unknown["exact_manual_action"]
    for item in payload["items"]:
        assert item["generation_id"]
        assert item["producer"]
        assert "regenerator" in item
        assert isinstance(item["confidence"], float)
        assert item["classification"]
        assert item["registration_ids"]
        assert item["paths"]


def test_cleanup_checklist_human_output(monkeypatch, tmp_path):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: snapshot())
    trace = write_trace(tmp_path / "trace")

    result = CliRunner().invoke(app, ["launchservices", "cleanup-checklist", "--trace", str(trace)])

    assert result.exit_code == 0
    assert "LaunchServices cleanup checklist" in result.stdout
    assert "Trash registrations" in result.stdout
    assert "Mounted installer registrations" in result.stdout
    assert "Updater registrations" in result.stdout
    assert "Unknown regenerator Chrome application generations" in result.stdout
    assert "No automatic cleanup is performed" in result.stdout


def test_local_network_report_and_bundle_include_cleanup_checklist(monkeypatch, tmp_path):
    snap = snapshot()
    trace_dir = write_trace(tmp_path / "trace")
    report = build_local_network_report(snap, trace_analysis=trace_analysis())

    payload = report.to_json_dict()
    bundle = write_local_network_support_bundle(report, tmp_path / "bundle", branch_id="manual-empty-trash-reboot", trace_path=trace_dir)

    assert "launchservices_cleanup_checklist_summary" in payload
    assert payload["launchservices_cleanup_checklist_summary"]["counts_by_category"]["trash"] == 1
    assert payload["launchservices_cleanup_checklist_summary"]["first_recommended_manual_action"].startswith("Inspect Finder Trash")
    assert "LaunchServices cleanup checklist" in report.render_text()
    assert (bundle / "cleanup-checklist.json").exists()
    assert (bundle / "cleanup-checklist.txt").exists()
    assert json.loads((bundle / "cleanup-checklist.json").read_text())["command"] == "launchservices cleanup-checklist"


def test_bundle_diff_includes_cleanup_checklist_changes(tmp_path):
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    (before / "report.json").write_text(
        json.dumps(
            {
                "command": "report local-network",
                "evidence": [],
                "launchservices_cleanup_checklist_summary": {
                    "item_ids": ["trash:a"],
                    "first_recommended_manual_action": "Inspect Finder Trash, empty only if contents are disposable, reboot, verify.",
                },
            }
        )
    )
    (after / "report.json").write_text(
        json.dumps(
            {
                "command": "report local-network",
                "evidence": [],
                "launchservices_cleanup_checklist_summary": {
                    "item_ids": ["mounted_installer:b"],
                    "first_recommended_manual_action": "Eject /Volumes/Google Chrome, reboot or relaunch System Settings, verify.",
                },
            }
        )
    )

    result = CliRunner().invoke(app, ["diff", "bundles", str(before), str(after), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["cleanup_checklist_diff"] == {
        "added_item_ids": ["mounted_installer:b"],
        "removed_item_ids": ["trash:a"],
        "changed_item_ids": [],
        "first_recommended_action_changed": True,
    }


def test_cleanup_checklist_command_does_not_call_mutation_paths(monkeypatch, tmp_path):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: snapshot())
    monkeypatch.setattr("macos_state_explorer.cli._launchservices_execute_plan_confirm", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("mutation called")))
    trace = write_trace(tmp_path / "trace")

    result = CliRunner().invoke(app, ["launchservices", "cleanup-checklist", "--trace", str(trace), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["read_only"] is True
    assert payload["mutation_performed"] is False
