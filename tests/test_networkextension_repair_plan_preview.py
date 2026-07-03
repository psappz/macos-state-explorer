from __future__ import annotations

import json
import plistlib
from pathlib import Path

from typer.testing import CliRunner

from macos_state_explorer.cli import app
from macos_state_explorer.core.model import Observation, Snapshot
from macos_state_explorer.networkextension_candidate_validation import build_networkextension_candidate_validation
from macos_state_explorer.networkextension_repair_plan_preview import build_networkextension_repair_plan_preview
from macos_state_explorer.reports.local_network import build_local_network_report, write_local_network_support_bundle


def snapshot_with_launchservices(entries: list[dict] | None = None) -> Snapshot:
    return Snapshot(
        host="repair-plan-preview-host",
        created_at=123.0,
        observations=[
            Observation(collector="tcc", started_at=1, ended_at=2, payload={"direct_localnetwork_query": {"stdout": ""}, "user_tcc": {"hits": []}}),
            Observation(collector="launchservices", started_at=1, ended_at=2, payload={"entries": entries or []}),
        ],
    )


def write_candidate_validation_fixture(root: Path) -> dict[str, Path]:
    prefs = root / "Library" / "Preferences"
    prefs.mkdir(parents=True)
    installed_exe = root / "Applications" / "Google Chrome.app" / "Contents" / "MacOS" / "Google Chrome"
    installed_exe.parent.mkdir(parents=True)
    installed_exe.write_text("#!/bin/sh\n", encoding="utf-8")
    installed_absent = root / "Applications" / "Absent Chrome.app" / "Contents" / "MacOS" / "Google Chrome"
    installed_absent.parent.mkdir(parents=True)
    missing_clone = root / "private" / "var" / "folders" / "xx" / "com.google.Chrome.code_sign_clone" / "Contents" / "MacOS" / "Google Chrome"
    missing_normal = root / "Applications" / "Missing Chrome.app" / "Contents" / "MacOS" / "Google Chrome"
    archive = {
        "$archiver": "NSKeyedArchiver",
        "$version": 100000,
        "$top": {"root": plistlib.UID(1)},
        "$objects": [
            "$null",
            {"ClientIdentities": plistlib.UID(2)},
            [plistlib.UID(3), plistlib.UID(5), plistlib.UID(7), plistlib.UID(9), plistlib.UID(11)],
            {"ClientIdentity": plistlib.UID(4), "State": "active"},
            {"SigningIdentifier": "com.google.Chrome", "Path": str(installed_exe), "Kind": "client identity active"},
            {"ClientIdentity": plistlib.UID(6), "State": "installed absent"},
            {"SigningIdentifier": "com.google.Chrome", "Path": str(installed_absent), "Kind": "client identity installed absent"},
            {"ClientIdentity": plistlib.UID(8), "State": "historical"},
            {"SigningIdentifier": "com.google.Chrome.code_sign_clone", "Path": str(missing_clone), "Kind": "client identity clone"},
            {"ClientIdentity": plistlib.UID(10), "State": "orphaned"},
            {"SigningIdentifier": "com.google.Chrome", "Path": str(missing_normal), "Kind": "client identity missing"},
            {"ClientIdentity": plistlib.UID(12), "State": "incomplete"},
            {"SigningIdentifier": "com.google.Chrome", "Kind": "client identity incomplete"},
        ],
    }
    with (prefs / "com.apple.networkextension.plist").open("wb") as handle:
        plistlib.dump(archive, handle, fmt=plistlib.FMT_BINARY, sort_keys=True)
    (prefs / "com.apple.networkextension.malformed.plist").write_bytes(b"not a plist com.google.Chrome")
    return {
        "root": root,
        "installed_exe": installed_exe,
        "installed_absent": installed_absent,
        "missing_clone": missing_clone,
        "missing_normal": missing_normal,
    }


def test_repair_plan_preview_json_groups_stale_candidates_deterministically(tmp_path):
    fixture = write_candidate_validation_fixture(tmp_path / "ne")
    validation = build_networkextension_candidate_validation([fixture["root"]], process_rows=[])

    first = build_networkextension_repair_plan_preview(validation).to_json_dict()
    second = build_networkextension_repair_plan_preview(validation).to_json_dict()

    assert first == second
    assert list(first)[:8] == [
        "command",
        "repair_plan_preview_id",
        "timestamp",
        "read_only",
        "mutation_performed",
        "automatic_execution_recommendation",
        "summary",
        "manual_preconditions",
    ]
    assert first["command"] == "networkextension repair-plan-preview"
    assert first["read_only"] is True
    assert first["mutation_performed"] is False
    assert first["automatic_execution_recommendation"] == "never"
    assert first["summary"]["total_candidates"] == 5
    assert first["summary"]["grouped_preview_targets"] == 2
    assert first["summary"]["stale_code_sign_clone_targets"] == 1
    assert first["summary"]["stale_missing_executable_targets"] == 1
    assert first["summary"]["preview_only_operations"] == 2
    assert first["manual_preconditions"] == [
        "user-reviewed support bundle",
        "backup of affected plist",
        "Chrome not running",
        "System Settings closed",
        "post-change reboot required",
        "post-change verification required",
    ]
    assert first["automatic_execution_blockers"] == [
        "NSKeyedArchiver mutation risk",
        "object graph integrity risk",
        "macOS private preference format",
        "runtime absence alone insufficient",
    ]

    groups = first["preview_groups"]
    assert [group["classification"] for group in groups] == [
        "stale_code_sign_clone_preview_target",
        "stale_missing_executable_preview_target",
    ]
    clone = groups[0]
    assert clone["operation"] == "preview_only"
    assert clone["preview_only"] is True
    assert clone["would_target"]["plist_artifact"] == "com.apple.networkextension.plist"
    assert clone["would_target"]["validation_status"] == "stale_code_sign_clone"
    assert clone["would_target"]["executable_path_class"] == "code_sign_clone_temp_container"
    assert clone["would_target"]["candidate_count"] == 1
    assert "runtime absence alone is insufficient" in clone["explanation"]
    missing = groups[1]
    assert missing["classification"] == "stale_missing_executable_preview_target"
    assert missing["would_target"]["executable_path_class"] == "missing_executable_path"

    for group in groups:
        assert group["manual_preconditions"] == first["manual_preconditions"]
        assert group["automatic_execution_blockers"] == first["automatic_execution_blockers"]
        assert group["actionability"] == {
            "preview_only": True,
            "still_read_only": True,
            "requires_manual_confirmation": True,
            "never_auto_delete": True,
        }


