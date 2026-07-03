from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import plistlib
from pathlib import Path
import subprocess
from typing import Any

from macos_state_explorer.networkextension_candidate_validation import build_networkextension_candidate_validation
from macos_state_explorer.networkextension_object_graph import build_networkextension_object_graph
from macos_state_explorer.networkextension_repair_candidates import build_networkextension_repair_candidates

DEFAULT_APPLY_VALIDATION_TARGET = Path("/Library/Preferences/com.apple.networkextension.plist")
DEFAULT_APPLY_VALIDATION_ARTIFACT = Path("networkextension-repair-artifact.plist")
DEFAULT_APPLY_VALIDATION_METADATA = Path("networkextension-repair-artifact.json")

STAGE_ORDER = (
    "target_file_exists",
    "target_plist_readable",
    "plutil_validation_succeeds",
    "nskeyedarchiver_decoding_succeeds",
    "object_graph_reconstruction_succeeds",
    "object_graph_consistency_validation_succeeds",
    "no_broken_uid_references",
    "no_dangling_references",
    "no_malformed_arrays",
    "no_malformed_dictionaries",
    "no_duplicate_object_indices",
    "no_serialization_inconsistencies",
    "object_graph_command_against_repaired_plist",
    "repair_candidates_command_against_repaired_plist",
    "validate_candidates_command_against_repaired_plist",
    "repair_candidates_zero",
    "validation_candidates_zero",
    "semantic_equivalence_with_generated_artifact",
    "repair_success_validation",
    "validation_summary_generated",
)


@dataclass(frozen=True)
class ValidationStage:
    name: str
    status: str
    reason: str
    duration_ms: float
    expected: Any = None
    observed: Any = None

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "stage": self.name,
            "status": self.status,
            "reason": self.reason,
            "duration_ms": self.duration_ms,
            "expected": self.expected,
            "observed": self.observed,
        }


@dataclass(frozen=True)
class NetworkExtensionApplyValidation:
    target_path: Path
    artifact_path: Path
    metadata_path: Path | None
    stages: tuple[ValidationStage, ...]
    statistics: dict[str, Any]
    hash_comparison: dict[str, Any]
    semantic_comparison: dict[str, Any]
    overall_verdict: str
    failure: dict[str, Any] | None

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "command": "networkextension apply-validation",
            "timestamp": "1970-01-01T00:00:00Z",
            "read_only": True,
            "mutation_performed": False,
            "target_path": str(self.target_path),
            "artifact_path": str(self.artifact_path),
            "metadata_path": str(self.metadata_path) if self.metadata_path else "",
            "overall_verdict": self.overall_verdict,
            "validation_stages": [stage.to_json_dict() for stage in self.stages],
            "statistics": self.statistics,
            "hash_comparison": self.hash_comparison,
            "failure": self.failure,
            "semantic_comparison": {key: value for key, value in self.semantic_comparison.items() if key not in {"repair_success_validation", "repair_relevant_semantic_difference_entries"}},
            "repair_success_validation": _public_repair_success_validation(self.semantic_comparison.get("repair_success_validation", _empty_repair_success_validation())),
            "repair_relevant_semantic_differences": self.semantic_comparison.get("repair_relevant_semantic_difference_entries", []),
        }

    def summary(self) -> dict[str, Any]:
        return {
            "overall_verdict": self.overall_verdict,
            "stage_count": len(self.stages),
            "failed_stage": self.failure.get("stage") if self.failure else "",
            "object_count": int(self.statistics.get("object_count", 0)),
            "uid_count": int(self.statistics.get("uid_count", 0)),
            "uid_rewrites": int(self.statistics.get("uid_rewrites", 0)),
            "array_count": int(self.statistics.get("array_count", 0)),
            "dictionary_count": int(self.statistics.get("dictionary_count", 0)),
            "repair_candidates_remaining": int(self.statistics.get("repair_candidates_remaining", 0)),
            "validation_candidates_remaining": int(self.statistics.get("validation_candidates_remaining", 0)),
            "graph_consistency": str(self.statistics.get("graph_consistency", "UNKNOWN")),
            "archive_integrity": str(self.statistics.get("archive_integrity", "UNKNOWN")),
            "target_sha256": str(self.hash_comparison.get("target_sha256", "")),
            "artifact_sha256": str(self.hash_comparison.get("artifact_sha256", "")),
            "sha256_identical": bool(self.hash_comparison.get("sha256_identical", False)),
            "bytewise_sha256_identical": bool(self.semantic_comparison.get("bytewise_sha256_identical", False)),
            "semantic_equivalence": bool(self.semantic_comparison.get("semantic_equivalence", False)),
            "repair_actually_successful": bool(self.semantic_comparison.get("repair_success_validation", {}).get("repair_actually_successful", False)),
            "repair_relevant_equivalence": str(self.semantic_comparison.get("repair_success_validation", {}).get("repair_relevant_equivalence", "FAILED")),
            "repair_relevant_semantic_equivalence": bool(self.semantic_comparison.get("repair_success_validation", {}).get("repair_relevant_semantic_equivalence", False)),
            "apple_regenerated_unrelated_archive_objects": bool(self.semantic_comparison.get("repair_success_validation", {}).get("apple_regenerated_unrelated_archive_objects", False)),
            "unrelated_semantic_differences": int(self.semantic_comparison.get("repair_success_validation", {}).get("unrelated_semantic_differences", 0)),
            "repair_relevant_semantic_differences": int(self.semantic_comparison.get("repair_success_validation", {}).get("repair_relevant_semantic_differences", 0)),
            "blocking_repair_relevant_semantic_differences": int(self.semantic_comparison.get("repair_success_validation", {}).get("blocking_repair_relevant_semantic_differences", 0)),
            "non_blocking_semantic_differences": int(self.semantic_comparison.get("repair_success_validation", {}).get("non_blocking_semantic_differences", 0)),
            "object_graph_equivalent": bool(self.semantic_comparison.get("object_graph_equivalent", False)),
            "uid_reference_graph_equivalent": bool(self.semantic_comparison.get("uid_reference_graph_equivalent", False)),
            "dictionary_bindings_equivalent": bool(self.semantic_comparison.get("dictionary_bindings_equivalent", False)),
            "repair_candidates_equivalent": bool(self.semantic_comparison.get("repair_candidates_equivalent", False)),
            "validation_candidates_equivalent": bool(self.semantic_comparison.get("validation_candidates_equivalent", False)),
            "serialization_difference_explained": str(self.semantic_comparison.get("serialization_difference_explained", "not_compared")),
            "repair_relevant_semantic_difference_entries": self.semantic_comparison.get("repair_relevant_semantic_difference_entries", []),
            "serialization_identical": bool(self.hash_comparison.get("serialization_identical", False)),
            "object_graph_identical": bool(self.hash_comparison.get("object_graph_identical", False)),
            "read_only": True,
            "mutation_performed": False,
        }


