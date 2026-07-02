from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
import hashlib
import json
import plistlib
from pathlib import Path
from typing import Any, Iterable

from macos_state_explorer.networkextension_state import default_networkextension_roots


@dataclass(frozen=True)
class NetworkExtensionRepairCandidate:
    artifact: str
    artifact_path: str
    object_index: int
    object_reference: str
    identity_type: str
    signing_identifier: str | None
    executable_path: str | None
    code_sign_clone_usage: bool
    object_graph_location: str
    parent_dictionary: str | None
    appears_complete: bool
    appears_duplicated: bool
    appears_active: bool
    appears_historical: bool
    appears_orphaned: bool
    references_installed_application: bool
    references_only_code_sign_clone: bool
    executable_exists: bool
    could_ever_be_safely_removed: bool
    additional_runtime_evidence_required: bool
    safety_classification: str
    explanation: str

    def sort_key(self) -> tuple[str, int, str, str]:
        return (self.artifact_path, self.object_index, self.signing_identifier or "", self.executable_path or "")

    def identity_key(self) -> tuple[str, str]:
        return (self.signing_identifier or "", self.executable_path or "")

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "artifact": self.artifact,
            "artifact_path": self.artifact_path,
            "object_index": self.object_index,
            "object_reference": self.object_reference,
            "identity_type": self.identity_type,
            "signing_identifier": self.signing_identifier,
            "executable_path": self.executable_path,
            "code_sign_clone_usage": self.code_sign_clone_usage,
            "object_graph_location": self.object_graph_location,
            "parent_dictionary": self.parent_dictionary,
            "appears_complete": self.appears_complete,
            "appears_duplicated": self.appears_duplicated,
            "appears_active": self.appears_active,
            "appears_historical": self.appears_historical,
            "appears_orphaned": self.appears_orphaned,
            "references_installed_application": self.references_installed_application,
            "references_only_code_sign_clone": self.references_only_code_sign_clone,
            "executable_exists": self.executable_exists,
            "could_ever_be_safely_removed": self.could_ever_be_safely_removed,
            "additional_runtime_evidence_required": self.additional_runtime_evidence_required,
            "safety_classification": self.safety_classification,
            "explanation": self.explanation,
        }


@dataclass(frozen=True)
class RepairCandidateArtifact:
    artifact: str
    artifact_path: str
    decoded: bool
    object_count: int
    malformed: bool = False
    error: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "artifact": self.artifact,
            "artifact_path": self.artifact_path,
            "decoded": self.decoded,
            "object_count": self.object_count,
            "malformed": self.malformed,
            "error": self.error,
        }


@dataclass(frozen=True)
class NetworkExtensionRepairCandidates:
    repair_candidates_id: str
    candidates: tuple[NetworkExtensionRepairCandidate, ...]
    decoded_artifacts: tuple[RepairCandidateArtifact, ...]
    roots: tuple[str, ...]

    def summary(self) -> dict[str, Any]:
        safety_counts = _counts(item.safety_classification for item in self.candidates)
        return {
            "total_candidates": len(self.candidates),
            "decoded_artifacts": sum(item.decoded for item in self.decoded_artifacts),
            "malformed_artifacts": sum(item.malformed for item in self.decoded_artifacts),
            "candidate_object_refs": sorted(f"{item.artifact}:{item.object_reference}" for item in self.candidates),
            "complete_records": sum(item.appears_complete for item in self.candidates),
            "duplicate_records": sum(item.appears_duplicated for item in self.candidates),
            "active_records": sum(item.appears_active for item in self.candidates),
            "historical_records": sum(item.appears_historical for item in self.candidates),
            "orphaned_records": sum(item.appears_orphaned for item in self.candidates),
            "installed_application_references": sum(item.references_installed_application for item in self.candidates),
            "code_sign_clone_only_records": sum(item.references_only_code_sign_clone for item in self.candidates),
            "executable_exists_records": sum(item.executable_exists for item in self.candidates),
            "runtime_confirmation_required": sum(item.additional_runtime_evidence_required for item in self.candidates),
            "safety_classifications": safety_counts,
            "read_only": True,
            "mutation_performed": False,
        }

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "command": "networkextension repair-candidates",
            "repair_candidates_id": self.repair_candidates_id,
            "timestamp": "1970-01-01T00:00:00Z",
            "read_only": True,
            "mutation_performed": False,
            "summary": self.summary(),
            "candidates": [item.to_json_dict() for item in self.candidates],
            "decoded_artifacts": [item.to_json_dict() for item in self.decoded_artifacts],
            "roots": list(self.roots),
        }


