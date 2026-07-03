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


def _archive_value(path: Path):
    return plistlib.loads(path.read_bytes())


def _write_archive(path: Path, value):
    path.write_bytes(plistlib.dumps(value, fmt=plistlib.FMT_BINARY, sort_keys=False))


def _append_unrelated_apple_metadata(value, *, label="apple-regenerated"):
    cloned = _reverse_dictionary_order(value)
    cloned["$objects"] = list(cloned["$objects"])
    cloned["$objects"].append({"AppleGeneratedMetadata": label, "Generation": 2})
    return cloned


def _append_many_unrelated_archive_objects(value, count=12):
    cloned = _reverse_dictionary_order(value)
    cloned["$objects"] = list(cloned["$objects"])
    for index in range(count):
        cloned["$objects"].append({"UnrelatedArchiveCache": f"cache-{index}", "Generation": index})
    return cloned


def _append_reappeared_repair_target(value, path="/missing/reappeared/Google Chrome"):
    cloned = _reverse_dictionary_order(value)
    cloned["$objects"] = list(cloned["$objects"])
    wrapper_index = len(cloned["$objects"])
    identity_index = wrapper_index + 1
    if isinstance(cloned["$objects"][2], list):
        cloned["$objects"][2] = list(cloned["$objects"][2]) + [plistlib.UID(wrapper_index)]
    cloned["$objects"].append({"ClientIdentity": plistlib.UID(identity_index), "State": "stale"})
    cloned["$objects"].append({"SigningIdentifier": "com.google.Chrome", "Path": path})
    return cloned


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
    assert payload["overall_verdict"] == "VALIDATION_PASSED_REPAIR_EFFECTIVE"
    assert payload["repair_success_validation"]["repair_actually_successful"] is True
    assert payload["repair_success_validation"]["repair_relevant_semantic_equivalence"] is True
    assert all(stage["status"] == "PASS" for stage in payload["validation_stages"])
    assert payload["statistics"]["repair_candidates_remaining"] == 0
    assert payload["statistics"]["validation_candidates_remaining"] == 0
    assert payload["hash_comparison"]["sha256_identical"] is True
    assert payload["hash_comparison"]["serialization_identical"] is True
    assert payload["hash_comparison"]["object_graph_identical"] is True
    assert payload["semantic_comparison"]["bytewise_sha256_identical"] is True
    assert payload["semantic_comparison"]["semantic_equivalence"] is True
    assert payload["semantic_comparison"]["serialization_difference_explained"] == "byte_identical"
    assert payload["repair_success_validation"]["apple_regenerated_unrelated_archive_objects"] is False
    assert payload["repair_success_validation"]["unrelated_semantic_differences"] == 0
    assert payload["repair_success_validation"]["repair_relevant_semantic_differences"] == 0


def test_apply_validation_passes_when_apple_regenerates_unrelated_objects(tmp_path):
    fixture = generated_repaired_artifact(tmp_path)
    artifact_value = _archive_value(fixture["artifact"])
    _write_archive(fixture["source"], _append_unrelated_apple_metadata(artifact_value))

    payload = validate_networkextension_apply(fixture["source"], fixture["artifact"], metadata_path=fixture["metadata"]).to_json_dict()

    assert payload["overall_verdict"] == "VALIDATION_PASSED_REPAIR_EFFECTIVE"
    assert payload["repair_success_validation"] == {
        "repair_actually_successful": True,
        "repair_relevant_equivalence": "PASSED",
        "full_semantic_equivalence": False,
        "repair_relevant_semantic_equivalence": True,
        "apple_regenerated_unrelated_archive_objects": True,
        "unrelated_semantic_differences": 1,
        "repair_relevant_semantic_differences": 0,
        "blocking_repair_relevant_semantic_differences": 0,
        "non_blocking_semantic_differences": 1,
        "difference_classification": "unrelated_semantic_difference",
        "failure_explanation": "",
        "remaining_repair_candidates": 0,
        "remaining_validation_candidates": 0,
    }
    stage = next(item for item in payload["validation_stages"] if item["stage"] == "repair_success_validation")
    assert stage["status"] == "PASS"


