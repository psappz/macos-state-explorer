from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

from macos_state_explorer.networkextension_repair_plan_preview import (
    AUTOMATIC_EXECUTION_BLOCKERS,
    MANUAL_PRECONDITIONS,
    NetworkExtensionRepairPlanPreview,
    NetworkExtensionRepairPlanPreviewGroup,
)

POST_CHANGE_VERIFICATION_COMMANDS = (
    "mse networkextension validate-candidates",
    "mse networkextension repair-plan-preview",
    "mse networkextension repair-transaction-package",
    "mse report local-network --bundle ~/Desktop/mse-local-network-post-change-bundle",
)
ROLLBACK_REQUIREMENT = "Restore the backed-up source plist artifact before reboot and rerun post-change verification."
NOT_EXECUTABLE_STATEMENT = "This transaction package is not executable by macos-state-explorer."


@dataclass(frozen=True)
class SourceArtifact:
    path: str
    name: str
    artifact_type: str
    sha256: str | None
    digest_available: bool

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "name": self.name,
            "artifact_type": self.artifact_type,
            "sha256": self.sha256,
            "digest_available": self.digest_available,
        }


@dataclass(frozen=True)
class RepairTransaction:
    transaction_id: str
    source_artifact: SourceArtifact
    backup_required: bool
    affected_parent_object_record: str
    grouped_preview_target_ids: tuple[str, ...]
    candidate_object_refs: tuple[str, ...]
    validation_status: str
    executable_path_class: str
    signing_identifier: str
    manual_preconditions: tuple[str, ...]
    execution_blockers: tuple[str, ...]
    post_change_verification_commands: tuple[str, ...]
    rollback_required: bool
    rollback_requirement: str
    preview_only: bool
    mutation_performed: bool
    executable_by_tool: bool
    not_executable_by_tool: bool
    not_executable_statement: str

    def sort_key(self) -> tuple[str, str, str, str, str]:
        return (
            self.source_artifact.name,
            self.affected_parent_object_record,
            self.signing_identifier,
            self.executable_path_class,
            self.validation_status,
        )

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "transaction_id": self.transaction_id,
            "source_artifact": self.source_artifact.to_json_dict(),
            "backup_required": self.backup_required,
            "affected_parent_object_record": self.affected_parent_object_record,
            "grouped_preview_target_ids": list(self.grouped_preview_target_ids),
            "candidate_object_refs": list(self.candidate_object_refs),
            "validation_status": self.validation_status,
            "executable_path_class": self.executable_path_class,
            "signing_identifier": self.signing_identifier,
            "manual_preconditions": list(self.manual_preconditions),
            "execution_blockers": list(self.execution_blockers),
            "post_change_verification_commands": list(self.post_change_verification_commands),
            "rollback_required": self.rollback_required,
            "rollback_requirement": self.rollback_requirement,
            "preview_only": self.preview_only,
            "mutation_performed": self.mutation_performed,
            "executable_by_tool": self.executable_by_tool,
            "not_executable_by_tool": self.not_executable_by_tool,
            "not_executable_statement": self.not_executable_statement,
        }


@dataclass(frozen=True)
class NetworkExtensionRepairTransactionPackage:
    repair_transaction_package_id: str
    source_repair_plan_preview_id: str
    transactions: tuple[RepairTransaction, ...]

    def summary(self) -> dict[str, Any]:
        validation_status_counts = _counts(transaction.validation_status for transaction in self.transactions)
        return {
            "transaction_count": len(self.transactions),
            "transaction_ids": [transaction.transaction_id for transaction in self.transactions],
            "preview_only_transactions": sum(transaction.preview_only for transaction in self.transactions),
            "backup_required_count": sum(transaction.backup_required for transaction in self.transactions),
            "rollback_required_count": sum(transaction.rollback_required for transaction in self.transactions),
            "validation_status_counts": validation_status_counts,
            "read_only": True,
            "mutation_performed": False,
            "executable_by_tool": False,
            "automatic_execution_recommendation": "never",
        }

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "command": "networkextension repair-transaction-package",
            "repair_transaction_package_id": self.repair_transaction_package_id,
            "timestamp": "1970-01-01T00:00:00Z",
            "read_only": True,
            "mutation_performed": False,
            "executable_by_tool": False,
            "automatic_execution_recommendation": "never",
            "summary": self.summary(),
            "manual_preconditions": list(MANUAL_PRECONDITIONS),
            "execution_blockers": list(AUTOMATIC_EXECUTION_BLOCKERS),
            "post_change_verification_commands": list(POST_CHANGE_VERIFICATION_COMMANDS),
            "rollback_requirement": ROLLBACK_REQUIREMENT,
            "not_executable_statement": NOT_EXECUTABLE_STATEMENT,
            "transactions": [transaction.to_json_dict() for transaction in self.transactions],
            "source_repair_plan_preview_id": self.source_repair_plan_preview_id,
        }


def build_networkextension_repair_transaction_package(
    preview: NetworkExtensionRepairPlanPreview,
    roots: Sequence[Path] | None = None,
) -> NetworkExtensionRepairTransactionPackage:
    transactions = tuple(
        sorted(
            (_transaction_from_group(group, roots or ()) for group in preview.preview_groups),
            key=lambda transaction: transaction.sort_key(),
        )
    )
    package_id = hashlib.sha256(json.dumps([transaction.to_json_dict() for transaction in transactions], sort_keys=True).encode()).hexdigest()[:16]
    return NetworkExtensionRepairTransactionPackage(
        repair_transaction_package_id=f"networkextension-repair-transaction-package-{package_id}",
        source_repair_plan_preview_id=preview.repair_plan_preview_id,
        transactions=transactions,
    )


