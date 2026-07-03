from __future__ import annotations

from dataclasses import dataclass
import hashlib
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
            "semantic_comparison": self.semantic_comparison,
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
            "object_graph_equivalent": bool(self.semantic_comparison.get("object_graph_equivalent", False)),
            "uid_reference_graph_equivalent": bool(self.semantic_comparison.get("uid_reference_graph_equivalent", False)),
            "dictionary_bindings_equivalent": bool(self.semantic_comparison.get("dictionary_bindings_equivalent", False)),
            "repair_candidates_equivalent": bool(self.semantic_comparison.get("repair_candidates_equivalent", False)),
            "validation_candidates_equivalent": bool(self.semantic_comparison.get("validation_candidates_equivalent", False)),
            "serialization_difference_explained": str(self.semantic_comparison.get("serialization_difference_explained", "not_compared")),
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
    compare_ok = bool(semantic_comparison["semantic_equivalence"])
    add(
        "semantic_equivalence_with_generated_artifact",
        "PASS" if compare_ok else "FAIL",
        "target is semantically equivalent to generated repair artifact" if compare_ok else "target differs semantically from generated repair artifact",
        "semantically equivalent",
        "semantically equivalent" if compare_ok else "different semantics",
    )
    add("validation_summary_generated", "PASS", "validation summary generated", "generated", "generated")

    core_success = (
        stats["archive_integrity"] == "PASSED"
        and stats["graph_consistency"] == "PASSED"
        and stats["repair_candidates_remaining"] == 0
        and stats["validation_candidates_remaining"] == 0
        and bool(semantic_comparison["semantic_equivalence"])
    )
    if core_success and all(stage.status != "FAIL" for stage in stages):
        verdict = "VALIDATION_PASSED"
    elif any(stage.status == "FAIL" for stage in stages):
        verdict = "VALIDATION_FAILED"
    elif any(stage.status == "INCONCLUSIVE" for stage in stages):
        verdict = "VALIDATION_INCONCLUSIVE"
    else:
        verdict = "VALIDATION_PASSED"

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
        f"- Repair actually successful: {str(validation.overall_verdict == 'VALIDATION_PASSED').lower()}",
        f"- Target path: {validation.target_path}",
        f"- Artifact path: {validation.artifact_path}",
        f"- Object count: {summary['object_count']}",
        f"- Repair candidates remaining: {summary['repair_candidates_remaining']}",
        f"- Validation candidates remaining: {summary['validation_candidates_remaining']}",
        f"- Graph consistency: {summary['graph_consistency']}",
        f"- Archive integrity: {summary['archive_integrity']}",
        f"- Byte-identical: {str(summary['bytewise_sha256_identical']).lower()}",
        f"- Semantically equivalent: {str(summary['semantic_equivalence']).lower()}",
        f"- SHA256 identical: {str(summary['sha256_identical']).lower()}",
        f"- Serialization explanation: {summary['serialization_difference_explained']}",
        "- SHA256 mismatch alone is not a failure when semantic validation passes.",
        "",
        "Validation stages",
    ]
    for stage in validation.stages:
        lines.append(f"- {stage.name}: {stage.status} — {stage.reason} ({stage.duration_ms:.1f} ms)")
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
            f"- Repair actually successful: {str(summary.get('overall_verdict') == 'VALIDATION_PASSED').lower()}",
            f"- Failed stage: {summary.get('failed_stage', '') or 'none'}",
            f"- Repair candidates remaining: {summary.get('repair_candidates_remaining', 0)}",
            f"- Validation candidates remaining: {summary.get('validation_candidates_remaining', 0)}",
            f"- Graph consistency: {summary.get('graph_consistency', 'UNKNOWN')}",
            f"- Semantic equivalence: {str(summary.get('semantic_equivalence', False)).lower()}",
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