def test_apply_validation_passes_when_unrelated_metadata_changes(tmp_path):
    fixture = generated_repaired_artifact(tmp_path)
    artifact_value = _archive_value(fixture["artifact"])
    changed = _append_unrelated_apple_metadata(artifact_value, label="new-policy-cache")
    changed["$top"] = dict(changed["$top"], AppleCacheVersion="2")
    _write_archive(fixture["source"], changed)

    payload = validate_networkextension_apply(fixture["source"], fixture["artifact"], metadata_path=fixture["metadata"]).to_json_dict()

    assert payload["overall_verdict"] == "VALIDATION_PASSED_REPAIR_EFFECTIVE"
    assert payload["semantic_comparison"]["semantic_equivalence"] is False
    assert payload["repair_success_validation"]["repair_relevant_semantic_equivalence"] is True
    assert payload["repair_success_validation"]["apple_regenerated_unrelated_archive_objects"] is True
    assert payload["repair_success_validation"]["unrelated_semantic_differences"] >= 1


def test_apply_validation_passes_when_unrelated_objects_are_reordered(tmp_path):
    fixture = generated_repaired_artifact(tmp_path)
    artifact_value = _archive_value(fixture["artifact"])
    reordered = _append_unrelated_apple_metadata(artifact_value, label="reordered")
    reordered["$objects"] = reordered["$objects"][:-1] + list(reversed(reordered["$objects"][-1:]))
    _write_archive(fixture["source"], _reverse_dictionary_order(reordered))

    payload = validate_networkextension_apply(fixture["source"], fixture["artifact"], metadata_path=fixture["metadata"]).to_json_dict()

    assert payload["overall_verdict"] == "VALIDATION_PASSED_REPAIR_EFFECTIVE"
    assert payload["hash_comparison"]["sha256_identical"] is False
    assert payload["semantic_comparison"]["semantic_equivalence"] is False
    assert payload["repair_success_validation"]["repair_relevant_semantic_equivalence"] is True


def test_apply_validation_passes_when_bytewise_mismatch_is_semantically_equivalent(tmp_path):
    fixture = generated_repaired_artifact(tmp_path)
    semantic_value = plistlib.loads(fixture["artifact"].read_bytes())
    fixture["source"].write_bytes(plistlib.dumps(_reverse_dictionary_order(semantic_value), fmt=plistlib.FMT_BINARY, sort_keys=False))

    payload = validate_networkextension_apply(fixture["source"], fixture["artifact"], metadata_path=fixture["metadata"]).to_json_dict()

    assert payload["overall_verdict"] == "VALIDATION_PASSED_REPAIR_EFFECTIVE"
    assert payload["repair_success_validation"]["repair_actually_successful"] is True
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


def test_apply_validation_non_blocking_unrelated_diffs_do_not_fail_or_inflate_repair_relevant_counts(tmp_path):
    fixture = generated_repaired_artifact(tmp_path)
    artifact_value = _archive_value(fixture["artifact"])
    _write_archive(fixture["source"], _append_many_unrelated_archive_objects(artifact_value, count=12))

    payload = validate_networkextension_apply(fixture["source"], fixture["artifact"], metadata_path=fixture["metadata"]).to_json_dict()

    assert payload["overall_verdict"] == "VALIDATION_PASSED_REPAIR_EFFECTIVE"
    assert payload["repair_success_validation"]["repair_actually_successful"] is True
    assert payload["repair_success_validation"]["repair_relevant_semantic_differences"] == 0
    assert payload["repair_success_validation"]["blocking_repair_relevant_semantic_differences"] == 0
    assert payload["repair_success_validation"]["non_blocking_semantic_differences"] == 12
    assert len(payload["repair_relevant_semantic_differences"]) == 12
    assert {entry["blocks_repair_success"] for entry in payload["repair_relevant_semantic_differences"]} == {False}


