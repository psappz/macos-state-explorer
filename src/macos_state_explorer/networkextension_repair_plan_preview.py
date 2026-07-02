from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Iterable

from macos_state_explorer.networkextension_candidate_validation import (
    NetworkExtensionCandidateValidation,
    NetworkExtensionCandidateValidationReport,
)

MANUAL_PRECONDITIONS = (
    "user-reviewed support bundle",
    "backup of affected plist",
    "Chrome not running",
    "System Settings closed",
    "post-change reboot required",
    "post-change verification required",
)

AUTOMATIC_EXECUTION_BLOCKERS = (
    "NSKeyedArchiver mutation risk",
    "object graph integrity risk",
    "macOS private preference format",
    "runtime absence alone insufficient",
)


@dataclass(frozen=True)
class PreviewActionability:
    preview_only: bool = True
    still_read_only: bool = True
    requires_manual_confirmation: bool = True
    never_auto_delete: bool = True

    def to_json_dict(self) -> dict[str, bool]:
        return {
            "preview_only": self.preview_only,
            "still_read_only": self.still_read_only,
            "requires_manual_confirmation": self.requires_manual_confirmation,
            "never_auto_delete": self.never_auto_delete,
        }


@dataclass(frozen=True)
class PreviewTarget:
    plist_artifact: str
    parent_object_record: str
    signing_identifier: str
    executable_path: str
    executable_path_class: str
    validation_status: str
    candidate_count: int
    candidate_refs: tuple[str, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "plist_artifact": self.plist_artifact,
            "parent_object_record": self.parent_object_record,
            "signing_identifier": self.signing_identifier,
            "executable_path": self.executable_path,
            "executable_path_class": self.executable_path_class,
            "validation_status": self.validation_status,
            "candidate_count": self.candidate_count,
            "candidate_refs": list(self.candidate_refs),
        }


@dataclass(frozen=True)
class NetworkExtensionRepairPlanPreviewGroup:
    preview_group_id: str
    classification: str
    operation: str
    preview_only: bool
    would_target: PreviewTarget
    manual_preconditions: tuple[str, ...]
    automatic_execution_blockers: tuple[str, ...]
    actionability: PreviewActionability
    explanation: str

    def sort_key(self) -> tuple[str, str, str, str, str]:
        target = self.would_target
        return (
            target.plist_artifact,
            target.parent_object_record,
            target.signing_identifier,
            target.executable_path_class,
            target.validation_status,
        )

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "preview_group_id": self.preview_group_id,
            "classification": self.classification,
            "operation": self.operation,
            "preview_only": self.preview_only,
            "would_target": self.would_target.to_json_dict(),
            "manual_preconditions": list(self.manual_preconditions),
            "automatic_execution_blockers": list(self.automatic_execution_blockers),
            "actionability": self.actionability.to_json_dict(),
            "explanation": self.explanation,
        }


@dataclass(frozen=True)
class NetworkExtensionRepairPlanPreview:
    repair_plan_preview_id: str
    source_candidate_validation_id: str
    total_candidates: int
    preview_groups: tuple[NetworkExtensionRepairPlanPreviewGroup, ...]

    def summary(self) -> dict[str, Any]:
        classification_counts = _counts(group.classification for group in self.preview_groups)
        return {
            "total_candidates": self.total_candidates,
            "grouped_preview_targets": len(self.preview_groups),
            "stale_code_sign_clone_targets": sum(group.classification == "stale_code_sign_clone_preview_target" for group in self.preview_groups),
            "stale_missing_executable_targets": sum(group.classification == "stale_missing_executable_preview_target" for group in self.preview_groups),
            "preview_only_operations": sum(group.preview_only for group in self.preview_groups),
            "preview_group_ids": [group.preview_group_id for group in self.preview_groups],
            "classification_counts": classification_counts,
            "read_only": True,
            "mutation_performed": False,
            "automatic_execution_recommendation": "never",
        }

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "command": "networkextension repair-plan-preview",
            "repair_plan_preview_id": self.repair_plan_preview_id,
            "timestamp": "1970-01-01T00:00:00Z",
            "read_only": True,
            "mutation_performed": False,
            "automatic_execution_recommendation": "never",
            "summary": self.summary(),
            "manual_preconditions": list(MANUAL_PRECONDITIONS),
            "automatic_execution_blockers": list(AUTOMATIC_EXECUTION_BLOCKERS),
            "preview_groups": [group.to_json_dict() for group in self.preview_groups],
            "source_candidate_validation_id": self.source_candidate_validation_id,
        }


