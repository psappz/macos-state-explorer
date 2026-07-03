from __future__ import annotations

import json
import plistlib
from pathlib import Path

from typer.testing import CliRunner

from macos_state_explorer.cli import app
from macos_state_explorer.core.model import Observation, Snapshot
from macos_state_explorer.networkextension_candidate_validation import build_networkextension_candidate_validation
from macos_state_explorer.networkextension_repair_plan_preview import build_networkextension_repair_plan_preview
from macos_state_explorer.networkextension_repair_transaction_package import build_networkextension_repair_transaction_package
from macos_state_explorer.reports.local_network import build_local_network_report, write_local_network_support_bundle


def snapshot_with_launchservices(entries: list[dict] | None = None) -> Snapshot:
    return Snapshot(
        host="repair-transaction-package-host",
        created_at=123.0,
        observations=[
            Observation(collector="tcc", started_at=1, ended_at=2, payload={"direct_localnetwork_query": {"stdout": ""}, "user_tcc": {"hits": []}}),
            Observation(collector="launchservices", started_at=1, ended_at=2, payload={"entries": entries or []}),
        ],
    )


def write_candidate_fixture(root: Path) -> dict[str, Path]:
    prefs = root / "Library" / "Preferences"
    prefs.mkdir(parents=True)
    installed_exe = root / "Applications" / "Google Chrome.app" / "Contents" / "MacOS" / "Google Chrome"
    installed_exe.parent.mkdir(parents=True)
    installed_exe.write_text("#!/bin/sh\n", encoding="utf-8")
    installed_absent = root / "Applications" / "Absent Chrome.app" / "Contents" / "MacOS" / "Google Chrome"
    installed_absent.parent.mkdir(parents=True)
    missing_clone = root / "private" / "var" / "folders" / "xx" / "com.google.Chrome.code_sign_clone" / "Contents" / "MacOS" / "Google Chrome"
    missing_normal = root / "Applications" / "Missing Chrome.app" / "Contents" / "MacOS" / "Google Chrome"
    artifact = prefs / "com.apple.networkextension.plist"
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
    with artifact.open("wb") as handle:
        plistlib.dump(archive, handle, fmt=plistlib.FMT_BINARY, sort_keys=True)
    return {"root": root, "artifact": artifact, "missing_clone": missing_clone, "missing_normal": missing_normal}


def test_repair_transaction_package_json_is_deterministic_and_non_executable(tmp_path):
    fixture = write_candidate_fixture(tmp_path / "ne")
    validation = build_networkextension_candidate_validation([fixture["root"]], process_rows=[])
    preview = build_networkextension_repair_plan_preview(validation)

    first = build_networkextension_repair_transaction_package(preview, [fixture["root"]]).to_json_dict()
    second = build_networkextension_repair_transaction_package(preview, [fixture["root"]]).to_json_dict()

    assert first == second
    assert list(first)[:9] == [
        "command",
        "repair_transaction_package_id",
        "timestamp",
        "read_only",
        "mutation_performed",
        "executable_by_tool",
        "automatic_execution_recommendation",
        "summary",
        "manual_preconditions",
    ]
    assert first["command"] == "networkextension repair-transaction-package"
    assert first["read_only"] is True
    assert first["mutation_performed"] is False
    assert first["executable_by_tool"] is False
    assert first["automatic_execution_recommendation"] == "never"
    assert first["not_executable_statement"] == "This transaction package is not executable by macos-state-explorer."
    assert first["summary"]["transaction_count"] == 2
    assert first["summary"]["backup_required_count"] == 2
    assert first["summary"]["rollback_required_count"] == 2
    assert first["summary"]["preview_only_transactions"] == 2
    assert first["manual_preconditions"] == preview.to_json_dict()["manual_preconditions"]
    assert first["execution_blockers"] == preview.to_json_dict()["automatic_execution_blockers"]

    transactions = first["transactions"]
    assert [item["validation_status"] for item in transactions] == ["stale_code_sign_clone", "stale_missing_executable"]
    for transaction in transactions:
        assert transaction["preview_only"] is True
        assert transaction["mutation_performed"] is False
        assert transaction["executable_by_tool"] is False
        assert transaction["backup_required"] is True
        assert transaction["rollback_required"] is True
        assert transaction["source_artifact"]["name"] == "com.apple.networkextension.plist"
        assert transaction["source_artifact"]["artifact_type"] == "networkextension_preferences_plist"
        assert transaction["source_artifact"]["sha256"]
        assert transaction["affected_parent_object_record"].startswith("$objects[")
        assert transaction["grouped_preview_target_ids"]
        assert transaction["candidate_object_refs"]
        assert transaction["signing_identifier"]
        assert transaction["executable_path_class"] in {"code_sign_clone_temp_container", "missing_executable_path"}
        assert transaction["post_change_verification_commands"] == [
            "mse networkextension validate-candidates",
            "mse networkextension repair-plan-preview",
            "mse networkextension repair-transaction-package",
            "mse report local-network --bundle ~/Desktop/mse-local-network-post-change-bundle",
        ]
        assert transaction["rollback_requirement"] == "Restore the backed-up source plist artifact before reboot and rerun post-change verification."
        assert transaction["not_executable_by_tool"] is True


