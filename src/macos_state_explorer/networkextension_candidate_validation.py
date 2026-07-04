from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Iterable, Sequence

from macos_state_explorer.networkextension_repair_candidates import (
    NetworkExtensionRepairCandidate,
    RepairCandidateArtifact,
    build_networkextension_repair_candidates,
)
from macos_state_explorer.networkextension_state import default_networkextension_roots


@dataclass(frozen=True)
class CandidateRuntimeEvidence:
    executable_exists: bool
    parent_bundle_exists: bool
    installed_app_exists: bool
    path_is_code_sign_clone: bool
    path_is_temp_container: bool
    launchservices_generation_match: bool
    running_process_match: bool | None

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "executable_exists": self.executable_exists,
            "parent_bundle_exists": self.parent_bundle_exists,
            "installed_app_exists": self.installed_app_exists,
            "path_is_code_sign_clone": self.path_is_code_sign_clone,
            "path_is_temp_container": self.path_is_temp_container,
            "launchservices_generation_match": self.launchservices_generation_match,
            "running_process_match": self.running_process_match,
        }


@dataclass(frozen=True)
class CandidateRuntimeActionability:
    still_read_only: bool = True
    requires_manual_confirmation: bool = True
    never_auto_delete: bool = True

    def to_json_dict(self) -> dict[str, bool]:
        return {
            "still_read_only": self.still_read_only,
            "requires_manual_confirmation": self.requires_manual_confirmation,
            "never_auto_delete": self.never_auto_delete,
        }


@dataclass(frozen=True)
class NetworkExtensionCandidateValidation:
    artifact: str
    object_ref: str
    signing_identifier: str | None
    executable_path: str | None
    object_graph_parent_chain: tuple[str, ...]
    candidate_status: str
    evidence: CandidateRuntimeEvidence
    actionability: CandidateRuntimeActionability
    explanation: str

    def sort_key(self) -> tuple[str, str, str, str]:
        return (self.artifact, self.object_ref, self.signing_identifier or "", self.executable_path or "")

    def candidate_ref(self) -> str:
        return f"{self.artifact}:{self.object_ref}"

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "artifact": self.artifact,
            "object_ref": self.object_ref,
            "signing_identifier": self.signing_identifier,
            "executable_path": self.executable_path,
            "object_graph_parent_chain": list(self.object_graph_parent_chain),
            "candidate_status": self.candidate_status,
            "evidence": self.evidence.to_json_dict(),
            "actionability": self.actionability.to_json_dict(),
            "explanation": self.explanation,
        }


@dataclass(frozen=True)
class NetworkExtensionCandidateValidationReport:
    candidate_validation_id: str
    validations: tuple[NetworkExtensionCandidateValidation, ...]
    decoded_artifacts: tuple[RepairCandidateArtifact, ...]
    roots: tuple[str, ...]

    def summary(self) -> dict[str, Any]:
        status_counts = _counts(item.candidate_status for item in self.validations)
        return {
            "total_candidates": len(self.validations),
            "decoded_artifacts": sum(item.decoded for item in self.decoded_artifacts),
            "malformed_artifacts": sum(item.malformed for item in self.decoded_artifacts),
            "candidate_refs": sorted(item.candidate_ref() for item in self.validations),
            "status_counts": status_counts,
            "runtime_present_records": sum(item.candidate_status in {"runtime_present", "active_installed_app"} for item in self.validations),
            "runtime_absent_records": sum(item.candidate_status == "runtime_absent" for item in self.validations),
            "stale_records": sum(item.candidate_status in {"stale_code_sign_clone", "stale_missing_executable"} for item in self.validations),
            "ambiguous_records": sum(item.candidate_status == "ambiguous" for item in self.validations),
            "unverifiable_records": sum(item.candidate_status == "unverifiable" for item in self.validations),
            "launchservices_generation_matches": sum(item.evidence.launchservices_generation_match for item in self.validations),
            "running_process_matches": sum(item.evidence.running_process_match is True for item in self.validations),
            "read_only": True,
            "mutation_performed": False,
        }

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "command": "networkextension validate-candidates",
            "candidate_validation_id": self.candidate_validation_id,
            "timestamp": "1970-01-01T00:00:00Z",
            "read_only": True,
            "mutation_performed": False,
            "summary": self.summary(),
            "validations": [item.to_json_dict() for item in self.validations],
            "decoded_artifacts": [item.to_json_dict() for item in self.decoded_artifacts],
            "roots": list(self.roots),
        }