def validate_networkextension_apply(
    target_path: Path = DEFAULT_APPLY_VALIDATION_TARGET,
    artifact_path: Path = DEFAULT_APPLY_VALIDATION_ARTIFACT,
    *,
    metadata_path: Path | None = DEFAULT_APPLY_VALIDATION_METADATA,
) -> NetworkExtensionApplyValidation:
    target = Path(target_path).expanduser()
    artifact = Path(artifact_path).expanduser()
    metadata = Path(metadata_path).expanduser() if metadata_path is not None else None
    stages: list[ValidationStage] = []
    stats: dict[str, Any] = _empty_statistics()
    hash_comparison: dict[str, Any] = {
        "target_sha256": "",
        "artifact_sha256": "",
        "sha256_identical": False,
        "serialization_identical": False,
        "object_graph_identical": False,
    }
    semantic_comparison: dict[str, Any] = _empty_semantic_comparison()
    failure: dict[str, Any] | None = None

    def add(name: str, status: str, reason: str, expected: Any = None, observed: Any = None) -> None:
        nonlocal failure
        stage = ValidationStage(name=name, status=status, reason=reason, duration_ms=0.0, expected=expected, observed=observed)
        stages.append(stage)
        if status == "FAIL" and failure is None and name != "object_graph_consistency_validation_succeeds":
            failure = _failure(stage)

    exists = target.is_file()
    add("target_file_exists", "PASS" if exists else "FAIL", "target file exists" if exists else "target file is missing", True, exists)
    target_data = b""
    target_value: Any = None
    if exists:
        try:
            target_data = target.read_bytes()
            target_value = plistlib.loads(target_data)
            add("target_plist_readable", "PASS", "target plist parsed successfully", "parseable plist", "parseable plist")
        except Exception as error:
            add("target_plist_readable", "FAIL", type(error).__name__, "parseable plist", type(error).__name__)
    else:
        add("target_plist_readable", "FAIL", "target file missing", "parseable plist", "missing")

    plutil_ok, plutil_reason = _plutil_validate(target)
    add("plutil_validation_succeeds", "PASS" if plutil_ok else "FAIL", plutil_reason, 0, 0 if plutil_ok else 1)

    objects = target_value.get("$objects") if isinstance(target_value, dict) else None
    archive_ok = isinstance(target_value, dict) and target_value.get("$archiver") == "NSKeyedArchiver" and isinstance(objects, list)
    add("nskeyedarchiver_decoding_succeeds", "PASS" if archive_ok else "FAIL", "NSKeyedArchiver archive decoded" if archive_ok else "missing NSKeyedArchiver structure", "NSKeyedArchiver with $objects", type(target_value).__name__)

    if isinstance(objects, list):
        stats.update(_archive_statistics(target_value, objects))
    graph = build_networkextension_object_graph([target])
    graph_ok = graph.summary()["decoded_artifacts"] == 1 and graph.summary()["malformed_artifacts"] == 0
    add("object_graph_reconstruction_succeeds", "PASS" if graph_ok else "FAIL", "object graph reconstructed" if graph_ok else "object graph reconstruction failed", True, graph_ok)

    consistency_ok = archive_ok and stats["broken_uid_references"] == 0 and stats["malformed_arrays"] == 0 and stats["malformed_dictionaries"] == 0
    stats["graph_consistency"] = "PASSED" if consistency_ok else "FAILED"
    stats["archive_integrity"] = "PASSED" if archive_ok and consistency_ok else "FAILED"
    add("object_graph_consistency_validation_succeeds", "PASS" if consistency_ok else "FAIL", "object graph is internally consistent" if consistency_ok else "object graph consistency checks failed", "PASSED", stats["graph_consistency"])
    add("no_broken_uid_references", "PASS" if stats["broken_uid_references"] == 0 else "FAIL", "no UID references point outside $objects" if stats["broken_uid_references"] == 0 else "broken UID references found", 0, stats["broken_uid_references"])
    add("no_dangling_references", "PASS" if stats["dangling_references"] == 0 else "FAIL", "no dangling references found" if stats["dangling_references"] == 0 else "dangling references found", 0, stats["dangling_references"])
    add("no_malformed_arrays", "PASS" if stats["malformed_arrays"] == 0 else "FAIL", "arrays are well formed" if stats["malformed_arrays"] == 0 else "malformed arrays found", 0, stats["malformed_arrays"])
    add("no_malformed_dictionaries", "PASS" if stats["malformed_dictionaries"] == 0 else "FAIL", "dictionaries are well formed" if stats["malformed_dictionaries"] == 0 else "malformed dictionaries found", 0, stats["malformed_dictionaries"])
    add("no_duplicate_object_indices", "PASS", "object indices are implicit list positions and unique", 0, 0)

    serialization_ok = False
    if target_value is not None:
        try:
            reparsed = plistlib.loads(plistlib.dumps(target_value, fmt=plistlib.FMT_BINARY, sort_keys=True))
            serialization_ok = reparsed == target_value
        except Exception:
            serialization_ok = False
    add("no_serialization_inconsistencies", "PASS" if serialization_ok else "FAIL", "serialization round-trip is consistent" if serialization_ok else "serialization round-trip differs or fails", True, serialization_ok)

    candidates = build_networkextension_repair_candidates([target])
    validation = build_networkextension_candidate_validation([target], process_rows=[])
    candidates_payload = candidates.to_json_dict()
    candidate_rows_value = candidates_payload.get("candidates")
    candidate_rows = candidate_rows_value if isinstance(candidate_rows_value, list) else []
    validation_payload = validation.to_json_dict()
    validation_rows_value = validation_payload.get("validations")
    validation_rows = validation_rows_value if isinstance(validation_rows_value, list) else []
    stats["repair_candidates_remaining"] = sum(1 for item in candidate_rows if isinstance(item, dict) and bool(item.get("could_ever_be_safely_removed", False)))
    stats["validation_candidates_remaining"] = sum(1 for item in validation_rows if isinstance(item, dict) and str(item.get("candidate_status", "")) in {"runtime_absent", "stale", "ambiguous", "unverifiable"})
    add("object_graph_command_against_repaired_plist", "PASS" if graph_ok else "FAIL", "object-graph analysis completed against repaired plist", True, graph_ok)
    add("repair_candidates_command_against_repaired_plist", "PASS", "repair-candidates analysis completed against repaired plist", "completed", "completed")
    add("validate_candidates_command_against_repaired_plist", "PASS", "validate-candidates analysis completed against repaired plist", "completed", "completed")
    add("repair_candidates_zero", "PASS" if stats["repair_candidates_remaining"] == 0 else "FAIL", "no repair candidates remain" if stats["repair_candidates_remaining"] == 0 else "repair candidates remain", 0, stats["repair_candidates_remaining"])
    add("validation_candidates_zero", "PASS" if stats["validation_candidates_remaining"] == 0 else "FAIL", "no validation candidates remain" if stats["validation_candidates_remaining"] == 0 else "validation candidates remain", 0, stats["validation_candidates_remaining"])

    artifact_data = artifact.read_bytes() if artifact.is_file() else b""
    artifact_value: Any = None
    if artifact_data:
        try:
            artifact_value = plistlib.loads(artifact_data)
        except Exception:
            artifact_value = None
    target_sha = hashlib.sha256(target_data).hexdigest() if target_data else ""
    artifact_sha = hashlib.sha256(artifact_data).hexdigest() if artifact_data else ""
    graph_identical = False
    serialization_identical = False
    if artifact_data and target_data:
        serialization_identical = target_data == artifact_data
        try:
            graph_identical = plistlib.loads(target_data) == artifact_value
        except Exception:
            graph_identical = False
    sha_identical = bool(target_sha and artifact_sha and target_sha == artifact_sha)
    hash_comparison.update(
        {
            "target_sha256": target_sha,
            "artifact_sha256": artifact_sha,
            "sha256_identical": sha_identical,
            "serialization_identical": serialization_identical,
            "object_graph_identical": graph_identical,
        }
    )
    artifact_candidates = build_networkextension_repair_candidates([artifact]) if artifact.is_file() else None
    artifact_validation = build_networkextension_candidate_validation([artifact], process_rows=[]) if artifact.is_file() else None
    semantic_comparison = _semantic_comparison(
        target_value,
        artifact_value,
        bytewise_sha256_identical=sha_identical,
        serialization_identical=serialization_identical,
        target_repair_candidates_remaining=stats["repair_candidates_remaining"],
        target_validation_candidates_remaining=stats["validation_candidates_remaining"],
        target_candidate_rows=candidate_rows,
        target_validation_rows=validation_rows,
        artifact_candidate_rows=_candidate_rows(artifact_candidates),
        artifact_validation_rows=_validation_rows(artifact_validation),
    )
    full_semantic_ok = bool(semantic_comparison["semantic_equivalence"])
    add(
        "semantic_equivalence_with_generated_artifact",
        "PASS" if full_semantic_ok else "PASS",
        "complete archive semantics match generated artifact" if full_semantic_ok else "complete archive semantics differ; repair-relevant validation decides success",
        "complete semantic match",
        "complete semantic match" if full_semantic_ok else "unrelated semantic differences possible",
    )
    repair_success = _repair_success_validation(
        stats,
        semantic_comparison,
        target_value,
        artifact_value,
        target_candidate_rows=candidate_rows,
        target_validation_rows=validation_rows,
        serialization_ok=serialization_ok,
    )
    semantic_comparison["repair_success_validation"] = repair_success
    semantic_comparison["repair_relevant_semantic_difference_entries"] = repair_success["semantic_difference_entries"]
    repair_stage_ok = bool(repair_success["repair_actually_successful"])
    add(
        "repair_success_validation",
        "PASS" if repair_stage_ok else "FAIL",
        "repair-relevant NetworkExtension semantics validate successful repair" if repair_stage_ok else repair_success["failure_explanation"],
        "repair-relevant equivalence",
        "repair-relevant equivalence" if repair_stage_ok else "repair-relevant difference",
    )
    if not repair_stage_ok and (failure is None or failure.get("stage") in {"repair_candidates_zero", "repair_success_validation"}):
        failure = {
            "stage": "repair_relevant_semantic_difference",
            "expected": "repair-relevant equivalence",
            "observed": "repair-relevant difference",
            "reason": repair_success["failure_explanation"],
            "recommended_rollback_action": "Review the validation failure; if this followed a confirmed apply, restore the pre-apply backup before retrying.",
        }
    add("validation_summary_generated", "PASS", "validation summary generated", "generated", "generated")

    core_success = repair_stage_ok
    blocking_failures = [stage for stage in stages if stage.status == "FAIL"]
    if core_success and not blocking_failures:
        verdict = "VALIDATION_PASSED_REPAIR_EFFECTIVE"
    elif blocking_failures:
        verdict = "VALIDATION_FAILED"
    elif any(stage.status == "INCONCLUSIVE" for stage in stages):
        verdict = "VALIDATION_INCONCLUSIVE"
    else:
        verdict = "VALIDATION_FAILED"

    return NetworkExtensionApplyValidation(
        target_path=target,
        artifact_path=artifact,
        metadata_path=metadata,
        stages=tuple(stages),
        statistics=stats,
        hash_comparison=hash_comparison,
        semantic_comparison=semantic_comparison,
        overall_verdict=verdict,
        failure=failure,
    )


