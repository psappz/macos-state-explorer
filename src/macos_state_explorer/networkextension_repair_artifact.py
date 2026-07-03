from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import plistlib
from pathlib import Path
from typing import Any, Sequence

from macos_state_explorer.networkextension_manual_repair_runbook import NetworkExtensionManualRepairRunbook, ManualRepairRunbookTransaction
from macos_state_explorer.networkextension_repair_simulation import (
    NetworkExtensionRepairSimulation,
    _object_ref_sort_key,
    _planned_removal_indices,
    _resolve_artifact_path,
    _rewrite_archive,
)

NO_INSTALL_STATEMENT = "This artifact is offline/generated/not installed; macos-state-explorer does not install or repair system artifacts."


@dataclass(frozen=True)
class NetworkExtensionRepairArtifact:
    repair_artifact_id: str
    output_path: Path
    source_artifact: dict[str, Any]
    source_sha256: str
    generated_artifact_sha256: str
    removed_object_refs: tuple[str, ...]
    uid_rewrite_count: int
    array_change_count: int
    dictionary_change_count: int
    simulation_id: str
    simulation_safety_verdict: str
    validation_result: str
    reparse_success: bool
    reparse_errors: tuple[str, ...]

    def summary(self) -> dict[str, Any]:
        return {
            "repair_artifact_ids": [self.repair_artifact_id],
            "validation_result": self.validation_result,
            "removed_object_count": len(self.removed_object_refs),
            "uid_rewrite_count": self.uid_rewrite_count,
            "array_change_count": self.array_change_count,
            "dictionary_change_count": self.dictionary_change_count,
            "generated_artifact_sha256": self.generated_artifact_sha256,
            "read_only": True,
            "mutation_performed": False,
            "system_artifact_modified": False,
            "executable_by_tool": False,
            "offline_generated": True,
            "installed": False,
            "automatic_execution_recommendation": "never",
        }

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "command": "networkextension generate-repair-artifact",
            "repair_artifact_id": self.repair_artifact_id,
            "timestamp": "1970-01-01T00:00:00Z",
            "read_only": True,
            "mutation_performed": False,
            "system_artifact_modified": False,
            "executable_by_tool": False,
            "offline_generated": True,
            "installed": False,
            "automatic_execution_recommendation": "never",
            "output_path": str(self.output_path),
            "source_artifact": self.source_artifact,
            "source_sha256": self.source_sha256,
            "generated_artifact_sha256": self.generated_artifact_sha256,
            "removed_object_refs": list(self.removed_object_refs),
            "uid_rewrite_count": self.uid_rewrite_count,
            "array_change_count": self.array_change_count,
            "dictionary_change_count": self.dictionary_change_count,
            "simulation": {"repair_simulation_id": self.simulation_id, "safety_verdict": self.simulation_safety_verdict},
            "reparse": {"success": self.reparse_success, "errors": list(self.reparse_errors)},
            "validation_result": self.validation_result,
            "explanation": NO_INSTALL_STATEMENT,
            "summary": self.summary(),
        }


def build_networkextension_repair_artifact(
    runbook: NetworkExtensionManualRepairRunbook,
    simulation: NetworkExtensionRepairSimulation,
    output_path: Path,
    roots: Sequence[Path] | None = None,
) -> NetworkExtensionRepairArtifact:
    if simulation.safety_verdict != "simulation_passed":
        raise ValueError("simulation_passed required before generating a repair artifact")
    if not runbook.transactions:
        raise ValueError("simulation_passed required before generating a repair artifact")
    root_paths = tuple(Path(root).expanduser() for root in (roots or ()))
    output = Path(output_path).expanduser()
    source_transactions = sorted(runbook.transactions, key=lambda tx: tx.transaction_id)
    source_path = _single_source_path(source_transactions, root_paths)
    _validate_output_path(output, source_path)

    archive = plistlib.loads(source_path.read_bytes())
    objects = archive.get("$objects") if isinstance(archive, dict) else None
    if not isinstance(objects, list):
        raise ValueError("source artifact is not an NSKeyedArchiver-style plist")
    remove_indices = sorted({idx for tx in source_transactions for idx in _planned_removal_indices(tx) if 0 <= idx < len(objects)})
    if not remove_indices:
        raise ValueError("simulation_passed required before generating a repair artifact")
    rewritten_archive, stats = _rewrite_archive(archive, set(remove_indices))
    serialized = plistlib.dumps(rewritten_archive, fmt=plistlib.FMT_BINARY, sort_keys=True)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(serialized)
    reparse_errors: list[str] = []
    try:
        reparsed = plistlib.loads(output.read_bytes())
        reparsed_objects = reparsed.get("$objects") if isinstance(reparsed, dict) else None
        reparse_success = isinstance(reparsed_objects, list) and len(reparsed_objects) == len(objects) - len(remove_indices)
        if not reparse_success:
            reparse_errors.append("reparse_object_count_mismatch")
    except Exception as error:  # pragma: no cover - exact plist parse error text is platform-dependent
        reparse_success = False
        reparse_errors.append(type(error).__name__)
    if not reparse_success:
        try:
            output.unlink()
        except FileNotFoundError:
            pass
        raise ValueError("generated artifact failed closed because it could not be reparsed")

    source_sha = _sha256_file(source_path)
    generated_sha = _sha256_file(output)
    removed_refs = tuple(sorted((f"$objects[{idx}]" for idx in remove_indices), key=_object_ref_sort_key))
    source_artifact = dict(source_transactions[0].source_artifact)
    source_artifact.setdefault("path", str(source_path))
    source_artifact["offline_generated"] = True
    digest_payload = {
        "source_sha256": source_sha,
        "generated_sha256": generated_sha,
        "removed": removed_refs,
        "simulation": simulation.repair_simulation_id,
        "validation_result": "artifact_generated",
    }
    digest = hashlib.sha256(json.dumps(digest_payload, sort_keys=True).encode()).hexdigest()[:16]
    return NetworkExtensionRepairArtifact(
        repair_artifact_id=f"networkextension-repair-artifact-{digest}",
        output_path=output,
        source_artifact=source_artifact,
        source_sha256=source_sha,
        generated_artifact_sha256=generated_sha,
        removed_object_refs=removed_refs,
        uid_rewrite_count=stats["uid_rewrites"],
        array_change_count=stats["array_changes"],
        dictionary_change_count=stats["dictionary_changes"],
        simulation_id=simulation.repair_simulation_id,
        simulation_safety_verdict=simulation.safety_verdict,
        validation_result="artifact_generated",
        reparse_success=True,
        reparse_errors=tuple(reparse_errors),
    )