def build_networkextension_candidate_validation(
    roots: Iterable[Path] | None = None,
    *,
    launchservices_entries: Iterable[Any] | None = None,
    process_rows: Sequence[str] | None = None,
) -> NetworkExtensionCandidateValidationReport:
    root_paths = [Path(root).expanduser() for root in (roots if roots is not None else default_networkextension_roots())]
    repair_candidates = build_networkextension_repair_candidates(root_paths)
    rows = tuple(process_rows) if process_rows is not None else tuple(_process_rows())
    entries = tuple(launchservices_entries or ())
    validations = tuple(
        sorted(
            (_validate_candidate(candidate, entries, rows) for candidate in repair_candidates.candidates),
            key=lambda item: item.sort_key(),
        )
    )
    digest = hashlib.sha256(
        json.dumps(
            {
                "artifacts": [item.to_json_dict() for item in repair_candidates.decoded_artifacts],
                "validations": [item.to_json_dict() for item in validations],
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()[:16]
    return NetworkExtensionCandidateValidationReport(
        candidate_validation_id=f"networkextension-candidate-validation-{digest}",
        validations=validations,
        decoded_artifacts=repair_candidates.decoded_artifacts,
        roots=tuple(str(root) for root in root_paths),
    )


def networkextension_candidate_validation_summary(report: NetworkExtensionCandidateValidationReport) -> dict[str, Any]:
    return report.summary()


def render_networkextension_candidate_validation(report: NetworkExtensionCandidateValidationReport) -> str:
    summary = report.summary()
    lines = [
        "NetworkExtension candidate runtime validation",
        "- Read-only: true",
        "- Mutation performed: false",
        f"- Total candidates: {summary['total_candidates']}",
        f"- Runtime present records: {summary['runtime_present_records']}",
        f"- Runtime absent records: {summary['runtime_absent_records']}",
        f"- Stale records: {summary['stale_records']}",
        f"- Unverifiable records: {summary['unverifiable_records']}",
        "- Automatic deletion recommendation: never",
        "- Runtime absence alone is insufficient for automatic deletion.",
        "",
        "Validated candidates",
    ]
    if not report.validations:
        lines.append("- none")
    for item in report.validations:
        lines.append(f"- {item.artifact} :: {item.object_ref} :: {item.signing_identifier or 'unknown'} [{item.candidate_status}]")
        lines.append(f"  - Executable path: {item.executable_path or 'unknown'}")
        lines.append(
            "  - Evidence: "
            f"executable_exists={str(item.evidence.executable_exists).lower()}, "
            f"installed_app_exists={str(item.evidence.installed_app_exists).lower()}, "
            f"code_sign_clone={str(item.evidence.path_is_code_sign_clone).lower()}, "
            f"launchservices_match={str(item.evidence.launchservices_generation_match).lower()}, "
            f"running_process_match={_bool_text(item.evidence.running_process_match)}"
        )
        lines.append("  - Actionability: still_read_only=true, requires_manual_confirmation=true, never_auto_delete=true")
        lines.append(f"  - Explanation: {item.explanation}")
    return "\n".join(lines)


def render_networkextension_candidate_validation_summary(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "NetworkExtension candidate runtime validation",
            f"- Total candidates: {summary.get('total_candidates', 0)}",
            f"- Runtime present records: {summary.get('runtime_present_records', 0)}",
            f"- Runtime absent records: {summary.get('runtime_absent_records', 0)}",
            f"- Stale records: {summary.get('stale_records', 0)}",
            f"- Unverifiable records: {summary.get('unverifiable_records', 0)}",
            "- Automatic deletion recommendation: never",
            "- Runtime absence alone is insufficient for automatic deletion.",
        ]
    )


def _validate_candidate(
    candidate: NetworkExtensionRepairCandidate,
    launchservices_entries: tuple[Any, ...],
    process_rows: tuple[str, ...],
) -> NetworkExtensionCandidateValidation:
    executable_path = candidate.executable_path
    signing_identifier = candidate.signing_identifier
    executable_exists = bool(executable_path and Path(executable_path).exists())
    parent_bundle = _parent_bundle_path(executable_path)
    parent_bundle_exists = bool(parent_bundle and Path(parent_bundle).exists())
    installed_app = _app_path(executable_path)
    installed_app_exists = bool(installed_app and Path(installed_app).exists())
    path_is_code_sign_clone = _is_code_sign_clone(executable_path) or _is_code_sign_clone(signing_identifier)
    path_is_temp_container = _is_temp_container(executable_path)
    launchservices_match = _launchservices_match(candidate, launchservices_entries)
    running_match = _running_process_match(candidate, process_rows)
    evidence = CandidateRuntimeEvidence(
        executable_exists=executable_exists,
        parent_bundle_exists=parent_bundle_exists,
        installed_app_exists=installed_app_exists,
        path_is_code_sign_clone=path_is_code_sign_clone,
        path_is_temp_container=path_is_temp_container,
        launchservices_generation_match=launchservices_match,
        running_process_match=running_match,
    )
    status = _candidate_status(candidate, evidence)
    return NetworkExtensionCandidateValidation(
        artifact=candidate.artifact,
        object_ref=candidate.object_reference,
        signing_identifier=signing_identifier,
        executable_path=executable_path,
        object_graph_parent_chain=tuple(part for part in [candidate.parent_dictionary, candidate.object_reference] if part),
        candidate_status=status,
        evidence=evidence,
        actionability=CandidateRuntimeActionability(),
        explanation=_explanation(status, evidence, candidate),
    )


def _candidate_status(candidate: NetworkExtensionRepairCandidate, evidence: CandidateRuntimeEvidence) -> str:
    if not candidate.signing_identifier or not candidate.executable_path:
        return "unverifiable"
    if evidence.running_process_match is True and evidence.installed_app_exists and evidence.executable_exists:
        return "active_installed_app"
    if evidence.path_is_code_sign_clone and not evidence.executable_exists:
        return "stale_code_sign_clone"
    if evidence.executable_exists:
        if evidence.launchservices_generation_match and not evidence.installed_app_exists and not evidence.path_is_code_sign_clone:
            return "ambiguous"
        return "runtime_present"
    if evidence.parent_bundle_exists or evidence.installed_app_exists:
        return "runtime_absent"
    if evidence.launchservices_generation_match:
        return "ambiguous"
    return "stale_missing_executable"


def _explanation(status: str, evidence: CandidateRuntimeEvidence, candidate: NetworkExtensionRepairCandidate) -> str:
    base = "runtime absence alone is insufficient for automatic deletion; output is evidence only and never an automatic delete recommendation."
    if status == "active_installed_app":
        return "referenced executable, installed app bundle, LaunchServices/process evidence, or both indicate a currently active installed app; still read-only and requires manual confirmation."
    if status == "runtime_present":
        return "referenced executable is currently present; still read-only and requires manual confirmation before any future action."
    if status == "runtime_absent":
        return f"parent app/container exists but referenced executable is absent; {base}"
    if status == "stale_code_sign_clone":
        return f"candidate references a code_sign_clone path and the executable is absent; {base}"
    if status == "stale_missing_executable":
        return f"candidate references a missing executable path with no observable active runtime binding; {base}"
    if status == "ambiguous":
        return "runtime evidence conflicts or is incomplete; manual confirmation is required and no automatic deletion is recommended."
    return "insufficient candidate identity or path evidence to validate runtime state; manual confirmation is required and no automatic deletion is recommended."


def _launchservices_match(candidate: NetworkExtensionRepairCandidate, entries: tuple[Any, ...]) -> bool:
    path = candidate.executable_path or ""
    signing = candidate.signing_identifier or ""
    for entry in entries:
        blob = json.dumps(entry, sort_keys=True, default=str) if not isinstance(entry, str) else entry
        if path:
            if path in blob:
                return True
            continue
        if signing and signing in blob:
            return True
    return False


def _running_process_match(candidate: NetworkExtensionRepairCandidate, rows: tuple[str, ...]) -> bool | None:
    if not rows:
        return None
    path = candidate.executable_path or ""
    signing = candidate.signing_identifier or ""
    for row in rows:
        if path and path in row:
            return True
        if signing and signing in row:
            return True
    return False


def _process_rows() -> list[str]:
    try:
        result = subprocess.run(["ps", "-axo", "pid=,comm=,args="], text=True, capture_output=True, check=False, timeout=5)
    except Exception:
        return []
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _parent_bundle_path(path: str | None) -> str | None:
    if not path:
        return None
    if ".app" in path:
        return path.split(".app", 1)[0] + ".app"
    if "code_sign_clone" in path:
        prefix = path.split("code_sign_clone", 1)[0] + "code_sign_clone"
        return prefix
    parent = Path(path).parent
    return str(parent) if str(parent) != "." else None


def _app_path(path: str | None) -> str | None:
    if not path or ".app" not in path:
        return None
    return path.split(".app", 1)[0] + ".app"


def _is_code_sign_clone(value: str | None) -> bool:
    return "code_sign_clone" in (value or "").lower()


def _is_temp_container(path: str | None) -> bool:
    lower = (path or "").lower()
    return "/private/var/" in lower or "/var/folders/" in lower or "/tmp/" in lower or "/temporaryitems/" in lower


def _counts(values: Iterable[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        result[value] = result.get(value, 0) + 1
    return dict(sorted(result.items()))


def _bool_text(value: bool | None) -> str:
    if value is None:
        return "unobservable"
    return str(value).lower()