def build_networkextension_repair_plan_preview(validation: NetworkExtensionCandidateValidationReport) -> NetworkExtensionRepairPlanPreview:
    grouped: dict[tuple[str, str, str, str, str], list[NetworkExtensionCandidateValidation]] = {}
    for candidate in validation.validations:
        classification = _classification(candidate)
        if classification not in {"stale_code_sign_clone_preview_target", "stale_missing_executable_preview_target"}:
            continue
        key = (
            candidate.artifact,
            _parent_object_record(candidate),
            candidate.signing_identifier or "unknown",
            _path_class(candidate),
            candidate.candidate_status,
        )
        grouped.setdefault(key, []).append(candidate)
    groups = []
    for key, candidates in grouped.items():
        artifact, parent_record, signing_identifier, path_class, validation_status = key
        candidate_refs = tuple(sorted(candidate.candidate_ref() for candidate in candidates))
        executable_path = sorted({candidate.executable_path or "unknown" for candidate in candidates})[0]
        target = PreviewTarget(
            plist_artifact=artifact,
            parent_object_record=parent_record,
            signing_identifier=signing_identifier,
            executable_path=executable_path,
            executable_path_class=path_class,
            validation_status=validation_status,
            candidate_count=len(candidates),
            candidate_refs=candidate_refs,
        )
        classification = _classification(candidates[0])
        group_id = _group_id(target, classification)
        groups.append(
            NetworkExtensionRepairPlanPreviewGroup(
                preview_group_id=group_id,
                classification=classification,
                operation="preview_only",
                preview_only=True,
                would_target=target,
                manual_preconditions=MANUAL_PRECONDITIONS,
                automatic_execution_blockers=AUTOMATIC_EXECUTION_BLOCKERS,
                actionability=PreviewActionability(),
                explanation=_explanation(classification),
            )
        )
    groups_tuple = tuple(sorted(groups, key=lambda group: group.sort_key()))
    preview_id = hashlib.sha256(
        json.dumps([group.to_json_dict() for group in groups_tuple], sort_keys=True).encode()
    ).hexdigest()[:16]
    return NetworkExtensionRepairPlanPreview(
        repair_plan_preview_id=f"networkextension-repair-plan-preview-{preview_id}",
        source_candidate_validation_id=validation.candidate_validation_id,
        total_candidates=len(validation.validations),
        preview_groups=groups_tuple,
    )


def networkextension_repair_plan_preview_summary(preview: NetworkExtensionRepairPlanPreview) -> dict[str, Any]:
    return preview.summary()