def networkextension_repair_artifact_summary(artifact: NetworkExtensionRepairArtifact) -> dict[str, Any]:
    return artifact.summary()


def networkextension_repair_artifact_not_generated(reason: str = "simulation_passed required") -> NetworkExtensionRepairArtifact:
    return NetworkExtensionRepairArtifact(
        repair_artifact_id="networkextension-repair-artifact-not-generated",
        output_path=Path("networkextension-repair-artifact.plist"),
        source_artifact={"status": "not_generated"},
        source_sha256="",
        generated_artifact_sha256="",
        removed_object_refs=(),
        uid_rewrite_count=0,
        array_change_count=0,
        dictionary_change_count=0,
        simulation_id="",
        simulation_safety_verdict="simulation_inconclusive",
        validation_result=f"not_generated:{reason}",
        reparse_success=False,
        reparse_errors=(reason,),
    )


def render_networkextension_repair_artifact(artifact: NetworkExtensionRepairArtifact) -> str:
    return "\n".join(
        [
            "NetworkExtension generated repair artifact",
            "- Read-only: true",
            "- Mutation performed: false",
            "- System artifact modified: false",
            "- Executable by tool: false",
            "- Offline/generated/not installed: true",
            "- Automatic execution recommendation: never",
            f"- Output path: {artifact.output_path}",
            f"- Source artifact: {artifact.source_artifact.get('path', artifact.source_artifact.get('name', 'unknown'))}",
            f"- Source SHA256: {artifact.source_sha256}",
            f"- Generated artifact SHA256: {artifact.generated_artifact_sha256}",
            f"- Removed objects: {len(artifact.removed_object_refs)}",
            f"- UID rewrites: {artifact.uid_rewrite_count}",
            f"- Array changes: {artifact.array_change_count}",
            f"- Dictionary changes: {artifact.dictionary_change_count}",
            f"- Simulation verdict: {artifact.simulation_safety_verdict}",
            f"- Re-parse: {'success' if artifact.reparse_success else 'failure'}",
            f"- Validation result: {artifact.validation_result}",
            f"- {NO_INSTALL_STATEMENT}",
        ]
    )


def render_networkextension_repair_artifact_summary(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "NetworkExtension generated repair artifact",
            f"- Validation result: {summary.get('validation_result', 'not_generated')}",
            f"- Removed objects: {summary.get('removed_object_count', 0)}",
            f"- UID rewrites: {summary.get('uid_rewrite_count', 0)}",
            f"- Array changes: {summary.get('array_change_count', 0)}",
            f"- Dictionary changes: {summary.get('dictionary_change_count', 0)}",
            "- Read-only: true",
            "- Mutation performed: false",
            "- System artifact modified: false",
            "- Offline/generated/not installed: true",
        ]
    )


def _single_source_path(transactions: Sequence[ManualRepairRunbookTransaction], roots: Sequence[Path]) -> Path:
    paths: set[Path] = set()
    for transaction in transactions:
        path_text = str(transaction.source_artifact.get("path") or transaction.source_artifact.get("name") or "")
        path = _resolve_artifact_path(path_text, transaction.source_artifact.get("name"), roots)
        if path is None or not path.is_file():
            raise ValueError("source artifact missing; cannot generate repair artifact")
        paths.add(path.resolve())
    if len(paths) != 1:
        raise ValueError("exactly one source artifact is required to generate a repair artifact")
    return next(iter(paths))


def _validate_output_path(output_path: Path, source_path: Path) -> None:
    resolved = output_path.resolve(strict=False)
    source_resolved = source_path.resolve(strict=False)
    protected_prefixes = (Path("/Library"), Path("/System"), Path("/private/var/db"))
    if resolved == source_resolved:
        raise ValueError("refusing protected or live output path")
    for prefix in protected_prefixes:
        try:
            resolved.relative_to(prefix)
            raise ValueError("refusing protected or live output path")
        except ValueError as error:
            if str(error) == "refusing protected or live output path":
                raise
    parts = resolved.parts
    if len(parts) >= 3 and resolved.name == "com.apple.networkextension.plist" and parts[-3:-1] == ("Library", "Preferences"):
        raise ValueError("refusing protected or live output path")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
