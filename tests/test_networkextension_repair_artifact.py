from __future__ import annotations

import json
import plistlib
from pathlib import Path

from typer.testing import CliRunner

from macos_state_explorer.cli import app
from macos_state_explorer.core.model import Observation, Snapshot
from macos_state_explorer.networkextension_candidate_validation import build_networkextension_candidate_validation
from macos_state_explorer.networkextension_manual_repair_runbook import build_networkextension_manual_repair_runbook
from macos_state_explorer.networkextension_repair_artifact import build_networkextension_repair_artifact
from macos_state_explorer.networkextension_repair_plan_preview import build_networkextension_repair_plan_preview
from macos_state_explorer.networkextension_repair_simulation import build_networkextension_repair_simulation
from macos_state_explorer.networkextension_repair_transaction_package import build_networkextension_repair_transaction_package
from macos_state_explorer.reports.local_network import build_local_network_report, write_local_network_support_bundle


def snapshot_with_launchservices(entries: list[dict] | None = None) -> Snapshot:
    return Snapshot(
        host="repair-artifact-host",
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


def test_generate_repair_artifact_json_contract_and_reparse_are_deterministic(tmp_path):
    fixture = write_candidate_fixture(tmp_path / "ne")
    runbook = build_runbook(fixture["root"])
    simulation = build_networkextension_repair_simulation(runbook, [fixture["root"]])
    output = tmp_path / "generated" / "networkextension-repaired.plist"

    first = build_networkextension_repair_artifact(runbook, simulation, output, [fixture["root"]]).to_json_dict()
    second = build_networkextension_repair_artifact(runbook, simulation, output, [fixture["root"]]).to_json_dict()

    assert first == second
    assert list(first)[:13] == [
        "command",
        "repair_artifact_id",
        "timestamp",
        "read_only",
        "mutation_performed",
        "system_artifact_modified",
        "executable_by_tool",
        "offline_generated",
        "installed",
        "automatic_execution_recommendation",
        "output_path",
        "source_artifact",
        "source_sha256",
    ]
    assert first["command"] == "networkextension generate-repair-artifact"
    assert first["read_only"] is True
    assert first["mutation_performed"] is False
    assert first["system_artifact_modified"] is False
    assert first["executable_by_tool"] is False
    assert first["offline_generated"] is True
    assert first["installed"] is False
    assert first["automatic_execution_recommendation"] == "never"
    assert first["simulation"]["safety_verdict"] == "simulation_passed"
    assert first["validation_result"] == "artifact_generated"
    assert first["reparse"]["success"] is True
    assert first["removed_object_refs"] == ["$objects[7]", "$objects[8]", "$objects[9]", "$objects[10]"]
    assert first["uid_rewrite_count"] > 0
    assert first["array_change_count"] > 0
    assert len(first["source_sha256"]) == 64
    assert len(first["generated_artifact_sha256"]) == 64
    assert output.exists()
    reparsed = plistlib.load(output.open("rb"))
    assert len(reparsed["$objects"]) == 9
    assert plistlib.load(fixture["artifact"].open("rb"))["$objects"][8]["SigningIdentifier"] == "com.google.Chrome.code_sign_clone"


def test_generate_repair_artifact_cli_text_and_json_are_offline_only(monkeypatch, tmp_path):
    fixture = write_candidate_fixture(tmp_path / "ne")
    monkeypatch.setattr("macos_state_explorer.networkextension_candidate_validation._process_rows", lambda: [])
    output = tmp_path / "offline" / "repair-output.plist"

    json_result = CliRunner().invoke(app, ["networkextension", "generate-repair-artifact", "--root", str(fixture["root"]), "--output", str(output), "--json"])
    assert json_result.exit_code == 0
    payload = json.loads(json_result.stdout)
    assert payload["read_only"] is True
    assert payload["mutation_performed"] is False
    assert payload["system_artifact_modified"] is False
    assert payload["offline_generated"] is True
    assert payload["installed"] is False
    assert payload["validation_result"] == "artifact_generated"
    assert payload["output_path"] == str(output)
    assert output.exists()

    text_output = tmp_path / "offline" / "repair-output-text.plist"
    text_result = CliRunner().invoke(app, ["networkextension", "generate-repair-artifact", "--root", str(fixture["root"]), "--output", str(text_output)])
    assert text_result.exit_code == 0
    assert "NetworkExtension generated repair artifact" in text_result.stdout
    assert "Read-only: true" in text_result.stdout
    assert "Mutation performed: false" in text_result.stdout
    assert "System artifact modified: false" in text_result.stdout
    assert "Offline/generated/not installed: true" in text_result.stdout
    assert "Simulation verdict: simulation_passed" in text_result.stdout
    assert "Validation result: artifact_generated" in text_result.stdout
    assert "not install or repair" in text_result.stdout
    for token in ["defaults write", "defaults delete", "killall", "sudo rm", "rm -rf", "tccutil reset"]:
        assert token not in text_result.stdout.lower()


def test_generate_repair_artifact_rejects_protected_and_live_paths(tmp_path):
    fixture = write_candidate_fixture(tmp_path / "ne")
    runbook = build_runbook(fixture["root"])
    simulation = build_networkextension_repair_simulation(runbook, [fixture["root"]])

    for protected in [
        Path("/Library/Preferences/com.apple.networkextension.plist"),
        Path("/System/Library/com.apple.networkextension.plist"),
        Path("/private/var/db/com.apple.networkextension.plist"),
        fixture["artifact"],
    ]:
        try:
            build_networkextension_repair_artifact(runbook, simulation, protected, [fixture["root"]])
        except ValueError as error:
            assert "refusing protected or live output path" in str(error)
        else:  # pragma: no cover - asserted by failing test
            raise AssertionError(f"protected path accepted: {protected}")
        if protected == fixture["artifact"]:
            assert protected.exists()


def test_generate_repair_artifact_fails_closed_when_simulation_is_not_successful(tmp_path):
    missing_root = tmp_path / "missing-root"
    runbook = build_runbook(missing_root)
    simulation = build_networkextension_repair_simulation(runbook, [missing_root])
    output = tmp_path / "should-not-exist.plist"

    try:
        build_networkextension_repair_artifact(runbook, simulation, output, [missing_root])
    except ValueError as error:
        assert "simulation_passed required" in str(error)
    else:  # pragma: no cover - asserted by failing test
        raise AssertionError("inconclusive simulation generated an artifact")
    assert not output.exists()


def test_report_bundle_and_diff_include_generated_repair_artifact(monkeypatch, tmp_path):
    fixture = write_candidate_fixture(tmp_path / "ne")
    monkeypatch.setattr("macos_state_explorer.reports.local_network.default_networkextension_roots", lambda: [fixture["root"]])
    monkeypatch.setattr("macos_state_explorer.networkextension_candidate_validation._process_rows", lambda: [])
    report = build_local_network_report(snapshot_with_launchservices())

    payload = report.to_json_dict()
    summary = payload["networkextension_repair_artifact_summary"]
    assert summary["validation_result"] == "artifact_generated"
    assert summary["read_only"] is True
    assert summary["mutation_performed"] is False
    assert summary["system_artifact_modified"] is False
    assert "NetworkExtension generated repair artifact" in report.render_text()

    bundle = write_local_network_support_bundle(report, tmp_path / "bundle", branch_id="manual-empty-trash-reboot")
    assert (bundle / "networkextension-repair-artifact.json").exists()
    assert (bundle / "networkextension-repair-artifact.txt").exists()
    assert (bundle / "networkextension-repair-artifact.plist").exists()
    metadata = json.loads((bundle / "networkextension-repair-artifact.json").read_text())
    assert metadata["validation_result"] == "artifact_generated"
    assert plistlib.load((bundle / "networkextension-repair-artifact.plist").open("rb"))["$objects"]

    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    (before / "report.json").write_text(json.dumps({
        "command": "report local-network",
        "evidence": [],
        "networkextension_repair_artifact_summary": {
            "repair_artifact_ids": ["old-artifact"],
            "validation_result": "not_generated",
            "removed_object_count": 0,
            "generated_artifact_sha256": "old",
        },
    }, sort_keys=True))
    (after / "report.json").write_text(json.dumps({
        "command": "report local-network",
        "evidence": [],
        "networkextension_repair_artifact_summary": {
            "repair_artifact_ids": ["new-artifact"],
            "validation_result": "artifact_generated",
            "removed_object_count": 4,
            "uid_rewrite_count": 8,
            "array_change_count": 1,
            "dictionary_change_count": 0,
            "generated_artifact_sha256": "new",
        },
    }, sort_keys=True))

    diff_json = CliRunner().invoke(app, ["diff", "bundles", str(before), str(after), "--json"])
    assert diff_json.exit_code == 0
    diff = json.loads(diff_json.stdout)
    artifact_diff = diff["networkextension_repair_artifact_diff"]
    assert artifact_diff["added_artifact_ids"] == ["new-artifact"]
    assert artifact_diff["removed_artifact_ids"] == ["old-artifact"]
    assert artifact_diff["validation_result_before"] == "not_generated"
    assert artifact_diff["validation_result_after"] == "artifact_generated"
    assert artifact_diff["removed_object_count_delta"] == 4
    diff_text = CliRunner().invoke(app, ["diff", "bundles", str(before), str(after)]).stdout
    assert "NetworkExtension Repair Artifact Diff" in diff_text
    assert "Validation result: not_generated → artifact_generated" in diff_text
