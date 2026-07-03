from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
import json
import plistlib
from pathlib import Path
from typing import Any, Iterable, Sequence

from macos_state_explorer.networkextension_repair_transaction_package import (
    NetworkExtensionRepairTransactionPackage,
    RepairTransaction,
)

OPERATOR_WARNING = "Generated operator specification only; macos-state-explorer will not execute this repair."
POST_REPAIR_VALIDATION_COMMANDS = (
    "mse networkextension validate-candidates",
    "mse networkextension repair-plan-preview",
    "mse networkextension repair-transaction-package",
    "mse networkextension manual-repair-runbook",
    "mse networkextension object-graph",
    "mse networkextension raw-references",
    "mse report local-network --bundle ~/Desktop/mse-local-network-post-repair-bundle",
    "mse diff bundles ~/Desktop/mse-local-network-pre-repair-bundle ~/Desktop/mse-local-network-post-repair-bundle",
)
ROLLBACK_PLAN = (
    "Restore the original plist artifact from backup.",
    "Reboot.",
    "Verify restored artifact SHA256 matches the pre-repair hash.",
    "Run mse networkextension validate-candidates.",
    "Run mse report local-network.",
    "Run mse networkextension object-graph.",
    "Run mse launchservices analyze.",
)
FAILURE_MODES = (
    "broken UID graph",
    "invalid NSKeyedArchiver archive",
    "dangling references",
    "dictionary key mismatch",
    "orphan arrays",
    "missing class records",
    "boot-time preference rejection",
    "NetworkExtension silently rebuilding archive",
    "preference cache regeneration",
    "System Settings overwrite",
)


@dataclass(frozen=True)
class AffectedObjectDetail:
    object_index: int
    object_class: str
    parent_chain: tuple[str, ...]
    referenced_uids: tuple[int, ...]
    referencing_objects: tuple[str, ...]
    dictionary_keys: tuple[str, ...]
    array_memberships: tuple[str, ...]
    incoming_references: tuple[str, ...]
    outgoing_references: tuple[str, ...]
    dependency_graph: dict[str, list[str]]
    can_be_deleted_independently: bool
    requires_graph_rewrite: bool

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "object_index": self.object_index,
            "object_class": self.object_class,
            "parent_chain": list(self.parent_chain),
            "referenced_uids": list(self.referenced_uids),
            "referencing_objects": list(self.referencing_objects),
            "dictionary_keys": list(self.dictionary_keys),
            "array_memberships": list(self.array_memberships),
            "incoming_references": list(self.incoming_references),
            "outgoing_references": list(self.outgoing_references),
            "dependency_graph": self.dependency_graph,
            "can_be_deleted_independently": self.can_be_deleted_independently,
            "requires_graph_rewrite": self.requires_graph_rewrite,
        }


