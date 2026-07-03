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
from macos_state_explorer.networkextension_manual_repair_runbook import build_networkextension_manual_repair_runbook
from macos_state_explorer.reports.local_network import build_local_network_report, write_local_network_support_bundle


def snapshot_with_launchservices(entries: list[dict] | None = None) -> Snapshot:
    return Snapshot(
        host="manual-repair-runbook-host",
        created_at=123.0,
        observations=[
            Observation(collector="tcc", started_at=1, ended_at=2, payload={"direct_localnetwork_query": {"stdout": ""}, "user_tcc": {"hits": []}}),
            Observation(collector="launchservices", started_at=1, ended_at=2, payload={"entries": entries or []}),
        ],
    )


def write_candidate_fixture(root: Path, *, include_second_stale: bool = True) -> dict[str, Path]:
    prefs = root / "Library" / "Preferences"
    prefs.mkdir(parents=True)
    installed_exe = root / "Applications" / "Google Chrome.app" / "Contents" / "MacOS" / "Google Chrome"
    installed_exe.parent.mkdir(parents=True)
    installed_exe.write_text("#!/bin/sh\n", encoding="utf-8")
    installed_absent = root / "Applications" / "Absent Chrome.app" / "Contents" / "MacOS" / "Google Chrome"
    installed_absent.parent.mkdir(parents=True)
    missing_clone = root / "private" / "var" / "folders" / "xx" / "com.google.Chrome.code_sign_clone" / "Contents" / "MacOS" / "Google Chrome"
    missing_normal = root / "Applications" / "Missing Chrome.app" / "Contents" / "MacOS" / "Google Chrome"
    objects = [
        "$null",
        {"ClientIdentities": plistlib.UID(2)},
        [plistlib.UID(3), plistlib.UID(5), plistlib.UID(7), plistlib.UID(9), plistlib.UID(11)],
        {"ClientIdentity": plistlib.UID(4), "State": "active"},
        {"SigningIdentifier": "com.google.Chrome", "Path": str(installed_exe), "Kind": "client identity active"},
        {"ClientIdentity": plistlib.UID(6), "State": "installed absent"},
        {"SigningIdentifier": "com.google.Chrome", "Path": str(installed_absent), "Kind": "client identity installed absent"},
        {"ClientIdentity": plistlib.UID(8), "State": "historical"},
        {"SigningIdentifier": "com.google.Chrome.code_sign_clone", "Path": str(missing_clone), "Kind": "client identity clone"},
    ]
    if include_second_stale:
        objects.extend([
            {"ClientIdentity": plistlib.UID(10), "State": "orphaned"},
            {"SigningIdentifier": "com.google.Chrome", "Path": str(missing_normal), "Kind": "client identity missing"},
        ])
    objects.extend([
        {"ClientIdentity": plistlib.UID(12), "State": "incomplete"},
        {"SigningIdentifier": "com.google.Chrome", "Kind": "client identity incomplete"},
    ])
    artifact = prefs / "com.apple.networkextension.plist"
    archive = {"$archiver": "NSKeyedArchiver", "$version": 100000, "$top": {"root": plistlib.UID(1)}, "$objects": objects}
    with artifact.open("wb") as handle:
        plistlib.dump(archive, handle, fmt=plistlib.FMT_BINARY, sort_keys=True)
    return {"root": root, "artifact": artifact}


def build_runbook(root: Path):
    validation = build_networkextension_candidate_validation([root], process_rows=[])
    preview = build_networkextension_repair_plan_preview(validation)
    package = build_networkextension_repair_transaction_package(preview, [root])
    return build_networkextension_manual_repair_runbook(package, [root])


