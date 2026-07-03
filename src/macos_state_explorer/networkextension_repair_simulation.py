from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import plistlib
import shutil
import tempfile
from pathlib import Path
from typing import Any, Iterable, Sequence

from macos_state_explorer.networkextension_candidate_validation import build_networkextension_candidate_validation
from macos_state_explorer.networkextension_manual_repair_runbook import NetworkExtensionManualRepairRunbook, ManualRepairRunbookTransaction
from macos_state_explorer.networkextension_repair_plan_preview import build_networkextension_repair_plan_preview
from macos_state_explorer.networkextension_repair_transaction_package import build_networkextension_repair_transaction_package

NO_REPAIR_STATEMENT = "This is a read-only simulation; it does not execute a repair or modify system artifacts."


@dataclass(frozen=True)
class SimulationResult:
    transaction_id: str
    source_artifact: str
    validation_status: str
    planned_object_refs: tuple[str, ...]
    removed_object_refs: tuple[str, ...]
    uid_rewrites: int
    array_changes: int
    dictionary_changes: int
    serialization_success: bool
    reparse_success: bool
    result: str
    errors: tuple[str, ...] = ()

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "transaction_id": self.transaction_id,
            "source_artifact": self.source_artifact,
            "validation_status": self.validation_status,
            "planned_object_refs": list(self.planned_object_refs),
            "removed_object_refs": list(self.removed_object_refs),
            "uid_rewrites": self.uid_rewrites,
            "array_changes": self.array_changes,
            "dictionary_changes": self.dictionary_changes,
            "serialization_success": self.serialization_success,
            "reparse_success": self.reparse_success,
            "result": self.result,
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class NetworkExtensionRepairSimulation:
    repair_simulation_id: str
    source_manual_repair_runbook_id: str
    input_transactions: int
    simulated_transactions: int
    simulation_results: tuple[SimulationResult, ...]
    removed_object_refs: tuple[str, ...]
    uid_rewrite_count: int
    array_changes: int
    dictionary_changes: int
    serialization_success: bool
    serialization_errors: tuple[str, ...]
    reparse_success: bool
    reparse_errors: tuple[str, ...]
    post_simulation_candidate_count: int
    post_simulation_validation_status_counts: dict[str, int]
    post_simulation_transaction_count: int
    safety_verdict: str

    def summary(self) -> dict[str, Any]:
        return {
            "repair_simulation_ids": [self.repair_simulation_id],
            "input_transactions": self.input_transactions,
            "simulated_transactions": self.simulated_transactions,
            "removed_object_count": len(self.removed_object_refs),
            "uid_rewrite_count": self.uid_rewrite_count,
            "array_changes": self.array_changes,
            "dictionary_changes": self.dictionary_changes,
            "serialization_success": self.serialization_success,
            "reparse_success": self.reparse_success,
            "post_simulation_candidate_count": self.post_simulation_candidate_count,
            "post_simulation_validation_status_counts": self.post_simulation_validation_status_counts,
            "post_simulation_transaction_count": self.post_simulation_transaction_count,
            "safety_verdict": self.safety_verdict,
            "read_only": True,
            "mutation_performed": False,
            "system_artifact_modified": False,
            "executable_by_tool": False,
            "automatic_execution_recommendation": "never",
        }

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "command": "networkextension repair-simulation",
            "repair_simulation_id": self.repair_simulation_id,
            "timestamp": "1970-01-01T00:00:00Z",
            "read_only": True,
            "mutation_performed": False,
            "system_artifact_modified": False,
            "executable_by_tool": False,
            "automatic_execution_recommendation": "never",
            "input_transactions": self.input_transactions,
            "simulated_transactions": self.simulated_transactions,
            "simulation_results": [item.to_json_dict() for item in self.simulation_results],
            "removed_object_refs": list(self.removed_object_refs),
            "uid_rewrite_summary": {"rewrite_count": self.uid_rewrite_count},
            "array_change_summary": {"array_changes": self.array_changes},
            "dictionary_change_summary": {"dictionary_changes": self.dictionary_changes},
            "serialization": {"success": self.serialization_success, "errors": list(self.serialization_errors)},
            "reparse": {"success": self.reparse_success, "errors": list(self.reparse_errors)},
            "post_simulation_validation": {
                "candidate_count": self.post_simulation_candidate_count,
                "status_counts": self.post_simulation_validation_status_counts,
                "post_simulation_transaction_count": self.post_simulation_transaction_count,
            },
            "safety_verdict": self.safety_verdict,
            "explanation": NO_REPAIR_STATEMENT,
            "source_manual_repair_runbook_id": self.source_manual_repair_runbook_id,
            "summary": self.summary(),
        }


