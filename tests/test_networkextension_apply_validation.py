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


def _reverse_dictionary_order(value):
    if isinstance(value, dict):
        return {key: _reverse_dictionary_order(value[key]) for key in reversed(list(value))}
    if isinstance(value, list):
        return [_reverse_dictionary_order(item) for item in value]
    return value


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
    assert payload["semantic_comparison"]["bytewise_sha256_identical"] is True
    assert payload["semantic_comparison"]["semantic_equivalence"] is True
    assert payload["semantic_comparison"]["serialization_difference_explained"] == "byte_identical"


def test_apply_validation_passes_when_bytewise_mismatch_is_semantically_equivalent(tmp_path):
    fixture = generated_repaired_artifact(tmp_path)
    semantic_value = plistlib.loads(fixture["artifact"].read_bytes())
    fixture["source"].write_bytes(plistlib.dumps(_reverse_dictionary_order(semantic_value), fmt=plistlib.FMT_BINARY, sort_keys=False))

    payload = validate_networkextension_apply(fixture["source"], fixture["artifact"], metadata_path=fixture["metadata"]).to_json_dict()

    assert payload["overall_verdict"] == "VALIDATION_PASSED"
    assert payload["hash_comparison"]["sha256_identical"] is False
    assert payload["semantic_comparison"] == {
        "bytewise_sha256_identical": False,
        "semantic_equivalence": True,
        "object_graph_equivalent": True,
        "uid_reference_graph_equivalent": True,
        "dictionary_bindings_equivalent": True,
        "repair_candidates_equivalent": True,
        "validation_candidates_equivalent": True,
        "remaining_repair_candidates": 0,
        "remaining_validation_candidates": 0,
        "serialization_difference_explained": "bytewise serialization differs, but decoded NSKeyedArchiver semantics are equivalent",
    }
    assert all(stage["status"] == "PASS" for stage in payload["validation_stages"])


def test_apply_validation_fails_when_semantic_structure_differs(tmp_path):
    fixture = generated_repaired_artifact(tmp_path)
    live_value = plistlib.loads(fixture["artifact"].read_bytes())
    live_value["$objects"].append({"SigningIdentifier": "com.example.SemanticDrift", "Path": "/missing"})
    fixture["source"].write_bytes(plistlib.dumps(live_value, fmt=plistlib.FMT_BINARY, sort_keys=True))

    payload = validate_networkextension_apply(fixture["source"], fixture["artifact"], metadata_path=fixture["metadata"]).to_json_dict()

    assert payload["overall_verdict"] == "VALIDATION_FAILED"
    assert payload["semantic_comparison"]["semantic_equivalence"] is False
    assert payload["semantic_comparison"]["object_graph_equivalent"] is False
    assert payload["failure"]["stage"] == "semantic_equivalence_with_generated_artifact"


def test_apply_validation_fails_when_validation_candidates_remain(tmp_path, monkeypatch):
    fixture = generated_repaired_artifact(tmp_path)
    semantic_value = plistlib.loads(fixture["artifact"].read_bytes())
    fixture["source"].write_bytes(plistlib.dumps(_reverse_dictionary_order(semantic_value), fmt=plistlib.FMT_BINARY, sort_keys=False))

    original = build_networkextension_candidate_validation

    class ValidationWithRemaining:
        def __init__(self, wrapped):
            self.wrapped = wrapped

        def summary(self):
            payload = dict(self.wrapped.summary())
            payload["total_candidates"] = 1
            return payload

        def to_json_dict(self):
            payload = self.wrapped.to_json_dict()
            payload["validations"] = [
                {
                    "object_ref": "$objects[4]",
                    "signing_identifier": "com.google.Chrome",
                    "executable_path": "/missing",
                    "candidate_status": "stale",
                }
            ]
            return payload

    def fake_validation(paths, *, process_rows=None):
        return ValidationWithRemaining(original(paths, process_rows=process_rows))

    monkeypatch.setattr("macos_state_explorer.networkextension_apply_validation.build_networkextension_candidate_validation", fake_validation)

    payload = validate_networkextension_apply(fixture["source"], fixture["artifact"], metadata_path=fixture["metadata"]).to_json_dict()

    assert payload["overall_verdict"] == "VALIDATION_FAILED"
    assert payload["failure"]["stage"] == "validation_candidates_zero"
    assert payload["statistics"]["validation_candidates_remaining"] == 1
    assert payload["semantic_comparison"]["remaining_validation_candidates"] == 1