def test_repair_plan_preview_cli_text_is_read_only(monkeypatch, tmp_path):
    fixture = write_candidate_validation_fixture(tmp_path / "ne")
    monkeypatch.setattr("macos_state_explorer.networkextension_candidate_validation._process_rows", lambda: [])

    result = CliRunner().invoke(app, ["networkextension", "repair-plan-preview", "--root", str(fixture["root"])])

    assert result.exit_code == 0
    assert "NetworkExtension repair plan preview" in result.stdout
    assert "Mutation performed: false" in result.stdout
    assert "Automatic execution recommendation: never" in result.stdout
    assert "preview_only" in result.stdout
    assert "NSKeyedArchiver mutation risk" in result.stdout
    assert "runtime absence alone is insufficient" in result.stdout
    forbidden = ["defaults write", "defaults delete", "plistbuddy", "killall", "rm ", "reset", "reboot now", "execute repair"]
    lowered = result.stdout.lower()
    for token in forbidden:
        assert token not in lowered


def test_report_bundle_and_diff_include_repair_plan_preview(monkeypatch, tmp_path):
    fixture = write_candidate_validation_fixture(tmp_path / "ne")
    monkeypatch.setattr("macos_state_explorer.reports.local_network.default_networkextension_roots", lambda: [fixture["root"]])
    monkeypatch.setattr("macos_state_explorer.networkextension_candidate_validation._process_rows", lambda: [])
    report = build_local_network_report(snapshot_with_launchservices())

    payload = report.to_json_dict()
    assert payload["networkextension_repair_plan_preview_summary"]["grouped_preview_targets"] == 2
    assert "NetworkExtension repair plan preview" in report.render_text()

    bundle = write_local_network_support_bundle(report, tmp_path / "bundle", branch_id="manual-empty-trash-reboot")
    assert (bundle / "networkextension-repair-plan-preview.json").exists()
    assert (bundle / "networkextension-repair-plan-preview.txt").exists()
    artifact = json.loads((bundle / "networkextension-repair-plan-preview.json").read_text())
    assert artifact["summary"]["preview_only_operations"] == 2
    assert artifact["mutation_performed"] is False

    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    before_report = {
        "command": "report local-network",
        "evidence": [],
        "networkextension_repair_plan_preview_summary": {
            "preview_group_ids": ["old-group"],
            "classification_counts": {"never_auto_delete": 1},
            "grouped_preview_targets": 1,
            "preview_only_operations": 1,
            "stale_code_sign_clone_targets": 0,
            "stale_missing_executable_targets": 0,
        },
    }
    after_report = {
        "command": "report local-network",
        "evidence": [],
        "networkextension_repair_plan_preview_summary": {
            "preview_group_ids": ["new-group"],
            "classification_counts": {"stale_code_sign_clone_preview_target": 1},
            "grouped_preview_targets": 1,
            "preview_only_operations": 1,
            "stale_code_sign_clone_targets": 1,
            "stale_missing_executable_targets": 0,
        },
    }
    (before / "report.json").write_text(json.dumps(before_report, sort_keys=True))
    (after / "report.json").write_text(json.dumps(after_report, sort_keys=True))

    diff_json = CliRunner().invoke(app, ["diff", "bundles", str(before), str(after), "--json"])
    assert diff_json.exit_code == 0
    diff = json.loads(diff_json.stdout)
    preview_diff = diff["networkextension_repair_plan_preview_diff"]
    assert preview_diff["added_preview_group_ids"] == ["new-group"]
    assert preview_diff["removed_preview_group_ids"] == ["old-group"]
    assert preview_diff["changed_classifications"] == ["never_auto_delete", "stale_code_sign_clone_preview_target"]
    assert preview_diff["stale_code_sign_clone_targets_delta"] == 1
    diff_text = CliRunner().invoke(app, ["diff", "bundles", str(before), str(after)]).stdout
    assert "NetworkExtension Repair Plan Preview Diff" in diff_text
    assert "Added preview groups: new-group" in diff_text