@dataclass(frozen=True)
class ManualRepairRunbookTransaction:
    transaction_id: str
    source_artifact: dict[str, Any]
    sha256: str | None
    parent_object: str
    candidate_object_refs: tuple[str, ...]
    signing_identifier: str
    validation_status: str
    executable_path_class: str
    repair_class: str
    expected_mutation: str
    expected_object_removal: tuple[str, ...]
    expected_object_rewrite: tuple[str, ...]
    expected_uid_rewiring: tuple[str, ...]
    expected_array_changes: tuple[str, ...]
    expected_dictionary_changes: tuple[str, ...]
    expected_object_count_delta: int
    objects_that_must_remain_untouched: tuple[str, ...]
    objects_requiring_reindexing: tuple[str, ...]
    objects_requiring_uid_remapping: tuple[str, ...]
    objects_requiring_archive_regeneration: tuple[str, ...]
    affected_objects: tuple[AffectedObjectDetail, ...]
    safety_analysis: dict[str, bool]
    risk_assessment: str
    difficulty: str
    difficulty_explanation: str
    failure_modes: tuple[str, ...]
    rollback_requirements: tuple[str, ...]
    verification_commands: tuple[str, ...]
    expected_verification_outcome: str
    read_only: bool
    preview_only: bool
    mutation_performed: bool
    executable_by_tool: bool
    not_executable_by_tool: bool

    def sort_key(self) -> tuple[str, int, str]:
        status_order = {"stale_code_sign_clone": 0, "stale_missing_executable": 1}
        return (self.source_artifact.get("name", ""), status_order.get(self.validation_status, 99), self.transaction_id)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "transaction_id": self.transaction_id,
            "source_artifact": self.source_artifact,
            "sha256": self.sha256,
            "parent_object": self.parent_object,
            "candidate_object_refs": list(self.candidate_object_refs),
            "signing_identifier": self.signing_identifier,
            "validation_status": self.validation_status,
            "executable_path_class": self.executable_path_class,
            "repair_class": self.repair_class,
            "expected_mutation": self.expected_mutation,
            "expected_object_removal": list(self.expected_object_removal),
            "expected_object_rewrite": list(self.expected_object_rewrite),
            "expected_uid_rewiring": list(self.expected_uid_rewiring),
            "expected_array_changes": list(self.expected_array_changes),
            "expected_dictionary_changes": list(self.expected_dictionary_changes),
            "expected_object_count_delta": self.expected_object_count_delta,
            "objects_that_must_remain_untouched": list(self.objects_that_must_remain_untouched),
            "objects_requiring_reindexing": list(self.objects_requiring_reindexing),
            "objects_requiring_uid_remapping": list(self.objects_requiring_uid_remapping),
            "objects_requiring_archive_regeneration": list(self.objects_requiring_archive_regeneration),
            "affected_objects": [item.to_json_dict() for item in self.affected_objects],
            "safety_analysis": self.safety_analysis,
            "risk_assessment": self.risk_assessment,
            "difficulty": self.difficulty,
            "difficulty_explanation": self.difficulty_explanation,
            "failure_modes": list(self.failure_modes),
            "rollback_requirements": list(self.rollback_requirements),
            "verification_commands": list(self.verification_commands),
            "expected_verification_outcome": self.expected_verification_outcome,
            "read_only": self.read_only,
            "preview_only": self.preview_only,
            "mutation_performed": self.mutation_performed,
            "executable_by_tool": self.executable_by_tool,
            "not_executable_by_tool": self.not_executable_by_tool,
        }


@dataclass(frozen=True)
class NetworkExtensionManualRepairRunbook:
    manual_repair_runbook_id: str
    source_transaction_package_id: str
    transactions: tuple[ManualRepairRunbookTransaction, ...]

    def summary(self) -> dict[str, Any]:
        return {
            "runbook_ids": [self.manual_repair_runbook_id],
            "transaction_count": len(self.transactions),
            "transaction_ids": [item.transaction_id for item in self.transactions],
            "difficulty_counts": _counts(item.difficulty for item in self.transactions),
            "requires_archive_regeneration_count": sum(item.safety_analysis.get("archive_rebuild", False) for item in self.transactions),
            "manual_only": True,
            "read_only": True,
            "mutation_performed": False,
            "executable_by_tool": False,
            "automatic_execution_recommendation": "never",
        }

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "command": "networkextension manual-repair-runbook",
            "manual_repair_runbook_id": self.manual_repair_runbook_id,
            "timestamp": "1970-01-01T00:00:00Z",
            "read_only": True,
            "mutation_performed": False,
            "executable_by_tool": False,
            "automatic_execution_recommendation": "never",
            "source_transaction_package_id": self.source_transaction_package_id,
            "summary": self.summary(),
            "operator_warning": OPERATOR_WARNING,
            "failure_modes": list(FAILURE_MODES),
            "rollback_plan": list(ROLLBACK_PLAN),
            "post_repair_validation_commands": list(POST_REPAIR_VALIDATION_COMMANDS),
            "transactions": [item.to_json_dict() for item in self.transactions],
        }


def build_networkextension_manual_repair_runbook(
    transaction_package: NetworkExtensionRepairTransactionPackage,
    roots: Sequence[Path] | None = None,
) -> NetworkExtensionManualRepairRunbook:
    root_paths = tuple(Path(root).expanduser() for root in (roots or ()))
    transactions = tuple(sorted((_runbook_transaction(item, root_paths) for item in transaction_package.transactions), key=lambda item: item.sort_key()))
    digest = hashlib.sha256(json.dumps([item.to_json_dict() for item in transactions], sort_keys=True).encode()).hexdigest()[:16]
    return NetworkExtensionManualRepairRunbook(
        manual_repair_runbook_id=f"networkextension-manual-repair-runbook-{digest}",
        source_transaction_package_id=transaction_package.repair_transaction_package_id,
        transactions=transactions,
    )


def networkextension_manual_repair_runbook_summary(runbook: NetworkExtensionManualRepairRunbook) -> dict[str, Any]:
    return runbook.summary()