def test_apply_validation_zero_blocking_diffs_with_candidate_row_noise_is_success(tmp_path, monkeypatch):
    fixture = generated_repaired_artifact(tmp_path)
    artifact_value = _archive_value(fixture["artifact"])
    _write_archive(fixture["source"], _append_many_unrelated_archive_objects(artifact_value, count=4))

    class CandidateRowsWithNonExecutableNoise:
        def to_json_dict(self):
            return {
                "candidates": [
                    {
                        "object_reference": "$objects[99]",
                        "signing_identifier": "com.google.Chrome",
                        "executable_path": "/diagnostic/noise/Google Chrome",
                        "could_ever_be_safely_removed": False,
                        "safety_classification": "manual_only",
                    }
                ]
            }

    monkeypatch.setattr(
        "macos_state_explorer.networkextension_apply_validation.build_networkextension_repair_candidates",
        lambda paths: CandidateRowsWithNonExecutableNoise(),
    )

    payload = validate_networkextension_apply(fixture["source"], fixture["artifact"], metadata_path=fixture["metadata"]).to_json_dict()

    assert payload["overall_verdict"] == "VALIDATION_PASSED_REPAIR_EFFECTIVE"
    assert payload["failure"] is None
    assert payload["repair_success_validation"]["repair_actually_successful"] is True
    assert payload["repair_success_validation"]["blocking_repair_relevant_semantic_differences"] == 0
    assert payload["repair_success_validation"]["repair_relevant_semantic_differences"] == 0
    assert payload["repair_success_validation"]["non_blocking_semantic_differences"] == 4
    assert payload["statistics"]["repair_candidates_remaining"] == 0
    assert payload["statistics"]["validation_candidates_remaining"] == 0
    assert next(stage for stage in payload["validation_stages"] if stage["stage"] == "repair_success_validation")["status"] == "PASS"


def test_apply_validation_text_bounds_non_blocking_diff_samples(tmp_path):
    fixture = generated_repaired_artifact(tmp_path)
    artifact_value = _archive_value(fixture["artifact"])
    _write_archive(fixture["source"], _append_many_unrelated_archive_objects(artifact_value, count=12))

    result = CliRunner().invoke(app, ["networkextension", "apply-validation", "--target", str(fixture["source"]), "--artifact", str(fixture["artifact"]), "--metadata", str(fixture["metadata"])])

    assert result.exit_code == 0
    assert "Blocking repair-relevant semantic differences: 0" in result.stdout
    assert "Non-blocking semantic drift differences: 12" in result.stdout
    assert "Non-blocking archive drift is diagnostic and does not imply repair failure." in result.stdout
    assert result.stdout.count("blocks repair success: false") <= 3
    assert "9 additional non-blocking semantic drift entries omitted" in result.stdout


def test_apply_validation_text_bounds_blocking_diff_samples(tmp_path):
    fixture = generated_repaired_artifact(tmp_path)
    artifact_value = _archive_value(fixture["artifact"])
    changed = _reverse_dictionary_order(artifact_value)
    changed["$objects"] = list(changed["$objects"])
    changed["$objects"][4] = dict(
        changed["$objects"][4],
        SigningIdentifier="com.google.Chrome.BlockingDrift",
        Path="/different/Google Chrome",
        TeamIdentifier="TEAM-A",
        BundleVersion="1",
        DesignatedRequirement="req-a",
        AuditToken="token-a",
        ExtraRepairRelevantA="A",
        ExtraRepairRelevantB="B",
    )
    _write_archive(fixture["source"], changed)

    result = CliRunner().invoke(app, ["networkextension", "apply-validation", "--target", str(fixture["source"]), "--artifact", str(fixture["artifact"]), "--metadata", str(fixture["metadata"])])

    assert result.exit_code == 0
    assert result.stdout.count("blocks repair success: true") == 5
    assert "3 additional blocking repair-relevant semantic difference entries omitted" in result.stdout


