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
from macos_state_explorer.networkextension_repair_simulation import build_networkextension_repair_simulation
from macos_state_explorer.reports.local_network import build_local_network_report, write_local_network_support_bundle


def snapshot_with_launchservices(entries: list[dict] | None = None) -> Snapshot:
    return Snapshot(
        host="repair-simulation-host",
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
        {"ClientIdentities": plistlib.UID(2), "Metadata": {"Keep": plistlib.UID(4)}},
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


def test_repair_simulation_json_contract_is_read_only_and_deterministic(tmp_path):
    fixture = write_candidate_fixture(tmp_path / "ne")
    runbook = build_runbook(fixture["root"])

    first = build_networkextension_repair_simulation(runbook, [fixture["root"]]).to_json_dict()
    second = build_networkextension_repair_simulation(runbook, [fixture["root"]]).to_json_dict()

    assert first == second
    assert list(first)[:14] == [
        "command",
        "repair_simulation_id",
        "timestamp",
        "read_only",
        "mutation_performed",
        "system_artifact_modified",
        "executable_by_tool",
        "automatic_execution_recommendation",
        "input_transactions",
        "simulated_transactions",
        "simulation_results",
        "removed_object_refs",
        "uid_rewrite_summary",
        "array_change_summary",
    ]
    assert first["command"] == "networkextension repair-simulation"
    assert first["read_only"] is True
    assert first["mutation_performed"] is False
    assert first["system_artifact_modified"] is False
    assert first["executable_by_tool"] is False
    assert first["automatic_execution_recommendation"] == "never"
    assert first["input_transactions"] == 2
    assert first["simulated_transactions"] == 2
    assert first["removed_object_refs"] == ["$objects[7]", "$objects[8]", "$objects[9]", "$objects[10]"]
    assert first["uid_rewrite_summary"]["rewrite_count"] > 0
    assert first["array_change_summary"]["array_changes"] > 0
    assert first["dictionary_change_summary"]["dictionary_changes"] >= 0
    assert first["serialization"]["success"] is True
    assert first["reparse"]["success"] is True
    assert first["post_simulation_validation"]["candidate_count"] < 4
    assert first["safety_verdict"] == "simulation_passed"

    assert fixture["artifact"].exists()
    original = plistlib.load(fixture["artifact"].open("rb"))
    assert len(original["$objects"]) == 13


def test_repair_simulation_cli_text_and_json_output_are_non_mutating(monkeypatch, tmp_path):
    fixture = write_candidate_fixture(tmp_path / "ne")
    monkeypatch.setattr("macos_state_explorer.networkextension_candidate_validation._process_rows", lambda: [])

    json_result = CliRunner().invoke(app, ["networkextension", "repair-simulation", "--root", str(fixture["root"]), "--json"])
    assert json_result.exit_code == 0
    payload = json.loads(json_result.stdout)
    assert payload["read_only"] is True
    assert payload["mutation_performed"] is False
    assert payload["system_artifact_modified"] is False
    assert payload["executable_by_tool"] is False
    assert payload["safety_verdict"] == "simulation_passed"

    text_result = CliRunner().invoke(app, ["networkextension", "repair-simulation", "--root", str(fixture["root"])])
    assert text_result.exit_code == 0
    assert "NetworkExtension repair simulation" in text_result.stdout
    assert "Read-only: true" in text_result.stdout
    assert "Mutation performed: false" in text_result.stdout
    assert "System artifact modified: false" in text_result.stdout
    assert "Input transactions: 2" in text_result.stdout
    assert "Simulated transactions: 2" in text_result.stdout
    assert "Removed objects: 4" in text_result.stdout
    assert "UID rewrites:" in text_result.stdout
    assert "Array changes:" in text_result.stdout
    assert "Dictionary changes:" in text_result.stdout
    assert "Serialization: success" in text_result.stdout
    assert "Re-parse: success" in text_result.stdout
    assert "Post-simulation candidates:" in text_result.stdout
    assert "Safety verdict: simulation_passed" in text_result.stdout
    assert "does not execute a repair" in text_result.stdout
    forbidden = ["defaults write", "defaults delete", "plistbuddy", "killall", "sudo rm", "rm -rf", "tccutil reset"]
    lowered = text_result.stdout.lower()
    for token in forbidden:
        assert token not in lowered


def test_repair_simulation_handles_missing_and_broken_inputs(tmp_path):
    missing_root = tmp_path / "missing-root"
    missing_runbook = build_runbook(missing_root)
    missing_payload = build_networkextension_repair_simulation(missing_runbook, [missing_root]).to_json_dict()
    assert missing_payload["input_transactions"] == 0
    assert missing_payload["simulated_transactions"] == 0
    assert missing_payload["safety_verdict"] == "simulation_inconclusive"
    assert missing_payload["serialization"]["success"] is False
    assert missing_payload["reparse"]["success"] is False

    broken_root = tmp_path / "broken"
    prefs = broken_root / "Library" / "Preferences"
    prefs.mkdir(parents=True)
    (prefs / "com.apple.networkextension.plist").write_text("not a plist", encoding="utf-8")
    broken_runbook = build_runbook(broken_root)
    broken_payload = build_networkextension_repair_simulation(broken_runbook, [broken_root]).to_json_dict()
    assert broken_payload["safety_verdict"] in {"simulation_failed", "simulation_inconclusive"}
    assert broken_payload["read_only"] is True
    assert broken_payload["system_artifact_modified"] is False


def test_report_bundle_and_diff_include_repair_simulation(monkeypatch, tmp_path):
    fixture = write_candidate_fixture(tmp_path / "ne")
    monkeypatch.setattr("macos_state_explorer.reports.local_network.default_networkextension_roots", lambda: [fixture["root"]])
    monkeypatch.setattr("macos_state_explorer.networkextension_candidate_validation._process_rows", lambda: [])
    report = build_local_network_report(snapshot_with_launchservices())

    payload = report.to_json_dict()
    summary = payload["networkextension_repair_simulation_summary"]
    assert summary["input_transactions"] == 2
    assert summary["simulated_transactions"] == 2
    assert summary["read_only"] is True
    assert "NetworkExtension repair simulation" in report.render_text()

    bundle = write_local_network_support_bundle(report, tmp_path / "bundle", branch_id="manual-empty-trash-reboot")
    assert (bundle / "networkextension-repair-simulation.json").exists()
    assert (bundle / "networkextension-repair-simulation.txt").exists()
    artifact = json.loads((bundle / "networkextension-repair-simulation.json").read_text())
    assert artifact["safety_verdict"] == "simulation_passed"
    assert artifact["mutation_performed"] is False

    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    (before / "report.json").write_text(json.dumps({
        "command": "report local-network",
        "evidence": [],
        "networkextension_repair_simulation_summary": {
            "repair_simulation_ids": ["old-simulation"],
            "input_transactions": 1,
            "simulated_transactions": 0,
            "removed_object_count": 0,
            "uid_rewrite_count": 0,
            "array_changes": 0,
            "dictionary_changes": 0,
            "safety_verdict": "simulation_inconclusive",
        },
    }, sort_keys=True))
    (after / "report.json").write_text(json.dumps({
        "command": "report local-network",
        "evidence": [],
        "networkextension_repair_simulation_summary": {
            "repair_simulation_ids": ["new-simulation"],
            "input_transactions": 2,
            "simulated_transactions": 2,
            "removed_object_count": 4,
            "uid_rewrite_count": 8,
            "array_changes": 1,
            "dictionary_changes": 0,
            "safety_verdict": "simulation_passed",
        },
    }, sort_keys=True))

    diff_json = CliRunner().invoke(app, ["diff", "bundles", str(before), str(after), "--json"])
    assert diff_json.exit_code == 0
    diff = json.loads(diff_json.stdout)
    simulation_diff = diff["networkextension_repair_simulation_diff"]
    assert simulation_diff["added_simulation_ids"] == ["new-simulation"]
    assert simulation_diff["removed_simulation_ids"] == ["old-simulation"]
    assert simulation_diff["safety_verdict_before"] == "simulation_inconclusive"
    assert simulation_diff["safety_verdict_after"] == "simulation_passed"
    assert simulation_diff["removed_object_count_delta"] == 4
    diff_text = CliRunner().invoke(app, ["diff", "bundles", str(before), str(after)]).stdout
    assert "NetworkExtension Repair Simulation Diff" in diff_text
    assert "Safety verdict: simulation_inconclusive → simulation_passed" in diff_text