def test_repair_transaction_package_cli_text_is_read_only(monkeypatch, tmp_path):
    fixture = write_candidate_fixture(tmp_path / "ne")
    monkeypatch.setattr("macos_state_explorer.networkextension_candidate_validation._process_rows", lambda: [])

    result = CliRunner().invoke(app, ["networkextension", "repair-transaction-package", "--root", str(fixture["root"])])

    assert result.exit_code == 0
    assert "NetworkExtension repair transaction package" in result.stdout
    assert "Mutation performed: false" in result.stdout
    assert "Executable by tool: false" in result.stdout
    assert "Automatic execution recommendation: never" in result.stdout
    assert "This transaction package is not executable by macos-state-explorer." in result.stdout
    assert "Post-change verification commands" in result.stdout
    forbidden = ["defaults write", "defaults delete", "plistbuddy", "killall", "rm ", "reset", "execute repair", "automatic execution recommended"]
    lowered = result.stdout.lower()
    for token in forbidden:
        assert token not in lowered


def test_report_bundle_and_diff_include_repair_transaction_package(monkeypatch, tmp_path):
    fixture = write_candidate_fixture(tmp_path / "ne")
    monkeypatch.setattr("macos_state_explorer.reports.local_network.default_networkextension_roots", lambda: [fixture["root"]])
    monkeypatch.setattr("macos_state_explorer.networkextension_candidate_validation._process_rows", lambda: [])
    report = build_local_network_report(snapshot_with_launchservices())

    payload = report.to_json_dict()
    assert payload["networkextension_repair_transaction_package_summary"]["transaction_count"] == 2
    assert "NetworkExtension repair transaction package" in report.render_text()

    bundle = write_local_network_support_bundle(report, tmp_path / "bundle", branch_id="manual-empty-trash-reboot")
    assert (bundle / "networkextension-repair-transaction-package.json").exists()
    assert (bundle / "networkextension-repair-transaction-package.txt").exists()
    artifact = json.loads((bundle / "networkextension-repair-transaction-package.json").read_text())
    assert artifact["summary"]["transaction_count"] == 2
    assert artifact["mutation_performed"] is False
    assert artifact["executable_by_tool"] is False

    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    before_report = {
        "command": "report local-network",
        "evidence": [],
        "networkextension_repair_transaction_package_summary": {
            "transaction_ids": ["old-transaction"],
            "transaction_count": 1,
            "preview_only_transactions": 1,
            "backup_required_count": 1,
            "rollback_required_count": 1,
            "validation_status_counts": {"stale_code_sign_clone": 1},
        },
    }
    after_report = {
        "command": "report local-network",
        "evidence": [],
        "networkextension_repair_transaction_package_summary": {
            "transaction_ids": ["new-transaction"],
            "transaction_count": 1,
            "preview_only_transactions": 1,
            "backup_required_count": 1,
            "rollback_required_count": 1,
            "validation_status_counts": {"stale_missing_executable": 1},
        },
    }
    (before / "report.json").write_text(json.dumps(before_report, sort_keys=True))
    (after / "report.json").write_text(json.dumps(after_report, sort_keys=True))

    diff_json = CliRunner().invoke(app, ["diff", "bundles", str(before), str(after), "--json"])
    assert diff_json.exit_code == 0
    diff = json.loads(diff_json.stdout)
    package_diff = diff["networkextension_repair_transaction_package_diff"]
    assert package_diff["added_transaction_ids"] == ["new-transaction"]
    assert package_diff["removed_transaction_ids"] == ["old-transaction"]
    assert package_diff["changed_validation_statuses"] == ["stale_code_sign_clone", "stale_missing_executable"]
    diff_text = CliRunner().invoke(app, ["diff", "bundles", str(before), str(after)]).stdout
    assert "NetworkExtension Repair Transaction Package Diff" in diff_text
    assert "Added transactions: new-transaction" in diff_text
