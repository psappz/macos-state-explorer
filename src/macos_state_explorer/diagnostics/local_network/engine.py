from __future__ import annotations

from macos_state_explorer.core.model import Snapshot
from macos_state_explorer.diagnostics.local_network.models import (
    DiagnosticFinding,
    DiagnosticStep,
    LocalNetworkDiagnosis,
    VerificationStep,
)
from macos_state_explorer.diagnostics.local_network.reasoning import build_local_network_reasoning
from macos_state_explorer.evidence.engine import extract_evidence
from macos_state_explorer.evidence.models import EvidenceItem
from macos_state_explorer.remediation.rules import build_remediation_plan


def diagnose_local_network(snapshot: Snapshot) -> LocalNetworkDiagnosis:
    evidence = extract_evidence(snapshot)
    plan = build_remediation_plan(evidence)
    findings = [_finding_from_evidence(item) for item in evidence.items]
    evidence_by_id = {item.id: item for item in evidence.items}
    reasoning = build_local_network_reasoning(snapshot)

    if reasoning.current_functional_state.status == "BROKEN":
        return _with_reasoning(_broken_functional_state_diagnosis(findings), reasoning)
    if reasoning.current_functional_state.status == "DEGRADED":
        return _with_reasoning(_degraded_functional_state_diagnosis(findings), reasoning)
    if reasoning.current_functional_state.status == "HEALTHY" and reasoning.historical_evidence.launchservices_stale_count:
        return _with_reasoning(_healthy_with_historical_evidence_diagnosis(findings), reasoning)
    if reasoning.current_functional_state.status == "HEALTHY":
        return _with_reasoning(_healthy_functional_state_diagnosis(findings), reasoning)

    orphaned = evidence_by_id.get("launchservices.orphaned_registrations")
    if orphaned and _mentions_chrome_or_google(orphaned):
        return _with_reasoning(_chrome_launchservices_diagnosis(findings), reasoning)

    if "tcc.no_localnetwork_rows" in evidence_by_id:
        return _with_reasoning(_missing_tcc_rows_diagnosis(findings), reasoning)

    stale_ids = {
        "launchservices.stale_app_paths",
        "launchservices.missing_volume_registrations",
        "launchservices.duplicate_bundle_registrations",
    }
    if stale_ids & set(evidence_by_id):
        return _with_reasoning(_stale_launchservices_diagnosis(findings), reasoning)

    return _with_reasoning(_no_clear_issue_diagnosis(findings, len(plan.actions)), reasoning)


def _with_reasoning(diagnosis: LocalNetworkDiagnosis, reasoning) -> LocalNetworkDiagnosis:
    payload = diagnosis.model_dump()
    reasoning_payload = reasoning.to_json_dict()
    payload.update(
        {
            "historical_evidence": reasoning_payload["historical_evidence"],
            "functional_state": reasoning_payload["current_functional_state"],
            "current_risk": reasoning_payload["current_risk"],
            "diagnosis_state": reasoning_payload["diagnosis_state"],
            "confidence_scores": reasoning_payload["confidence_scores"],
            "conclusion": reasoning.conclusion,
        }
    )
    return LocalNetworkDiagnosis.model_validate(payload)


def _broken_functional_state_diagnosis(findings: list[DiagnosticFinding]) -> LocalNetworkDiagnosis:
    action = DiagnosticStep(
        id="localnetwork.inspect_current_functional_failure",
        title="Inspect the current Local Network functional failure",
        description="Current functional state is broken; prioritize current Local Network and NetworkExtension evidence over historical LaunchServices records.",
        risk="high",
        mode="read-only",
        commands=["mse report local-network --bundle ~/Desktop/mse-local-network-current"],
        expected_result="The report preserves historical evidence while identifying the current broken functional layer.",
    )
    return LocalNetworkDiagnosis(
        diagnosis="NetworkExtension or Local Network functional state is broken.",
        confidence=0.92,
        most_likely_cause="Current Local Network functionality is broken; historical LaunchServices evidence is contextual, not sufficient by itself.",
        evidence=findings,
        recommended_next_action=action,
        risk=action.risk,
        expected_result=action.expected_result,
        verification=VerificationStep(
            title="Rerun diagnosis",
            command="mse diagnose local-network",
            expected_result="The current functional state changes from broken to healthy or degraded after external remediation.",
        ),
        fallback_path=[],
    )