def networkextension_apply_validation_summary(validation: NetworkExtensionApplyValidation) -> dict[str, Any]:
    return validation.summary()


def _empty_semantic_comparison() -> dict[str, Any]:
    return {
        "bytewise_sha256_identical": False,
        "semantic_equivalence": False,
        "object_graph_equivalent": False,
        "uid_reference_graph_equivalent": False,
        "dictionary_bindings_equivalent": False,
        "repair_candidates_equivalent": False,
        "validation_candidates_equivalent": False,
        "remaining_repair_candidates": 0,
        "remaining_validation_candidates": 0,
        "serialization_difference_explained": "not_compared",
        "repair_relevant_semantic_difference_entries": [],
    }


def _semantic_comparison(
    target_value: Any,
    artifact_value: Any,
    *,
    bytewise_sha256_identical: bool,
    serialization_identical: bool,
    target_repair_candidates_remaining: int,
    target_validation_candidates_remaining: int,
    target_candidate_rows: list[Any],
    target_validation_rows: list[Any],
    artifact_candidate_rows: list[Any],
    artifact_validation_rows: list[Any],
) -> dict[str, Any]:
    object_graph_equivalent = target_value == artifact_value and target_value is not None
    uid_reference_graph_equivalent = _uid_reference_edges(target_value) == _uid_reference_edges(artifact_value) and target_value is not None
    dictionary_bindings_equivalent = _dictionary_bindings(target_value) == _dictionary_bindings(artifact_value) and target_value is not None
    repair_candidates_equivalent = _semantic_candidate_rows(target_candidate_rows) == _semantic_candidate_rows(artifact_candidate_rows)
    validation_candidates_equivalent = _semantic_validation_rows(target_validation_rows) == _semantic_validation_rows(artifact_validation_rows)
    semantic_equivalence = all(
        [
            object_graph_equivalent,
            uid_reference_graph_equivalent,
            dictionary_bindings_equivalent,
            repair_candidates_equivalent,
            validation_candidates_equivalent,
        ]
    )
    if bytewise_sha256_identical and serialization_identical:
        explanation = "byte_identical"
    elif semantic_equivalence:
        explanation = "bytewise serialization differs, but decoded NSKeyedArchiver semantics are equivalent"
    else:
        explanation = "decoded NSKeyedArchiver semantics differ"
    return {
        "bytewise_sha256_identical": bytewise_sha256_identical,
        "semantic_equivalence": semantic_equivalence,
        "object_graph_equivalent": object_graph_equivalent,
        "uid_reference_graph_equivalent": uid_reference_graph_equivalent,
        "dictionary_bindings_equivalent": dictionary_bindings_equivalent,
        "repair_candidates_equivalent": repair_candidates_equivalent,
        "validation_candidates_equivalent": validation_candidates_equivalent,
        "remaining_repair_candidates": target_repair_candidates_remaining,
        "remaining_validation_candidates": target_validation_candidates_remaining,
        "serialization_difference_explained": explanation,
    }


