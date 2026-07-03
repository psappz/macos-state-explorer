from __future__ import annotations

import json
import plistlib
from pathlib import Path

from typer.testing import CliRunner

from macos_state_explorer.cli import app
from macos_state_explorer.core.model import Observation, Snapshot
from macos_state_explorer.networkextension_apply_validation import validate_networkextension_apply
from macos_state_explorer.networkextension_candidate_validation import build_networkextension_candidate_validation
from macos_state_explorer.networkextension_manual_repair_runbook import build_networkextension_manual_repair_runbook
from macos_state_explorer.networkextension_repair_artifact import build_networkextension_repair_artifact
from macos_state_explorer.networkextension_repair_plan_preview import build_networkextension_repair_plan_preview
from macos_state_explorer.networkextension_repair_simulation import build_networkextension_repair_simulation
from macos_state_explorer.networkextension_repair_transaction_package import build_networkextension_repair_transaction_package
from macos_state_explorer.reports.local_network import build_local_network_report, write_local_network_support_bundle


def write_candidate_fixture(root: Path) -> dict[str, Path]:
    prefs = root / "Library" / "Preferences"
    prefs.mkdir(parents=True)
    installed_exe = root / "Applications" / "Google Chrome.app" / "Contents" / "MacOS" / "Google Chrome"
    installed_exe.parent.mkdir(parents=True)
    installed_exe.write_text("#!/bin/sh\n", encoding="utf-8")
    missing_clone = root / "private" / "var" / "folders" / "xx" / "com.google.Chrome.code_sign_clone" / "Contents" / "MacOS" / "Google Chrome"
    missing_normal = root / "Applications" / "Missing Chrome.app" / "Contents" / "MacOS" / "Google Chrome"
    objects = [
        "$null",
        {"ClientIdentities": plistlib.UID(2)},
        [plistlib.UID(3), plistlib.UID(5), plistlib.UID(7), plistlib.UID(9)],
        {"ClientIdentity": plistlib.UID(4), "State": "active"},
        {"SigningIdentifier": "com.google.Chrome", "Path": str(installed_exe)},
        {"ClientIdentity": plistlib.UID(6), "State": "historical"},
        {"SigningIdentifier": "com.google.Chrome.code_sign_clone", "Path": str(missing_clone)},
        {"ClientIdentity": plistlib.UID(8), "State": "orphaned"},
        {"SigningIdentifier": "com.google.Chrome", "Path": str(missing_normal)},
        {"ClientIdentity": plistlib.UID(10), "State": "stale"},
        {"SigningIdentifier": "com.google.Chrome", "Path": str(missing_normal)},
    ]
    artifact = prefs / "com.apple.networkextension.plist"
    with artifact.open("wb") as handle:
        plistlib.dump({"$archiver": "NSKeyedArchiver", "$version": 100000, "$top": {"root": plistlib.UID(1)}, "$objects": objects}, handle, fmt=plistlib.FMT_BINARY, sort_keys=True)
    return {"root": root, "source": artifact}


def generated_repaired_artifact(tmp_path: Path) -> dict[str, Path]:
    fixture = write_candidate_fixture(tmp_path / "ne")
    validation = build_networkextension_candidate_validation([fixture["root"]], process_rows=[])
    preview = build_networkextension_repair_plan_preview(validation)
    package = build_networkextension_repair_transaction_package(preview, [fixture["root"]])
    runbook = build_networkextension_manual_repair_runbook(package, [fixture["root"]])
    simulation = build_networkextension_repair_simulation(runbook, [fixture["root"]])
    artifact_path = tmp_path / "generated" / "networkextension-repair-artifact.plist"
    artifact = build_networkextension_repair_artifact(runbook, simulation, artifact_path, [fixture["root"]])
    metadata = artifact_path.with_suffix(".json")
    metadata.write_text(json.dumps(artifact.to_json_dict(), sort_keys=True), encoding="utf-8")
    return {"root": fixture["root"], "source": fixture["source"], "artifact": artifact_path, "metadata": metadata}


def test_apply_validation_passes_for_target_identical_to_generated_artifact(tmp_path):
    fixture = generated_repaired_artifact(tmp_path)
    fixture["source"].write_bytes(fixture["artifact"].read_bytes())

    result = validate_networkextension_apply(fixture["source"], fixture["artifact"], metadata_path=fixture["metadata"])
    payload = result.to_json_dict()

    assert list(payload)[:12] == [
        "command",
        "timestamp",
        "read_only",
        "mutation_performed",
        "target_path",
        "artifact_path",
        "metadata_path",
        "overall_verdict",
        "validation_stages",
        "statistics",
        "hash_comparison",
        "failure",
    ]
    assert payload["read_only"] is True
    assert payload["mutation_performed"] is False
    assert payload["overall_verdict"] == "VALIDATION_PASSED"
    assert all(stage["status"] == "PASS" for stage in payload["validation_stages"])
    assert payload["statistics"]["repair_candidates_remaining"] == 0
    assert payload["statistics"]["validation_candidates_remaining"] == 0
    assert payload["hash_comparison"]["sha256_identical"] is True
    assert payload["hash_comparison"]["serialization_identical"] is True
    assert payload["hash_comparison"]["object_graph_identical"] is True