def build_networkextension_repair_simulation(
    runbook: NetworkExtensionManualRepairRunbook,
    roots: Sequence[Path] | None = None,
) -> NetworkExtensionRepairSimulation:
    root_paths = tuple(Path(root).expanduser() for root in (roots or ()))
    results: list[SimulationResult] = []
    removed_refs: set[str] = set()
    total_uid_rewrites = 0
    total_array_changes = 0
    total_dictionary_changes = 0
    serialization_errors: list[str] = []
    reparse_errors: list[str] = []
    simulated_transactions = 0
    post_candidate_count = 0
    post_status_counts: dict[str, int] = {}
    post_transaction_count = 0

    with tempfile.TemporaryDirectory(prefix="mse-ne-repair-simulation-") as temp_name:
        temp_root = Path(temp_name) / "simulation-root"
        for source_path in sorted({str(item.source_artifact.get("path") or "") for item in runbook.transactions}):
            if source_path:
                _copy_source_artifact(Path(source_path).expanduser(), root_paths, temp_root)
        transactions_by_artifact: dict[str, list[ManualRepairRunbookTransaction]] = {}
        for transaction in runbook.transactions:
            path_text = str(transaction.source_artifact.get("path") or transaction.source_artifact.get("name") or "")
            transactions_by_artifact.setdefault(path_text, []).append(transaction)

        for path_text, transactions in sorted(transactions_by_artifact.items()):
            original_path = _resolve_artifact_path(path_text, transactions[0].source_artifact.get("name"), root_paths)
            if original_path is None or not original_path.is_file():
                error = "source_artifact_missing"
                serialization_errors.append(error)
                reparse_errors.append(error)
                for transaction in transactions:
                    results.append(_failed_result(transaction, error, "not_simulated"))
                continue
            temp_path = _copy_source_artifact(original_path, root_paths, temp_root)
            try:
                archive = plistlib.loads(temp_path.read_bytes())
                objects = archive.get("$objects") if isinstance(archive, dict) else None
                if not isinstance(objects, list):
                    raise ValueError("missing_$objects")
            except Exception as error:  # pragma: no cover - exact parser errors are platform-dependent
                message = type(error).__name__ if not isinstance(error, ValueError) else str(error)
                serialization_errors.append(message)
                reparse_errors.append(message)
                for transaction in transactions:
                    results.append(_failed_result(transaction, message, "not_simulated"))
                continue

            remove_indices = sorted({idx for transaction in transactions for idx in _planned_removal_indices(transaction) if 0 <= idx < len(objects)})
            if not remove_indices:
                for transaction in transactions:
                    results.append(_failed_result(transaction, "no_planned_objects", "not_simulated"))
                continue
            before_objects = len(objects)
            rewritten_archive, stats = _rewrite_archive(archive, set(remove_indices))
            try:
                serialized = plistlib.dumps(rewritten_archive, fmt=plistlib.FMT_BINARY, sort_keys=True)
                temp_path.write_bytes(serialized)
                serialization_success = True
            except Exception as error:
                serialization_success = False
                serialization_errors.append(type(error).__name__)
            try:
                reparsed = plistlib.loads(temp_path.read_bytes()) if serialization_success else None
                reparsed_objects = reparsed.get("$objects") if isinstance(reparsed, dict) else None
                reparse_success = isinstance(reparsed_objects, list) and len(reparsed_objects) == before_objects - len(remove_indices)
                if not reparse_success:
                    reparse_errors.append("reparse_object_count_mismatch")
            except Exception as error:
                reparse_success = False
                reparse_errors.append(type(error).__name__)
            total_uid_rewrites += stats["uid_rewrites"]
            total_array_changes += stats["array_changes"]
            total_dictionary_changes += stats["dictionary_changes"]
            removed_for_artifact = tuple(f"$objects[{idx}]" for idx in remove_indices)
            removed_refs.update(removed_for_artifact)
            for transaction in transactions:
                tx_indices = sorted(idx for idx in _planned_removal_indices(transaction) if idx in remove_indices)
                results.append(
                    SimulationResult(
                        transaction_id=transaction.transaction_id,
                        source_artifact=str(transaction.source_artifact.get("name") or Path(path_text).name),
                        validation_status=transaction.validation_status,
                        planned_object_refs=tuple(dict.fromkeys((transaction.parent_object, *transaction.candidate_object_refs))),
                        removed_object_refs=tuple(f"$objects[{idx}]" for idx in tx_indices),
                        uid_rewrites=stats["uid_rewrites"],
                        array_changes=stats["array_changes"],
                        dictionary_changes=stats["dictionary_changes"],
                        serialization_success=serialization_success,
                        reparse_success=reparse_success,
                        result="simulated" if serialization_success and reparse_success else "failed",
                    )
                )
                if serialization_success and reparse_success:
                    simulated_transactions += 1

        if runbook.transactions:
            try:
                validation = build_networkextension_candidate_validation([temp_root], process_rows=[])
                preview = build_networkextension_repair_plan_preview(validation)
                package = build_networkextension_repair_transaction_package(preview, [temp_root])
                post_candidate_count = validation.summary()["total_candidates"]
                post_status_counts = validation.summary()["status_counts"]
                post_transaction_count = package.summary()["transaction_count"]
            except Exception as error:
                reparse_errors.append(f"post_validation:{type(error).__name__}")

    serialization_success = bool(runbook.transactions) and not serialization_errors and all(item.serialization_success for item in results)
    reparse_success = bool(runbook.transactions) and not reparse_errors and all(item.reparse_success for item in results)
    safety_verdict = _safety_verdict(
        input_transactions=len(runbook.transactions),
        simulated_transactions=simulated_transactions,
        serialization_success=serialization_success,
        reparse_success=reparse_success,
        post_transaction_count=post_transaction_count,
    )
    digest_payload = {
        "source": runbook.manual_repair_runbook_id,
        "results": [item.to_json_dict() for item in sorted(results, key=lambda item: item.transaction_id)],
        "removed": sorted(removed_refs, key=_object_ref_sort_key),
        "post": {"candidate_count": post_candidate_count, "status_counts": post_status_counts, "transaction_count": post_transaction_count},
        "verdict": safety_verdict,
    }
    digest = hashlib.sha256(json.dumps(digest_payload, sort_keys=True).encode()).hexdigest()[:16]
    return NetworkExtensionRepairSimulation(
        repair_simulation_id=f"networkextension-repair-simulation-{digest}",
        source_manual_repair_runbook_id=runbook.manual_repair_runbook_id,
        input_transactions=len(runbook.transactions),
        simulated_transactions=simulated_transactions,
        simulation_results=tuple(sorted(results, key=lambda item: item.transaction_id)),
        removed_object_refs=tuple(sorted(removed_refs, key=_object_ref_sort_key)),
        uid_rewrite_count=total_uid_rewrites,
        array_changes=total_array_changes,
        dictionary_changes=total_dictionary_changes,
        serialization_success=serialization_success,
        serialization_errors=tuple(sorted(set(serialization_errors))),
        reparse_success=reparse_success,
        reparse_errors=tuple(sorted(set(reparse_errors))),
        post_simulation_candidate_count=post_candidate_count,
        post_simulation_validation_status_counts=dict(sorted(post_status_counts.items())),
        post_simulation_transaction_count=post_transaction_count,
        safety_verdict=safety_verdict,
    )