def render_networkextension_manual_repair_runbook(runbook: NetworkExtensionManualRepairRunbook) -> str:
    summary = runbook.summary()
    lines = [
        "NetworkExtension manual repair runbook",
        "- Read-only: true",
        "- Mutation performed: false",
        "- Executable by tool: false",
        "- Automatic execution recommendation: never",
        f"- Transactions: {summary['transaction_count']}",
        f"- Difficulty counts: {', '.join(f'{key}={value}' for key, value in summary['difficulty_counts'].items()) or 'none'}",
        f"- {OPERATOR_WARNING}",
        "",
        "Failure modes",
    ]
    lines.extend(f"- {item}" for item in FAILURE_MODES)
    lines.extend(["", "Rollback procedure"])
    lines.extend(f"- {item}" for item in ROLLBACK_PLAN)
    lines.extend(["", "Post-repair validation commands"])
    lines.extend(f"- {item}" for item in POST_REPAIR_VALIDATION_COMMANDS)
    lines.extend(["", "Transactions"])
    if not runbook.transactions:
        lines.append("- none")
    for transaction in runbook.transactions:
        lines.append(f"- {transaction.transaction_id}")
        lines.append(f"  - Source artifact: {transaction.source_artifact.get('name')} sha256={transaction.sha256 or 'unavailable'}")
        lines.append(f"  - Parent object: {transaction.parent_object}")
        lines.append(f"  - Candidate refs: {', '.join(transaction.candidate_object_refs)}")
        lines.append(f"  - SigningIdentifier: {transaction.signing_identifier}")
        lines.append(f"  - Validation status: {transaction.validation_status}")
        lines.append(f"  - Executable path class: {transaction.executable_path_class}")
        lines.append(f"  - Repair class: {transaction.repair_class}")
        lines.append(f"  - Difficulty: {transaction.difficulty} — {transaction.difficulty_explanation}")
        lines.append(f"  - Expected object removal: {', '.join(transaction.expected_object_removal) if transaction.expected_object_removal else 'none'}")
        lines.append(f"  - Expected UID rewiring: {', '.join(transaction.expected_uid_rewiring) if transaction.expected_uid_rewiring else 'none'}")
        lines.append(f"  - Expected array changes: {', '.join(transaction.expected_array_changes) if transaction.expected_array_changes else 'none'}")
        lines.append(f"  - Expected dictionary changes: {', '.join(transaction.expected_dictionary_changes) if transaction.expected_dictionary_changes else 'none'}")
        lines.append(f"  - Expected object count delta: {transaction.expected_object_count_delta}")
        lines.append(f"  - Risk assessment: {transaction.risk_assessment}")
        lines.append("  - Flags: preview_only=true, mutation_performed=false, executable_by_tool=false")
    return "\n".join(lines)


def render_networkextension_manual_repair_runbook_summary(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "NetworkExtension manual repair runbook",
            f"- Transactions: {summary.get('transaction_count', 0)}",
            f"- Difficulty counts: {summary.get('difficulty_counts', {})}",
            f"- Requires archive regeneration: {summary.get('requires_archive_regeneration_count', 0)}",
            "- Manual only: true",
            "- Mutation performed: false",
            "- Executable by tool: false",
        ]
    )


