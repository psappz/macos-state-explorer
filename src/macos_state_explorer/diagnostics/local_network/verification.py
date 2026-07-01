from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from macos_state_explorer.core.model import Snapshot
from macos_state_explorer.diagnostics.local_network.engine import diagnose_local_network
from macos_state_explorer.diagnostics.local_network.models import LocalNetworkDiagnosis
from macos_state_explorer.evidence.engine import extract_evidence
from macos_state_explorer.evidence.models import EvidenceItem
from macos_state_explorer.solver.local_network import RepairCandidate, build_local_network_solution

VerificationStatus = Literal["SUCCESS", "FAILED", "RETRY"]
VerificationTransition = Literal[
    "workflow-complete",
    "advance",
    "fallback-to-current-plan",
    "retry-current-branch",
]

MANUAL_LAUNCHSERVICES_BRANCHES = {"manual-empty-trash-reboot", "manual-reinstall-chrome"}


class LocalNetworkVerification(BaseModel):
    status: VerificationStatus
    branch_id: str
    expected_change: str
    observed_result: str
    current_diagnosis: LocalNetworkDiagnosis
    next_repair_candidate: RepairCandidate | None = None
    continues_workflow: bool = False
    evidence_ids: list[str] = Field(default_factory=list)
    transition: VerificationTransition
    next_step: str
    retry_guidance: str
    fallback_guidance: str


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

    if expected_branch_id not in _known_branch_ids(candidates) and expected_branch_id not in MANUAL_LAUNCHSERVICES_BRANCHES:
        next_candidate = candidates[0] if candidates else None
        return LocalNetworkVerification(
            status="FAILED",
            branch_id=expected_branch_id,
            expected_change="The requested verification branch should match a known Local Network repair branch.",
            observed_result=(
                f"Branch {expected_branch_id!r} is unknown, so verification cannot map it to a deterministic "
                "expected evidence change. Falling back to the current evidence-ranked plan."
            ),
            current_diagnosis=diagnosis,
            next_repair_candidate=next_candidate,
            continues_workflow=next_candidate is not None,
            evidence_ids=_diagnosis_evidence_ids(diagnosis),
            transition="fallback-to-current-plan",
            next_step=_next_step(next_candidate),
            retry_guidance="Retry with one of the branch IDs printed by mse solve local-network.",
            fallback_guidance=_fallback_guidance(next_candidate),
        )

    if expected_branch_id in MANUAL_LAUNCHSERVICES_BRANCHES:
        if not _has_launchservices_observation(snapshot):
            return LocalNetworkVerification(
                status="RETRY",
                branch_id=expected_branch_id,
                expected_change="LaunchServices Chrome/Google stale evidence can be compared before and after the manual repair.",
                observed_result="LaunchServices evidence is incomplete in this snapshot, so absence of stale Chrome/Google evidence cannot be treated as success.",
                current_diagnosis=diagnosis,
                next_repair_candidate=None,
                continues_workflow=False,
                evidence_ids=_diagnosis_evidence_ids(diagnosis),
                transition="retry-current-branch",
                next_step=f"Rerun verification for {expected_branch_id} after a fresh read-only diagnosis snapshot.",
                retry_guidance=(
                    f"Run mse diagnose local-network, then rerun mse verify local-network --branch {expected_branch_id}. "
                    "Do not advance repair branches until LaunchServices evidence is present."
                ),
                fallback_guidance="If LaunchServices remains unavailable, run mse collect ~/Desktop/mse-local-network-collect --fast and inspect the bundle before proposing another repair.",
            )

        chrome_evidence = _chrome_launchservices_evidence(evidence.items)
        if chrome_evidence:
            if current_index < 0:
                next_candidate = candidates[0] if candidates else None
                transition: VerificationTransition = "fallback-to-current-plan"
                observed_result = (
                    "Chrome/Google LaunchServices stale or orphaned evidence is still present, and "
                    f"{expected_branch_id!r} is not in the current evidence-ranked plan."
                )
            else:
                next_candidate = candidates[current_index + 1] if current_index + 1 < len(candidates) else None
                transition = "advance"
                observed_result = "Chrome/Google LaunchServices stale or orphaned evidence is still present."
            return LocalNetworkVerification(
                status="FAILED",
                branch_id=expected_branch_id,
                expected_change="LaunchServices Chrome/Google stale evidence is absent after the manual repair.",
                observed_result=observed_result,
                current_diagnosis=diagnosis,
                next_repair_candidate=next_candidate,
                continues_workflow=next_candidate is not None,
                evidence_ids=[item.id for item in chrome_evidence],
                transition=transition,
                next_step=_next_step(next_candidate),
                retry_guidance=(
                    f"Retry the same branch only if {expected_branch_id} was not fully completed "
                    "or macOS was not rebooted before verification."
                ),
                fallback_guidance=_fallback_guidance(next_candidate),
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
            transition="workflow-complete",
            next_step="No next repair branch is needed unless the user-facing Local Network symptom is still reproducible.",
            retry_guidance="If Chrome still fails to prompt for Local Network, rerun mse solve local-network on a fresh snapshot before trying another manual repair.",
            fallback_guidance="If the symptom persists despite clean LaunchServices evidence, collect a focused trace with mse trace local-network and inspect trace evidence before higher-risk actions.",
        )

    return LocalNetworkVerification(
        status="RETRY",
        branch_id=expected_branch_id,
        expected_change="Focused trace should isolate a more specific root cause or produce new correlated evidence.",
        observed_result="Trace-result verification requires the trace output; snapshot-only verification cannot confirm whether the trace branch worked.",
        current_diagnosis=diagnosis,
        next_repair_candidate=None,
        continues_workflow=False,
        evidence_ids=_diagnosis_evidence_ids(diagnosis),
        transition="retry-current-branch",
        next_step="Run the trace branch and inspect the generated Root-cause Signals before advancing repairs.",
        retry_guidance="Run mse trace local-network --out ~/Desktop/mse-local-network-trace while opening System Settings → Privacy & Security → Local Network.",
        fallback_guidance="If the trace is inconclusive, run mse collect ~/Desktop/mse-local-network-collect --fast and review the full read-only evidence bundle.",
    )