def networkextension_repair_simulation_summary(simulation: NetworkExtensionRepairSimulation) -> dict[str, Any]:
    return simulation.summary()


def render_networkextension_repair_simulation(simulation: NetworkExtensionRepairSimulation) -> str:
    summary = simulation.summary()
    lines = [
        "NetworkExtension repair simulation",
        "- Read-only: true",
        "- Mutation performed: false",
        "- System artifact modified: false",
        "- Executable by tool: false",
        "- Automatic execution recommendation: never",
        f"- Input transactions: {summary['input_transactions']}",
        f"- Simulated transactions: {summary['simulated_transactions']}",
        f"- Removed objects: {summary['removed_object_count']}",
        f"- UID rewrites: {summary['uid_rewrite_count']}",
        f"- Array changes: {summary['array_changes']}",
        f"- Dictionary changes: {summary['dictionary_changes']}",
        f"- Serialization: {'success' if simulation.serialization_success else 'failure'}",
        f"- Re-parse: {'success' if simulation.reparse_success else 'failure'}",
        f"- Post-simulation candidates: {summary['post_simulation_candidate_count']}",
        f"- Post-simulation validation statuses: {summary['post_simulation_validation_status_counts']}",
        f"- Safety verdict: {simulation.safety_verdict}",
        f"- {NO_REPAIR_STATEMENT}",
        "",
        "Simulation results",
    ]
    if not simulation.simulation_results:
        lines.append("- none")
    for item in simulation.simulation_results:
        lines.append(f"- {item.transaction_id} [{item.result}]")
        lines.append(f"  - Validation status: {item.validation_status}")
        lines.append(f"  - Removed refs: {', '.join(item.removed_object_refs) if item.removed_object_refs else 'none'}")
        lines.append(f"  - UID rewrites: {item.uid_rewrites}")
        lines.append(f"  - Array changes: {item.array_changes}")
        lines.append(f"  - Dictionary changes: {item.dictionary_changes}")
        if item.errors:
            lines.append(f"  - Errors: {', '.join(item.errors)}")
    return "\n".join(lines)


