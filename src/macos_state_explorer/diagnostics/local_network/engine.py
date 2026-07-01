from __future__ import annotations

from macos_state_explorer.core.model import Snapshot
from macos_state_explorer.diagnostics.local_network.models import (
    DiagnosticFinding,
    DiagnosticStep,
    LocalNetworkDiagnosis,
    VerificationStep,
)
from macos_state_explorer.evidence.engine import extract_evidence
from macos_state_explorer.evidence.models import EvidenceItem
from macos_state_explorer.remediation.rules import build_remediation_plan


def diagnose_local_network(snapshot: Snapshot) -> LocalNetworkDiagnosis:
    evidence = extract_evidence(snapshot)
    plan = build_remediation_plan(evidence)
    findings = [_finding_from_evidence(item) for item in evidence.items]
    evidence_by_id = {item.id: item for item in evidence.items}

    orphaned = evidence_by_id.get("launchservices.orphaned_registrations")
    if orphaned and _mentions_chrome_or_google(orphaned):
        return _chrome_launchservices_diagnosis(findings)

    if "tcc.no_localnetwork_rows" in evidence_by_id:
        return _missing_tcc_rows_diagnosis(findings)

    stale_ids = {
        "launchservices.stale_app_paths",
        "launchservices.missing_volume_registrations",
        "launchservices.duplicate_bundle_registrations",
    }
    if stale_ids & set(evidence_by_id):
        return _stale_launchservices_diagnosis(findings)

    return _no_clear_issue_diagnosis(findings, len(plan.actions))


def _chrome_launchservices_diagnosis(findings: list[DiagnosticFinding]) -> LocalNetworkDiagnosis:
    action = DiagnosticStep(
        id="chrome.manual_trash_reboot_reinstall",
        title="Manually empty Trash if Chrome is there, then reboot",
        description=(
            "If Chrome or Chrome Helper is in Trash, empty Trash manually after review. Reboot macOS. "
            "If the Local Network entry is still broken, clean reinstall Chrome from the official installer."
        ),
        risk="medium",
        mode="manual",
        commands=[],
        expected_result="LaunchServices stops surfacing stale Chrome records and System Settings reflects current app state.",
    )
    return LocalNetworkDiagnosis(
        diagnosis="Chrome Local Network state is probably backed by stale or orphaned LaunchServices registrations.",
        confidence=0.9,
        most_likely_cause="A removed or moved Chrome/Google app registration remains visible to LaunchServices.",
        evidence=findings,
        recommended_next_action=action,
        risk=action.risk,
        expected_result=action.expected_result,
        verification=VerificationStep(
            title="Rerun diagnosis",
            command="mse diagnose local-network",
            expected_result="The orphaned Chrome/Google LaunchServices evidence disappears or changes.",
        ),
        fallback_path=[
            DiagnosticStep(
                id="chrome.trace_if_still_broken",
                title="Trace Local Network UI behavior if still broken",
                description="If diagnosis still reports stale Chrome state, capture a focused read-only trace.",
                risk="low",
                mode="read-only",
                commands=["mse trace local-network --out ~/Desktop/mse-local-network-trace"],
                expected_result="Trace artifacts help identify whether System Settings is reading a cache or registry layer.",
            )
        ],
    )