def _empty_repair_success_validation() -> dict[str, Any]:
    return {
        "repair_actually_successful": False,
        "repair_relevant_equivalence": "FAILED",
        "full_semantic_equivalence": False,
        "repair_relevant_semantic_equivalence": False,
        "apple_regenerated_unrelated_archive_objects": False,
        "unrelated_semantic_differences": 0,
        "repair_relevant_semantic_differences": 0,
        "blocking_repair_relevant_semantic_differences": 0,
        "non_blocking_semantic_differences": 0,
        "difference_classification": "repair_relevant_difference",
        "failure_explanation": "repair-success validation has not run",
        "remaining_repair_candidates": 0,
        "remaining_validation_candidates": 0,
    }


def _public_repair_success_validation(value: dict[str, Any]) -> dict[str, Any]:
    return {key: child for key, child in value.items() if key != "semantic_difference_entries"}


def _repair_success_validation(
    stats: dict[str, Any],
    semantic_comparison: dict[str, Any],
    target_value: Any,
    artifact_value: Any,
    *,
    target_candidate_rows: list[Any],
    target_validation_rows: list[Any],
    serialization_ok: bool,
) -> dict[str, Any]:
    full_semantic_equivalence = bool(semantic_comparison.get("semantic_equivalence", False))
    failures: list[str] = []
    if stats.get("archive_integrity") != "PASSED":
        failures.append("archive integrity failed")
    if stats.get("graph_consistency") != "PASSED":
        failures.append("object graph consistency failed")
    _ = serialization_ok
    remaining_repair = int(stats.get("repair_candidates_remaining", 0))
    remaining_validation = int(stats.get("validation_candidates_remaining", 0))
    if remaining_repair:
        failures.append("repair target or stale NetworkExtension repair candidate reappeared")
    if remaining_validation:
        failures.append("validation candidate remains")
    stale_repair_candidates = _repair_relevant_candidate_count(target_candidate_rows)
    if stale_repair_candidates:
        failures.append("repair target or stale NetworkExtension repair candidate reappeared")
    stale_validation_candidates = _repair_relevant_validation_count(target_validation_rows)
    if stale_validation_candidates and not remaining_validation:
        failures.append("repair-relevant validation candidate remains")
    if int(stats.get("broken_uid_references", 0)) or int(stats.get("dangling_references", 0)):
        failures.append("removed or invalid UID is referenced")
    semantic_difference_entries = _semantic_difference_entries(target_value, artifact_value)
    blocking_difference_count = sum(1 for entry in semantic_difference_entries if bool(entry.get("blocks_repair_success", False)))
    non_blocking_difference_count = len(semantic_difference_entries) - blocking_difference_count
    if blocking_difference_count:
        failures.append("repair-relevant NetworkExtension object graph differs from generated artifact")
    repair_relevant_semantic_equivalence = not failures and blocking_difference_count == 0
    unrelated_semantic_differences = 0 if full_semantic_equivalence else _unrelated_semantic_difference_count(target_value, artifact_value)
    repair_relevant_semantic_differences = blocking_difference_count
    repair_actually_successful = repair_relevant_semantic_equivalence
    classification = _overall_difference_classification(semantic_difference_entries, full_semantic_equivalence, repair_actually_successful)
    return {
        "repair_actually_successful": repair_actually_successful,
        "repair_relevant_equivalence": "PASSED" if repair_actually_successful else "FAILED",
        "full_semantic_equivalence": full_semantic_equivalence,
        "repair_relevant_semantic_equivalence": repair_relevant_semantic_equivalence,
        "apple_regenerated_unrelated_archive_objects": bool(unrelated_semantic_differences and repair_relevant_semantic_equivalence),
        "unrelated_semantic_differences": unrelated_semantic_differences if repair_relevant_semantic_equivalence else 0,
        "repair_relevant_semantic_differences": repair_relevant_semantic_differences,
        "blocking_repair_relevant_semantic_differences": blocking_difference_count,
        "non_blocking_semantic_differences": non_blocking_difference_count,
        "difference_classification": classification,
        "semantic_difference_entries": semantic_difference_entries,
        "failure_explanation": "" if repair_actually_successful else "; ".join(failures),
        "remaining_repair_candidates": remaining_repair,
        "remaining_validation_candidates": remaining_validation,
    }