def render_networkextension_repair_simulation_summary(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "NetworkExtension repair simulation",
            f"- Input transactions: {summary.get('input_transactions', 0)}",
            f"- Simulated transactions: {summary.get('simulated_transactions', 0)}",
            f"- Removed objects: {summary.get('removed_object_count', 0)}",
            f"- UID rewrites: {summary.get('uid_rewrite_count', 0)}",
            f"- Array changes: {summary.get('array_changes', 0)}",
            f"- Dictionary changes: {summary.get('dictionary_changes', 0)}",
            f"- Safety verdict: {summary.get('safety_verdict', 'simulation_inconclusive')}",
            "- Read-only: true",
            "- Mutation performed: false",
            "- Executable by tool: false",
        ]
    )


def _failed_result(transaction: ManualRepairRunbookTransaction, error: str, result: str) -> SimulationResult:
    return SimulationResult(
        transaction_id=transaction.transaction_id,
        source_artifact=str(transaction.source_artifact.get("name") or "unknown"),
        validation_status=transaction.validation_status,
        planned_object_refs=tuple(dict.fromkeys((transaction.parent_object, *transaction.candidate_object_refs))),
        removed_object_refs=(),
        uid_rewrites=0,
        array_changes=0,
        dictionary_changes=0,
        serialization_success=False,
        reparse_success=False,
        result=result,
        errors=(error,),
    )


def _planned_removal_indices(transaction: ManualRepairRunbookTransaction) -> tuple[int, ...]:
    refs = tuple(dict.fromkeys((transaction.parent_object, *transaction.candidate_object_refs, *transaction.expected_object_removal)))
    return tuple(idx for idx in (_object_index(ref) for ref in refs) if idx is not None)