def build_networkextension_repair_candidates(roots: Iterable[Path] | None = None) -> NetworkExtensionRepairCandidates:
    root_paths = [Path(root).expanduser() for root in (roots if roots is not None else default_networkextension_roots())]
    candidates: list[NetworkExtensionRepairCandidate] = []
    artifacts: list[RepairCandidateArtifact] = []
    for root in root_paths:
        for path in _candidate_files(root):
            artifact, records = _decode_artifact(path, root)
            artifacts.append(artifact)
            candidates.extend(records)
    duplicate_keys = {key for key, count in _key_counts(item.identity_key() for item in candidates).items() if key != ("", "") and count > 1}
    finalized = tuple(sorted((_with_duplicate(item, item.identity_key() in duplicate_keys) for item in candidates), key=lambda item: item.sort_key()))
    ordered_artifacts = tuple(sorted(artifacts, key=lambda item: item.artifact_path))
    digest = hashlib.sha256(
        json.dumps(
            {
                "artifacts": [item.to_json_dict() for item in ordered_artifacts],
                "candidates": [item.to_json_dict() for item in finalized],
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()[:16]
    return NetworkExtensionRepairCandidates(
        repair_candidates_id=f"networkextension-repair-candidates-{digest}",
        candidates=finalized,
        decoded_artifacts=ordered_artifacts,
        roots=tuple(str(root) for root in root_paths),
    )


def networkextension_repair_candidates_summary(candidates: NetworkExtensionRepairCandidates) -> dict[str, Any]:
    return candidates.summary()


def render_networkextension_repair_candidates(candidates: NetworkExtensionRepairCandidates) -> str:
    summary = candidates.summary()
    lines = [
        "NetworkExtension repair candidates",
        "- Read-only: true",
        "- Mutation performed: false",
        f"- Total candidates: {summary['total_candidates']}",
        f"- Duplicate records: {summary['duplicate_records']}",
        f"- Historical records: {summary['historical_records']}",
        f"- Orphaned records: {summary['orphaned_records']}",
        f"- Runtime confirmation required: {summary['runtime_confirmation_required']}",
        "- Automatic deletion recommendation: never",
        "",
        "Candidates",
    ]
    if not candidates.candidates:
        lines.append("- none")
    for item in candidates.candidates:
        lines.append(f"- {item.artifact} :: {item.object_reference} :: {item.signing_identifier or 'unknown'} [{item.safety_classification}]")
        lines.append(f"  - Identity type: {item.identity_type}")
        lines.append(f"  - Executable path: {item.executable_path or 'unknown'}")
        lines.append(f"  - Complete: {str(item.appears_complete).lower()}; duplicated: {str(item.appears_duplicated).lower()}; active: {str(item.appears_active).lower()}; historical: {str(item.appears_historical).lower()}; orphaned: {str(item.appears_orphaned).lower()}")
        lines.append(f"  - Executable exists: {str(item.executable_exists).lower()}; installed app: {str(item.references_installed_application).lower()}; code_sign_clone only: {str(item.references_only_code_sign_clone).lower()}")
        lines.append(f"  - Runtime evidence required: {str(item.additional_runtime_evidence_required).lower()}")
        lines.append(f"  - Explanation: {item.explanation}")
    return "\n".join(lines)


def render_networkextension_repair_candidates_summary(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "NetworkExtension repair candidates",
            f"- Total candidates: {summary.get('total_candidates', 0)}",
            f"- Duplicate records: {summary.get('duplicate_records', 0)}",
            f"- Historical records: {summary.get('historical_records', 0)}",
            f"- Orphaned records: {summary.get('orphaned_records', 0)}",
            f"- Runtime confirmation required: {summary.get('runtime_confirmation_required', 0)}",
            "- Automatic deletion recommendation: never",
        ]
    )


def _decode_artifact(path: Path, root: Path) -> tuple[RepairCandidateArtifact, list[NetworkExtensionRepairCandidate]]:
    display = _display_path(path, root)
    artifact_name = path.name
    try:
        value = plistlib.loads(path.read_bytes())
    except Exception as error:
        return RepairCandidateArtifact(artifact=artifact_name, artifact_path=display, decoded=False, object_count=0, malformed=True, error=type(error).__name__), []
    objects = value.get("$objects") if isinstance(value, dict) else None
    if not isinstance(objects, list):
        return RepairCandidateArtifact(artifact=artifact_name, artifact_path=display, decoded=False, object_count=0, malformed=True, error="missing_$objects"), []
    parent_edges = _build_parent_edges(objects)
    top_indices = _top_indices(value)
    candidates = [_candidate_from_object(artifact_name, display, index, node, objects, parent_edges, top_indices) for index, node in enumerate(objects) if isinstance(node, dict)]
    return RepairCandidateArtifact(artifact=artifact_name, artifact_path=display, decoded=True, object_count=len(objects)), [item for item in candidates if item is not None]


def _candidate_from_object(
    artifact: str,
    artifact_path: str,
    index: int,
    node: dict[Any, Any],
    objects: list[Any],
    parent_edges: dict[int, list[tuple[int, str | None]]],
    top_indices: set[int],
) -> NetworkExtensionRepairCandidate | None:
    signing_identifier = _string_value(node, objects, ["SigningIdentifier", "signing_identifier", "bundleID", "BundleIdentifier", "CodeSign", "CodeSigningIdentifier"])
    executable_path = _string_value(node, objects, ["Path", "ExecutablePath", "Executable", "path"])
    if not (signing_identifier or executable_path):
        return None
    raw_context = " ".join([str(key) for key in node] + [str(_resolve(value, objects)) for value in node.values()])
    if not _is_chrome_identity(signing_identifier, executable_path, raw_context):
        return None
    parent_chain = _parent_chain(index, parent_edges, top_indices)
    object_reference = f"$objects[{index}]"
    parent_dictionary = f"$objects[{parent_chain[-1]}]" if parent_chain else None
    code_sign_clone_usage = _contains_clone(signing_identifier) or _contains_clone(executable_path) or _contains_clone(raw_context)
    references_only_code_sign_clone = code_sign_clone_usage and not _contains_plain_chrome(executable_path) and _contains_clone(signing_identifier)
    appears_complete = bool(signing_identifier and executable_path)
    executable_exists = bool(executable_path and Path(executable_path).exists())
    references_installed_application = bool(_app_path(executable_path) and Path(_app_path(executable_path) or "").exists())
    nearest_parent_context = " ".join(str(objects[parent]) for parent in parent_chain[-2:])
    context_lower = " ".join([raw_context, nearest_parent_context]).lower()
    appears_historical = any(token in context_lower for token in ["historical", "history", "cache", "archive"])
    appears_active = any(token in context_lower for token in ["active", "allow", "enabled"]) and not appears_historical
    appears_orphaned = (appears_complete and not executable_exists) or "orphan" in context_lower
    safety = _safety_classification(appears_complete, appears_active, appears_historical, appears_orphaned, references_only_code_sign_clone, executable_exists)
    return NetworkExtensionRepairCandidate(
        artifact=artifact,
        artifact_path=artifact_path,
        object_index=index,
        object_reference=object_reference,
        identity_type="client_identity_record",
        signing_identifier=signing_identifier,
        executable_path=executable_path,
        code_sign_clone_usage=code_sign_clone_usage,
        object_graph_location=f"{artifact}:{object_reference}",
        parent_dictionary=parent_dictionary,
        appears_complete=appears_complete,
        appears_duplicated=False,
        appears_active=appears_active,
        appears_historical=appears_historical,
        appears_orphaned=appears_orphaned,
        references_installed_application=references_installed_application,
        references_only_code_sign_clone=references_only_code_sign_clone,
        executable_exists=executable_exists,
        could_ever_be_safely_removed=False,
        additional_runtime_evidence_required=appears_complete,
        safety_classification=safety,
        explanation=_explanation(safety, appears_complete, appears_active, appears_historical, appears_orphaned, references_only_code_sign_clone, executable_exists),
    )


def _with_duplicate(item: NetworkExtensionRepairCandidate, duplicate: bool) -> NetworkExtensionRepairCandidate:
    if item.appears_duplicated == duplicate:
        return item
    safety = _safety_classification(item.appears_complete, item.appears_active, item.appears_historical, item.appears_orphaned, item.references_only_code_sign_clone, item.executable_exists, duplicate=duplicate)
    return NetworkExtensionRepairCandidate(
        artifact=item.artifact,
        artifact_path=item.artifact_path,
        object_index=item.object_index,
        object_reference=item.object_reference,
        identity_type=item.identity_type,
        signing_identifier=item.signing_identifier,
        executable_path=item.executable_path,
        code_sign_clone_usage=item.code_sign_clone_usage,
        object_graph_location=item.object_graph_location,
        parent_dictionary=item.parent_dictionary,
        appears_complete=item.appears_complete,
        appears_duplicated=duplicate,
        appears_active=item.appears_active,
        appears_historical=item.appears_historical,
        appears_orphaned=item.appears_orphaned,
        references_installed_application=item.references_installed_application,
        references_only_code_sign_clone=item.references_only_code_sign_clone,
        executable_exists=item.executable_exists,
        could_ever_be_safely_removed=False,
        additional_runtime_evidence_required=item.additional_runtime_evidence_required,
        safety_classification=safety,
        explanation=_explanation(safety, item.appears_complete, item.appears_active, item.appears_historical, item.appears_orphaned, item.references_only_code_sign_clone, item.executable_exists, duplicate=duplicate),
    )


def _safety_classification(
    complete: bool,
    active: bool,
    historical: bool,
    orphaned: bool,
    clone_only: bool,
    executable_exists: bool,
    *,
    duplicate: bool = False,
) -> str:
    if not complete:
        return "not_actionable"
    if active and executable_exists:
        return "requires_runtime_confirmation"
    if clone_only:
        return "manual_only" if executable_exists else "potential_future_repair_candidate"
    if orphaned or historical or duplicate:
        return "potential_future_repair_candidate"
    return "never_delete"


def _explanation(
    safety: str,
    complete: bool,
    active: bool,
    historical: bool,
    orphaned: bool,
    clone_only: bool,
    executable_exists: bool,
    *,
    duplicate: bool = False,
) -> str:
    if not complete:
        return "insufficient object graph evidence: signing identifier or executable path is missing; never automatically delete."
    if active and executable_exists:
        return "complete installed client identity record appears active; requires runtime confirmation and never automatically delete."
    if clone_only:
        return "record references only code_sign_clone identity context; manual review and runtime confirmation are required; never automatically delete."
    if orphaned:
        return "object graph references a Chrome executable path that is not currently present; potential future repair candidate but never automatically delete."
    if historical:
        return "object graph context appears historical/archive-like; future repair would require runtime confirmation; never automatically delete."
    if duplicate:
        return "duplicate client identity record observed; future repair would require runtime confirmation; never automatically delete."
    return "evidence is insufficient to prove safe removal; never automatically delete."


def _string_value(node: dict[Any, Any], objects: list[Any], keys: list[str]) -> str | None:
    for key in keys:
        if key in node:
            resolved = _resolve(node[key], objects)
            if isinstance(resolved, str):
                return resolved
    return None


def _resolve(value: Any, objects: list[Any]) -> Any:
    if isinstance(value, plistlib.UID) and 0 <= value.data < len(objects):
        return objects[value.data]
    return value


def _is_chrome_identity(signing_identifier: str | None, executable_path: str | None, raw_context: str) -> bool:
    lower = " ".join([signing_identifier or "", executable_path or "", raw_context]).lower()
    return "com.google.chrome" in lower or "google chrome" in lower or "chromium" in lower


def _contains_clone(value: str | None) -> bool:
    return "code_sign_clone" in (value or "").lower()


def _contains_plain_chrome(value: str | None) -> bool:
    lower = (value or "").lower()
    return "google chrome.app" in lower or lower == "com.google.chrome"


def _app_path(path: str | None) -> str | None:
    if not path or ".app" not in path:
        return None
    prefix = path.split(".app", 1)[0] + ".app"
    return prefix


def _build_parent_edges(objects: list[Any]) -> dict[int, list[tuple[int, str | None]]]:
    parents: dict[int, list[tuple[int, str | None]]] = defaultdict(list)
    for index, node in enumerate(objects):
        for child, label in _uid_children(node):
            if 0 <= child < len(objects):
                parents[child].append((index, label))
    return parents


def _uid_children(value: Any, prefix: str | None = None) -> list[tuple[int, str | None]]:
    if isinstance(value, plistlib.UID):
        return [(value.data, prefix)]
    if isinstance(value, dict):
        result: list[tuple[int, str | None]] = []
        for key in sorted(value):
            child_prefix = str(key) if prefix is None else f"{prefix}.{key}"
            result.extend(_uid_children(value[key], child_prefix))
        return result
    if isinstance(value, list):
        result = []
        for idx, item in enumerate(value):
            child_prefix = f"[{idx}]" if prefix is None else f"{prefix}[{idx}]"
            result.extend(_uid_children(item, child_prefix))
        return result
    return []


def _top_indices(value: dict[str, Any]) -> set[int]:
    top = value.get("$top")
    return {index for index, _label in _uid_children(top)} if isinstance(top, dict) else set()


def _parent_chain(index: int, parent_edges: dict[int, list[tuple[int, str | None]]], top_indices: set[int]) -> list[int]:
    if index in top_indices:
        return []
    queue = deque([(index, [])])
    visited = {index}
    while queue:
        current, path = queue.popleft()
        for parent, _label in sorted(parent_edges.get(current, []), key=lambda item: (item[0], item[1] or "")):
            next_path = [parent, *path]
            if parent in top_indices or not parent_edges.get(parent):
                return next_path
            if parent not in visited:
                visited.add(parent)
                queue.append((parent, next_path))
    return []


def _candidate_files(root: Path) -> list[Path]:
    root = root.expanduser()
    if root.is_file():
        return [root]
    if root.is_dir():
        return sorted(path for path in root.rglob("*") if path.is_file() and _is_candidate(path))
    return []


def _is_candidate(path: Path) -> bool:
    lower = path.name.lower()
    return any(token in lower for token in ["networkextension", "localnetwork", "local-network", "securityprivacyextension", "systemsettings"])


def _display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _counts(values: Iterable[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        result[value] = result.get(value, 0) + 1
    return dict(sorted(result.items()))


def _key_counts(values: Iterable[tuple[str, str]]) -> dict[tuple[str, str], int]:
    result: dict[tuple[str, str], int] = {}
    for value in values:
        result[value] = result.get(value, 0) + 1
    return result