def test_manual_repair_runbook_single_transaction_schema_and_safety(tmp_path):
    fixture = write_candidate_fixture(tmp_path / "ne", include_second_stale=False)

    first = build_runbook(fixture["root"]).to_json_dict()
    second = build_runbook(fixture["root"]).to_json_dict()

    assert first == second
    assert list(first)[:10] == [
        "command",
        "manual_repair_runbook_id",
        "timestamp",
        "read_only",
        "mutation_performed",
        "executable_by_tool",
        "automatic_execution_recommendation",
        "source_transaction_package_id",
        "summary",
        "operator_warning",
    ]
    assert first["command"] == "networkextension manual-repair-runbook"
    assert first["read_only"] is True
    assert first["mutation_performed"] is False
    assert first["executable_by_tool"] is False
    assert first["automatic_execution_recommendation"] == "never"
    assert first["operator_warning"] == "Generated operator specification only; macos-state-explorer will not execute this repair."
    assert first["summary"]["transaction_count"] == 1
    assert first["summary"]["difficulty_counts"] == {"high": 1}
    assert first["summary"]["requires_archive_regeneration_count"] == 1
    assert "broken UID graph" in first["failure_modes"]
    assert first["rollback_plan"][0] == "Restore the original plist artifact from backup."
    assert first["post_repair_validation_commands"] == [
        "mse networkextension validate-candidates",
        "mse networkextension repair-plan-preview",
        "mse networkextension repair-transaction-package",
        "mse networkextension manual-repair-runbook",
        "mse networkextension object-graph",
        "mse networkextension raw-references",
        "mse report local-network --bundle ~/Desktop/mse-local-network-post-repair-bundle",
        "mse diff bundles ~/Desktop/mse-local-network-pre-repair-bundle ~/Desktop/mse-local-network-post-repair-bundle",
    ]

    transaction = first["transactions"][0]
    assert transaction["repair_class"] == "manual_nskeyedarchiver_object_graph_rewrite"
    assert transaction["difficulty"] == "high"
    assert transaction["expected_mutation"] == "manual_object_graph_edit_specification_only"
    assert transaction["expected_object_removal"]
    assert transaction["expected_object_rewrite"]
    assert transaction["expected_uid_rewiring"]
    assert transaction["expected_array_changes"]
    assert transaction["expected_dictionary_changes"]
    assert transaction["expected_object_count_delta"] < 0
    assert "$objects[0]" in transaction["objects_that_must_remain_untouched"]
    assert transaction["objects_requiring_reindexing"]
    assert transaction["objects_requiring_uid_remapping"]
    assert transaction["objects_requiring_archive_regeneration"]
    assert transaction["safety_analysis"]["archive_rebuild"] is True
    assert transaction["safety_analysis"]["uid_rewrite"] is True
    assert transaction["safety_analysis"]["array_compaction"] is True
    assert transaction["safety_analysis"]["cross_reference_update"] is True
    assert "array compaction" in transaction["difficulty_explanation"]
    assert "invalid NSKeyedArchiver archive" in transaction["failure_modes"]
    assert transaction["rollback_requirements"] == [
        "Restore original plist artifact from backup.",
        "Reboot before rechecking NetworkExtension/System Settings state.",
        "Verify restored artifact SHA256 matches the pre-repair hash.",
    ]
    assert transaction["expected_verification_outcome"] == "candidate absent from validation and transaction package after manual edit; no new object graph errors."
    assert transaction["not_executable_by_tool"] is True
    assert transaction["mutation_performed"] is False

    detail = transaction["affected_objects"][0]
    assert detail["object_index"] >= 0
    assert detail["object_class"] in {"dict", "list", "str"}
    assert detail["parent_chain"]
    assert "referenced_uids" in detail
    assert "referencing_objects" in detail
    assert "dictionary_keys" in detail
    assert "array_memberships" in detail
    assert "incoming_references" in detail
    assert "outgoing_references" in detail
    assert "dependency_graph" in detail
    assert detail["can_be_deleted_independently"] is False
    assert detail["requires_graph_rewrite"] is True