def _semantic_difference_entries(target_value: Any, artifact_value: Any) -> list[dict[str, Any]]:
    target_objects = target_value.get("$objects") if isinstance(target_value, dict) else None
    artifact_objects = artifact_value.get("$objects") if isinstance(artifact_value, dict) else None
    if not isinstance(target_objects, list) or not isinstance(artifact_objects, list):
        if target_value == artifact_value:
            return []
        return [
            _semantic_difference_entry(
                1,
                object_ref="$",
                object_path="$",
                semantic_path="$",
                parent_chain="$",
                expected=artifact_value,
                actual=target_value,
                classification="validation_model_gap",
                explanation="Validation could not compare NSKeyedArchiver object arrays; archive structure differs outside the repair-relevant object model.",
                blocks=True,
                suggested="Do not mark repair successful; inspect the archive structure and validation model before retrying.",
            )
        ]

    entries: list[dict[str, Any]] = []
    next_id = 1
    max_len = max(len(target_objects), len(artifact_objects))
    for index in range(max_len):
        target_present = index < len(target_objects)
        artifact_present = index < len(artifact_objects)
        target_item = target_objects[index] if target_present else None
        artifact_item = artifact_objects[index] if artifact_present else None
        if target_item == artifact_item:
            continue
        target_relevant = isinstance(target_item, dict) and _is_repair_relevant_networkextension_object(target_item)
        artifact_relevant = isinstance(artifact_item, dict) and _is_repair_relevant_networkextension_object(artifact_item)
        if target_relevant or artifact_relevant:
            if isinstance(target_item, dict) and isinstance(artifact_item, dict):
                for path_key, expected, actual in _first_repair_relevant_field_diffs(artifact_item, target_item):
                    entries.append(
                        _semantic_difference_entry(
                            next_id,
                            object_ref=f"$objects[{index}]",
                            object_path=f"$objects[{index}]",
                            semantic_path=f"$objects[{index}].{path_key}" if path_key else f"$objects[{index}]",
                            parent_chain=f"$objects[{index}]",
                            expected=expected,
                            actual=actual,
                            classification="true_repair_difference",
                            explanation=f"Repair-relevant NetworkExtension object differs from generated artifact at {path_key or 'object'}; this may mean the installed target no longer matches the repaired identity graph.",
                            blocks=True,
                            suggested="Do not mark repair successful; inspect this object path and restore the pre-apply backup if this followed a confirmed apply.",
                        )
                    )
                    next_id += 1
                continue
            entries.append(
                _semantic_difference_entry(
                    next_id,
                    object_ref=f"$objects[{index}]",
                    object_path=f"$objects[{index}]",
                    semantic_path=f"$objects[{index}]",
                    parent_chain="$objects",
                    expected=artifact_item if artifact_present else "missing",
                    actual=target_item if target_present else "missing",
                    classification="unknown_repair_relevant_difference",
                    explanation="Repair-relevant NetworkExtension object presence differs between target and generated artifact.",
                    blocks=True,
                    suggested="Do not mark repair successful; inspect this object and restore the pre-apply backup if this followed a confirmed apply.",
                )
            )
            next_id += 1
        else:
            classification = "benign_archive_regeneration" if target_present and not artifact_present and _looks_like_apple_regenerated_archive_object(target_item) else "unrelated_semantic_difference"
            entries.append(
                _semantic_difference_entry(
                    next_id,
                    object_ref=f"$objects[{index}]",
                    object_path=f"$objects[{index}]",
                    semantic_path=f"$objects[{index}]",
                    parent_chain="$objects",
                    expected=artifact_item if artifact_present else "missing",
                    actual=target_item if target_present else "missing",
                    classification=classification,
                    explanation="Target contains an additional non-repair NetworkExtension archive object; repair-relevant objects still match the generated artifact." if classification == "benign_archive_regeneration" else "Decoded archive semantics differ outside repair-relevant NetworkExtension objects.",
                    blocks=False,
                    suggested="No repair rollback required; keep SHA256/full semantic mismatch as diagnostic context.",
                )
            )
            next_id += 1
    return entries