def _degraded_functional_state_diagnosis(findings: list[DiagnosticFinding]) -> LocalNetworkDiagnosis:
    action = DiagnosticStep(
        id="localnetwork.trace_current_communication_failure",
        title="Trace the current Local Network communication failure",
        description="Communication is failing now; preserve stale LaunchServices evidence as history while collecting current runtime evidence.",
        risk="medium",
        mode="read-only",
        commands=["mse trace local-network ~/Desktop/mse-local-network-trace"],
        expected_result="Trace evidence identifies the current communication failure path.",
    )
    return LocalNetworkDiagnosis(
        diagnosis="Local Network communication is currently failing; historical LaunchServices evidence may be relevant but is not sufficient alone.",
        confidence=0.7,
        most_likely_cause="Current communication failure is active; historical LaunchServices records are supporting evidence only.",
        evidence=findings,
        recommended_next_action=action,
        risk=action.risk,
        expected_result=action.expected_result,
        verification=VerificationStep(
            title="Rerun diagnosis",
            command="mse diagnose local-network",
            expected_result="The diagnosis updates when communication succeeds or the current functional failure is resolved.",
        ),
        fallback_path=[],
    )


def _healthy_with_historical_evidence_diagnosis(findings: list[DiagnosticFinding]) -> LocalNetworkDiagnosis:
    action = DiagnosticStep(
        id="localnetwork.monitor_historical_launchservices_evidence",
        title="Preserve evidence and monitor current functionality",
        description="Do not treat stale LaunchServices records as an active failure while Local Network UI, permission, and communication are healthy.",
        risk="low",
        mode="read-only",
        commands=[],
        expected_result="Historical observations remain visible without forcing an active broken diagnosis.",
    )
    return LocalNetworkDiagnosis(
        diagnosis="Historical LaunchServices orphaned registrations remain present but are not currently affecting Local Network functionality.",
        confidence=0.8,
        most_likely_cause="Current Local Network state is functional; stale LaunchServices records are historical observations.",
        evidence=findings,
        recommended_next_action=action,
        risk=action.risk,
        expected_result=action.expected_result,
        verification=VerificationStep(
            title="Rerun diagnosis",
            command="mse diagnose local-network",
            expected_result="The current functional state remains healthy or new evidence explains any regression.",
        ),
        fallback_path=[],
    )


def _healthy_functional_state_diagnosis(findings: list[DiagnosticFinding]) -> LocalNetworkDiagnosis:
    action = DiagnosticStep(
        id="localnetwork.no_action_when_functional",
        title="No Local Network repair action is indicated",
        description="Current Local Network permissions and communication are healthy.",
        risk="low",
        mode="read-only",
        commands=[],
        expected_result="No active Local Network failure is diagnosed.",
    )
    return LocalNetworkDiagnosis(
        diagnosis="Local Network permissions are healthy and current communication evidence is working.",
        confidence=0.9,
        most_likely_cause="No current Local Network failure is present in the functional-state evidence.",
        evidence=findings,
        recommended_next_action=action,
        risk=action.risk,
        expected_result=action.expected_result,
        verification=VerificationStep(
            title="Rerun diagnosis",
            command="mse diagnose local-network",
            expected_result="The current functional state remains healthy.",
        ),
        fallback_path=[],
    )


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
                commands=["mse trace local-network ~/Desktop/mse-local-network-trace"],
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
                commands=["mse trace local-network ~/Desktop/mse-local-network-trace"],
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
                commands=["mse trace local-network ~/Desktop/mse-local-network-trace"],
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
        commands=["mse trace local-network ~/Desktop/mse-local-network-trace"],
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