def networkextension_repair_transaction_package_summary(package: NetworkExtensionRepairTransactionPackage) -> dict[str, Any]:
    return package.summary()


def render_networkextension_repair_transaction_package(package: NetworkExtensionRepairTransactionPackage) -> str:
    summary = package.summary()
    lines = [
        "NetworkExtension repair transaction package",
        "- Read-only: true",
        "- Mutation performed: false",
        "- Executable by tool: false",
        "- Automatic execution recommendation: never",
        f"- Transactions: {summary['transaction_count']}",
        f"- Preview-only transactions: {summary['preview_only_transactions']}",
        f"- Backup required: {summary['backup_required_count']}",
        f"- Rollback required: {summary['rollback_required_count']}",
        f"- {NOT_EXECUTABLE_STATEMENT}",
        "",
        "Manual preconditions",
    ]
    lines.extend(f"- {item}" for item in MANUAL_PRECONDITIONS)
    lines.extend(["", "Execution blockers"])
    lines.extend(f"- {item}" for item in AUTOMATIC_EXECUTION_BLOCKERS)
    lines.extend(["", "Post-change verification commands"])
    lines.extend(f"- {command}" for command in POST_CHANGE_VERIFICATION_COMMANDS)
    lines.extend(["", "Transactions"])
    if not package.transactions:
        lines.append("- none")
    for transaction in package.transactions:
        lines.append(f"- {transaction.transaction_id}")
        lines.append(f"  - Source artifact: {transaction.source_artifact.name} ({transaction.source_artifact.artifact_type})")
        lines.append(f"  - Source SHA256: {transaction.source_artifact.sha256 or 'unavailable'}")
        lines.append(f"  - Parent object record: {transaction.affected_parent_object_record}")
        lines.append(f"  - Preview group IDs: {', '.join(transaction.grouped_preview_target_ids)}")
        lines.append(f"  - Candidate object refs: {', '.join(transaction.candidate_object_refs)}")
        lines.append(f"  - Validation status: {transaction.validation_status}")
        lines.append(f"  - Executable path class: {transaction.executable_path_class}")
        lines.append(f"  - SigningIdentifier: {transaction.signing_identifier}")
        lines.append("  - Flags: preview_only=true, mutation_performed=false, executable_by_tool=false")
        lines.append(f"  - Rollback requirement: {transaction.rollback_requirement}")
    return "\n".join(lines)


def render_networkextension_repair_transaction_package_summary(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "NetworkExtension repair transaction package",
            f"- Transactions: {summary.get('transaction_count', 0)}",
            f"- Preview-only transactions: {summary.get('preview_only_transactions', 0)}",
            f"- Backup required: {summary.get('backup_required_count', 0)}",
            f"- Rollback required: {summary.get('rollback_required_count', 0)}",
            "- Automatic execution recommendation: never",
            "- Mutation performed: false",
            "- Executable by tool: false",
        ]
    )


def _transaction_from_group(group: NetworkExtensionRepairPlanPreviewGroup, roots: Sequence[Path]) -> RepairTransaction:
    target = group.would_target
    artifact = _source_artifact(target.plist_artifact, roots)
    transaction_seed = {
        "artifact": artifact.to_json_dict(),
        "parent": target.parent_object_record,
        "preview_groups": [group.preview_group_id],
        "candidate_refs": list(target.candidate_refs),
        "validation_status": target.validation_status,
        "path_class": target.executable_path_class,
        "signing_identifier": target.signing_identifier,
    }
    digest = hashlib.sha256(json.dumps(transaction_seed, sort_keys=True).encode()).hexdigest()[:12]
    return RepairTransaction(
        transaction_id=f"ne-repair-transaction-{digest}",
        source_artifact=artifact,
        backup_required=True,
        affected_parent_object_record=target.parent_object_record,
        grouped_preview_target_ids=(group.preview_group_id,),
        candidate_object_refs=target.candidate_refs,
        validation_status=target.validation_status,
        executable_path_class=target.executable_path_class,
        signing_identifier=target.signing_identifier,
        manual_preconditions=MANUAL_PRECONDITIONS,
        execution_blockers=AUTOMATIC_EXECUTION_BLOCKERS,
        post_change_verification_commands=POST_CHANGE_VERIFICATION_COMMANDS,
        rollback_required=True,
        rollback_requirement=ROLLBACK_REQUIREMENT,
        preview_only=True,
        mutation_performed=False,
        executable_by_tool=False,
        not_executable_by_tool=True,
        not_executable_statement=NOT_EXECUTABLE_STATEMENT,
    )


def _source_artifact(artifact_name: str, roots: Sequence[Path]) -> SourceArtifact:
    path = _find_artifact_path(artifact_name, roots)
    sha256 = _sha256(path) if path and path.is_file() else None
    return SourceArtifact(
        path=str(path) if path else artifact_name,
        name=artifact_name,
        artifact_type=_artifact_type(artifact_name),
        sha256=sha256,
        digest_available=sha256 is not None,
    )


def _find_artifact_path(artifact_name: str, roots: Sequence[Path]) -> Path | None:
    for root in roots:
        expanded = Path(root).expanduser()
        if expanded.is_file() and expanded.name == artifact_name:
            return expanded
        candidate = expanded / "Library" / "Preferences" / artifact_name
        if candidate.is_file():
            return candidate
        if expanded.is_dir():
            direct = expanded / artifact_name
            if direct.is_file():
                return direct
    return None


def _artifact_type(artifact_name: str) -> str:
    if artifact_name == "com.apple.networkextension.plist":
        return "networkextension_preferences_plist"
    if artifact_name.endswith(".plist"):
        return "plist"
    return "unknown_artifact"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _counts(values: Iterable[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        result[value] = result.get(value, 0) + 1
    return dict(sorted(result.items()))