def test_manual_repair_runbook_multiple_transactions_cli_text_is_non_mutating(monkeypatch, tmp_path):
    fixture = write_candidate_fixture(tmp_path / "ne", include_second_stale=True)
    monkeypatch.setattr("macos_state_explorer.networkextension_candidate_validation._process_rows", lambda: [])

    json_result = CliRunner().invoke(app, ["networkextension", "manual-repair-runbook", "--root", str(fixture["root"]), "--json"])
    assert json_result.exit_code == 0
    payload = json.loads(json_result.stdout)
    assert payload["summary"]["transaction_count"] == 2
    assert payload["summary"]["manual_only"] is True
    assert payload["summary"]["mutation_performed"] is False
    assert [item["validation_status"] for item in payload["transactions"]] == ["stale_code_sign_clone", "stale_missing_executable"]

    text_result = CliRunner().invoke(app, ["networkextension", "manual-repair-runbook", "--root", str(fixture["root"])])
    assert text_result.exit_code == 0
    assert "NetworkExtension manual repair runbook" in text_result.stdout
    assert "Mutation performed: false" in text_result.stdout
    assert "Executable by tool: false" in text_result.stdout
    assert "Automatic execution recommendation: never" in text_result.stdout
    assert "Failure modes" in text_result.stdout
    assert "Rollback procedure" in text_result.stdout
    assert "Post-repair validation commands" in text_result.stdout
    forbidden = ["defaults write", "defaults delete", "plistbuddy", "killall", "rm ", "repair --confirm", "execute repair", "automatic execution recommended"]
    lowered = text_result.stdout.lower()
    for token in forbidden:
        assert token not in lowered


def test_report_bundle_and_diff_include_manual_repair_runbook(monkeypatch, tmp_path):
    fixture = write_candidate_fixture(tmp_path / "ne")
    monkeypatch.setattr("macos_state_explorer.reports.local_network.default_networkextension_roots", lambda: [fixture["root"]])
    monkeypatch.setattr("macos_state_explorer.networkextension_candidate_validation._process_rows", lambda: [])
    report = build_local_network_report(snapshot_with_launchservices())

    payload = report.to_json_dict()
    assert payload["networkextension_manual_repair_runbook_summary"]["transaction_count"] == 2
    assert "NetworkExtension manual repair runbook" in report.render_text()

    bundle = write_local_network_support_bundle(report, tmp_path / "bundle", branch_id="manual-empty-trash-reboot")
    assert (bundle / "networkextension-manual-repair-runbook.json").exists()
    assert (bundle / "networkextension-manual-repair-runbook.txt").exists()
    artifact = json.loads((bundle / "networkextension-manual-repair-runbook.json").read_text())
    assert artifact["summary"]["transaction_count"] == 2
    assert artifact["mutation_performed"] is False
    assert artifact["executable_by_tool"] is False

    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    (before / "report.json").write_text(json.dumps({
        "command": "report local-network",
        "evidence": [],
        "networkextension_manual_repair_runbook_summary": {
            "runbook_ids": ["old-runbook"],
            "transaction_count": 1,
            "difficulty_counts": {"medium": 1},
            "requires_archive_regeneration_count": 1,
            "manual_only": True,
            "mutation_performed": False,
        },
    }, sort_keys=True))
    (after / "report.json").write_text(json.dumps({
        "command": "report local-network",
        "evidence": [],
        "networkextension_manual_repair_runbook_summary": {
            "runbook_ids": ["new-runbook"],
            "transaction_count": 1,
            "difficulty_counts": {"high": 1},
            "requires_archive_regeneration_count": 1,
            "manual_only": True,
            "mutation_performed": False,
        },
    }, sort_keys=True))

    diff_json = CliRunner().invoke(app, ["diff", "bundles", str(before), str(after), "--json"])
    assert diff_json.exit_code == 0
    diff = json.loads(diff_json.stdout)
    runbook_diff = diff["networkextension_manual_repair_runbook_diff"]
    assert runbook_diff["added_runbook_ids"] == ["new-runbook"]
    assert runbook_diff["removed_runbook_ids"] == ["old-runbook"]
    assert runbook_diff["changed_difficulties"] == ["high", "medium"]
    diff_text = CliRunner().invoke(app, ["diff", "bundles", str(before), str(after)]).stdout
    assert "NetworkExtension Manual Repair Runbook Diff" in diff_text
    assert "Added runbooks: new-runbook" in diff_text