def test_apply_validation_reports_failure_stage_and_rollback_guidance(tmp_path):
    fixture = generated_repaired_artifact(tmp_path)
    target_before = fixture["source"].read_bytes()
    artifact_before = fixture["artifact"].read_bytes()

    payload = validate_networkextension_apply(fixture["source"], fixture["artifact"], metadata_path=fixture["metadata"]).to_json_dict()

    assert payload["overall_verdict"] == "VALIDATION_FAILED"
    assert payload["mutation_performed"] is False
    assert payload["failure"]["stage"] == "compare_repaired_with_generated_artifact"
    assert payload["failure"]["expected"] == "identical"
    assert payload["failure"]["observed"] == "different"
    assert "restore the pre-apply backup" in payload["failure"]["recommended_rollback_action"]
    assert fixture["source"].read_bytes() == target_before
    assert fixture["artifact"].read_bytes() == artifact_before


def test_apply_validation_detects_broken_uid_references(tmp_path):
    artifact = tmp_path / "artifact.plist"
    target = tmp_path / "target.plist"
    malformed = {"$archiver": "NSKeyedArchiver", "$version": 100000, "$top": {"root": plistlib.UID(99)}, "$objects": ["$null"]}
    target.write_bytes(plistlib.dumps(malformed, fmt=plistlib.FMT_BINARY, sort_keys=True))
    artifact.write_bytes(target.read_bytes())

    payload = validate_networkextension_apply(target, artifact).to_json_dict()

    assert payload["overall_verdict"] == "VALIDATION_FAILED"
    assert payload["failure"]["stage"] == "no_broken_uid_references"
    assert payload["statistics"]["broken_uid_references"] == 1
    assert payload["statistics"]["graph_consistency"] == "FAILED"


def test_apply_validation_cli_text_and_json(tmp_path):
    fixture = generated_repaired_artifact(tmp_path)
    fixture["source"].write_bytes(fixture["artifact"].read_bytes())

    json_result = CliRunner().invoke(app, ["networkextension", "apply-validation", "--target", str(fixture["source"]), "--artifact", str(fixture["artifact"]), "--metadata", str(fixture["metadata"]), "--json"])
    assert json_result.exit_code == 0
    payload = json.loads(json_result.stdout)
    assert payload["overall_verdict"] == "VALIDATION_PASSED"
    assert payload["statistics"]["object_count"] > 0

    text_result = CliRunner().invoke(app, ["networkextension", "apply-validation", "--target", str(fixture["source"]), "--artifact", str(fixture["artifact"]), "--metadata", str(fixture["metadata"])])
    assert text_result.exit_code == 0
    assert "NetworkExtension apply validation" in text_result.stdout
    assert "Overall verdict: VALIDATION_PASSED" in text_result.stdout
    assert "repair_candidates_zero: PASS" in text_result.stdout


def test_apply_validation_report_bundle_and_diff(monkeypatch, tmp_path):
    fixture = generated_repaired_artifact(tmp_path)
    fixture["source"].write_bytes(fixture["artifact"].read_bytes())
    monkeypatch.setattr("macos_state_explorer.reports.local_network.DEFAULT_APPLY_VALIDATION_TARGET", fixture["source"])
    monkeypatch.setattr("macos_state_explorer.reports.local_network.DEFAULT_APPLY_VALIDATION_ARTIFACT", fixture["artifact"])
    monkeypatch.setattr("macos_state_explorer.reports.local_network.DEFAULT_APPLY_VALIDATION_METADATA", fixture["metadata"])

    report = build_local_network_report(Snapshot(host="h", created_at=1, observations=[Observation(collector="launchservices", started_at=1, ended_at=1, payload={"entries": []})]))
    payload = report.to_json_dict()
    assert payload["networkextension_apply_validation_summary"]["overall_verdict"] == "VALIDATION_PASSED"

    bundle = write_local_network_support_bundle(report, tmp_path / "bundle", branch_id="manual-empty-trash-reboot")
    assert (bundle / "networkextension-apply-validation.json").exists()
    assert (bundle / "networkextension-apply-validation.txt").exists()

    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    (before / "report.json").write_text(json.dumps({"command": "report local-network", "evidence": [], "networkextension_apply_validation_summary": {"overall_verdict": "VALIDATION_FAILED", "repair_candidates_remaining": 2, "target_sha256": "old", "artifact_sha256": "new", "graph_consistency": "FAILED"}}))
    (after / "report.json").write_text(json.dumps({"command": "report local-network", "evidence": [], "networkextension_apply_validation_summary": {"overall_verdict": "VALIDATION_PASSED", "repair_candidates_remaining": 0, "target_sha256": "same", "artifact_sha256": "same", "graph_consistency": "PASSED"}}))

    diff = json.loads(CliRunner().invoke(app, ["diff", "bundles", str(before), str(after), "--json"]).stdout)
    assert diff["networkextension_apply_validation_diff"]["verdict_before"] == "VALIDATION_FAILED"
    assert diff["networkextension_apply_validation_diff"]["verdict_after"] == "VALIDATION_PASSED"
    assert diff["networkextension_apply_validation_diff"]["repair_candidates_remaining_delta"] == -2
    rendered = CliRunner().invoke(app, ["diff", "bundles", str(before), str(after)]).stdout
    assert "NetworkExtension Apply Validation Diff" in rendered
    assert "Validation result: VALIDATION_FAILED → VALIDATION_PASSED" in rendered