def _rewrite_archive(archive: dict[str, Any], remove_indices: set[int]) -> tuple[dict[str, Any], dict[str, int]]:
    objects = archive.get("$objects")
    if not isinstance(objects, list):
        raise ValueError("missing_$objects")
    remap: dict[int, int] = {}
    new_objects: list[Any] = []
    for old_index, value in enumerate(objects):
        if old_index in remove_indices:
            continue
        remap[old_index] = len(new_objects)
        new_objects.append(value)
    stats = {"uid_rewrites": 0, "array_changes": 0, "dictionary_changes": 0}
    rewritten_objects = [_rewrite_value(value, remap, remove_indices, stats) for value in new_objects]
    rewritten = dict(archive)
    rewritten["$objects"] = rewritten_objects
    if isinstance(rewritten.get("$top"), dict):
        rewritten["$top"] = _rewrite_value(rewritten["$top"], remap, remove_indices, stats)
    return rewritten, stats


def _rewrite_value(value: Any, remap: dict[int, int], remove_indices: set[int], stats: dict[str, int]) -> Any:
    if isinstance(value, plistlib.UID):
        if value.data in remove_indices:
            return None
        new_value = remap.get(value.data, value.data)
        if new_value != value.data:
            stats["uid_rewrites"] += 1
        return plistlib.UID(new_value)
    if isinstance(value, list):
        rewritten_list: list[Any] = []
        changed = False
        for item in value:
            next_item = _rewrite_value(item, remap, remove_indices, stats)
            if next_item is None:
                changed = True
                continue
            if next_item != item:
                changed = True
            rewritten_list.append(next_item)
        if changed or len(rewritten_list) != len(value):
            stats["array_changes"] += 1
        return rewritten_list
    if isinstance(value, dict):
        rewritten_dict: dict[Any, Any] = {}
        changed = False
        for key in sorted(value):
            next_item = _rewrite_value(value[key], remap, remove_indices, stats)
            if next_item is None:
                changed = True
                stats["dictionary_changes"] += 1
                continue
            if next_item != value[key]:
                changed = True
            rewritten_dict[key] = next_item
        return rewritten_dict if changed else value
    return value


def _copy_source_artifact(path: Path, roots: Sequence[Path], temp_root: Path) -> Path:
    if not path.is_file():
        return temp_root / "Library" / "Preferences" / path.name
    relative = _relative_artifact_path(path, roots)
    destination = temp_root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.resolve() != path.resolve():
        shutil.copy2(path, destination)
    return destination


def _relative_artifact_path(path: Path, roots: Sequence[Path]) -> Path:
    for root in roots:
        try:
            return path.relative_to(root)
        except ValueError:
            continue
    if path.name:
        return Path("Library") / "Preferences" / path.name
    return Path("Library") / "Preferences" / "com.apple.networkextension.plist"


def _resolve_artifact_path(path_text: str, artifact_name: object, roots: Sequence[Path]) -> Path | None:
    path = Path(path_text).expanduser() if path_text else Path(str(artifact_name or ""))
    if path.is_file():
        return path
    name = str(artifact_name or path.name or "com.apple.networkextension.plist")
    for root in roots:
        for candidate in (root / "Library" / "Preferences" / name, root / name):
            if candidate.is_file():
                return candidate
    return None


def _safety_verdict(*, input_transactions: int, simulated_transactions: int, serialization_success: bool, reparse_success: bool, post_transaction_count: int) -> str:
    if input_transactions == 0:
        return "simulation_inconclusive"
    if not serialization_success or not reparse_success:
        return "simulation_failed"
    if simulated_transactions != input_transactions:
        return "simulation_inconclusive"
    if post_transaction_count == 0:
        return "simulation_passed"
    return "simulation_inconclusive"


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


def _object_ref_sort_key(ref: str) -> tuple[int, str]:
    index = _object_index(ref)
    return (index if index is not None else 10**9, ref)


def _counts(values: Iterable[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        result[value] = result.get(value, 0) + 1
    return dict(sorted(result.items()))