def render_networkextension_repair_plan_preview(preview: NetworkExtensionRepairPlanPreview) -> str:
    summary = preview.summary()
    lines = [
        "NetworkExtension repair plan preview",
        "- Read-only: true",
        "- Mutation performed: false",
        f"- Total candidates: {summary['total_candidates']}",
        f"- Grouped preview targets: {summary['grouped_preview_targets']}",
        f"- Stale code_sign_clone targets: {summary['stale_code_sign_clone_targets']}",
        f"- Stale missing executable targets: {summary['stale_missing_executable_targets']}",
        "- Automatic execution recommendation: never",
        "- Runtime absence note: runtime absence alone is insufficient for automatic deletion",
        "",
        "Manual preconditions",
    ]
    lines.extend(f"- {item}" for item in MANUAL_PRECONDITIONS)
    lines.extend(["", "Automatic execution blockers"])
    lines.extend(f"- {item}" for item in AUTOMATIC_EXECUTION_BLOCKERS)
    lines.extend(["", "Preview groups"])
    if not preview.preview_groups:
        lines.append("- none")
    for group in preview.preview_groups:
        target = group.would_target
        lines.append(f"- {group.preview_group_id} [{group.classification}] operation={group.operation}")
        lines.append(f"  - Artifact: {target.plist_artifact}")
        lines.append(f"  - Parent object record: {target.parent_object_record}")
        lines.append(f"  - SigningIdentifier: {target.signing_identifier}")
        lines.append(f"  - Validation status: {target.validation_status}")
        lines.append(f"  - Executable path class: {target.executable_path_class}")
        lines.append(f"  - Candidate refs: {', '.join(target.candidate_refs)}")
        lines.append("  - Actionability: preview_only=true, still_read_only=true, requires_manual_confirmation=true, never_auto_delete=true")
        lines.append(f"  - Explanation: {group.explanation}")
    return "\n".join(lines)


def render_networkextension_repair_plan_preview_summary(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "NetworkExtension repair plan preview",
            f"- Total candidates: {summary.get('total_candidates', 0)}",
            f"- Grouped preview targets: {summary.get('grouped_preview_targets', 0)}",
            f"- Stale code_sign_clone targets: {summary.get('stale_code_sign_clone_targets', 0)}",
            f"- Stale missing executable targets: {summary.get('stale_missing_executable_targets', 0)}",
            "- Automatic execution recommendation: never",
            "- Mutation performed: false",
        ]
    )


def _classification(candidate: NetworkExtensionCandidateValidation) -> str:
    if candidate.candidate_status == "stale_code_sign_clone":
        return "stale_code_sign_clone_preview_target"
    if candidate.candidate_status == "stale_missing_executable":
        return "stale_missing_executable_preview_target"
    if candidate.candidate_status in {"runtime_absent", "ambiguous", "unverifiable"}:
        return "unsafe_without_manual_confirmation"
    return "never_auto_delete"


def _path_class(candidate: NetworkExtensionCandidateValidation) -> str:
    if candidate.evidence.path_is_code_sign_clone and candidate.evidence.path_is_temp_container:
        return "code_sign_clone_temp_container"
    if candidate.evidence.path_is_code_sign_clone:
        return "code_sign_clone"
    if candidate.candidate_status == "stale_missing_executable":
        return "missing_executable_path"
    if candidate.evidence.installed_app_exists:
        return "installed_app_path"
    if candidate.evidence.parent_bundle_exists:
        return "parent_bundle_path"
    return "unknown_path_class"


def _parent_object_record(candidate: NetworkExtensionCandidateValidation) -> str:
    if candidate.object_graph_parent_chain:
        return candidate.object_graph_parent_chain[0]
    return "unknown_parent"


def _group_id(target: PreviewTarget, classification: str) -> str:
    digest = hashlib.sha256(json.dumps({"target": target.to_json_dict(), "classification": classification}, sort_keys=True).encode()).hexdigest()[:12]
    return f"ne-repair-preview-{digest}"


def _explanation(classification: str) -> str:
    if classification == "stale_code_sign_clone_preview_target":
        return "Preview-only group for stale code_sign_clone evidence. runtime absence alone is insufficient for automatic deletion; NSKeyedArchiver and private preference risks require manual review."
    if classification == "stale_missing_executable_preview_target":
        return "Preview-only group for a stale missing executable path. runtime absence alone is insufficient for automatic deletion; any future repair requires manual plist backup, review, reboot, and verification."
    if classification == "unsafe_without_manual_confirmation":
        return "Evidence is insufficient or ambiguous; manual confirmation is required and no automatic action is permitted."
    return "Candidate is not a repair target and must never be automatically deleted."


def _counts(values: Iterable[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        result[value] = result.get(value, 0) + 1
    return dict(sorted(result.items()))