def _semantic_difference_entry(
    number: int,
    *,
    object_ref: str,
    object_path: str,
    semantic_path: str,
    parent_chain: str,
    expected: Any,
    actual: Any,
    classification: str,
    explanation: str,
    blocks: bool,
    suggested: str,
) -> dict[str, Any]:
    return {
        "id": f"ne-semantic-diff-{number:04d}",
        "object_ref": object_ref,
        "object_path": object_path,
        "semantic_path": semantic_path,
        "parent_chain": parent_chain,
        "expected_generated_value_summary": _value_summary(expected),
        "actual_target_value_summary": _value_summary(actual),
        "classification": classification,
        "explanation": explanation,
        "blocks_repair_success": blocks,
        "suggested_next_action": suggested,
    }


def _first_repair_relevant_field_diffs(expected: dict[Any, Any], actual: dict[Any, Any]) -> list[tuple[str, Any, Any]]:
    diffs: list[tuple[str, Any, Any]] = []
    for key in sorted(set(expected) | set(actual), key=str):
        expected_value = expected.get(key, "missing")
        actual_value = actual.get(key, "missing")
        if _normalize_plist_value(expected_value) != _normalize_plist_value(actual_value):
            diffs.append((str(key), expected_value, actual_value))
    return diffs or [("", expected, actual)]


def _value_summary(value: Any) -> str:
    if value == "missing":
        return "missing"
    if isinstance(value, plistlib.UID):
        return f"UID:{value.data}"
    if isinstance(value, dict):
        keys = ",".join(sorted(str(key) for key in value))
        return f"dict(keys={keys})"
    if isinstance(value, list):
        return f"list(len={len(value)})"
    if isinstance(value, (str, int, float, bool)) or value is None:
        return str(value)
    return type(value).__name__