def render_verification_report(result: LocalNetworkVerification) -> str:
    lines = [
        f"Verification: {result.status}",
        f"Branch: {result.branch_id}",
        f"Transition: {result.transition}",
        f"Expected change: {result.expected_change}",
        f"Observed result: {result.observed_result}",
        f"Current diagnosis: {result.current_diagnosis.diagnosis}",
        f"Next step: {result.next_step}",
        f"Retry guidance: {result.retry_guidance}",
        f"Fallback guidance: {result.fallback_guidance}",
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


def _known_branch_ids(candidates: list[RepairCandidate]) -> set[str]:
    return {candidate.id for candidate in candidates} | {"trace-local-network"}


def _has_launchservices_observation(snapshot: Snapshot) -> bool:
    return any(observation.collector == "launchservices" for observation in snapshot.observations)


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


def _diagnosis_evidence_ids(diagnosis: LocalNetworkDiagnosis) -> list[str]:
    return [evidence_id for finding in diagnosis.evidence for evidence_id in finding.evidence_ids]


def _next_step(candidate: RepairCandidate | None) -> str:
    if candidate is None:
        return "No deterministic next repair branch remains in the current evidence-ranked plan."
    return f"Continue with {candidate.id}: {candidate.title}."


def _fallback_guidance(candidate: RepairCandidate | None) -> str:
    if candidate is None:
        return "If the symptom persists, run mse trace local-network and mse collect before considering any higher-risk manual action."
    return f"If the next branch does not change the diagnosis, follow its fallback: {candidate.fallback_branch}"