def test_apply_validation_fails_when_semantic_structure_differs(tmp_path):
    fixture = generated_repaired_artifact(tmp_path)
    live_value = plistlib.loads(fixture["artifact"].read_bytes())
    live_value["$objects"].append({"SigningIdentifier": "com.example.SemanticDrift", "Path": "/missing"})
    fixture["source"].write_bytes(plistlib.dumps(live_value, fmt=plistlib.FMT_BINARY, sort_keys=True))

    payload = validate_networkextension_apply(fixture["source"], fixture["artifact"], metadata_path=fixture["metadata"]).to_json_dict()

    assert payload["overall_verdict"] == "VALIDATION_PASSED_REPAIR_EFFECTIVE"
    assert payload["semantic_comparison"]["semantic_equivalence"] is False
    assert payload["semantic_comparison"]["object_graph_equivalent"] is False
    assert payload["repair_success_validation"]["difference_classification"] == "unrelated_semantic_difference"
    assert payload["repair_success_validation"]["repair_relevant_semantic_differences"] == 0


def test_apply_validation_fails_when_repair_target_reappears(tmp_path):
    fixture = generated_repaired_artifact(tmp_path)
    artifact_value = _archive_value(fixture["artifact"])
    _write_archive(fixture["source"], _append_reappeared_repair_target(artifact_value))

    payload = validate_networkextension_apply(fixture["source"], fixture["artifact"], metadata_path=fixture["metadata"]).to_json_dict()

    assert payload["overall_verdict"] == "VALIDATION_FAILED"
    assert payload["repair_success_validation"]["repair_actually_successful"] is False
    assert payload["repair_success_validation"]["difference_classification"] == "repair_relevant_difference"
    assert payload["repair_success_validation"]["repair_relevant_semantic_equivalence"] is False
    entries = payload["repair_relevant_semantic_differences"]
    blocking_entries = [entry for entry in entries if entry["blocks_repair_success"]]
    non_blocking_entries = [entry for entry in entries if not entry["blocks_repair_success"]]
    assert payload["repair_success_validation"]["repair_relevant_semantic_differences"] == len(blocking_entries)
    assert payload["repair_success_validation"]["blocking_repair_relevant_semantic_differences"] == len(blocking_entries)
    assert payload["repair_success_validation"]["non_blocking_semantic_differences"] == len(non_blocking_entries)
    assert blocking_entries
    assert payload["failure"]["stage"] == "repair_relevant_semantic_difference"
    assert "repair-relevant NetworkExtension object graph differs" in payload["repair_success_validation"]["failure_explanation"]


def test_apply_validation_fails_when_surviving_repair_relevant_identity_changes(tmp_path):
    fixture = generated_repaired_artifact(tmp_path)
    artifact_value = _archive_value(fixture["artifact"])
    changed = _reverse_dictionary_order(artifact_value)
    changed["$objects"] = list(changed["$objects"])
    changed["$objects"][4] = dict(changed["$objects"][4], SigningIdentifier="com.google.Chrome.EvilDrift")
    _write_archive(fixture["source"], changed)

    payload = validate_networkextension_apply(fixture["source"], fixture["artifact"], metadata_path=fixture["metadata"]).to_json_dict()

    assert payload["overall_verdict"] == "VALIDATION_FAILED"
    assert payload["repair_success_validation"]["repair_actually_successful"] is False
    assert payload["repair_success_validation"]["difference_classification"] == "repair_relevant_difference"
    assert payload["repair_success_validation"]["repair_relevant_semantic_equivalence"] is False
    assert payload["failure"]["stage"] == "repair_relevant_semantic_difference"
    assert "repair-relevant NetworkExtension object graph differs" in payload["repair_success_validation"]["failure_explanation"]
    assert payload["repair_success_validation"]["blocking_repair_relevant_semantic_differences"] == 1
    assert payload["repair_success_validation"]["non_blocking_semantic_differences"] == 0
    assert payload["repair_relevant_semantic_differences"] == [
        {
            "id": "ne-semantic-diff-0001",
            "object_ref": "$objects[4]",
            "object_path": "$objects[4]",
            "semantic_path": "$objects[4].SigningIdentifier",
            "parent_chain": "$objects[4]",
            "expected_generated_value_summary": "com.google.Chrome",
            "actual_target_value_summary": "com.google.Chrome.EvilDrift",
            "classification": "true_repair_difference",
            "explanation": "Repair-relevant NetworkExtension object differs from generated artifact at SigningIdentifier; this may mean the installed target no longer matches the repaired identity graph.",
            "blocks_repair_success": True,
            "suggested_next_action": "Do not mark repair successful; inspect this object path and restore the pre-apply backup if this followed a confirmed apply.",
        }
    ]