def test_apply_validation_reports_failure_stage_and_rollback_guidance(tmp_path):
    fixture = generated_repaired_artifact(tmp_path)
    target_before = fixture["source"].read_bytes()
    artifact_before = fixture["artifact"].read_bytes()

    payload = validate_networkextension_apply(fixture["source"], fixture["artifact"], metadata_path=fixture["metadata"]).to_json_dict()

    assert payload["overall_verdict"] == "VALIDATION_FAILED"
    assert payload["mutation_performed"] is False
    assert payload["failure"]["stage"] == "semantic_equivalence_with_generated_artifact"
    assert payload["failure"]["expected"] == "semantically equivalent"
    assert payload["failure"]["observed"] == "different semantics"
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


def test_apply_validation_malformed_archive_fails_before_semantic_success(tmp_path):
    artifact = tmp_path / "artifact.plist"
    target = tmp_path / "target.plist"
    target.write_text("not a plist", encoding="utf-8")
    artifact.write_bytes(plistlib.dumps({"$archiver": "NSKeyedArchiver", "$version": 100000, "$top": {"root": plistlib.UID(0)}, "$objects": ["$null"]}, fmt=plistlib.FMT_BINARY, sort_keys=True))

    payload = validate_networkextension_apply(target, artifact).to_json_dict()

    assert payload["overall_verdict"] == "VALIDATION_FAILED"
    assert payload["failure"]["stage"] == "target_plist_readable"
    assert payload["semantic_comparison"]["semantic_equivalence"] is False


def test_apply_validation_cli_text_and_json(tmp_path):
    fixture = generated_repaired_artifact(tmp_path)
    fixture["source"].write_bytes(fixture["artifact"].read_bytes())

    json_result = CliRunner().invoke(app, ["networkextension", "apply-validation", "--target", str(fixture["source"]), "--artifact", str(fixture["artifact"]), "--metadata", str(fixture["metadata"]), "--json"])
    assert json_result.exit_code == 0
    payload = json.loads(json_result.stdout)
    assert payload["overall_verdict"] == "VALIDATION_PASSED"
    assert payload["statistics"]["object_count"] > 0
    assert payload["semantic_comparison"]["semantic_equivalence"] is True

    text_result = CliRunner().invoke(app, ["networkextension", "apply-validation", "--target", str(fixture["source"]), "--artifact", str(fixture["artifact"]), "--metadata", str(fixture["metadata"])])
    assert text_result.exit_code == 0
    assert "NetworkExtension apply validation" in text_result.stdout
    assert "Overall verdict: VALIDATION_PASSED" in text_result.stdout
    assert "repair_candidates_zero: PASS" in text_result.stdout
    assert "Byte-identical:" in text_result.stdout
    assert "Semantically equivalent:" in text_result.stdout
    assert "SHA256 mismatch alone is not a failure when semantic validation passes." in text_result.stdout


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
    (before / "report.json").write_text(json.dumps({"command": "report local-network", "evidence": [], "networkextension_apply_validation_summary": {"overall_verdict": "VALIDATION_FAILED", "repair_candidates_remaining": 2, "target_sha256": "old", "artifact_sha256": "new", "graph_consistency": "FAILED", "semantic_equivalence": False, "bytewise_sha256_identical": False, "serialization_difference_explained": "semantic mismatch"}}))
    (after / "report.json").write_text(json.dumps({"command": "report local-network", "evidence": [], "networkextension_apply_validation_summary": {"overall_verdict": "VALIDATION_PASSED", "repair_candidates_remaining": 0, "target_sha256": "same", "artifact_sha256": "same", "graph_consistency": "PASSED", "semantic_equivalence": True, "bytewise_sha256_identical": False, "serialization_difference_explained": "bytewise serialization differs, but decoded NSKeyedArchiver semantics are equivalent"}}))

    diff = json.loads(CliRunner().invoke(app, ["diff", "bundles", str(before), str(after), "--json"]).stdout)
    assert diff["networkextension_apply_validation_diff"]["verdict_before"] == "VALIDATION_FAILED"
    assert diff["networkextension_apply_validation_diff"]["verdict_after"] == "VALIDATION_PASSED"
    assert diff["networkextension_apply_validation_diff"]["repair_candidates_remaining_delta"] == -2
    assert diff["networkextension_apply_validation_diff"]["semantic_equivalence_before"] is False
    assert diff["networkextension_apply_validation_diff"]["semantic_equivalence_after"] is True
    assert diff["networkextension_apply_validation_diff"]["serialization_difference_explained_after"] == "bytewise serialization differs, but decoded NSKeyedArchiver semantics are equivalent"
    rendered = CliRunner().invoke(app, ["diff", "bundles", str(before), str(after)]).stdout
    assert "NetworkExtension Apply Validation Diff" in rendered
    assert "Validation result: VALIDATION_FAILED → VALIDATION_PASSED" in rendered
    assert "Semantic equivalence: false → true" in rendered