def _runbook_transaction(transaction: RepairTransaction, roots: Sequence[Path]) -> ManualRepairRunbookTransaction:
    graph = _load_artifact_graph(transaction.source_artifact.path, transaction.source_artifact.name, roots)
    object_refs = tuple(dict.fromkeys((transaction.affected_parent_object_record, *transaction.candidate_object_refs)))
    details = tuple(_object_detail(graph, _object_index(ref)) for ref in object_refs if _object_index(ref) is not None)
    candidate_refs = tuple(ref for ref in transaction.candidate_object_refs)
    refs_for_rewrite = tuple(dict.fromkeys((transaction.affected_parent_object_record, *candidate_refs)))
    safety = _safety_analysis(details)
    difficulty, explanation = _difficulty(transaction, details, safety)
    return ManualRepairRunbookTransaction(
        transaction_id=transaction.transaction_id,
        source_artifact=transaction.source_artifact.to_json_dict(),
        sha256=transaction.source_artifact.sha256,
        parent_object=transaction.affected_parent_object_record,
        candidate_object_refs=candidate_refs,
        signing_identifier=transaction.signing_identifier,
        validation_status=transaction.validation_status,
        executable_path_class=transaction.executable_path_class,
        repair_class="manual_nskeyedarchiver_object_graph_rewrite",
        expected_mutation="manual_object_graph_edit_specification_only",
        expected_object_removal=candidate_refs,
        expected_object_rewrite=refs_for_rewrite,
        expected_uid_rewiring=tuple(f"rewire UID references after removing {ref}" for ref in candidate_refs),
        expected_array_changes=(f"remove candidate UID entries from arrays referencing {transaction.affected_parent_object_record}",),
        expected_dictionary_changes=(f"remove dictionary entries that point at {', '.join(candidate_refs)}",),
        expected_object_count_delta=-len(candidate_refs),
        objects_that_must_remain_untouched=("$objects[0]", "$archiver", "$version", "$top"),
        objects_requiring_reindexing=refs_for_rewrite,
        objects_requiring_uid_remapping=refs_for_rewrite,
        objects_requiring_archive_regeneration=(transaction.source_artifact.name,),
        affected_objects=details,
        safety_analysis=safety,
        risk_assessment="High: NSKeyedArchiver object graph edits can corrupt UID references, array memberships, dictionary bindings, or preference cache state.",
        difficulty=difficulty,
        difficulty_explanation=explanation,
        failure_modes=FAILURE_MODES,
        rollback_requirements=(
            "Restore original plist artifact from backup.",
            "Reboot before rechecking NetworkExtension/System Settings state.",
            "Verify restored artifact SHA256 matches the pre-repair hash.",
        ),
        verification_commands=POST_REPAIR_VALIDATION_COMMANDS,
        expected_verification_outcome="candidate absent from validation and transaction package after manual edit; no new object graph errors.",
        read_only=True,
        preview_only=True,
        mutation_performed=False,
        executable_by_tool=False,
        not_executable_by_tool=True,
    )


def _safety_analysis(details: tuple[AffectedObjectDetail, ...]) -> dict[str, bool]:
    multiple = len(details) > 1
    has_arrays = any(detail.array_memberships for detail in details)
    has_incoming = any(detail.incoming_references for detail in details)
    has_outgoing = any(detail.outgoing_references for detail in details)
    return {
        "single_object_deletion": len(details) == 1,
        "dictionary_update": True,
        "array_compaction": has_arrays or multiple,
        "uid_rewrite": has_incoming or has_outgoing or multiple,
        "archive_rebuild": True,
        "multiple_object_removal": multiple,
        "cross_reference_update": has_incoming or has_outgoing or multiple,
        "complete_archive_regeneration": True,
    }


def _difficulty(transaction: RepairTransaction, details: tuple[AffectedObjectDetail, ...], safety: dict[str, bool]) -> tuple[str, str]:
    if transaction.validation_status not in {"stale_code_sign_clone", "stale_missing_executable"}:
        return "unsafe", "validation status is not a stale preview target; manual repair would be unsafe."
    if safety.get("complete_archive_regeneration") or safety.get("archive_rebuild"):
        return "high", "manual repair requires UID rewrite, array compaction, cross-reference update, and archive regeneration."
    if safety.get("multiple_object_removal") or safety.get("cross_reference_update"):
        return "medium", "manual repair touches multiple object graph references."
    if safety.get("dictionary_update") or safety.get("array_compaction"):
        return "low", "manual repair is limited to local dictionary/array updates."
    return "trivial", "manual repair only documents a single object deletion."