def test_apply_validation_fails_when_surviving_repair_relevant_identity_metadata_changes(tmp_path):
    fixture = generated_repaired_artifact(tmp_path)
    artifact_value = _archive_value(fixture["artifact"])
    artifact_value["$objects"] = list(artifact_value["$objects"])
    artifact_value["$objects"][4] = dict(artifact_value["$objects"][4], TeamIdentifier="GOODTEAM")
    _write_archive(fixture["artifact"], artifact_value)
    changed = _reverse_dictionary_order(artifact_value)
    changed["$objects"] = list(changed["$objects"])
    changed["$objects"][4] = dict(changed["$objects"][4], TeamIdentifier="EVILTEAM")
    _write_archive(fixture["source"], changed)

    payload = validate_networkextension_apply(fixture["source"], fixture["artifact"], metadata_path=fixture["metadata"]).to_json_dict()

    assert payload["overall_verdict"] == "VALIDATION_FAILED"
    assert payload["repair_success_validation"]["difference_classification"] == "repair_relevant_difference"
    assert payload["repair_success_validation"]["repair_relevant_semantic_equivalence"] is False
    assert payload["failure"]["stage"] == "repair_relevant_semantic_difference"


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
    assert payload["repair_success_validation"]["repair_actually_successful"] is False
    assert payload["statistics"]["validation_candidates_remaining"] == 1
    assert payload["semantic_comparison"]["remaining_validation_candidates"] == 1


def test_apply_validation_reports_failure_stage_and_rollback_guidance(tmp_path):
    fixture = generated_repaired_artifact(tmp_path)
    target_before = fixture["source"].read_bytes()
    artifact_before = fixture["artifact"].read_bytes()

    payload = validate_networkextension_apply(fixture["source"], fixture["artifact"], metadata_path=fixture["metadata"]).to_json_dict()

    assert payload["overall_verdict"] == "VALIDATION_FAILED"
    assert payload["mutation_performed"] is False
    assert payload["failure"]["stage"] == "repair_relevant_semantic_difference"
    assert payload["failure"]["expected"] == "repair-relevant equivalence"
    assert payload["failure"]["observed"] == "repair-relevant difference"
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
    assert payload["overall_verdict"] == "VALIDATION_PASSED_REPAIR_EFFECTIVE"
    assert payload["statistics"]["object_count"] > 0
    assert payload["semantic_comparison"]["semantic_equivalence"] is True
    assert payload["repair_success_validation"]["repair_actually_successful"] is True

    text_result = CliRunner().invoke(app, ["networkextension", "apply-validation", "--target", str(fixture["source"]), "--artifact", str(fixture["artifact"]), "--metadata", str(fixture["metadata"])])
    assert text_result.exit_code == 0
    assert "NetworkExtension apply validation" in text_result.stdout
    assert "Overall verdict: VALIDATION_PASSED_REPAIR_EFFECTIVE" in text_result.stdout
    assert "repair_candidates_zero: PASS" in text_result.stdout
    assert "repair_success_validation: PASS" in text_result.stdout
    assert "Repair-relevant equivalence: PASSED" in text_result.stdout
    assert "Repair-relevant semantic equivalence: true" in text_result.stdout
    assert "Byte-identical:" in text_result.stdout
    assert "Semantically equivalent:" in text_result.stdout
    assert "Full semantic mismatch is diagnostic only when repair validation passes." in text_result.stdout
    assert "Non-blocking archive drift is diagnostic and does not imply repair failure." in text_result.stdout