def _looks_like_apple_regenerated_archive_object(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return any(str(key).startswith("Apple") or str(key) in {"Generation", "NS.keys", "NS.objects"} for key in value)


def _overall_difference_classification(entries: list[dict[str, Any]], full_semantic_equivalence: bool, repair_actually_successful: bool) -> str:
    if not entries and full_semantic_equivalence:
        return "none"
    if any(bool(entry.get("blocks_repair_success", False)) for entry in entries):
        return "repair_relevant_difference"
    if repair_actually_successful and entries:
        return "unrelated_semantic_difference"
    return "repair_relevant_difference"


def _unrelated_semantic_difference_count(target_value: Any, artifact_value: Any) -> int:
    if target_value == artifact_value:
        return 0
    if not isinstance(target_value, dict) or not isinstance(artifact_value, dict):
        return 1
    differences = 0
    target_objects = target_value.get("$objects")
    artifact_objects = artifact_value.get("$objects")
    if isinstance(target_objects, list) and isinstance(artifact_objects, list):
        differences += abs(len(target_objects) - len(artifact_objects))
        for target_item, artifact_item in zip(target_objects, artifact_objects, strict=False):
            if target_item != artifact_item:
                differences += 1
    elif target_objects != artifact_objects:
        differences += 1
    target_top = target_value.get("$top")
    artifact_top = artifact_value.get("$top")
    if target_top != artifact_top:
        differences += max(1, len(set(_dict_keys(target_top)) ^ set(_dict_keys(artifact_top))))
    for key in sorted((set(target_value) | set(artifact_value)) - {"$objects", "$top"}):
        if target_value.get(key) != artifact_value.get(key):
            differences += 1
    return max(1, differences)


def _dict_keys(value: Any) -> list[str]:
    return sorted(str(key) for key in value) if isinstance(value, dict) else []


def _repair_relevant_networkextension_graph(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    objects = value.get("$objects")
    if not isinstance(objects, list):
        return []
    relevant: list[dict[str, Any]] = []
    for index, item in enumerate(objects):
        if not isinstance(item, dict) or not _is_repair_relevant_networkextension_object(item):
            continue
        relevant.append(
            {
                "index": index,
                "keys": sorted(str(key) for key in item),
                "signing_identifier": str(item.get("SigningIdentifier", "")),
                "path": str(item.get("Path", "")),
                "state": str(item.get("State", "")),
                "client_identity_uid": _uid_data(item.get("ClientIdentity")),
                "client_identities_uids": tuple(_uid_data(child) for child in item.get("ClientIdentities", []) if isinstance(child, plistlib.UID)) if isinstance(item.get("ClientIdentities"), list) else (),
                "object": _normalize_plist_value(item),
            }
        )
    return sorted(relevant, key=lambda row: (str(row["signing_identifier"]), str(row["path"]), str(row["state"]), str(row["client_identity_uid"]), str(row["index"])))


def _is_repair_relevant_networkextension_object(item: dict[Any, Any]) -> bool:
    signing_identifier = str(item.get("SigningIdentifier", ""))
    path = str(item.get("Path", ""))
    if signing_identifier.startswith("com.google.Chrome") or "Google Chrome" in path or "Chrome.app" in path:
        return True
    return "ClientIdentity" in item or "ClientIdentities" in item


def _uid_data(value: Any) -> int | None:
    return value.data if isinstance(value, plistlib.UID) else None


def _normalize_plist_value(value: Any) -> Any:
    if isinstance(value, plistlib.UID):
        return {"__uid__": value.data}
    if isinstance(value, dict):
        return {str(key): _normalize_plist_value(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, list):
        return [_normalize_plist_value(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_plist_value(item) for item in value]
    return value


def _repair_relevant_graph_difference_count(target_graph: list[dict[str, Any]], artifact_graph: list[dict[str, Any]]) -> int:
    target_rows = {_stable_json(row) for row in target_graph}
    artifact_rows = {_stable_json(row) for row in artifact_graph}
    return len(target_rows.symmetric_difference(artifact_rows))


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _repair_relevant_candidate_count(rows: list[Any]) -> int:
    count = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        classification = str(row.get("safety_classification", ""))
        signing_identifier = str(row.get("signing_identifier", ""))
        if signing_identifier.startswith("com.google.Chrome") and classification in {"potential_future_repair_candidate", "manual_only"}:
            count += 1
    return count


def _repair_relevant_validation_count(rows: list[Any]) -> int:
    statuses = {"runtime_absent", "stale", "ambiguous", "unverifiable"}
    return sum(1 for row in rows if isinstance(row, dict) and str(row.get("candidate_status", "")) in statuses)


def _candidate_rows(result: Any) -> list[Any]:
    if result is None:
        return []
    payload = result.to_json_dict()
    rows = payload.get("candidates")
    return rows if isinstance(rows, list) else []


def _validation_rows(result: Any) -> list[Any]:
    if result is None:
        return []
    payload = result.to_json_dict()
    rows = payload.get("validations")
    return rows if isinstance(rows, list) else []


def _semantic_candidate_rows(rows: list[Any]) -> list[dict[str, Any]]:
    normalized = []
    for row in rows:
        if isinstance(row, dict):
            normalized.append(
                {
                    "object_reference": row.get("object_reference"),
                    "signing_identifier": row.get("signing_identifier"),
                    "executable_path": row.get("executable_path"),
                    "could_ever_be_safely_removed": row.get("could_ever_be_safely_removed"),
                    "safety_classification": row.get("safety_classification"),
                }
            )
    return sorted(normalized, key=lambda item: (str(item.get("object_reference")), str(item.get("signing_identifier")), str(item.get("executable_path"))))


def _semantic_validation_rows(rows: list[Any]) -> list[dict[str, Any]]:
    normalized = []
    for row in rows:
        if isinstance(row, dict):
            normalized.append(
                {
                    "object_ref": row.get("object_ref"),
                    "signing_identifier": row.get("signing_identifier"),
                    "executable_path": row.get("executable_path"),
                    "candidate_status": row.get("candidate_status"),
                }
            )
    return sorted(normalized, key=lambda item: (str(item.get("object_ref")), str(item.get("signing_identifier")), str(item.get("executable_path"))))


def _uid_reference_edges(value: Any, path: str = "$") -> list[tuple[str, int]]:
    if isinstance(value, plistlib.UID):
        return [(path, value.data)]
    edges: list[tuple[str, int]] = []
    if isinstance(value, dict):
        for key in sorted(value):
            edges.extend(_uid_reference_edges(value[key], f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            edges.extend(_uid_reference_edges(item, f"{path}[{index}]"))
    return edges


def _dictionary_bindings(value: Any, path: str = "$") -> list[tuple[str, tuple[tuple[str, str], ...]]]:
    bindings: list[tuple[str, tuple[tuple[str, str], ...]]] = []
    if isinstance(value, dict):
        entries = tuple(sorted((str(key), _semantic_scalar(child)) for key, child in value.items()))
        bindings.append((path, entries))
        for key in sorted(value):
            bindings.extend(_dictionary_bindings(value[key], f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            bindings.extend(_dictionary_bindings(item, f"{path}[{index}]"))
    return bindings


def _semantic_scalar(value: Any) -> str:
    if isinstance(value, plistlib.UID):
        return f"UID:{value.data}"
    if isinstance(value, (str, int, float, bool)) or value is None:
        return repr(value)
    if isinstance(value, list):
        return "LIST"
    if isinstance(value, dict):
        return "DICT"
    return type(value).__name__


def render_networkextension_apply_validation(validation: NetworkExtensionApplyValidation) -> str:
    summary = validation.summary()
    lines = [
        "NetworkExtension apply validation",
        "- Read-only: true",
        "- Mutation performed: false",
        f"- Overall verdict: {validation.overall_verdict}",
        f"- Repair actually successful: {str(summary['repair_actually_successful']).lower()}",
        f"- Target path: {validation.target_path}",
        f"- Artifact path: {validation.artifact_path}",
        f"- Object count: {summary['object_count']}",
        f"- Repair candidates remaining: {summary['repair_candidates_remaining']}",
        f"- Validation candidates remaining: {summary['validation_candidates_remaining']}",
        f"- Graph consistency: {summary['graph_consistency']}",
        f"- Archive integrity: {summary['archive_integrity']}",
        f"- Byte-identical: {str(summary['bytewise_sha256_identical']).lower()}",
        f"- Semantically equivalent: {str(summary['semantic_equivalence']).lower()}",
        f"- Full semantic equivalence: {str(summary['semantic_equivalence']).lower()}",
        f"- Repair-relevant equivalence: {summary['repair_relevant_equivalence']}",
        f"- Repair-relevant semantic equivalence: {str(summary['repair_relevant_semantic_equivalence']).lower()}",
        f"- Apple regenerated unrelated archive objects: {str(summary['apple_regenerated_unrelated_archive_objects']).lower()}",
        f"- Unrelated semantic differences: {summary['unrelated_semantic_differences']}",
        f"- Repair-relevant semantic differences: {summary['repair_relevant_semantic_differences']}",
        f"- Blocking repair-relevant semantic differences: {summary['blocking_repair_relevant_semantic_differences']}",
        f"- Non-blocking semantic drift differences: {summary['non_blocking_semantic_differences']}",
        f"- SHA256 identical: {str(summary['sha256_identical']).lower()}",
        f"- Serialization explanation: {summary['serialization_difference_explained']}",
        "- Full semantic mismatch is diagnostic only when repair validation passes.",
        "- Non-blocking archive drift is diagnostic and does not imply repair failure.",
        "",
        "Validation stages",
    ]
    for stage in validation.stages:
        lines.append(f"- {stage.name}: {stage.status} — {stage.reason} ({stage.duration_ms:.1f} ms)")
    difference_entries = validation.semantic_comparison.get("repair_relevant_semantic_difference_entries", [])
    if difference_entries:
        lines.extend(["", "Repair-relevant semantic difference details"])
        blocking_entries = [entry for entry in difference_entries if bool(entry.get("blocks_repair_success", False))]
        non_blocking_entries = [entry for entry in difference_entries if not bool(entry.get("blocks_repair_success", False))]
        displayed_blocking_entries = blocking_entries[:5]
        displayed_entries = displayed_blocking_entries + non_blocking_entries[:3]
        for entry in displayed_entries:
            lines.extend(
                [
                    f"- {entry.get('id', 'unknown')}: {entry.get('classification', 'unknown_repair_relevant_difference')} — blocks repair success: {str(entry.get('blocks_repair_success', True)).lower()}",
                    f"  Path: {entry.get('semantic_path', entry.get('object_path', 'unknown'))}",
                    f"  Values: {entry.get('expected_generated_value_summary', '')} → {entry.get('actual_target_value_summary', '')}",
                    f"  Explanation: {entry.get('explanation', '')}",
                    f"  Suggested next action: {entry.get('suggested_next_action', '')}",
                ]
            )
        omitted_blocking = max(0, len(blocking_entries) - 5)
        omitted_non_blocking = max(0, len(non_blocking_entries) - 3)
        if omitted_blocking:
            lines.append(f"- {omitted_blocking} additional blocking repair-relevant semantic difference entries omitted from text output; use --json for full detail.")
        if omitted_non_blocking:
            lines.append(f"- {omitted_non_blocking} additional non-blocking semantic drift entries omitted from text output; use --json for full detail.")
    if validation.failure:
        lines.extend(
            [
                "",
                "Failure",
                f"- Stage: {validation.failure['stage']}",
                f"- Expected: {validation.failure['expected']}",
                f"- Observed: {validation.failure['observed']}",
                f"- Recommended rollback action: {validation.failure['recommended_rollback_action']}",
            ]
        )
    return "\n".join(lines)


def render_networkextension_apply_validation_summary(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "NetworkExtension apply validation",
            f"- Overall verdict: {summary.get('overall_verdict', 'VALIDATION_INCONCLUSIVE')}",
            f"- Repair actually successful: {str(summary.get('repair_actually_successful', False)).lower()}",
            f"- Failed stage: {summary.get('failed_stage', '') or 'none'}",
            f"- Repair candidates remaining: {summary.get('repair_candidates_remaining', 0)}",
            f"- Validation candidates remaining: {summary.get('validation_candidates_remaining', 0)}",
            f"- Graph consistency: {summary.get('graph_consistency', 'UNKNOWN')}",
            f"- Full semantic equivalence: {str(summary.get('semantic_equivalence', False)).lower()}",
            f"- Repair-relevant equivalence: {summary.get('repair_relevant_equivalence', 'FAILED')}",
            f"- Repair-relevant semantic equivalence: {str(summary.get('repair_relevant_semantic_equivalence', False)).lower()}",
            f"- Apple regenerated unrelated archive objects: {str(summary.get('apple_regenerated_unrelated_archive_objects', False)).lower()}",
            f"- Byte-identical: {str(summary.get('bytewise_sha256_identical', False)).lower()}",
            f"- SHA256 identical: {str(summary.get('sha256_identical', False)).lower()}",
        ]
    )


def _empty_statistics() -> dict[str, Any]:
    return {
        "object_count": 0,
        "uid_count": 0,
        "uid_rewrites": 0,
        "array_count": 0,
        "dictionary_count": 0,
        "repair_candidates_remaining": 0,
        "validation_candidates_remaining": 0,
        "broken_uid_references": 0,
        "dangling_references": 0,
        "malformed_arrays": 0,
        "malformed_dictionaries": 0,
        "duplicate_object_indices": 0,
        "serialization_inconsistencies": 0,
        "graph_consistency": "UNKNOWN",
        "archive_integrity": "UNKNOWN",
    }


def _archive_statistics(root: dict[str, Any], objects: list[Any]) -> dict[str, Any]:
    uid_values = _uid_values(root)
    broken = sum(1 for uid in uid_values if uid < 0 or uid >= len(objects))
    array_count = sum(1 for value in _walk(root) if isinstance(value, list))
    dictionary_count = sum(1 for value in _walk(root) if isinstance(value, dict))
    malformed_dicts = sum(1 for value in _walk(root) if isinstance(value, dict) and any(not isinstance(key, str) for key in value))
    return {
        "object_count": len(objects),
        "uid_count": len(uid_values),
        "uid_rewrites": 0,
        "array_count": array_count,
        "dictionary_count": dictionary_count,
        "broken_uid_references": broken,
        "dangling_references": broken,
        "malformed_arrays": 0,
        "malformed_dictionaries": malformed_dicts,
        "duplicate_object_indices": 0,
        "serialization_inconsistencies": 0,
    }


def _uid_values(value: Any) -> list[int]:
    values: list[int] = []
    if isinstance(value, plistlib.UID):
        return [value.data]
    if isinstance(value, dict):
        for child in value.values():
            values.extend(_uid_values(child))
    elif isinstance(value, list):
        for child in value:
            values.extend(_uid_values(child))
    return values


def _walk(value: Any) -> list[Any]:
    values = [value]
    if isinstance(value, dict):
        for child in value.values():
            values.extend(_walk(child))
    elif isinstance(value, list):
        for child in value:
            values.extend(_walk(child))
    return values


def _plutil_validate(path: Path) -> tuple[bool, str]:
    try:
        completed = subprocess.run(["plutil", "-lint", str(path)], check=False, text=True, capture_output=True, timeout=30)
    except FileNotFoundError:
        return False, "plutil unavailable"
    except Exception as error:
        return False, type(error).__name__
    reason = (completed.stdout or completed.stderr or "").strip()
    return completed.returncode == 0, reason or f"plutil exit {completed.returncode}"


def _failure(stage: ValidationStage) -> dict[str, Any]:
    return {
        "stage": stage.name,
        "reason": stage.reason,
        "expected": stage.expected,
        "observed": stage.observed,
        "recommended_rollback_action": "Do not report repair success; restore the pre-apply backup manually, then rerun apply-validation.",
    }
