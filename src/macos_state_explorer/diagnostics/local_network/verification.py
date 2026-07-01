from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from macos_state_explorer.core.model import Snapshot
from macos_state_explorer.diagnostics.local_network.engine import diagnose_local_network
from macos_state_explorer.diagnostics.local_network.models import LocalNetworkDiagnosis
from macos_state_explorer.evidence.engine import extract_evidence
from macos_state_explorer.evidence.models import EvidenceItem
from macos_state_explorer.solver.local_network import RepairCandidate, build_local_network_solution

VerificationStatus = Literal["SUCCESS", "FAILED"]


class LocalNetworkVerification(BaseModel):
    status: VerificationStatus
    branch_id: str
    expected_change: str
    observed_result: str
    current_diagnosis: LocalNetworkDiagnosis
    next_repair_candidate: RepairCandidate | None = None
    continues_workflow: bool = False
    evidence_ids: list[str] = Field(default_factory=list)


def verify_local_network(
    snapshot: Snapshot,
    *,
    expected_branch_id: str = "manual-empty-trash-reboot",
) -> LocalNetworkVerification:
    """Evaluate whether the expected Local Network repair branch worked.

    This is read-only: it repeats diagnosis from a fresh snapshot and advances the
    decision tree when the expected evidence is still present.
    """
    diagnosis = diagnose_local_network(snapshot)
    evidence = extract_evidence(snapshot)
    solution = build_local_network_solution(snapshot)
    candidates = solution.repair_plan
    current_index = _candidate_index(candidates, expected_branch_id)

    if expected_branch_id in {"manual-empty-trash-reboot", "manual-reinstall-chrome"}:
        chrome_evidence = _chrome_launchservices_evidence(evidence.items)
        if chrome_evidence:
            if current_index < 0:
                next_candidate = candidates[0] if candidates else None
            else:
                next_candidate = candidates[current_index + 1] if current_index + 1 < len(candidates) else None
            return LocalNetworkVerification(
                status="FAILED",
                branch_id=expected_branch_id,
                expected_change="LaunchServices Chrome/Google stale evidence is absent after the manual repair.",
                observed_result="Chrome/Google LaunchServices stale or orphaned evidence is still present.",
                current_diagnosis=diagnosis,
                next_repair_candidate=next_candidate,
                continues_workflow=next_candidate is not None,
                evidence_ids=[item.id for item in chrome_evidence],
            )
        return LocalNetworkVerification(
            status="SUCCESS",
            branch_id=expected_branch_id,
            expected_change="LaunchServices Chrome/Google stale evidence is absent after the manual repair.",
            observed_result="LaunchServices Chrome/Google stale evidence is absent in the current diagnosis.",
            current_diagnosis=diagnosis,
            next_repair_candidate=None,
            continues_workflow=False,
            evidence_ids=[],
        )

    return LocalNetworkVerification(
        status="FAILED",
        branch_id=expected_branch_id,
        expected_change="Focused trace should isolate a more specific root cause or produce new correlated evidence.",
        observed_result="Automatic trace-result evaluation is not available in the current snapshot-only verification.",
        current_diagnosis=diagnosis,
        next_repair_candidate=None,
        continues_workflow=False,
        evidence_ids=[finding.evidence_ids[0] for finding in diagnosis.evidence if finding.evidence_ids],
    )


def render_verification_report(result: LocalNetworkVerification) -> str:
    lines = [
        f"Verification: {result.status}",
        f"Branch: {result.branch_id}",
        f"Expected change: {result.expected_change}",
        f"Observed result: {result.observed_result}",
        f"Current diagnosis: {result.current_diagnosis.diagnosis}",
    ]
    if result.evidence_ids:
        lines.append(f"Evidence IDs: {', '.join(result.evidence_ids)}")
    if result.next_repair_candidate:
        candidate = result.next_repair_candidate
        lines.extend(
            [
                "",
                "Next repair candidate",
                f"- {candidate.id}: {candidate.title}",
                f"- Risk: {candidate.risk}",
                f"- Expected result: {candidate.expected_result}",
                f"- Verification command: {candidate.verification_command}",
                f"- Fallback branch: {candidate.fallback_branch}",
            ]
        )
    return "\n".join(lines)


def _candidate_index(candidates: list[RepairCandidate], branch_id: str) -> int:
    for index, candidate in enumerate(candidates):
        if candidate.id == branch_id:
            return index
    return -1


def _chrome_launchservices_evidence(items: list[EvidenceItem]) -> list[EvidenceItem]:
    stale_launchservices_ids = {
        "launchservices.orphaned_registrations",
        "launchservices.stale_app_paths",
        "launchservices.missing_volume_registrations",
        "launchservices.duplicate_bundle_registrations",
    }
    return [
        item
        for item in items
        if item.id in stale_launchservices_ids and ("chrome" in str(item.data).lower() or "google" in str(item.data).lower())
    ]