def test_apply_validation_cli_text_explains_repair_relevant_difference(tmp_path):
    fixture = generated_repaired_artifact(tmp_path)
    artifact_value = _archive_value(fixture["artifact"])
    changed = _reverse_dictionary_order(artifact_value)
    changed["$objects"] = list(changed["$objects"])
    changed["$objects"][4] = dict(changed["$objects"][4], SigningIdentifier="com.google.Chrome.EvilDrift")
    _write_archive(fixture["source"], changed)

    result = CliRunner().invoke(app, ["networkextension", "apply-validation", "--target", str(fixture["source"]), "--artifact", str(fixture["artifact"]), "--metadata", str(fixture["metadata"])])

    assert result.exit_code == 0
    assert "Repair-relevant semantic difference details" in result.stdout
    assert "ne-semantic-diff-0001" in result.stdout
    assert "$objects[4].SigningIdentifier" in result.stdout
    assert "true_repair_difference" in result.stdout
    assert "blocks repair success: true" in result.stdout
    assert "com.google.Chrome → com.google.Chrome.EvilDrift" in result.stdout


def test_apply_validation_report_bundle_and_diff(monkeypatch, tmp_path):
    fixture = generated_repaired_artifact(tmp_path)
    fixture["source"].write_bytes(fixture["artifact"].read_bytes())
    monkeypatch.setattr("macos_state_explorer.reports.local_network.DEFAULT_APPLY_VALIDATION_TARGET", fixture["source"])
    monkeypatch.setattr("macos_state_explorer.reports.local_network.DEFAULT_APPLY_VALIDATION_ARTIFACT", fixture["artifact"])
    monkeypatch.setattr("macos_state_explorer.reports.local_network.DEFAULT_APPLY_VALIDATION_METADATA", fixture["metadata"])

    report = build_local_network_report(Snapshot(host="h", created_at=1, observations=[Observation(collector="launchservices", started_at=1, ended_at=1, payload={"entries": []})]))
    payload = report.to_json_dict()
    assert payload["networkextension_apply_validation_summary"]["overall_verdict"] == "VALIDATION_PASSED_REPAIR_EFFECTIVE"
    assert payload["networkextension_apply_validation_summary"]["repair_actually_successful"] is True
    assert payload["networkextension_apply_validation_summary"]["repair_relevant_semantic_difference_entries"] == []

    bundle = write_local_network_support_bundle(report, tmp_path / "bundle", branch_id="manual-empty-trash-reboot")
    assert (bundle / "networkextension-apply-validation.json").exists()
    assert (bundle / "networkextension-apply-validation.txt").exists()

    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    (before / "report.json").write_text(json.dumps({"command": "report local-network", "evidence": [], "networkextension_apply_validation_summary": {"overall_verdict": "VALIDATION_FAILED", "repair_candidates_remaining": 2, "target_sha256": "old", "artifact_sha256": "new", "graph_consistency": "FAILED", "semantic_equivalence": False, "bytewise_sha256_identical": False, "serialization_difference_explained": "semantic mismatch"}}))
    (after / "report.json").write_text(json.dumps({"command": "report local-network", "evidence": [], "networkextension_apply_validation_summary": {"overall_verdict": "VALIDATION_PASSED_REPAIR_EFFECTIVE", "repair_actually_successful": True, "repair_candidates_remaining": 0, "target_sha256": "same", "artifact_sha256": "same", "graph_consistency": "PASSED", "semantic_equivalence": False, "repair_relevant_semantic_equivalence": True, "apple_regenerated_unrelated_archive_objects": True, "unrelated_semantic_differences": 2, "repair_relevant_semantic_differences": 0, "blocking_repair_relevant_semantic_differences": 0, "non_blocking_semantic_differences": 1, "repair_relevant_semantic_difference_entries": [{"id": "ne-semantic-diff-0001", "classification": "benign_archive_regeneration", "blocks_repair_success": False, "semantic_path": "$objects[5]", "explanation": "Target contains unrelated regenerated metadata."}], "bytewise_sha256_identical": False, "serialization_difference_explained": "unrelated Apple-generated archive objects differ; repair-relevant semantics match"}}))

    diff = json.loads(CliRunner().invoke(app, ["diff", "bundles", str(before), str(after), "--json"]).stdout)
    assert diff["networkextension_apply_validation_diff"]["verdict_before"] == "VALIDATION_FAILED"
    assert diff["networkextension_apply_validation_diff"]["verdict_after"] == "VALIDATION_PASSED_REPAIR_EFFECTIVE"
    assert diff["networkextension_apply_validation_diff"]["repair_actually_successful_after"] is True
    assert diff["networkextension_apply_validation_diff"]["repair_relevant_semantic_equivalence_after"] is True
    assert diff["networkextension_apply_validation_diff"]["apple_regenerated_unrelated_archive_objects_after"] is True
    assert diff["networkextension_apply_validation_diff"]["unrelated_semantic_differences_delta"] == 2
    assert diff["networkextension_apply_validation_diff"]["repair_relevant_semantic_differences_delta"] == 0
    assert diff["networkextension_apply_validation_diff"]["blocking_repair_relevant_semantic_differences_delta"] == 0
    assert diff["networkextension_apply_validation_diff"]["non_blocking_semantic_differences_delta"] == 1
    assert diff["networkextension_apply_validation_diff"]["repair_candidates_remaining_delta"] == -2
    assert diff["networkextension_apply_validation_diff"]["semantic_equivalence_before"] is False
    assert diff["networkextension_apply_validation_diff"]["semantic_equivalence_after"] is False
    assert diff["networkextension_apply_validation_diff"]["serialization_difference_explained_after"] == "unrelated Apple-generated archive objects differ; repair-relevant semantics match"
    assert diff["networkextension_apply_validation_diff"]["semantic_difference_ids_added"] == ["ne-semantic-diff-0001"]
    assert diff["networkextension_apply_validation_diff"]["semantic_difference_classifications_after"] == ["benign_archive_regeneration"]
    assert diff["repair_branch_status_diff"] == {
        "networkextension_status_before": "UNRESOLVED",
        "networkextension_status_after": "COMPLETED",
        "launchservices_status_before": "UNRESOLVED",
        "launchservices_status_after": "UNRESOLVED",
        "next_action_focus_before": "networkextension",
        "next_action_focus_after": "launchservices",
    }
    rendered = CliRunner().invoke(app, ["diff", "bundles", str(before), str(after)]).stdout
    assert "NetworkExtension Apply Validation Diff" in rendered
    assert "Validation result: VALIDATION_FAILED → VALIDATION_PASSED_REPAIR_EFFECTIVE" in rendered
    assert "Repair actually successful: false → true" in rendered
    assert "Repair-relevant semantic equivalence: false → true" in rendered
    assert "Semantic difference IDs added: ne-semantic-diff-0001" in rendered
    assert "Semantic difference classifications: benign_archive_regeneration" in rendered
    assert "Blocking repair-relevant semantic differences: +0" in rendered
    assert "Non-blocking semantic drift differences: +1" in rendered
    assert "Full semantic mismatch diagnostic-only without blocking diffs." in rendered
    assert "Repair Branch Status Diff" in rendered
    assert "NetworkExtension branch: UNRESOLVED → COMPLETED" in rendered
    assert "Next action focus: networkextension → launchservices" in rendered