def _object_detail(graph: dict[str, Any], index: int | None) -> AffectedObjectDetail:
    if index is None:
        index = -1
    objects = graph.get("objects", []) if isinstance(graph.get("objects"), list) else []
    node = objects[index] if 0 <= index < len(objects) else None
    edges: dict[int, list[tuple[int, str | None]]] = graph.get("edges", {})
    parents: dict[int, list[tuple[int, str | None]]] = graph.get("parents", {})
    referenced = tuple(child for child, _label in sorted(edges.get(index, []), key=lambda item: (item[0], item[1] or "")))
    parent_edges = tuple(sorted(parents.get(index, []), key=lambda item: (item[0], item[1] or "")))
    outgoing = tuple(f"$objects[{index}] -> $objects[{child}]" + (f" ({label})" if label else "") for child, label in sorted(edges.get(index, []), key=lambda item: (item[0], item[1] or "")))
    incoming = tuple(f"$objects[{parent}] -> $objects[{index}]" + (f" ({label})" if label else "") for parent, label in parent_edges)
    dictionary_keys = tuple(sorted(str(key) for key in node)) if isinstance(node, dict) else ()
    memberships = tuple(f"$objects[{parent}][{position}]" for parent, position in _array_memberships(index, objects, parents))
    refs = tuple(f"$objects[{parent}]" for parent, _label in parent_edges)
    parent_chain = _parent_chain(index, parents)
    dependency = {f"$objects[{index}]": [f"$objects[{child}]" for child in referenced]}
    return AffectedObjectDetail(
        object_index=index,
        object_class=type(node).__name__ if node is not None else "unknown",
        parent_chain=parent_chain,
        referenced_uids=referenced,
        referencing_objects=refs,
        dictionary_keys=dictionary_keys,
        array_memberships=memberships,
        incoming_references=incoming,
        outgoing_references=outgoing,
        dependency_graph=dependency,
        can_be_deleted_independently=False,
        requires_graph_rewrite=True,
    )


def _load_artifact_graph(path_text: str, artifact_name: str, roots: Sequence[Path]) -> dict[str, Any]:
    path = Path(path_text).expanduser()
    if not path.is_file():
        for root in roots:
            candidate = root / "Library" / "Preferences" / artifact_name
            if candidate.is_file():
                path = candidate
                break
            direct = root / artifact_name
            if direct.is_file():
                path = direct
                break
    if not path.is_file():
        return {"objects": [], "edges": {}, "parents": {}}
    try:
        value = plistlib.loads(path.read_bytes())
    except Exception:
        return {"objects": [], "edges": {}, "parents": {}}
    objects = value.get("$objects") if isinstance(value, dict) else None
    if not isinstance(objects, list):
        return {"objects": [], "edges": {}, "parents": {}}
    edges, parents = _build_edges(objects)
    return {"objects": objects, "edges": edges, "parents": parents}


def _build_edges(objects: list[Any]) -> tuple[dict[int, list[tuple[int, str | None]]], dict[int, list[tuple[int, str | None]]]]:
    edges: dict[int, list[tuple[int, str | None]]] = defaultdict(list)
    parents: dict[int, list[tuple[int, str | None]]] = defaultdict(list)
    for index, node in enumerate(objects):
        for child, label in _uid_children(node):
            if 0 <= child < len(objects):
                edges[index].append((child, label))
                parents[child].append((index, label))
    return dict(edges), dict(parents)


def _uid_children(value: Any, prefix: str | None = None) -> list[tuple[int, str | None]]:
    if isinstance(value, plistlib.UID):
        return [(value.data, prefix)]
    if isinstance(value, dict):
        result: list[tuple[int, str | None]] = []
        for key in sorted(value):
            next_prefix = str(key) if prefix is None else f"{prefix}.{key}"
            result.extend(_uid_children(value[key], next_prefix))
        return result
    if isinstance(value, list):
        result = []
        for idx, item in enumerate(value):
            next_prefix = f"[{idx}]" if prefix is None else f"{prefix}[{idx}]"
            result.extend(_uid_children(item, next_prefix))
        return result
    return []


def _array_memberships(index: int, objects: list[Any], parents: dict[int, list[tuple[int, str | None]]]) -> list[tuple[int, int]]:
    result = []
    for parent, _label in parents.get(index, []):
        node = objects[parent]
        if isinstance(node, list):
            for position, item in enumerate(node):
                if isinstance(item, plistlib.UID) and item.data == index:
                    result.append((parent, position))
    return sorted(result)


def _parent_chain(index: int, parents: dict[int, list[tuple[int, str | None]]]) -> tuple[str, ...]:
    chain: list[str] = []
    current = index
    seen = {index}
    while parents.get(current):
        parent = sorted(parents[current], key=lambda item: (item[0], item[1] or ""))[0][0]
        if parent in seen:
            break
        chain.insert(0, f"$objects[{parent}]")
        seen.add(parent)
        current = parent
    chain.append(f"$objects[{index}]")
    return tuple(chain)


def _object_index(ref: str) -> int | None:
    marker = "$objects["
    if marker not in ref:
        return None
    tail = ref.split(marker, 1)[1]
    number = tail.split("]", 1)[0]
    try:
        return int(number)
    except ValueError:
        return None


def _counts(values: Iterable[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        result[value] = result.get(value, 0) + 1
    return dict(sorted(result.items()))