def _missing_tcc_rows_diagnosis(findings: list[DiagnosticFinding]) -> LocalNetworkDiagnosis:
    action = DiagnosticStep(
        id="localnetwork.trigger_real_access",
        title="Launch the affected app and trigger real local network access",
        description=(
            "Open the affected app, perform an action that reaches a local device or Bonjour service, then verify "
            "System Settings > Privacy & Security > Local Network."
        ),
        risk="low",
        mode="manual",
        commands=[],
        expected_result="macOS prompts for Local Network permission or writes a TCC Local Network row after real access.",
    )
    return LocalNetworkDiagnosis(
        diagnosis="TCC does not currently show Local Network authorization rows.",
        confidence=0.85,
        most_likely_cause="The app has not triggered a real Local Network permission flow in the collected TCC state.",
        evidence=findings,
        recommended_next_action=action,
        risk=action.risk,
        expected_result=action.expected_result,
        verification=VerificationStep(
            title="Rerun diagnosis",
            command="mse diagnose local-network",
            expected_result="The diagnosis reflects the new TCC state after the app attempts local network access.",
        ),
        fallback_path=[
            DiagnosticStep(
                id="localnetwork.trace_if_no_prompt",
                title="Trace Local Network behavior if no prompt appears",
                description="Capture a read-only trace if the app accesses local network resources but no prompt appears.",
                risk="low",
                mode="read-only",
                commands=["mse trace local-network --out ~/Desktop/mse-local-network-trace"],
                expected_result="Trace artifacts show whether the app reaches APIs that should trigger Local Network privacy.",
            )
        ],
    )


def _stale_launchservices_diagnosis(findings: list[DiagnosticFinding]) -> LocalNetworkDiagnosis:
    action = DiagnosticStep(
        id="launchservices.reboot_reinstall",
        title="Prefer reboot and clean reinstall over database edits",
        description="Do not edit LaunchServices databases manually. Reboot and reinstall affected apps if stale records persist.",
        risk="low",
        mode="manual",
        commands=[],
        expected_result="Stale LaunchServices records naturally age out or are replaced by current app registrations.",
    )
    return LocalNetworkDiagnosis(
        diagnosis="LaunchServices contains stale registrations that may influence the Local Network UI.",
        confidence=0.75,
        most_likely_cause="System Settings may be reading app registry metadata that still references missing paths.",
        evidence=findings,
        recommended_next_action=action,
        risk=action.risk,
        expected_result=action.expected_result,
        verification=VerificationStep(
            title="Rerun diagnosis",
            command="mse diagnose local-network",
            expected_result="Stale LaunchServices evidence decreases or disappears.",
        ),
        fallback_path=[
            DiagnosticStep(
                id="launchservices.trace_if_persistent",
                title="Trace Local Network UI behavior",
                description="Use a focused read-only trace if stale records persist after safe manual remediation.",
                risk="low",
                mode="read-only",
                commands=["mse trace local-network --out ~/Desktop/mse-local-network-trace"],
                expected_result="Trace artifacts identify which registry or privacy layer is involved.",
            )
        ],
    )


def _no_clear_issue_diagnosis(findings: list[DiagnosticFinding], action_count: int) -> LocalNetworkDiagnosis:
    action = DiagnosticStep(
        id="localnetwork.collect_more_evidence",
        title="Collect a focused Local Network trace",
        description="No specific Chrome LaunchServices or TCC Local Network issue was identified in the fast snapshot.",
        risk="low",
        mode="read-only",
        commands=["mse trace local-network --out ~/Desktop/mse-local-network-trace"],
        expected_result="Trace artifacts provide more evidence about System Settings and app privacy behavior.",
    )
    return LocalNetworkDiagnosis(
        diagnosis="No specific Local Network root cause was identified from the fast snapshot.",
        confidence=0.4 if action_count == 0 else 0.55,
        most_likely_cause="More focused runtime evidence is needed.",
        evidence=findings,
        recommended_next_action=action,
        risk=action.risk,
        expected_result=action.expected_result,
        verification=VerificationStep(
            title="Rerun diagnosis",
            command="mse diagnose local-network",
            expected_result="The diagnosis updates after additional evidence is collected.",
        ),
        fallback_path=[],
    )


def _finding_from_evidence(item: EvidenceItem) -> DiagnosticFinding:
    return DiagnosticFinding(
        id=f"finding.{item.id}",
        title=item.title,
        summary=item.summary,
        severity=item.severity,
        confidence=item.confidence,
        evidence_ids=[item.id],
    )


def _mentions_chrome_or_google(item: EvidenceItem) -> bool:
    text = str(item.data).lower()
    return "chrome" in text or "google" in text
